from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
import os
import json
import math
import time
import sys
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import undetected_chromedriver as uc  # type: ignore[import-untyped]
import urllib.request
from groq import Groq
from supabase import create_client

from backend.playdoit_browser import (
    configure_chrome_options,
    gate_interactive_driver,
    resolve_browser_mode,
)
from backend.publishing_policy import assign_visibility, public_payload, scheduled_event_date
from backend.odds_source import (
    OddsSourceError,
    SUPPORTED_MARKETS,
    SUPPORTED_SPORT_KEYS,
    fetch_odds_events,
    normalize_odds_event,
)
from backend.playdoit_source import (
    extract_playdoit_raw_events,
    normalize_playdoit_events,
)
from backend.playdoit_health import (
    PlaydoitSourceBlocked,
    PlaydoitSourceError,
    assert_playdoit_source_healthy,
)
from backend.pick_publisher import (
    AuditedBatchPublisher,
    PERSISTED_PICK_COLUMNS,
    SupabaseBatchRepository,
    revalidate_persisted_picks,
)
from backend.pick_selection import (
    CandidatePick,
    EvidenceScore,
    MAX_AI_RANKED_PICKS,
    RankedPick,
    _candidate_exclusivity_group,
    _canonical_line,
    _is_individually_valid,
    build_candidates,
    evidence_for_candidate,
    score_evidence,
    validate_ai_ranking,
)
from backend.scraper_config import ConfigError, ScraperSettings, load_settings
from backend.telegram_publisher import DeliveryResult, TelegramDestination, TelegramHttpTransport, deliver_batch

# Forzar codificación UTF-8
_reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure_stdout):
    _reconfigure_stdout(encoding="utf-8")

# Legacy phase helpers retain optional module defaults for backwards-compatible
# direct calls. The command path injects values loaded by scraper_config instead
# of reading dotenv or creating a privileged client during import.
GROQ_API_KEY = ""
ODDS_API_KEY = ""
SUPABASE_SERVICE_ROLE_KEY = ""
supabase = None
_VERIFIED_CANDIDATES_FIELD = "_verified_candidates"
# Keep the ranking request comfortably below Groq context/request limits while
# bounding model-controlled fan-out and preserving complete market groups.
MAX_AI_CATALOG_CANDIDATES = 32
MAX_AI_PROMPT_CHARS = 24_000
_AI_RANKING_SYSTEM_MESSAGE = (
    "Respondes solo con un objeto JSON que contiene rankings de "
    "candidate_id y rationale. "
    "No produces hechos de apuestas."
)


class PersistenceFailure(RuntimeError):
    """A bounded persistence phase failure safe to map at the CLI boundary."""


class DeliveryFailure(RuntimeError):
    """A bounded delivery bookkeeping failure safe to map at the CLI boundary."""

def retire_previous_public_pending_pick():
    """Fail closed: retire the old free pick before publishing today's batch."""
    if supabase:
        supabase.table("picks").update({"visibility": "premium"}).eq(
            "estado", "pendiente"
        ).eq("visibility", "public").execute()

def require_publish_backend():
    if supabase is None:
        raise RuntimeError(
            "Publicación cancelada: faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY."
        )

def normalizar_cuota_decimal(val: object) -> str | None:
    """Return an exact decimal quote or ``None`` for untrusted input.

    American odds are converted only when the source includes an explicit
    sign and an integer magnitude of at least 100.  Bare large numbers are not
    assumed to use a different odds format.
    """

    if val is None or isinstance(val, bool):
        return None

    if isinstance(val, (int, float)):
        number = float(val)
        if not math.isfinite(number) or not 1.01 <= number <= 50.0:
            return None
        return f"{number:.2f}"

    if not isinstance(val, str):
        return None
    value = val.strip()
    if re.fullmatch(r"[+-]\d+", value):
        american = int(value)
        if abs(american) < 100:
            return None
        decimal = (
            (american / 100) + 1
            if american > 0
            else (100 / abs(american)) + 1
        )
        if not 1.01 <= decimal <= 50.0:
            return None
        return f"{decimal:.2f}"

    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    decimal = float(value)
    if not math.isfinite(decimal) or not 1.01 <= decimal <= 50.0:
        return None
    return f"{decimal:.2f}"

def inferir_categoria_deporte(local, visitante, fallback="Fútbol Internacional"):
    """Infiere la liga y deporte exacto según los equipos involucrados."""
    txt = f"{local} {visitante}".lower()
    
    # 1. UEFA Champions League
    if any(w in txt for w in ['zagreb', 'qarabag', 'bodø', 'bodo', 'red star', 'estrella roja', 'lille', 'slavia', 'young boys', 'galatasaray', 'midtjylland', 'slovan', 'malmö', 'malmo', 'sparta', 'dynamo kyiv', 'kiev', 'salzburg', 'champions']):
        return "UEFA Champions League"
        
    # 2. KBO (Béisbol Coreano)
    if any(w in txt for w in ['kia tigers', 'kiwoom', 'lg twins', 'ssg landers', 'samsung lions', 'doosan bears', 'nc dinos', 'hanwha eagles', 'kt wiz', 'lotte giants', 'kbo', 'landers', 'wiz']):
        return "KBO"
        
    # 3. MLB (Grandes Ligas)
    if any(w in txt for w in ['yankees', 'dodgers', 'red sox', 'white sox', 'cubs', 'mets', 'padres', 'braves', 'twins', 'orioles', 'guardians', 'giants', 'astros', 'angels', 'rangers', 'nationals', 'mariners', 'brewers', 'blue jays', 'rays', 'cardinals', 'reds', 'marlins', 'phillies', 'diamondbacks', 'rockies', 'pirates', 'tigers', 'mlb']):
        return "MLB"
        
    # 4. Liga MX
    if any(w in txt for w in ['américa', 'america', 'chivas', 'guadalajara', 'cruz azul', 'tigres uanl', 'monterrey', 'rayados', 'pumas', 'unam', 'toluca', 'pachuca', 'necaxa', 'león', 'leon', 'atlas', 'puebla', 'juárez', 'juarez', 'san luis', 'tijuana', 'xolos', 'mazatlán', 'mazatlan', 'santos laguna', 'querétaro', 'queretaro', 'atlante']):
        return "Liga MX"
        
    # 5. MLS
    if any(w in txt for w in ['columbus crew', 'montreal', 'inter miami', 'philadelphia union', 'chicago fire', 'orlando city', 'lafc', 'galaxy', 'sounders', 'timbers', 'atlanta united', 'austin', 'mls']):
        return "MLS"
        
    # 6. Fútbol Internacional / Ligas Europeas
    if any(w in txt for w in ['atlético de madrid', 'atletico', 'málaga', 'malaga', 'real madrid', 'barcelona', 'arsenal', 'manchester', 'chelsea', 'liverpool', 'inter milan', 'milan', 'juventus', 'roma', 'napoli', 'psg', 'bayern', 'dortmund', 'benfica', 'porto', 'sporting', 'boca', 'river', 'flamengo', 'palmeiras']):
        return "Fútbol Internacional"
        
    # 7. NFL
    if any(w in txt for w in ['chiefs', '49ers', 'cowboys', 'eagles', 'bills', 'ravens', 'packers', 'texans', 'dolphins', 'patriots', 'steelers', 'nfl']):
        return "NFL"
        
    return fallback

# ============================================================
#  FASE 0: CONFIGURACIÓN DEL NAVEGADOR
# ============================================================
def get_chrome_version():
    """Detecta la versión mayor de Google Chrome instalada en el sistema (Linux / Windows / Mac)."""
    # 1. En Linux / Mac / CLI (GitHub Actions usa Ubuntu)
    try:
        import subprocess
        for cmd in ["google-chrome --version", "google-chrome-stable --version", "chromium --version", "chromium-browser --version", "chrome --version"]:
            try:
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
                match = re.search(r'(\d+)\.\d+\.\d+', output)
                if match:
                    return int(match.group(1))
            except Exception:
                continue
    except Exception:
        pass

    # 2. En Windows (Registro de Windows)
    try:
        import winreg
        for root in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
            try:
                key = winreg.OpenKey(root, r"Software\Google\Chrome\BLBeacon")
                version, _ = winreg.QueryValueEx(key, "version")
                return int(version.split('.')[0])
            except Exception:
                pass
    except Exception:
        pass

    # 3. Fallback inteligente en CI / GitHub Actions
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        return 151

    return None




def _normalized_event_identity(value):
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().casefold().split())
    return normalized or None


def _normalized_quote_mapping(value):
    if not isinstance(value, dict):
        return ()
    return tuple(
        sorted(
            (
                str(key).strip().casefold(),
                str(price).strip(),
            )
            for key, price in value.items()
        )
    )


def _event_record_identity(event):
    if not isinstance(event, dict):
        return None
    source_event_id = str(event.get('source_event_id') or '').strip()
    if source_event_id:
        source = _normalized_event_identity(event.get('source')) or 'unknown'
        return ('source', source, source_event_id)

    home = _normalized_event_identity(event.get('local'))
    away = _normalized_event_identity(event.get('visitante'))
    schedule = _normalized_event_identity(event.get('horario'))
    if (
        home is None
        or away is None
        or schedule is None
        or re.search(r'\d{1,2}:\d{2}', schedule) is None
    ):
        return None
    return ('legacy', home, away, schedule)


def _event_record_evidence(event):
    private_candidates = event.get(_VERIFIED_CANDIDATES_FIELD)
    if not isinstance(private_candidates, tuple) or not all(
        isinstance(candidate, CandidatePick) for candidate in private_candidates
    ):
        private_candidates = ()
    return (
        _normalized_event_identity(event.get('source')),
        _normalized_event_identity(event.get('source_event_id')),
        _normalized_event_identity(event.get('local')),
        _normalized_event_identity(event.get('visitante')),
        _normalized_event_identity(event.get('horario')),
        _normalized_event_identity(event.get('starts_at')),
        _normalized_event_identity(event.get('observed_at')),
        _normalized_event_identity(event.get('bookmaker_key')),
        _normalized_quote_mapping(event.get('cuotas_por_resultado')),
        tuple(str(value).strip() for value in event.get('cuotas_superficie', ())),
        private_candidates,
    )


def _deduplicate_event_records(events):
    """Keep stable event identities and omit identities with conflicting evidence."""

    selected = {}
    order = []
    conflicts = set()
    for event in events:
        identity = _event_record_identity(event)
        if identity is None or identity in conflicts:
            continue
        if identity not in selected:
            selected[identity] = event
            order.append(identity)
            continue
        if _event_record_evidence(selected[identity]) != _event_record_evidence(
            event
        ):
            selected.pop(identity)
            conflicts.add(identity)
    return [selected[identity] for identity in order if identity in selected]


def _verified_market_coverage(events):
    """Count events carrying canonical or official source-backed candidates."""

    coverage = {
        "h2h": 0,
        "totals": 0,
        "spreads": 0,
        "source_markets": 0,
    }
    for event in events:
        if not isinstance(event, dict):
            continue
        candidates = event.get(_VERIFIED_CANDIDATES_FIELD)
        if not isinstance(candidates, tuple):
            continue
        event_markets = set()
        for candidate in candidates:
            if not isinstance(candidate, CandidatePick):
                continue
            if candidate.market_key in {"h2h", "totals", "spreads"}:
                event_markets.add(candidate.market_key)
            elif candidate.market_key.startswith("playdoit_market:"):
                event_markets.add("source_markets")
        for market_key in event_markets:
            coverage[market_key] += 1
    return coverage


def _surface_event_record(event, category, schedule):
    """Project surface data without treating positional prices as named quotes."""

    home = event['local']
    away = event['visitante']
    match_name = f"{home} vs {away}"
    surface_prices = event.get('cuotas', [])
    return {
        "source_event_id": event.get('source_event_id'),
        "bookmaker_key": event.get('bookmaker_key'),
        "categoria": category,
        "partido": match_name,
        "local": home,
        "visitante": away,
        "horario": schedule,
        "cuotas_por_resultado": {},
        "cuotas_superficie": surface_prices[:4],
        "info_texto": (
            f"{category}: {match_name}. Horario: {schedule}. "
            f"Cuotas Playdoit: {' | '.join(surface_prices)}"
        ),
    }


def _match_observed_event(partido, source_event_id, events):
    """Match one exact home/away identity, optionally pinned to a source id."""

    requested_identity = _normalized_event_identity(partido)
    if requested_identity is None:
        return None
    requested_source_id = (
        str(source_event_id).strip() if source_event_id is not None else ""
    )

    matches = []
    seen = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        home = str(event.get("local") or "").strip()
        away = str(event.get("visitante") or "").strip()
        if not home or not away:
            continue
        event_identity = _normalized_event_identity(f"{home} vs {away}")
        if event_identity != requested_identity:
            continue
        event_source_id = str(event.get("source_event_id") or "").strip()
        if requested_source_id and event_source_id != requested_source_id:
            continue
        identity_token = (
            ("source", event_source_id)
            if event_source_id
            else ("object", id(event))
        )
        if identity_token in seen:
            prior_prices = seen[identity_token].get('cuotas_por_resultado')
            current_prices = event.get('cuotas_por_resultado')
            if prior_prices != current_prices:
                return None
            continue
        seen[identity_token] = event
        matches.append(event)

    return matches[0] if len(matches) == 1 else None

def get_chrome_driver():
    mode = resolve_browser_mode(os.environ)

    def make_options():
        options = uc.ChromeOptions()
        return configure_chrome_options(options, mode)

    def create_driver(**kwargs):
        driver = uc.Chrome(options=make_options(), **kwargs)
        gate_interactive_driver(driver, mode)
        return driver

    print(f"browser_mode={mode.value}")

    chrome_ver = get_chrome_version()
    if chrome_ver:
        print(f"   🌐 Google Chrome v{chrome_ver} detectado")
        try:
            return create_driver(version_main=chrome_ver)
        except Exception as e:
            print(f"   ⚠️ Intentando inicialización estándar; failure={type(e).__name__}")

    try:
        return create_driver()
    except Exception:
        return create_driver(version_main=None)

# ============================================================
#  UTILIDADES DE NAVEGACIÓN (Shadow DOM de Altenar)
# ============================================================
def get_shadow_script():
    return """
    function getShadow() {
        var host = document.querySelector('div#altenar > div');
        if (host && host.shadowRoot) return host.shadowRoot;
        var all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            if (all[i].shadowRoot) return all[i].shadowRoot;
        }
        return null;
    }
    """

def click_tab_hoy(driver):
    """Hace clic en la pestaña 'Hoy' para filtrar solo eventos del día (evita deseleccionar si ya está activo)."""
    script = get_shadow_script() + """
    try {
        var shadow = getShadow();
        if(!shadow) return false;
        var tabs = Array.from(shadow.querySelectorAll('*'));
        var hoyTab = tabs.find(n => n.textContent.trim().toLowerCase() === 'hoy' && n.children.length === 0);
        if(hoyTab) {
            var parent = hoyTab.parentElement || hoyTab;
            var isAlreadyActive = parent.classList.contains('active') || parent.classList.contains('selected') || parent.getAttribute('aria-selected') === 'true';
            if (!isAlreadyActive) {
                hoyTab.click();
                if (hoyTab.parentElement) hoyTab.parentElement.click();
                return true;
            }
            return true;
        }
        return false;
    } catch(e) { return false; }
    """
    result = driver.execute_script(script)
    if result:
        print("   ✅ Filtro 'Hoy' activado.")
    time.sleep(2)

def click_decimal_toggle(driver):
    """Cambia el formato de cuotas a Decimal en la barra lateral de Playdoit."""
    script_step1 = get_shadow_script() + """
    try {
        var shadow = getShadow();
        if(!shadow) return false;
        var btn = shadow.querySelector('[class*="OddsFormatBoxOptionName"], [class*="OddsFormat"]');
        if (btn) {
            btn.click();
            if (btn.parentElement) btn.parentElement.click();
            return true;
        }
        return false;
    } catch(e) { return false; }
    """
    driver.execute_script(script_step1)
    time.sleep(1)
    
    script_step2 = get_shadow_script() + """
    try {
        var shadow = getShadow();
        if(!shadow) return false;
        var all = Array.from(shadow.querySelectorAll('*'));
        var dec = all.find(n => n.children.length === 0 && n.textContent.trim().toLowerCase() === 'decimal');
        if (dec) {
            dec.click();
            if (dec.parentElement) dec.parentElement.click();
            return true;
        }
        return false;
    } catch(e) { return false; }
    """
    res = driver.execute_script(script_step2)
    if res:
        print("   ✅ Formato de cuotas cambiado a DECIMAL en Playdoit.")
    time.sleep(2)

def click_category(driver, category):
    """Hace clic en una categoría o liga del menú lateral o barra superior de Playdoit."""
    catLower = category.lower()
    
    # Manejo especializado paso a paso para KBO
    if 'kbo' in catLower or 'corea' in catLower:
        try:
            # 1. Clic en Béisbol
            s_beis = get_shadow_script() + """
            try {
                var shadow = getShadow();
                if(!shadow) return false;
                var all = Array.from(shadow.querySelectorAll('*'));
                var beis = all.find(n => n.children.length === 0 && (n.textContent||'').trim().toLowerCase() === 'béisbol');
                if (beis) {
                    (beis.parentElement || beis).click();
                    beis.click();
                    return true;
                }
                return false;
            } catch(e) { return false; }
            """
            driver.execute_script(s_beis)
            time.sleep(2)
            
            # 2. Clic en Corea del Sur
            s_corea = get_shadow_script() + """
            try {
                var shadow = getShadow();
                if(!shadow) return false;
                var all = Array.from(shadow.querySelectorAll('*'));
                var corea = all.find(n => n.children.length === 0 && ((n.textContent||'').trim().toLowerCase() === 'corea del sur' || (n.textContent||'').trim().toLowerCase() === 'kbo'));
                if (corea) {
                    (corea.parentElement || corea).click();
                    corea.click();
                    return true;
                }
                return false;
            } catch(e) { return false; }
            """
            driver.execute_script(s_corea)
            time.sleep(2)
            
            # 3. Clic en KBO League
            s_kbo = get_shadow_script() + """
            try {
                var shadow = getShadow();
                if(!shadow) return false;
                var all = Array.from(shadow.querySelectorAll('*'));
                var kbo = all.find(n => n.children.length === 0 && ((n.textContent||'').trim().toLowerCase() === 'kbo' || (n.textContent||'').trim().toLowerCase() === 'kbo league'));
                if (kbo) {
                    (kbo.parentElement || kbo).click();
                    kbo.click();
                    return true;
                }
                return false;
            } catch(e) { return false; }
            """
            return driver.execute_script(s_kbo) or True
        except Exception:
            pass

    # 1. Buscar en Top Leagues y Menú deportivo
    script = get_shadow_script() + """
    try {
        var shadow = getShadow();
        if (!shadow) return false;
        var all = Array.from(shadow.querySelectorAll('*'));
        var catLower = arguments[0];
        
        var match = all.find(n => {
            if (n.children.length > 0) return false;
            var t = (n.textContent || '').trim().toLowerCase();
            if ((catLower.includes('champions') || catLower.includes('uefa champions')) && (t === 'uefa champions league' || t.includes('champions league') || t.includes('liga de campeones'))) return true;
            if ((catLower.includes('europa') || catLower.includes('conference')) && (t.includes('europa league') || t.includes('conference league') || t.includes('liga europa'))) return true;
            if (catLower.includes('libertadores') && t.includes('libertadores')) return true;
            if (catLower.includes('la liga') && (t === 'la liga' || t === 'laliga')) return true;
            if (catLower.includes('liga mx') && (t === 'liga mx')) return true;
            if (catLower.includes('mlb') && (t === 'mlb' || t === 'béisbol' || t === 'beisbol')) return true;
            if (catLower.includes('mls') && (t === 'mls')) return true;
            if (catLower.includes('nfl') && (t === 'nfl' || t.includes('fútbol americano'))) return true;
            return t === catLower;
        });
        
        if (match) {
            (match.parentElement || match).click();
            match.click();
            return true;
        }
        return false;
    } catch(e) { return false; }
    """
    return driver.execute_script(script, catLower)

def es_partido_futuro_valido(horario_str):
    """
    Verifica si un partido es estrictamente de HOY (o máximo MAÑANA dentro de las próximas 30 horas)
    y que AÚN NO HAYA INICIADO respecto a la hora oficial actual de la Ciudad de México (CDMX).
    Descarta con precisión matemática partidos pasados, minutos de juego en vivo Y partidos lejanos.
    """
    try:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo("America/Mexico_City")
            ahora = datetime.now(tz)
        except Exception:
            ahora = datetime.utcnow() - timedelta(hours=6)
        
        limite_maximo = ahora + timedelta(hours=48)  # Próximas 48 horas (Hoy y Mañana completo)
        
        # 1. Formato con fecha y hora ej: "17/08 • 19:00" o "22/08 • 19:00"
        match_fecha_hora = re.search(r'(\d{1,2})[/.-](\d{1,2})\s*(?:•|\s+)?\s*(\d{1,2}):(\d{2})', horario_str)
        if match_fecha_hora:
            dia = int(match_fecha_hora.group(1))
            mes = int(match_fecha_hora.group(2))
            hora = int(match_fecha_hora.group(3))
            minuto = int(match_fecha_hora.group(4))
            
            if hora >= 24 or minuto >= 60 or mes > 12 or dia > 31:
                return False, f"Formato inválido ({dia}/{mes} {hora}:{minuto})"
            
            anio = ahora.year
            fecha_partido = datetime(anio, mes, dia, hora, minuto, tzinfo=ahora.tzinfo if hasattr(ahora, 'tzinfo') and ahora.tzinfo else None)
            
            # Si la hora de inicio ya pasó respecto a CDMX
            if fecha_partido <= (ahora + timedelta(minutes=5)):
                return False, f"Ya inició/terminó ({dia:02d}/{mes:02d} {hora:02d}:{minuto:02d})"
                
            # Si es de una fecha lejana (> 30 horas), se descarta.
            if fecha_partido > limite_maximo:
                return False, f"Descartado fecha lejana ({dia:02d}/{mes:02d} no es de hoy)"
                
            return True, f"{dia:02d}/{mes:02d} • {hora:02d}:{minuto:02d}"

        # 2. Solo Fecha ej: "17/08"
        match_solo_fecha = re.search(r'(\d{1,2})[/.-](\d{1,2})', horario_str)
        if match_solo_fecha:
            dia = int(match_solo_fecha.group(1))
            mes = int(match_solo_fecha.group(2))
            if mes > 12 or dia > 31:
                return False, "Fecha inválida"
            if (dia == ahora.day and mes == ahora.month) or (dia == (ahora + timedelta(days=1)).day and mes == (ahora + timedelta(days=1)).month):
                return True, f"{dia:02d}/{mes:02d} • Hoy"
            else:
                return False, f"Descartado fecha lejana ({dia:02d}/{mes:02d})"

        # 3. Solo Hora (ej: "Hoy • 19:00" o "Mañana • 21:00")
        match_hora = re.search(r'(\d{1,2}):(\d{2})', horario_str)
        if match_hora:
            hora = int(match_hora.group(1))
            minuto = int(match_hora.group(2))
            
            if hora >= 24 or minuto >= 60:
                return False, f"Hora inválida ({hora}:{minuto})"
            
            if "mañana" in horario_str.lower() or "tomorrow" in horario_str.lower():
                return True, f"Mañana • {hora:02d}:{minuto:02d}"
            
            fecha_partido = datetime(ahora.year, ahora.month, ahora.day, hora, minuto, tzinfo=ahora.tzinfo if hasattr(ahora, 'tzinfo') and ahora.tzinfo else None)
            if fecha_partido <= (ahora + timedelta(minutes=5)):
                return False, f"Ya inició/terminó (Hoy {hora:02d}:{minuto:02d})"
            return True, f"Hoy • {hora:02d}:{minuto:02d}"
            
        return False, "Sin horario específico confirmado"
    except Exception as e:
        return False, f"Error validación; failure={type(e).__name__}"

def _sport_for_category(category):
    normalized = str(category or '').casefold()
    if any(token in normalized for token in ('mlb', 'kbo', 'béisbol', 'beisbol')):
        return 'baseball'
    if 'nfl' in normalized or 'fútbol americano' in normalized:
        return 'americanfootball'
    return 'soccer'


def extract_events_from_page(
    driver,
    *,
    observed_at=None,
    fallback_league=None,
    fallback_sport=None,
    detail_cache=None,
):
    """Extract and normalize Playdoit records before legacy phase projection."""

    observed = observed_at or datetime.now(ZoneInfo("America/Mexico_City"))
    extraction_options = {}
    if detail_cache is not None:
        extraction_options["detail_cache"] = detail_cache
        extraction_options["detail_observed_at"] = observed
    raw_records = extract_playdoit_raw_events(driver, **extraction_options)
    enriched = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        record = dict(raw)
        inferred_league = fallback_league or inferir_categoria_deporte(
            record.get('home', ''), record.get('away', '')
        )
        record['league'] = record.get('league') or inferred_league
        record['sport'] = (
            record.get('sport')
            or fallback_sport
            or _sport_for_category(record['league'])
        )
        enriched.append(record)
    return [
        _legacy_odds_projection(event)
        for event in normalize_playdoit_events(enriched, observed)
        if event.markets
    ]

def _legacy_odds_projection(event):
    """Project a normalized event for legacy phases during the migration."""

    h2h = next((market for market in event.markets if market.key == "h2h"), None)
    named_h2h = {}
    surface_odds = []
    bookmaker_key = (
        event.markets[0].bookmaker_key if event.markets else None
    )
    if h2h is not None:
        bookmaker_key = h2h.bookmaker_key
        for key in ("home", "draw", "away"):
            try:
                price = f"{h2h.outcome(key).price:.2f}"
            except KeyError:
                continue
            named_h2h[key] = price
            surface_odds.append(price)

    market_descriptions = []
    for market in event.markets:
        selections = ", ".join(
            f"{outcome.name} @ {outcome.price:.2f}"
            for outcome in market.outcomes
        )
        line = "" if market.line is None else f" {market.line:g}"
        market_descriptions.append(
            f"[{market.key.upper()}{line}]: {selections}"
        )

    mexico_start = event.starts_at.astimezone(ZoneInfo("America/Mexico_City"))
    mexico_observed = event.observed_at.astimezone(ZoneInfo("America/Mexico_City"))
    if mexico_start.date() == mexico_observed.date():
        schedule = f"Hoy {mexico_start.strftime('%H:%M')} hrs"
    elif mexico_start.date() == mexico_observed.date() + timedelta(days=1):
        schedule = f"Mañana {mexico_start.strftime('%H:%M')} hrs"
    else:
        schedule = mexico_start.strftime("%d/%m %H:%M hrs")

    match_name = f"{event.home_team} vs {event.away_team}"
    return {
        "source": event.source,
        "source_event_id": event.source_event_id,
        "sport": event.sport,
        "starts_at": event.starts_at.isoformat(),
        "observed_at": event.observed_at.isoformat(),
        "bookmaker_key": bookmaker_key,
        "categoria": event.league,
        "partido": match_name,
        "local": event.home_team,
        "visitante": event.away_team,
        "horario": schedule,
        "cuotas_por_resultado": named_h2h,
        "cuotas_superficie": surface_odds,
        "mercados_reales": market_descriptions,
        "info_texto": (
            f"{event.league}: {match_name}. Horario: {schedule}. "
            f"Mercados verificados: {' | '.join(market_descriptions)}"
        ),
        _VERIFIED_CANDIDATES_FIELD: tuple(build_candidates([event])),
    }


def obtener_eventos_odds_api(odds_api_key=None, *, observed_at=None):
    """Obtiene ÚNICAMENTE partidos PRE-MATCH futuros con cuotas reales y exactas (1X2, Totales Over/Under y Spreads)."""
    active_odds_api_key = odds_api_key or ODDS_API_KEY
    if not active_odds_api_key:
        return []
    
    print("\n🌐 Conectando satélite The Odds API (Champions League, Liga MX, MLB, La Liga, MLS, Premier, NFL)...")
    eventos_api = []

    now_utc = observed_at or datetime.now(ZoneInfo("UTC"))
    min_time_utc = now_utc + timedelta(minutes=15) # Mínimo 15 minutos en el futuro
    max_time_utc = now_utc + timedelta(hours=36)

    for sport_key in SUPPORTED_SPORT_KEYS:
        try:
            raw_events = fetch_odds_events(
                active_odds_api_key,
                sport_key,
                regions=("us", "eu"),
                markets=SUPPORTED_MARKETS,
                timeout=10.0,
                opener=urllib.request.urlopen,
            )
            for raw_event in raw_events:
                try:
                    event = normalize_odds_event(raw_event, now_utc)
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    print(
                        f"   ⚠️ Evento inválido en {sport_key}; "
                        f"failure={type(exc).__name__}"
                    )
                    continue
                if not min_time_utc <= event.starts_at <= max_time_utc:
                    continue
                eventos_api.append(_legacy_odds_projection(event))
        except OddsSourceError as exc:
            print(f"   ⚠️ Error en {sport_key}; {exc}")
        except Exception as exc:
            print(f"   ⚠️ Error en {sport_key}; failure={type(exc).__name__}")
            
    eventos_api = _deduplicate_event_records(eventos_api)
    print(f"   ✅ {len(eventos_api)} partidos PRE-MATCH verificados listos con mercados reales.")
    return eventos_api

# ============================================================
#  FASE 1: ESCÁNER RADAR DE SUPERFICIE
# ============================================================
def fase1_escaneo_superficie(driver, *, odds_api_key=None):
    print("\n" + "="*60)
    print("🕵️  FASE 1: ESCÁNER RADAR DE SUPERFICIE (Solo Hoy y Mañana)")
    print("="*60)
    
    partidos_data = []
    detail_cache = {}
    observed_playdoit = datetime.now(ZoneInfo("America/Mexico_City"))
    try:
        driver.get("https://www.playdoit.mx/es/")
        time.sleep(8)

        assert_playdoit_source_healthy(
            title=str(driver.title or ""),
            body=str(driver.find_element("tag name", "body").text or ""),
            source=str(driver.page_source or ""),
        )
        
        # Configuración inicial: Formato Decimal (sin restringir a solo hoy para captar Champions/mañana)
        click_decimal_toggle(driver)
        time.sleep(2)
        
        # Esperar hasta que Altenar termine de renderizar los eventos en pantalla
        eventos_iniciales = []
        for intento_carga in range(5):
            eventos_iniciales = extract_events_from_page(
                driver,
                observed_at=observed_playdoit,
                detail_cache=detail_cache,
            )
            if eventos_iniciales:
                break
            time.sleep(2)
            
        print(f"   📡 Cartelera detectada con {len(eventos_iniciales)} eventos principales.")
        for e in eventos_iniciales:
            es_valido_tiempo, horario_limpio = es_partido_futuro_valido(
                e.get('horario') or ''
            )
            if not es_valido_tiempo:
                continue
            e['horario'] = horario_limpio
            partidos_data.append(e)
        
        # 2. Exploración de categorías específicas adicionales (Champions, Liga MX, Premier, MLB, KBO, etc.)
        categorias = [
            'UEFA Champions League', 'Liga MX', 'Premier League', 'La Liga', 
            'Serie A', 'Bundesliga', 'Ligue 1', 'MLB', 'KBO', 
            'UEFA Europa League', 'Copa Libertadores', 'MLS', 'NFL'
        ]
        
        for cat in categorias:
            print(f"   Explorando: {cat}...", end=" ")
            if click_category(driver, cat):
                time.sleep(3.5)
                eventos = []
                for _ in range(4):
                    eventos = extract_events_from_page(
                        driver,
                        observed_at=observed_playdoit,
                        fallback_league=cat,
                        fallback_sport=_sport_for_category(cat),
                        detail_cache=detail_cache,
                    )
                    if eventos: break
                    time.sleep(2.0)
                nuevos = 0
                for e in eventos:
                    es_valido_tiempo, horario_limpio = es_partido_futuro_valido(
                        e.get('horario') or ''
                    )
                    if not es_valido_tiempo:
                        continue

                    e['horario'] = horario_limpio
                    partidos_data.append(e)
                    nuevos += 1
                print(f"✅ {nuevos} nuevos futuros" if nuevos else "⏭️ sin nuevos")
            else:
                print("⚠️ no encontrada")
    except PlaydoitSourceError:
        raise
    except Exception as e:
        print(f"   ⚠️ Nota en escáner Playdoit; failure={type(e).__name__}")
    
    # Si la lista inicial en Playdoit tuviera pocos eventos o fuera entre semana (martes/miércoles)
    partidos_data = _deduplicate_event_records(partidos_data)
    coverage = _verified_market_coverage(partidos_data)
    print(
        "   market_coverage="
        f"h2h:{coverage['h2h']} "
        f"totals:{coverage['totals']} "
        f"spreads:{coverage['spreads']} "
        f"source_markets:{coverage['source_markets']}"
    )
    if len(partidos_data) < 4:
        print(f"\n   🌐 Cartelera en Playdoit reducida ({len(partidos_data)}). Conectando satélite The Odds API...")
        api_events = obtener_eventos_odds_api(odds_api_key)
        partidos_data = _deduplicate_event_records(partidos_data + api_events)
        
    print(f"\n   📊 Total eventos únicos de HOY/MAÑANA para análisis: {len(partidos_data)}")
    return partidos_data

# ============================================================
#  FASE 2: COMPARACIÓN CON MERCADO (The Odds API)
# ============================================================
def fase2_comparacion_mercado(
    partidos_data, *, odds_api_key=None, observed_at=None
):
    print("\n" + "="*60)
    print("📈  FASE 2: COMPARACIÓN CON CUOTAS DEL MERCADO")
    print("="*60)
    
    active_odds_api_key = odds_api_key or ODDS_API_KEY
    if not active_odds_api_key:
        print("   ⚠️ No hay ODDS_API_KEY. Saltando comparación de mercado.")
        print("   ℹ️ Para activar esta función, agrega ODDS_API_KEY en tu .env")
        return {}
    
    try:
        market_odds = {}
        observed = observed_at or datetime.now(ZoneInfo("UTC"))

        for sport_key in SUPPORTED_SPORT_KEYS:
            try:
                raw_events = fetch_odds_events(
                    active_odds_api_key,
                    sport_key,
                    regions=("us",),
                    markets=("h2h",),
                    timeout=10.0,
                    opener=urllib.request.urlopen,
                )
                normalized_events = []
                for raw_event in raw_events:
                    try:
                        normalized_events.append(
                            normalize_odds_event(raw_event, observed)
                        )
                    except (KeyError, TypeError, ValueError, OverflowError) as exc:
                        print(
                            f"   ⚠️ Evento inválido en {sport_key}; "
                            f"failure={type(exc).__name__}"
                        )

                for event in normalized_events:
                    for market in event.markets:
                        if market.key != "h2h":
                            continue
                        for key, team in (
                            ("home", event.home_team),
                            ("away", event.away_team),
                        ):
                            price = market.outcome(key).price
                            market_odds.setdefault(team.casefold(), []).append(price)

                print(
                    f"   ✅ {sport_key}: {len(normalized_events)} "
                    "eventos del mercado global."
                )
            except OddsSourceError as exc:
                print(f"   ⚠️ Error consultando {sport_key}; {exc}")
            except Exception as exc:
                print(
                    f"   ⚠️ Error consultando {sport_key}; "
                    f"failure={type(exc).__name__}"
                )

        averaged_odds = {
            team: round(sum(prices) / len(prices), 2)
            for team, prices in market_odds.items()
        }
        
        print(f"   📊 {len(averaged_odds)} cuotas de referencia del mercado obtenidas.")
        return averaged_odds
        
    except Exception as e:
        print(f"   ❌ Error general en comparación de mercado; failure={type(e).__name__}")
        return {}

def ejecutar_groq_con_fallback(
    client,
    messages,
    temperature=0.2,
    *,
    response_format=None,
    message_char_limit=4000,
    truncate_messages=True,
):
    """Ejecuta la llamada a Groq rotando inteligentemente con reintentos y pausa backoff."""
    modelos = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "groq/compound-mini",
        "qwen/qwen3.6-27b"
    ]
    import re
    if (
        isinstance(message_char_limit, bool)
        or not isinstance(message_char_limit, int)
        or message_char_limit <= 0
    ):
        return ""

    # Truncar mensajes excesivamente largos para evitar error 413. Callers
    # carrying structured JSON can disable truncation and fail closed instead.
    mensajes_limpios = []
    truncation_marker = "\n[...datos sintetizados...]"
    for m in messages:
        c = m.get("content", "")
        if len(c) > message_char_limit:
            if not truncate_messages:
                return ""
            prefix_length = max(0, message_char_limit - len(truncation_marker))
            c = c[:prefix_length] + truncation_marker
        mensajes_limpios.append({"role": m["role"], "content": c})

    for intento in range(2):
        for modelo in modelos:
            try:
                request = dict(
                    messages=mensajes_limpios,
                    model=modelo,
                    temperature=temperature,
                )
                if response_format is not None:
                    request["response_format"] = response_format
                resp = client.chat.completions.create(
                    **request,
                ).choices[0].message.content.strip()
                if resp:
                    resp = re.sub(r'<think>.*?</think>', '', resp, flags=re.DOTALL).strip()
                    return resp
            except Exception as e:
                if "429" in str(e) or "rate_limit" in str(e).lower():
                    print(f"   ⚠️ Rate limit en {modelo}. Pausando 3s para reintentar...")
                    time.sleep(3)
                    continue
                else:
                    print(f"   ⚠️ Nota en Groq ({modelo}); failure={type(e).__name__}")
                    continue
    return ""

# ============================================================
#  FASE 3: FILTRO INTELIGENTE (Top 8 por Groq)
# ============================================================
def fase3_filtro_inteligente(partidos_data, *, groq_api_key=None):
    print("\n" + "="*60)
    print("🧠  FASE 3: FILTRO INTELIGENTE (Groq selecciona Top 8 Pre-Match Multideporte)")
    print("="*60)
    
    if not partidos_data:
        return []
    
    client = Groq(api_key=groq_api_key or GROQ_API_KEY)
    
    # Filtrar solo eventos con horario futuro y priorizar deportes principales
    eventos_filtrados = []
    for p in partidos_data:
        es_val, h_limpio = es_partido_futuro_valido(p.get('horario') or '')
        if es_val:
            eventos_filtrados.append({
                "cat": p['categoria'],
                "partido": p['partido'],
                "horario": h_limpio,
                "cuotas": p.get('cuotas_superficie', [])[:3]
            })
            
    catalogo = eventos_filtrados[:30]
    
    prompt = f"""
    Catálogo de {len(catalogo)} eventos deportivos de HOY/MAÑANA.
    REGLA CRÍTICA PRE-MATCH:
    - Selecciona ÚNICAMENTE partidos que AÚN NO HAYAN COMENZADO.
    - Asegura MÁXIMA DIVERSIDAD: Incluir UEFA Champions League, Liga MX, Béisbol MLB y Béisbol KBO (para madrugadores).
    
    {json.dumps(catalogo)}
    
    Devuelve SOLO un JSON array de strings con los nombres exactos de los 8 mejores partidos.
    Ejemplo: ["Dinamo Zagreb vs Qarabag FK", "Kia Tigers vs Kiwoom Heroes", "NY Yankees vs BAL Orioles"]
    """
    
    try:
        response = ejecutar_groq_con_fallback(client, [{"role": "user", "content": prompt}], temperature=0.1)
        raw_objetivos = []
        try:
            inicio = response.find('[')
            fin = response.rfind(']') + 1
            if inicio != -1 and fin > inicio:
                raw_objetivos = json.loads(response[inicio:fin])
        except Exception:
            for m in re.finditer(r'"([^"]+vs[^"]+)"', response, re.IGNORECASE):
                raw_objetivos.append(m.group(1))
        
        # Validar estrictamente contra partidos reales y eliminar duplicados
        objetivos_unicos = []
        for obj in raw_objetivos:
            match_p = next((p['partido'] for p in partidos_data if p['partido'].lower() == obj.lower() or obj.lower() in p['partido'].lower() or p['partido'].lower() in obj.lower()), None)
            if match_p and match_p not in objetivos_unicos:
                objetivos_unicos.append(match_p)
        
        # Asegurar balance multideporte obligatorio (Champions + KBO + MLB + Fútbol)
        champs = [p['partido'] for p in partidos_data if ('champions' in p.get('categoria', '').lower() or 'uefa' in p.get('categoria', '').lower())]
        kbo = [p['partido'] for p in partidos_data if ('kbo' in p.get('categoria', '').lower() or 'corea' in p.get('categoria', '').lower())]
        mlb = [p['partido'] for p in partidos_data if ('mlb' in p.get('categoria', '').lower() or 'béisbol' in p.get('categoria', '').lower()) and p['partido'] not in kbo]
        otros = [p['partido'] for p in partidos_data if p['partido'] not in champs and p['partido'] not in mlb and p['partido'] not in kbo]
        
        objetivos_finales = []
        if champs: objetivos_finales.extend(champs[:2])
        if kbo: objetivos_finales.extend(kbo[:2])
        for obj in objetivos_unicos:
            if obj not in objetivos_finales and len(objetivos_finales) < 8:
                objetivos_finales.append(obj)
                
        if len(objetivos_finales) < 8:
            for p in (mlb + otros + champs + kbo):
                if p not in objetivos_finales and len(objetivos_finales) < 8:
                    objetivos_finales.append(p)
            
        print(f"   ✅ {len(objetivos_finales)} objetivos multideporte únicos listos para inmersión:")
        for i, obj in enumerate(objetivos_finales, 1):
            print(f"      {i}. {obj}")
        return objetivos_finales
    except Exception as e:
        print(f"   ⚠️ Nota en filtro IA; failure={type(e).__name__}. Aplicando balanceador multideporte...")
        # Selección balanceada: Champions League + KBO + MLB + Liga MX / Fútbol
        champs = [p['partido'] for p in partidos_data if 'champions' in p.get('categoria', '').lower() or 'uefa' in p.get('categoria', '').lower()]
        kbo = [p['partido'] for p in partidos_data if 'kbo' in p.get('categoria', '').lower() or 'corea' in p.get('categoria', '').lower()]
        mlb = [p['partido'] for p in partidos_data if ('mlb' in p.get('categoria', '').lower() or 'béisbol' in p.get('categoria', '').lower()) and p['partido'] not in kbo]
        otros = [p['partido'] for p in partidos_data if p['partido'] not in champs and p['partido'] not in mlb and p['partido'] not in kbo]
        
        balanceados = champs[:2] + kbo[:2] + mlb[:2] + otros[:2]
        if len(balanceados) < 8:
            balanceados += [p['partido'] for p in partidos_data if p['partido'] not in balanceados]
        return balanceados[:8]

# ============================================================
#  FASE 4: INMERSIÓN QUIRÚRGICA (Insights, Córners, Crear Apuesta)
# ============================================================
def _resolve_deep_objective(objective, events):
    """Resolve one exact unique event; text-only doubleheaders are ambiguous."""

    requested_source_id = ""
    requested_source = ""
    if isinstance(objective, dict):
        requested_match = _normalized_event_identity(objective.get('partido'))
        requested_source_id = str(
            objective.get('source_event_id') or ''
        ).strip()
        requested_source = str(objective.get('source') or '').strip().casefold()
    else:
        requested_match = _normalized_event_identity(objective)
    if requested_match is None:
        return None

    matches = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if _normalized_event_identity(event.get('partido')) != requested_match:
            continue
        event_source_id = str(event.get('source_event_id') or '').strip()
        event_source = str(event.get('source') or '').strip().casefold()
        if requested_source_id and event_source_id != requested_source_id:
            continue
        if requested_source and event_source != requested_source:
            continue
        matches.append(event)
    return matches[0] if len(matches) == 1 else None


def fase4_inmersion(driver, objetivos, partidos_data):
    """Use only already structured markets; unbounded deep DOM tabs are disabled."""

    print("\n" + "="*60)
    print("🎯  FASE 4: MERCADOS ESTRUCTURADOS VERIFICADOS")
    print("="*60)
    datos_profundos = []
    for i, objective in enumerate(objetivos, 1):
        base = _resolve_deep_objective(objective, partidos_data)
        if base is None:
            print(
                f"\n   [{i}/{len(objetivos)}] Omitido sin identidad exacta: "
                f"{objective}"
            )
            continue
        verified = base.get('mercados_reales')
        market_text = (
            "\n".join(str(item) for item in verified)[:1200]
            if isinstance(verified, list)
            else ""
        )
        datos_profundos.append({**base, "mercados_profundos": market_text})
    print(
        f"\n   📊 Inmersión completada: {len(datos_profundos)} "
        "partidos con evidencia estructurada."
    )
    return datos_profundos

# ============================================================
#  FASE 5: MEMORIA HISTÓRICA
# ============================================================
def fase5_memoria_historica(database=None):
    print("\n" + "="*60)
    print("📚  FASE 5: RECUPERANDO MEMORIA HISTÓRICA")
    print("="*60)
    
    active_database = database or supabase
    if not active_database:
        return "Sin conexión a base de datos."
    
    try:
        res = active_database.table("picks").select("categoria, partido, pick, cuota, estado, fecha_generacion").order("id", desc=True).limit(30).execute()
        picks = res.data
        
        if not picks:
            print("   ℹ️ Sin historial previo. Primera ejecución.")
            return "Sin historial previo. Esta es la primera ejecución del sistema."
        
        ganados = sum(1 for p in picks if p.get('estado') == 'ganado')
        perdidos = sum(1 for p in picks if p.get('estado') == 'perdido')
        pendientes = sum(1 for p in picks if p.get('estado', 'pendiente') == 'pendiente')
        
        memoria = f"""RESUMEN DE RENDIMIENTO:
- Total picks recientes: {len(picks)}
- Ganados: {ganados} | Perdidos: {perdidos} | Pendientes: {pendientes}
- Win Rate: {round(ganados/(ganados+perdidos)*100, 1) if (ganados+perdidos) > 0 else 0}%

PICKS RECIENTES:
"""
        for p in picks[:15]:
            estado = p.get('estado', 'pendiente')
            emoji = '✅' if estado == 'ganado' else '❌' if estado == 'perdido' else '⏳'
            memoria += f"  {emoji} {p.get('partido')} → {p.get('pick')} @ {p.get('cuota')} [{estado}]\n"
        
        print(f"   ✅ Memoria cargada: {len(picks)} picks, {ganados}W-{perdidos}L")
        return memoria
    except Exception as e:
        print(f"   ⚠️ Error leyendo historial; failure={type(e).__name__}")
        return "Error leyendo historial."

# ============================================================
#  FASE 6: ANÁLISIS FINAL — DEBATE Y CONSENSO MULTI-IA
# ============================================================
def _collect_verified_candidates(records) -> list[CandidatePick]:
    """Deduplicate exact private candidates and omit conflicting identities."""

    selected: dict[str, CandidatePick] = {}
    order: list[str] = []
    conflicts: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        private_candidates = record.get(_VERIFIED_CANDIDATES_FIELD)
        if not isinstance(private_candidates, tuple):
            continue
        for candidate in private_candidates:
            if not _is_individually_valid(candidate):
                continue
            candidate_id = candidate.candidate_id
            if candidate_id in conflicts:
                continue
            existing = selected.get(candidate_id)
            if existing is None:
                selected[candidate_id] = candidate
                order.append(candidate_id)
            elif existing != candidate:
                selected.pop(candidate_id, None)
                conflicts.add(candidate_id)
    return [
        selected[candidate_id]
        for candidate_id in order
        if candidate_id in selected
    ]


def _candidate_prompt_row(candidate: CandidatePick) -> dict[str, object]:
    """Serialize only read-only catalog facts, never the private object field."""

    return {
        "candidate_id": candidate.candidate_id,
        "source": candidate.source,
        "source_event_id": candidate.source_event_id,
        "bookmaker_key": candidate.bookmaker_key,
        "starts_at": candidate.starts_at.isoformat(),
        "observed_at": candidate.observed_at.isoformat(),
        "sport": candidate.sport,
        "league": candidate.league,
        "home_team": candidate.home_team,
        "away_team": candidate.away_team,
        "market_key": candidate.market_key,
        "market_name": candidate.market_name or candidate.market_key,
        "source_market_id": candidate.source_market_id,
        "period": candidate.period,
        "line": candidate.line,
        "selection_key": candidate.selection_key,
        "selection_name": candidate.selection_name,
        "source_selection_id": candidate.source_selection_id,
        "market_scope": candidate.market_scope,
        "participant_id": candidate.participant_id,
        "team_id": candidate.team_id,
        "competitor_id": candidate.competitor_id,
        "offer_kind": candidate.offer_kind,
        "offer_description": candidate.offer_description,
        "source_market_selection_ids": (
            candidate.source_market_selection_ids
        ),
        "lineup_confirmed": candidate.lineup_confirmed,
        "price": candidate.price,
    }


def _render_candidate_ranking_prompt(candidates) -> str:
    prompt_catalog = [_candidate_prompt_row(candidate) for candidate in candidates]
    catalog_json = json.dumps(
        prompt_catalog,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""
Ordena los candidatos verificados de mayor a menor utilidad editorial.
Los hechos del catálogo son de SOLO LECTURA: no cambies partido, mercado,
selección, horario, fuente, casa de apuestas ni cuota.

CATÁLOGO VERIFICADO:
{catalog_json}

Devuelve ÚNICAMENTE este objeto JSON:
{{"rankings": [{{"candidate_id": "ID exacto del catálogo", "rationale": "Explicación de 10 a 500 caracteres"}}]}}
No devuelvas partido, pick, cuota, precio, confianza, valor ni parlays.
"""


def _bounded_prompt_candidates(candidates):
    """Choose complete deterministic groups that fit both request bounds."""

    ordered = sorted(
        candidates,
        key=lambda candidate: (candidate.starts_at, candidate.candidate_id),
    )
    grouped = {}
    for candidate in ordered:
        grouped.setdefault(
            _candidate_exclusivity_group(candidate),
            [],
        ).append(candidate)

    selected = []
    prompt = _render_candidate_ranking_prompt(selected)
    for group in grouped.values():
        if len(selected) + len(group) > MAX_AI_CATALOG_CANDIDATES:
            continue
        trial = [*selected, *group]
        trial_prompt = _render_candidate_ranking_prompt(trial)
        total_chars = len(_AI_RANKING_SYSTEM_MESSAGE) + len(trial_prompt)
        if total_chars > MAX_AI_PROMPT_CHARS:
            continue
        selected = trial
        prompt = trial_prompt
    return selected, prompt


def _parse_strict_json_array(raw_response):
    """Parse one JSON array, optionally inside a complete Markdown fence."""

    if not isinstance(raw_response, str):
        return []
    clean_response = raw_response.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        clean_response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced is not None:
        clean_response = fenced.group(1).strip()

    def reject_non_finite_constant(_value):
        raise ValueError("non-finite JSON constants are not allowed")

    try:
        parsed = json.loads(
            clean_response,
            parse_constant=reject_non_finite_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and set(parsed) == {"rankings"}:
        rankings = parsed.get("rankings")
        return rankings if isinstance(rankings, list) else []
    return []


def _candidate_schedule(candidate: CandidatePick) -> str:
    start = candidate.starts_at.astimezone(ZoneInfo("America/Mexico_City"))
    observed = candidate.observed_at.astimezone(
        ZoneInfo("America/Mexico_City")
    )
    if start.date() == observed.date():
        return f"Hoy {start.strftime('%H:%M')} hrs"
    if start.date() == observed.date() + timedelta(days=1):
        return f"Mañana {start.strftime('%H:%M')} hrs"
    return start.strftime("%d/%m %H:%M hrs")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _legacy_ranked_pick_projection(
    ranked_pick: RankedPick,
    evidence_score: EvidenceScore,
) -> dict[str, object]:
    """Copy catalog facts plus a bounded data-support score, never win odds."""

    candidate = ranked_pick.candidate
    return {
        "source": candidate.source,
        "source_event_id": candidate.source_event_id,
        "bookmaker_key": candidate.bookmaker_key,
        "starts_at": candidate.starts_at.isoformat(),
        "observed_at": candidate.observed_at.isoformat(),
        "sport": candidate.sport,
        "categoria": candidate.league,
        "liga": candidate.league,
        "partido": f"{candidate.home_team} vs {candidate.away_team}",
        "local": candidate.home_team,
        "visitante": candidate.away_team,
        "horario": _candidate_schedule(candidate),
        "fecha_evento": candidate.starts_at.astimezone(
            ZoneInfo("America/Mexico_City")
        ).date().isoformat(),
        "market_key": candidate.market_key,
        "mercado": candidate.market_name or candidate.market_key,
        "period": candidate.period,
        "line": candidate.line,
        "selection_key": candidate.selection_key,
        "selection_name": candidate.selection_name,
        "pick": candidate.selection_name,
        "cuota": candidate.price,
        "source_market_key": _source_market_audit_key(candidate),
        "source_selection_key": (
            candidate.source_selection_id or candidate.selection_key
        ),
        "source_observed_at": candidate.observed_at.astimezone(
            timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "source_starts_at": candidate.starts_at.astimezone(
            timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "razonamiento": ranked_pick.rationale,
        "confianza": f"{evidence_score.percent}% respaldo de datos",
        "riesgo": evidence_score.label,
        "tiene_valor": evidence_score.has_value,
        "es_parlay": False,
    }


def _fase6_candidate_ranking(
    datos_profundos,
    partidos_data,
    *,
    groq_api_key,
    reference_at=None,
):
    records = list(datos_profundos or ()) + list(partidos_data or ())
    candidates = _collect_verified_candidates(records)
    if not groq_api_key or not candidates:
        return []

    try:
        catalog_reference_at = (
            datetime.now(timezone.utc)
            if reference_at is None
            else reference_at
        )
        if (
            catalog_reference_at.tzinfo is None
            or catalog_reference_at.utcoffset() is None
        ):
            return []
        candidates = [
            candidate
            for candidate in candidates
            if candidate.starts_at.astimezone(timezone.utc)
            > catalog_reference_at.astimezone(timezone.utc)
        ]
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    if not candidates:
        return []

    prompt_candidates, prompt = _bounded_prompt_candidates(candidates)
    if not prompt_candidates:
        return []
    messages = [
        {"role": "system", "content": _AI_RANKING_SYSTEM_MESSAGE},
        {"role": "user", "content": prompt},
    ]
    if sum(len(message["content"]) for message in messages) > MAX_AI_PROMPT_CHARS:
        return []
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "verified_candidate_ranking",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "rankings": {
                        "type": "array",
                        "maxItems": MAX_AI_RANKED_PICKS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "candidate_id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 2000,
                                },
                                "rationale": {
                                    "type": "string",
                                    "minLength": 10,
                                    "maxLength": 500,
                                },
                            },
                            "required": ["candidate_id", "rationale"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["rankings"],
                "additionalProperties": False,
            },
        },
    }
    try:
        client = Groq(api_key=groq_api_key)
        raw_response = ejecutar_groq_con_fallback(
            client,
            messages,
            temperature=0.1,
            response_format=response_format,
            message_char_limit=MAX_AI_PROMPT_CHARS,
            truncate_messages=False,
        )
    except Exception as exc:
        print(f"   ⚠️ Ranking IA no disponible; failure={type(exc).__name__}")
        return []

    raw_ranking = _parse_strict_json_array(raw_response)
    ranked = validate_ai_ranking(raw_ranking, prompt_candidates)
    try:
        evidence_reference_at = (
            datetime.now(timezone.utc)
            if reference_at is None
            else reference_at
        )
        ranked = [
            row
            for row in ranked
            if row.candidate.starts_at.astimezone(timezone.utc)
            > evidence_reference_at.astimezone(timezone.utc)
        ]
    except (AttributeError, TypeError, ValueError, OverflowError):
        return []
    picks = []
    for row in ranked:
        evidence = evidence_for_candidate(
            row.candidate,
            candidates,
            reference_at=evidence_reference_at,
        )
        picks.append(
            _legacy_ranked_pick_projection(row, score_evidence(evidence))
        )
    print(f"   🏆 Ranking verificado: {len(picks)} selecciones de catálogo.")
    for pick in picks:
        print(
            f"      → [{pick['categoria']}] {pick['partido']} | "
            f"{pick['pick']} @ {pick['cuota']}"
        )
    return picks


def fase6_analisis_final(
    datos_profundos,
    memoria,
    market_odds,
    partidos_data=None,
    *,
    groq_api_key=None,
    reference_at=None,
):
    if partidos_data is None:
        partidos_data = datos_profundos
    return _fase6_candidate_ranking(
        datos_profundos,
        partidos_data,
        groq_api_key=groq_api_key or GROQ_API_KEY,
        reference_at=reference_at,
    )


# ============================================================
#  FASE 7: GUARDADO Y NOTIFICACIONES
# ============================================================
def fase7_guardar_y_notificar(
    picks,
    *,
    repository=None,
    settings=None,
    transport=None,
    run_key,
    clock: Callable[[], datetime] | None = None,
    deliver: bool = True,
    write_public: bool = True,
):
    """Publish one atomic batch, then deliver each Telegram destination independently."""
    print("\n" + "="*60)
    print("💾  FASE 7: GUARDANDO Y NOTIFICANDO")
    print("="*60)

    if type(deliver) is not bool or type(write_public) is not bool:
        raise ValueError("delivery and public projection flags must be boolean")
    if not picks:
        print("   ❌ No hay picks para guardar.")
        return None, {}

    active_settings = settings or load_settings(dry_run=False)
    if repository is None:
        require_publish_backend()
        repository = SupabaseBatchRepository(supabase)

    hoy = datetime.now(ZoneInfo("America/Mexico_City")).date().isoformat()
    visible_picks = assign_visibility(picks)
    clean_picks = []
    for pick in visible_picks:
        prepared = dict(pick)
        prepared['fecha_generacion'] = hoy
        event_date = prepared.get('fecha_evento')
        try:
            if not isinstance(event_date, str):
                raise ValueError("missing verified event date")
            date.fromisoformat(event_date)
        except (TypeError, ValueError):
            event_date = scheduled_event_date(prepared.get('horario'), hoy)
        prepared['fecha_evento'] = event_date
        prepared['estado'] = 'pendiente'
        prepared['liga'] = prepared.get('liga') or prepared.get(
            'categoria', 'Fútbol Internacional'
        )
        prepared.setdefault('ganancia_simulada', 0)
        clean_picks.append(
            {
                key: value
                for key, value in prepared.items()
                if key in PERSISTED_PICK_COLUMNS
            }
        )

    # Public storage never receives premium rows or the public pick's rationale.
    persisted_picks = []
    for pick in clean_picks:
        persisted = dict(pick)
        if persisted.get('visibility') == 'public':
            persisted.pop('razonamiento', None)
        persisted_picks.append(persisted)

    picks = persisted_picks
    free_picks = public_payload(picks)
    if len(free_picks) != 1 or free_picks[0].get('es_parlay'):
        raise ValueError("La publicación requiere exactamente un pick público no parlay.")

    active_run_key = str(run_key or "").strip()
    if not active_run_key:
        raise RuntimeError(
            "No hay una clave estable de corrida; configura SCRAPER_RUN_KEY."
        )

    try:
        active_clock = clock or _utc_now
        publication = AuditedBatchPublisher(
            repository=repository,
            run_key=active_run_key,
            public_path=active_settings.public_picks_path,
            clock=active_clock,
        ).publish(
            picks,
            dry_run=False,
            write_public=write_public,
        )
    except Exception:
        raise PersistenceFailure("scraper batch persistence failed") from None
    print(f"   ✅ Lote {publication.batch_id} publicado atómicamente.")
    deliveries = {}
    if deliver:
        deliveries = _deliver_persisted_publication(
            publication,
            repository,
            active_settings,
            transport=transport,
            clock=active_clock,
        )
    return publication, deliveries


def _deliver_persisted_publication(
    publication,
    repository,
    settings,
    *,
    transport=None,
    clock: Callable[[], datetime] | None = None,
):
    """Deliver only destinations absent from the persisted success ledger."""
    try:
        validated_picks = revalidate_persisted_picks(
            publication.picks,
            reference_at=(clock or _utc_now)(),
        )
    except (RuntimeError, TypeError, ValueError):
        try:
            Path(settings.public_picks_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise PersistenceFailure("stale persisted picks") from None
    delivery_picks = [dict(row) for row in validated_picks]

    destinations = [
        TelegramDestination("admin", settings.telegram_admin_id, "all")
        if settings.telegram_admin_id
        else None,
        TelegramDestination("vip", settings.telegram_vip_id, "all")
        if settings.telegram_vip_id
        else None,
        TelegramDestination("free", settings.telegram_free_id, "public")
        if settings.telegram_free_id
        else None,
    ]
    active_destinations = [destination for destination in destinations if destination]

    if not active_destinations:
        print("   ℹ️ No hay destinos de Telegram configurados.")
        return {}

    completed = frozenset(
        name
        for name, status in publication.delivery_status.items()
        if status is True
        or (isinstance(status, dict) and status.get('success') is True)
    )
    pending_destinations = [
        destination
        for destination in active_destinations
        if destination.name not in completed
    ]
    if not pending_destinations:
        return {
            destination.name: DeliveryResult(success=True, skipped=True)
            for destination in active_destinations
        }

    if transport is None and not settings.telegram_token:
        print("   ❌ Falta el token de Telegram; se registraron las entregas como fallidas.")
        deliveries = {
            destination.name: (
                DeliveryResult(success=True, skipped=True)
                if destination.name in completed
                else DeliveryResult(
                    success=False,
                    error="missing_telegram_token",
                )
            )
            for destination in active_destinations
        }
    else:
        if transport is None:
            transport = TelegramHttpTransport(settings.telegram_token)
        deliveries = deliver_batch(
            delivery_picks,
            active_destinations,
            transport,
            completed=completed,
        )

    if publication.run_id is None:
        raise PersistenceFailure("scraper batch persistence failed")
    record_failures = []
    for destination, result in deliveries.items():
        if result.skipped:
            continue
        try:
            repository.record_delivery(
                publication.run_id,
                destination,
                result.success,
                result.error,
            )
        except Exception:
            record_failures.append(destination)
            print(f"   ❌ No se pudo registrar la entrega Telegram {destination}.")
            continue
        outcome = "✅" if result.success else "❌"
        print(f"   {outcome} Entrega Telegram {destination}.")

    if record_failures:
        raise DeliveryFailure(
            "No se pudieron registrar entregas de Telegram: "
            + ", ".join(record_failures)
        )

    return deliveries

# ============================================================
#  MAIN: SAFE COMMAND BOUNDARY AND LEGACY PIPELINE ADAPTER
# ============================================================
class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIGURATION = 2
    NO_EVENTS = 3
    NO_CANDIDATES = 4
    PERSISTENCE = 5
    DELIVERY = 6
    SOURCE = 7
    UNEXPECTED = 10


@dataclass(frozen=True, slots=True)
class FrozenPick(Mapping[str, object]):
    """Immutable scalar mapping that remains pickle/asdict serializable."""

    _items: tuple[tuple[str, object], ...]

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)


_UNSET_PIPELINE_PICKS = object()


@dataclass(frozen=True, init=False)
class PipelineResult:
    event_count: int
    pick_count: int
    persisted: bool
    failed_deliveries: tuple[str, ...]
    picks: tuple[FrozenPick, ...]

    def __init__(
        self,
        event_count: int,
        pick_count: int,
        persisted: bool,
        failed_deliveries: Sequence[str],
        picks: object = _UNSET_PIPELINE_PICKS,
    ) -> None:
        provided_picks = picks is not _UNSET_PIPELINE_PICKS
        frozen_picks = () if not provided_picks else _freeze_pipeline_picks(picks)
        _check_pipeline_result_fields(
            event_count,
            pick_count,
            persisted,
            failed_deliveries,
        )
        if provided_picks and pick_count != len(frozen_picks):
            raise ValueError("invalid pipeline result")
        object.__setattr__(self, "event_count", event_count)
        object.__setattr__(self, "pick_count", pick_count)
        object.__setattr__(self, "persisted", persisted)
        object.__setattr__(self, "failed_deliveries", tuple(failed_deliveries))
        object.__setattr__(self, "picks", frozen_picks)


def run_structured_pipeline(
    events,
    ranker,
    publisher,
    *,
    dry_run,
    reference_at=None,
):
    """Rank and publish only facts copied from normalized sportsbook evidence."""

    try:
        normalized_events = list(events)
    except Exception:
        return PipelineResult(0, 0, False, ())
    event_count = len(normalized_events)
    if type(dry_run) is not bool:
        return PipelineResult(event_count, 0, False, ())

    try:
        candidates = build_candidates(normalized_events)
    except Exception:
        return PipelineResult(event_count, 0, False, ())
    if not candidates:
        return PipelineResult(event_count, 0, False, ())

    try:
        reference = (
            datetime.now(timezone.utc)
            if reference_at is None
            else reference_at
        )
        if (
            not isinstance(reference, datetime)
            or reference.tzinfo is None
            or reference.utcoffset() is None
        ):
            return PipelineResult(event_count, 0, False, ())
        candidates = [
            candidate
            for candidate in candidates
            if (
                candidate.starts_at.astimezone(timezone.utc)
                > reference.astimezone(timezone.utc)
            )
        ]
        if not candidates:
            return PipelineResult(event_count, 0, False, ())
    except Exception:
        return PipelineResult(event_count, 0, False, ())

    try:
        raw_ranking = ranker(tuple(candidates))
    except Exception:
        return PipelineResult(event_count, 0, False, ())
    ranked = validate_ai_ranking(raw_ranking, candidates)
    if not ranked:
        return PipelineResult(event_count, 0, False, ())

    try:
        source_backed_rows = []
        for ranked_pick in ranked:
            evidence = evidence_for_candidate(
                ranked_pick.candidate,
                candidates,
                reference_at=reference,
            )
            if evidence.source_count == 0:
                return PipelineResult(event_count, 0, False, ())
            score = score_evidence(evidence)
            row = _source_backed_pick_row(ranked_pick, score, reference)
            if not _valid_source_audit_row(row, reference_at=reference):
                return PipelineResult(event_count, 0, False, ())
            source_backed_rows.append(row)
        visible_rows = assign_visibility(source_backed_rows)
        for visible_row in visible_rows:
            if visible_row.get("visibility") == "public":
                visible_row.pop("razonamiento", None)
        visible_rows = [
            {
                key: value
                for key, value in visible_row.items()
                if key in PERSISTED_PICK_COLUMNS
            }
            for visible_row in visible_rows
        ]
    except Exception:
        return PipelineResult(event_count, 0, False, ())

    if not _valid_visible_source_rows(visible_rows, reference_at=reference):
        return PipelineResult(event_count, 0, False, ())

    frozen_rows = _freeze_pipeline_picks(visible_rows)
    publisher_rows = [dict(row) for row in frozen_rows]
    try:
        publication = publisher.publish(publisher_rows, dry_run=dry_run)
    except Exception:
        return PipelineResult(
            event_count,
            len(frozen_rows),
            False,
            (),
            frozen_rows,
        )

    try:
        persisted = _publication_was_persisted(publication, dry_run=dry_run)
    except Exception:
        persisted = False
    return PipelineResult(
        event_count,
        len(frozen_rows),
        persisted,
        (),
        frozen_rows,
    )


def _source_market_audit_key(candidate: CandidatePick) -> str:
    identity = [
        candidate.bookmaker_key,
        candidate.market_key,
        candidate.period,
        _canonical_line(candidate.line),
    ]
    if candidate.source_market_id is not None:
        identity.append(candidate.source_market_id)
        identity.append({
            "scope": candidate.market_scope,
            "participant_id": candidate.participant_id,
            "team_id": candidate.team_id,
            "competitor_id": candidate.competitor_id,
            "offer_kind": candidate.offer_kind,
            "lineup_confirmed": candidate.lineup_confirmed,
        })
    return "market:v1:" + json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _source_backed_pick_row(
    ranked_pick: RankedPick,
    evidence_score: EvidenceScore,
    reference_at: datetime,
) -> dict[str, object]:
    candidate = ranked_pick.candidate
    row = _legacy_ranked_pick_projection(ranked_pick, evidence_score)
    row.update(
        {
            "source": candidate.source,
            "source_event_id": candidate.source_event_id,
            "source_market_key": _source_market_audit_key(candidate),
            "source_selection_key": (
                candidate.source_selection_id or candidate.selection_key
            ),
            "source_observed_at": candidate.observed_at.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "source_starts_at": candidate.starts_at.astimezone(
                timezone.utc
            ).isoformat().replace("+00:00", "Z"),
            "fecha_generacion": reference_at.astimezone(
                ZoneInfo("America/Mexico_City")
            ).date().isoformat(),
            "fecha_evento": candidate.starts_at.astimezone(
                ZoneInfo("America/Mexico_City")
            ).date().isoformat(),
            "estado": "pendiente",
            "ganancia_simulada": 0,
        }
    )
    return row


def _valid_source_audit_row(
    row: object,
    *,
    reference_at: datetime | None = None,
) -> bool:
    if not isinstance(row, Mapping):
        return False
    text_limits = {
        "source": 100,
        "source_event_id": 500,
        "source_market_key": 1000,
        "source_selection_key": 500,
        "source_observed_at": 100,
        "source_starts_at": 100,
    }
    for field, maximum_length in text_limits.items():
        value = row.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum_length
        ):
            return False
    observed_at = row.get("source_observed_at")
    starts_at = row.get("source_starts_at")
    utc_pattern = re.compile(
        r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:[.][0-9]{1,6})?(?:Z|[+]00:00)$"
    )
    if (
        not isinstance(observed_at, str)
        or not isinstance(starts_at, str)
        or utc_pattern.fullmatch(observed_at) is None
        or utc_pattern.fullmatch(starts_at) is None
    ):
        return False
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        parsed_starts_at = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        reference = _utc_now() if reference_at is None else reference_at
    except (AttributeError, TypeError, ValueError):
        return False
    if (
        parsed_observed_at.utcoffset() != timedelta(0)
        or parsed_starts_at.utcoffset() != timedelta(0)
        or reference.tzinfo is None
        or reference.utcoffset() is None
        or parsed_observed_at > reference.astimezone(timezone.utc)
        or parsed_starts_at <= parsed_observed_at
        or parsed_starts_at <= reference.astimezone(timezone.utc)
    ):
        return False
    price = row.get("cuota")
    maximum_price = 50.0
    source_market_key = row.get("source_market_key")
    if (
        isinstance(source_market_key, str)
        and source_market_key.startswith("market:v1:")
        and isinstance(row.get("source"), str)
        and str(row["source"]).casefold() == "playdoit"
    ):
        try:
            market_identity = json.loads(
                source_market_key.removeprefix("market:v1:")
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            market_identity = None
        if (
            isinstance(market_identity, list)
            and len(market_identity) == 6
            and market_identity[0] == "playdoit"
            and isinstance(market_identity[1], str)
            and isinstance(market_identity[2], str)
            and market_identity[2].strip()
            and market_identity[3] is None
            and isinstance(market_identity[4], str)
            and market_identity[4].strip()
            and market_identity[1]
            == f"playdoit_market:{market_identity[4]}".casefold()
            and isinstance(market_identity[5], dict)
            and set(market_identity[5]) == {
                "scope",
                "participant_id",
                "team_id",
                "competitor_id",
                "offer_kind",
                "lineup_confirmed",
            }
            and isinstance(market_identity[5].get("scope"), str)
            and isinstance(market_identity[5].get("offer_kind"), str)
            and isinstance(
                market_identity[5].get("lineup_confirmed"), bool
            )
            and all(
                value is None or (
                    isinstance(value, str) and bool(value.strip())
                )
                for value in (
                    market_identity[5].get("participant_id"),
                    market_identity[5].get("team_id"),
                    market_identity[5].get("competitor_id"),
                )
            )
            and (
                (
                    market_identity[5].get("participant_id") is None
                    and str(market_identity[5].get("scope")).casefold()
                    not in {"player", "participant", "player_prop"}
                )
                or market_identity[5].get("lineup_confirmed") is True
            )
        ):
            maximum_price = 1000.0
    return (
        type(row.get("tiene_valor")) is bool
        and isinstance(row.get("confianza"), str)
        and isinstance(row.get("riesgo"), str)
        and isinstance(price, (int, float))
        and not isinstance(price, bool)
        and math.isfinite(float(price))
        and 1.01 <= float(price) <= maximum_price
    )


def _valid_visible_source_rows(
    rows: object,
    *,
    reference_at: datetime | None = None,
) -> bool:
    if not isinstance(rows, list) or not rows:
        return False
    if not all(
        _valid_source_audit_row(row, reference_at=reference_at)
        for row in rows
    ):
        return False
    public_rows = [row for row in rows if row.get("visibility") == "public"]
    return (
        len(public_rows) == 1
        and public_rows[0].get("es_parlay") is False
        and all(row.get("visibility") in {"public", "premium"} for row in rows)
    )


def _freeze_pipeline_picks(picks: object) -> tuple[FrozenPick, ...]:
    if isinstance(picks, (str, bytes)) or not isinstance(picks, Sequence):
        raise ValueError("invalid pipeline picks")
    frozen = []
    for pick in picks:
        if not isinstance(pick, Mapping):
            raise ValueError("invalid pipeline picks")
        copied = {}
        for key, value in pick.items():
            if not isinstance(key, str) or not isinstance(
                value,
                (str, int, float, bool, type(None)),
            ):
                raise ValueError("invalid pipeline picks")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("invalid pipeline picks")
            copied[key] = value
        frozen.append(FrozenPick(tuple(copied.items())))
    return tuple(frozen)


def _publication_was_persisted(publication: object, *, dry_run: bool) -> bool:
    if type(dry_run) is not bool:
        return False
    try:
        response_dry_run = getattr(publication, "dry_run")
        created = getattr(publication, "created")
        run_id = getattr(publication, "run_id")
        batch_id = getattr(publication, "batch_id")
    except Exception:
        return False
    if type(response_dry_run) is not bool or response_dry_run is not dry_run:
        return False
    if type(created) is not bool:
        return False
    if dry_run:
        return False
    return (
        isinstance(run_id, str)
        and bool(run_id.strip())
        and isinstance(batch_id, str)
        and bool(batch_id.strip())
    )


def _check_pipeline_result_fields(
    event_count,
    pick_count,
    persisted,
    failed_deliveries,
):
    if type(event_count) is not int or event_count < 0:
        raise ValueError("invalid pipeline result")
    if type(pick_count) is not int or pick_count < 0:
        raise ValueError("invalid pipeline result")
    if type(persisted) is not bool:
        raise ValueError("invalid pipeline result")
    if isinstance(failed_deliveries, (str, bytes)) or not isinstance(
        failed_deliveries, Sequence
    ):
        raise ValueError("invalid pipeline result")
    if any(
        type(name) is not str
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,49}", name) is None
        for name in failed_deliveries
    ):
        raise ValueError("invalid pipeline result")
    if event_count == 0 and pick_count != 0:
        raise ValueError("invalid pipeline result")
    if pick_count == 0 and (persisted or failed_deliveries):
        raise ValueError("invalid pipeline result")
    if failed_deliveries and not persisted:
        raise ValueError("invalid pipeline result")


def _validated_pipeline_result(result, *, dry_run):
    try:
        event_count = result.event_count
        pick_count = result.pick_count
        persisted = result.persisted
        failed_deliveries = result.failed_deliveries
    except AttributeError:
        raise ValueError("invalid pipeline result") from None

    _check_pipeline_result_fields(
        event_count,
        pick_count,
        persisted,
        failed_deliveries,
    )
    if dry_run and (persisted or failed_deliveries):
        raise ValueError("invalid pipeline result")
    return PipelineResult(
        event_count,
        pick_count,
        persisted,
        tuple(failed_deliveries),
    )


def _schema_status_data(data):
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    return data if isinstance(data, dict) else None


def _schema_boolean_data(data):
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    return data is True


def probe_secure_schema(client):
    """Fail closed using a read-only RPC supplied by the scraper migration."""
    try:
        response = client.rpc("scraper_schema_status", {}).execute()
        status = _schema_status_data(response.data)
    except Exception:
        status = None
    if (
        status is None
        or type(status.get("version")) is not int
        or status.get("version") != 2
        or status.get("public_picks") is not True
        or status.get("publish_pick_batch") is not True
        or status.get("resume_pick_batch") is not True
        or status.get("source_audit") is not True
    ):
        raise ConfigError("secure Supabase scraper migration is not applied")
    try:
        response = client.rpc("picks_policy_allowlist_status", {}).execute()
        policy_allowlist_ok = _schema_boolean_data(response.data)
    except Exception:
        policy_allowlist_ok = False
    if not policy_allowlist_ok:
        raise ConfigError("secure Supabase scraper migration is not applied")


def _cleanup_chrome_driver(driver):
    """Quit once and disable undetected_chromedriver's destructor double-quit.

    On Windows, the upstream Chrome.__del__ calls ``quit`` again after manual
    cleanup and can raise ``WinError 6``. Instance replacement is deliberately
    limited to that concrete upstream class; ordinary drivers keep their normal
    method and the first cleanup failure still propagates.
    """
    driver_type = type(driver)
    is_undetected_chrome = driver_type.__name__ == "Chrome" and (
        driver_type.__module__ == "undetected_chromedriver"
        or driver_type.__module__.startswith("undetected_chromedriver.")
    )
    try:
        driver.quit()
    finally:
        if is_undetected_chrome:
            driver.quit = lambda: None


class LegacyPipeline:
    """Injectable adapter around the existing collection and publication phases."""

    def __init__(
        self,
        settings,
        *,
        repository=None,
        history_client=None,
        driver_factory=None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.history_client = history_client
        self.driver_factory = driver_factory or get_chrome_driver
        self.clock = clock or _utc_now

    def run(self, *, collect_only=False, deliver_only=False):
        if type(collect_only) is not bool or type(deliver_only) is not bool:
            raise ValueError("runtime mode flags must be boolean")
        if collect_only and deliver_only:
            raise ValueError("runtime modes are mutually exclusive")
        if self.settings.dry_run and (collect_only or deliver_only):
            raise ValueError("dry-run cannot use production runtime modes")

        print("\n" + "=" * 60)
        print("🌮  REY TACO PICKS BOT v5.0  🌮")
        print(
            "   Arquitectura: Escáner → Mercado → Filtro → "
            "Inmersión → Memoria → IA → Picks"
        )
        print("=" * 60)
        print(f"dry_run={str(self.settings.dry_run).lower()}")

        if not self.settings.dry_run:
            try:
                publication = AuditedBatchPublisher(
                    repository=self.repository,
                    run_key=self.settings.run_key,
                    public_path=self.settings.public_picks_path,
                    clock=self.clock,
                ).resume(
                    dry_run=False,
                    write_public=not (collect_only or deliver_only),
                )
            except Exception:
                raise PersistenceFailure("scraper batch persistence failed") from None
            if publication is not None:
                if collect_only:
                    print("collect_only=resumed")
                    deliveries = {}
                else:
                    print("resume_only=true")
                    deliveries = _deliver_persisted_publication(
                        publication,
                        self.repository,
                        self.settings,
                        clock=self.clock,
                    )
                failed = tuple(
                    sorted(
                        name
                        for name, result in deliveries.items()
                        if not result.success
                    )
                )
                persisted_rows = tuple(dict(row) for row in publication.picks)
                return PipelineResult(
                    len(persisted_rows),
                    len(persisted_rows),
                    True,
                    failed,
                    persisted_rows,
                )

            if deliver_only:
                return PipelineResult(0, 0, False, ())

        driver = self.driver_factory()
        try:
            partidos = fase1_escaneo_superficie(
                driver, odds_api_key=self.settings.odds_api_key
            )
            if not partidos:
                return PipelineResult(0, 0, False, ())

            market_odds = fase2_comparacion_mercado(
                partidos, odds_api_key=self.settings.odds_api_key
            )
            objetivos = fase3_filtro_inteligente(
                partidos, groq_api_key=self.settings.groq_api_key
            )
            datos_profundos = fase4_inmersion(driver, objetivos, partidos)
            memoria = fase5_memoria_historica(self.history_client)
            picks = fase6_analisis_final(
                datos_profundos,
                memoria,
                market_odds,
                partidos,
                groq_api_key=self.settings.groq_api_key,
            )
            if not picks:
                return PipelineResult(len(partidos), 0, False, ())

            if self.settings.dry_run:
                print(
                    f"dry_run=true events={len(partidos)} candidates={len(picks)} "
                    "persistence=skipped telegram=skipped"
                )
                return PipelineResult(len(partidos), len(picks), False, ())

            publication, deliveries = fase7_guardar_y_notificar(
                picks,
                repository=self.repository,
                settings=self.settings,
                run_key=self.settings.run_key,
                clock=self.clock,
                deliver=not collect_only,
                write_public=not collect_only,
            )
            failed = tuple(
                sorted(
                    name
                    for name, result in deliveries.items()
                    if not result.success
                )
            )
            persisted = bool(publication and publication.run_id)
            return PipelineResult(len(partidos), len(picks), persisted, failed)
        finally:
            _cleanup_chrome_driver(driver)
            print("🔒 Navegador cerrado.")


def build_pipeline(
    settings: ScraperSettings,
    *,
    client_factory=None,
    schema_probe=None,
    driver_factory=None,
):
    """Build production dependencies, probing secure schema before Chrome."""
    if settings.dry_run:
        return LegacyPipeline(settings, driver_factory=driver_factory)

    active_client_factory = client_factory or create_client
    active_probe = schema_probe or probe_secure_schema
    try:
        client: Any = active_client_factory(
            settings.supabase_url, settings.service_role_key
        )
    except Exception:
        raise ConfigError("could not initialize secure Supabase scraper client") from None
    active_probe(client)
    return LegacyPipeline(
        settings,
        repository=SupabaseBatchRepository(client),
        history_client=client,
        driver_factory=driver_factory,
    )


def parse_args(argv=None):
    parser = ArgumentParser(description="Rey Taco Picks scraper")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--collect-only", action="store_true")
    modes.add_argument("--deliver-only", action="store_true")
    return parser.parse_args(argv)


def run_main(argv=None, *, values=None, pipeline=None):
    args = parse_args(argv)
    try:
        settings_values = {} if args.dry_run and values is None else values
        settings = load_settings(settings_values, dry_run=args.dry_run)
        active_pipeline = pipeline or build_pipeline(settings)
        if args.collect_only:
            raw_result = active_pipeline.run(collect_only=True)
        elif args.deliver_only:
            raw_result = active_pipeline.run(deliver_only=True)
        else:
            raw_result = active_pipeline.run()
        result = _validated_pipeline_result(raw_result, dry_run=settings.dry_run)
        if (
            args.deliver_only
            and result.event_count == 0
            and result.pick_count == 0
            and not result.persisted
            and not result.failed_deliveries
        ):
            print("deliver_only=no_batch")
            return ExitCode.SUCCESS
        if result.event_count == 0:
            return ExitCode.NO_EVENTS
        if result.pick_count == 0:
            return ExitCode.NO_CANDIDATES
        if not settings.dry_run and not result.persisted:
            return ExitCode.PERSISTENCE
        if result.failed_deliveries:
            return ExitCode.DELIVERY
        return ExitCode.SUCCESS
    except ConfigError as error:
        print(f"configuration_error={_safe_configuration_error(error)}")
        return ExitCode.CONFIGURATION
    except PersistenceFailure:
        print("persistence_error=PersistenceFailure")
        return ExitCode.PERSISTENCE
    except DeliveryFailure:
        print("delivery_error=DeliveryFailure")
        return ExitCode.DELIVERY
    except PlaydoitSourceError as error:
        print(f"source_error={error.code}")
        return ExitCode.SOURCE
    except Exception as error:
        print(f"unexpected_error={type(error).__name__}")
        return ExitCode.UNEXPECTED


def _safe_configuration_error(error):
    message = str(error)
    if message.startswith("Required scraper configuration missing:"):
        return message
    if message in {
        "secure Supabase scraper migration is not applied",
        "could not initialize secure Supabase scraper client",
    }:
        return message
    return "invalid scraper configuration"


def main():
    return run_main()


if __name__ == "__main__":
    raise SystemExit(run_main())
