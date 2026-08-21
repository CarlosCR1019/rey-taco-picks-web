from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
import os
import json
import time
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import undetected_chromedriver as uc
import urllib.request
from groq import Groq
from supabase import create_client

from backend.publishing_policy import assign_visibility, event_labels_share_date, public_payload, scheduled_event_date
from backend.odds_source import (
    OddsSourceError,
    SUPPORTED_MARKETS,
    SUPPORTED_SPORT_KEYS,
    fetch_odds_events,
    normalize_odds_event,
)
from backend.pick_publisher import SupabaseBatchRepository, publish_batch
from backend.scraper_config import ConfigError, ScraperSettings, load_settings
from backend.telegram_publisher import DeliveryResult, TelegramDestination, TelegramHttpTransport, deliver_batch

# Forzar codificación UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Legacy phase helpers retain optional module defaults for backwards-compatible
# direct calls. The command path injects values loaded by scraper_config instead
# of reading dotenv or creating a privileged client during import.
GROQ_API_KEY = ""
ODDS_API_KEY = ""
SUPABASE_SERVICE_ROLE_KEY = ""
supabase = None


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

def normalizar_cuota_decimal(val, default="1.85"):
    try:
        val_str = str(val).strip()
        m = re.search(r'([+-]?\d+(?:\.\d+)?)', val_str)
        if not m: return default
        n = float(m.group(1))
        if n > 50:
            return f"{round((n / 100) + 1, 2):.2f}"
        elif n < -50:
            return f"{round((100 / abs(n)) + 1, 2):.2f}"
        elif 1.01 <= n <= 50.0:
            return f"{n:.2f}"
        else:
            return default
    except Exception:
        return default

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

def get_chrome_driver():
    def make_options():
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-gpu")
        
        # Modo headless para la nube (GitHub Actions / CI)
        is_ci = os.getenv("CI") or os.getenv("GITHUB_ACTIONS")
        if is_ci:
            options.add_argument("--headless=new")
        return options, is_ci

    opts, is_ci = make_options()
    if is_ci:
        print("   ☁️ Modo NUBE detectado (headless)")
    else:
        print("   🖥️ Modo LOCAL detectado (con ventana)")

    chrome_ver = get_chrome_version()
    if chrome_ver:
        print(f"   🌐 Google Chrome v{chrome_ver} detectado")
        try:
            fresh_opts, _ = make_options()
            return uc.Chrome(options=fresh_opts, version_main=chrome_ver)
        except Exception as e:
            print(f"   ⚠️ Intentando inicialización estándar; failure={type(e).__name__}")

    try:
        fresh_opts, _ = make_options()
        return uc.Chrome(options=fresh_opts)
    except Exception:
        fresh_opts, _ = make_options()
        return uc.Chrome(options=fresh_opts, version_main=None)

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
    script = get_shadow_script() + f"""
    try {{
        var shadow = getShadow();
        if (!shadow) return false;
        var all = Array.from(shadow.querySelectorAll('*'));
        var catLower = '{catLower}';
        
        var match = all.find(n => {{
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
        }});
        
        if (match) {{
            (match.parentElement || match).click();
            match.click();
            return true;
        }}
        return false;
    }} catch(e) {{ return false; }}
    """
    return driver.execute_script(script)

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
                
            # Si es de una fecha lejana (> 30 horas, ej. 19/08, 21/08, 22/08)
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

def extract_events_from_page(driver):
    """Extrae ÚNICAMENTE eventos PRE-MATCH directamente de Playdoit y convierte momios a Decimal."""
    script = get_shadow_script() + """
    var shadow = getShadow();
    if(!shadow) return [];
    
    var containers = Array.from(shadow.querySelectorAll('div[class*="EventBoxContainer"]'));
    var result = [];

    containers.forEach(function(c) {
        try {
            var rawText = c.innerText.trim();
            // Descartar solo si realmente tiene marcador en juego terminado o esports/virtuales
            if (/e-fútbol|esports|virtual|cyber|2x4\\s*min|2x5\\s*min|gt\\s*sports/i.test(rawText)) return;

            var lines = rawText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);

            // 1. Extraer Fecha y Hora
            var timeLine = lines.find(l => /^(?:0?[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$/.test(l)) || "Hoy";
            var dateLine = lines.find(l => /\\d{1,2}[\\/\\-]\\d{1,2}/.test(l)) || "18/08";
            var horario = dateLine + " " + timeLine + " hrs";

            // 2. Extraer Nombres de Equipos
            var compEls = Array.from(c.querySelectorAll('[class*="CompetitorName"], [class*="Competitors"], [class*="NameContainer"], [class*="EventName"]'));
            var teamNames = compEls.map(el => el.innerText.trim()).filter(t => t.length >= 3);
            
            var local = teamNames[0] || "";
            var visitante = teamNames[1] || "";
            
            if (!local || !visitante) {
                var candidates = lines.filter(l => {
                    if (l.length < 3 || l.length > 35) return false;
                    if (/^(sgp|en vivo|live|hoy|mañana|resultado final|tiempo regular|hándicap|totales|ganador)$/i.test(l)) return false;
                    if (/^[\\+\\-]?\\d+(\\.\\d+)?$/.test(l)) return false;
                    if (/^\\d{1,2}[\\/\\:]\\d{1,2}/.test(l)) return false;
                    if (/champions|league|copa|mlb|premier|laliga|liga/i.test(l) && !/pumas|américa|chivas|santos|tigres|monterrey|cruz azul/i.test(l)) return false;
                    return true;
                });
                if (candidates.length >= 2) {
                    local = candidates[0];
                    visitante = candidates[1];
                }
            }

            // 3. Extraer y Normalizar Cuotas a Formato Decimal
            var oddsElements = c.querySelectorAll('button[class*="OddBoxButton-"], div[class*="OddBox-"], span[class*="OddValue-"], [class*="Price"], [class*="OddButton"]');
            var cuotas = [];
            oddsElements.forEach(function(o) {
                var val = o.innerText.trim();
                if (val) {
                    // Convertir formato americano a decimal ej: -143 -> 1.70, +100 -> 2.00, +260 -> 3.60
                    if (/^[+-]\\d+$/.test(val)) {
                        var n = parseFloat(val);
                        if (n > 0) {
                            val = ((n / 100) + 1).toFixed(2);
                        } else if (n < 0) {
                            val = ((100 / Math.abs(n)) + 1).toFixed(2);
                        }
                    }
                    cuotas.push(val);
                }
            });

            if (local && visitante) {
                // Limpiar nombres con abridores de MLB
                local = local.split('\\n')[0].trim();
                visitante = visitante.split('\\n')[0].trim();

                if (/^\\d+$/.test(local) || /^\\d+$/.test(visitante) || local.length < 3 || visitante.length < 3) return;
                if (local.toLowerCase() === visitante.toLowerCase()) return;

                result.push({
                    local: local,
                    visitante: visitante,
                    partido: local + " vs " + visitante,
                    horario: horario,
                    cuotas: cuotas,
                    texto_completo: rawText.replace(/\\n+/g, ' | ')
                });
            }
        } catch(e) {}
    });
    return result;
    """
    return driver.execute_script(script) or []

def _legacy_odds_projection(event):
    """Project a normalized event for legacy phases during the migration."""

    h2h = next((market for market in event.markets if market.key == "h2h"), None)
    named_h2h = {}
    surface_odds = []
    if h2h is not None:
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
                projected = _legacy_odds_projection(event)
                if not any(
                    row["partido"].casefold() == projected["partido"].casefold()
                    for row in eventos_api
                ):
                    eventos_api.append(projected)
        except OddsSourceError as exc:
            print(f"   ⚠️ Error en {sport_key}; {exc}")
        except Exception as exc:
            print(f"   ⚠️ Error en {sport_key}; failure={type(exc).__name__}")
            
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
    try:
        driver.get("https://www.playdoit.mx/es/")
        time.sleep(8)
        
        # Configuración inicial: Formato Decimal (sin restringir a solo hoy para captar Champions/mañana)
        click_decimal_toggle(driver)
        time.sleep(2)
        
        # Esperar hasta que Altenar termine de renderizar los eventos en pantalla
        eventos_iniciales = []
        for intento_carga in range(5):
            eventos_iniciales = extract_events_from_page(driver)
            if eventos_iniciales:
                break
            time.sleep(2)
            
        print(f"   📡 Cartelera detectada con {len(eventos_iniciales)} eventos principales.")
        for e in eventos_iniciales:
            nombre = f"{e['local']} vs {e['visitante']}"
            es_valido_tiempo, horario_limpio = es_partido_futuro_valido(e.get('horario', 'Hoy'))
            if not es_valido_tiempo:
                continue
            cat_real = inferir_categoria_deporte(e['local'], e['visitante'])
            if not any(x["partido"] == nombre for x in partidos_data):
                partidos_data.append({
                    "categoria": cat_real,
                    "partido": nombre,
                    "local": e['local'],
                    "visitante": e['visitante'],
                    "horario": horario_limpio,
                    "cuotas_superficie": e.get('cuotas', [])[:4],
                    "info_texto": f"{cat_real}: {nombre}. Horario: {horario_limpio}. Cuotas Playdoit: {' | '.join(e.get('cuotas', []))}"
                })
        
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
                    eventos = extract_events_from_page(driver)
                    if eventos: break
                    time.sleep(2.0)
                nuevos = 0
                for e in eventos:
                    nombre = f"{e['local']} vs {e['visitante']}"
                    es_valido_tiempo, horario_limpio = es_partido_futuro_valido(e.get('horario', 'Hoy'))
                    if not es_valido_tiempo:
                        continue
                    
                    cat_real = inferir_categoria_deporte(e['local'], e['visitante'], fallback=cat)
                    if not any(x["partido"] == nombre for x in partidos_data):
                        partidos_data.append({
                            "categoria": cat_real,
                            "partido": nombre,
                            "local": e['local'],
                            "visitante": e['visitante'],
                            "horario": horario_limpio,
                            "cuotas_superficie": e.get('cuotas', [])[:4],
                            "info_texto": f"{cat_real}: {nombre}. Horario: {horario_limpio}. Cuotas Playdoit: {' | '.join(e.get('cuotas', []))}"
                        })
                        nuevos += 1
                print(f"✅ {nuevos} nuevos futuros" if nuevos else "⏭️ sin nuevos")
            else:
                print("⚠️ no encontrada")
    except Exception as e:
        print(f"   ⚠️ Nota en escáner Playdoit; failure={type(e).__name__}")
    
    # Si la lista inicial en Playdoit tuviera pocos eventos o fuera entre semana (martes/miércoles)
    if len(partidos_data) < 4:
        print(f"\n   🌐 Cartelera en Playdoit reducida ({len(partidos_data)}). Conectando satélite The Odds API...")
        api_events = obtener_eventos_odds_api(odds_api_key)
        for ae in api_events:
            if not any(x["partido"].lower() == ae["partido"].lower() for x in partidos_data):
                partidos_data.append(ae)
        
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

def ejecutar_groq_con_fallback(client, messages, temperature=0.2):
    """Ejecuta la llamada a Groq rotando inteligentemente con reintentos y pausa backoff."""
    modelos = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "groq/compound-mini",
        "qwen/qwen3.6-27b"
    ]
    import re
    # Truncar mensajes excesivamente largos para evitar error 413
    mensajes_limpios = []
    for m in messages:
        c = m.get("content", "")
        if len(c) > 4000:
            c = c[:4000] + "\n[...datos sintetizados...]"
        mensajes_limpios.append({"role": m["role"], "content": c})

    for intento in range(2):
        for modelo in modelos:
            try:
                resp = client.chat.completions.create(
                    messages=mensajes_limpios,
                    model=modelo,
                    temperature=temperature
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
        es_val, h_limpio = es_partido_futuro_valido(p.get('horario', 'Hoy'))
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
def fase4_inmersion(driver, objetivos, partidos_data):
    print("\n" + "="*60)
    print("🎯  FASE 4: INMERSIÓN QUIRÚRGICA (Insights + Mercados Profundos)")
    print("="*60)
    
    datos_profundos = []
    
    for i, obj in enumerate(objetivos, 1):
        base = next((p for p in partidos_data if p['partido'].lower() == obj.lower() or obj.lower() in p['partido'].lower()), None)
        if not base:
            base = next((p for p in partidos_data if (p.get('local') and p.get('local').lower() in obj.lower()) or (p.get('visitante') and p.get('visitante').lower() in obj.lower())), None)
        if not base:
            base = partidos_data[min(i-1, len(partidos_data)-1)]
        
        print(f"\n   [{i}/{len(objetivos)}] Infiltrando: {obj}")
        
        # Clic confiable con mouse dispatch en el partido dentro del Shadow DOM
        script_click = f"""
        try {{
            var host = document.querySelector('div#altenar > div') || document.querySelector('asb-sports-app, asb-app, altenar-app');
            if (!host || !host.shadowRoot) return false;
            var shadow = host.shadowRoot;
            
            var containers = Array.from(shadow.querySelectorAll('div[class*="EventBoxContainer"]'));
            var targetContainer = containers.find(function(c) {{
                var t = c.innerText.toLowerCase();
                return t.includes("{base['local'].lower()}") || t.includes("{base['visitante'].lower()}");
            }});
            
            if(targetContainer) {{ 
                var clickEl = targetContainer.querySelector('div[class*="Competitors"], div[class*="NameContainer"], div[class*="EventName"], [class*="CompetitorName"]') || targetContainer;
                ['mousedown', 'click', 'mouseup'].forEach(function(evtType) {{
                    clickEl.dispatchEvent(new MouseEvent(evtType, {{ bubbles: true, cancelable: true, view: window }}));
                }});
                return true; 
            }}
            return false;
        }} catch(e) {{ return false; }}
        """
        
        clicked = driver.execute_script(script_click)
        if not clicked:
            # Reintentar navegando si estaba en otra vista
            click_category(driver, base.get('categoria', 'Liga MX'))
            time.sleep(2)
            clicked = driver.execute_script(script_click)
            
        if clicked:
            time.sleep(3)
            
            # PASO A: Extraer Pestañas Profundas (Tiros de Esquina, Goles, Tarjetas, Jugador)
            script_extract_deep = """
            try {
                var host = document.querySelector('div#altenar > div') || document.querySelector('asb-sports-app, asb-app, altenar-app');
                if (!host || !host.shadowRoot) return "";
                var shadow = host.shadowRoot;
                
                var tabsToExplore = ['tiros esquina', 'goles', 'tarjetas', 'especiales por jugador', 'crear apuesta'];
                var allNodes = Array.from(shadow.querySelectorAll('*'));
                var marketSummary = [];
                
                tabsToExplore.forEach(function(tabName) {
                    var tabEl = allNodes.find(function(n) {
                        return n.children.length === 0 && n.textContent && n.textContent.trim().toLowerCase().includes(tabName);
                    });
                    if (tabEl) {
                        try {
                            tabEl.click();
                            if (tabEl.parentElement) tabEl.parentElement.click();
                        } catch(e) {}
                    }
                    
                    var boxes = Array.from(shadow.querySelectorAll('[class*="MarketBox"], [class*="EventDetailsMarketBox"]'));
                    boxes.forEach(function(box) {
                        var titleEl = box.querySelector('[class*="MarketName"], [class*="Title"], [class*="HeaderMarket"]');
                        var title = titleEl ? titleEl.innerText.trim() : box.innerText.split('\\n')[0];
                        
                        var buttons = Array.from(box.querySelectorAll('button, [class*="OddBoxButton"], [class*="SelectionButton"]'));
                        var odds = buttons.map(function(b) {
                            return b.innerText.replace(/\\n+/g, ' ').trim();
                        }).filter(Boolean);
                        
                        if (odds.length > 0) {
                            var entry = "▶ MERCADO [" + title + "]: " + odds.join(" | ");
                            if (!marketSummary.includes(entry)) {
                                marketSummary.push(entry);
                            }
                        }
                    });
                });
                
                return marketSummary.join("\\n");
            } catch(e) { return ""; }
            """
            
            mercados_texto = driver.execute_script(script_extract_deep) or ""
            if mercados_texto:
                print(f"      🎯 {len(mercados_texto.splitlines())} Mercados profundos extraídos (Córners, Goles, Tarjetas).")
            
            # Regresar al listado general haciendo clic en el botón 'Volver' o pestaña principal
            script_back = """
            try {
                var host = document.querySelector('div#altenar > div') || document.querySelector('asb-sports-app, asb-app, altenar-app');
                if (host && host.shadowRoot) {
                    var backBtn = host.shadowRoot.querySelector('button[class*="BackButton"], [class*="HeaderBack"]');
                    if (backBtn) backBtn.click();
                }
            } catch(e) {}
            """
            driver.execute_script(script_back)
            time.sleep(1)
            
            datos_profundos.append({
                "categoria": base['categoria'],
                "partido": obj,
                "local": base.get('local', ''),
                "visitante": base.get('visitante', ''),
                "horario": base.get('horario', 'Hoy'),
                "cuotas_superficie": base.get('cuotas_superficie', []),
                "mercados_profundos": mercados_texto[:1200]
            })
        else:
            if base.get('mercados_reales'):
                base['mercados_profundos'] = "\n".join(base['mercados_reales'])[:1200]
                print(f"      🎯 Usando {len(base['mercados_reales'])} mercados verificados del satélite.")
            else:
                print("      ⚠️ No se pudo entrar al partido, usando cuotas de superficie.")
            datos_profundos.append(base)
    
    print(f"\n   📊 Inmersión completada: {len(datos_profundos)} partidos analizados a fondo.")
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
def fase6_analisis_final(
    datos_profundos,
    memoria,
    market_odds,
    partidos_data=None,
    *,
    groq_api_key=None,
):
    print("\n" + "="*60)
    print("🧠⚡  FASE 6: DEBATE Y CONSENSO MULTI-IA (Quant vs Auditor vs Juez)")
    print("="*60)
    
    if partidos_data is None:
        partidos_data = datos_profundos
        
    active_groq_api_key = groq_api_key or GROQ_API_KEY
    if not active_groq_api_key or not (datos_profundos or partidos_data):
        return []
    
    client = Groq(api_key=active_groq_api_key)
    
    # Contexto de mercado global
    market_context = ""
    if market_odds:
        market_context = f"""
CUOTAS PROMEDIO DEL MERCADO GLOBAL (15+ casas de apuestas):
{json.dumps(market_odds, indent=2)}
"""

    datos_partidos_str = json.dumps(datos_profundos, indent=2)

    # -------------------------------------------------------------
    # RONDA 1: IA CUANTITATIVA ("Alpha Quant")
    # Busca valor matemático (+EV), córners, combos y estadísticas.
    # -------------------------------------------------------------
    print("   🤖 [IA 1: Alpha Quant] Analizando mercados profundos (Córners, Combos, Props, Totales)...")
    prompt_quant = f"""
Eres "Alpha Quant", la IA líder en análisis cuantitativo y micro-estadísticas para apuestas deportivas de élite.
Analiza los siguientes partidos y mercados especiales:

{memoria}
{market_context}
DATOS DE PARTIDOS Y MERCADOS:
{datos_partidos_str}

REGLAS ESTRICTAS DE TAXONOMÍA DEPORTIVA (CERO TOLERANCIA A ERRORES):
1. FÚTBOL (Soccer / Liga MX / La Liga / Champions / Premier):
   - Mercados válidos: Tiros de Esquina (Córners ej. "Más de 8.5 Córners"), Ambos Anotan (BTTS), Over/Under Goles (ej. "Más de 2.5 Goles"), 1X2 / Doble Oportunidad, Hándicap Asiático, Tarjetas.
   - NUNCA uses términos de béisbol o americano en fútbol.
2. BÉISBOL (MLB):
   - Mercados válidos: Over/Under Carreras (ej. "Más de 8.5 Carreras"), Carreras en 1er Inning (ej. "Sin Carreras en el 1er Inning - NRFI" o "Más de 0.5 Carreras 1er Inning"), Ponches del Pitcher (ej. "Más de 6.5 Ponches"), Moneyline (-1.5 Run Line).
   - ¡PROHIBIDO ROTUNDAMENTE usar "Córners", "Goles" o "Tiros de esquina" en Béisbol! En béisbol son CARRERAS, HITS y PONCHES.
3. FÚTBOL AMERICANO (NFL):
   - Mercados válidos: Spread / Hándicap (ej. "-3.5"), Over/Under Puntos Totales (ej. "Más de 44.5 Puntos"), Player Props (ej. "Anotador de Touchdown", "Más de 75.5 Yardas").
   - ¡PROHIBIDO usar "Goles" o "Córners" en NFL! En americano son PUNTOS, TOUCHDOWNS y YARDAS.

REGLAS DE PARLAYS ESTRATÉGICOS:
- "Parlay Seguro": 2 selecciones de altísima probabilidad con cuota combinada 2.10 - 2.80.
- "Parlay Estadístico Córners/Props": 2 selecciones de micro-estadísticas (Córners de fútbol o Ponches/Carreras de MLB) cuota 2.70 - 3.80.
- "Parlay Rompe-Bancas (+EV)": 3 selecciones de alto valor combinado (cuota 4.50 - 7.50).

Devuelve tu catálogo cuantitativo con las justificaciones matemáticas respetando estrictamente la terminología de cada deporte.
"""
    try:
        resp_quant = ejecutar_groq_con_fallback(client, [{"role": "user", "content": prompt_quant}], temperature=0.2)
        print("   ✅ [Alpha Quant] Propuestas de córners, combos y parlays generadas.")
    except Exception as e:
        print(f"   ⚠️ Error en IA Quant; failure={type(e).__name__}")
        resp_quant = "Análisis quant no disponible."

    # -------------------------------------------------------------
    # RONDA 2: IA AUDITORA DE RIESGO ("Risk Auditor")
    # Audita trampas, líneas infladas de córners y correlación de parlays.
    # -------------------------------------------------------------
    print("   🛡️ [IA 2: Risk Auditor] Auditando riesgo en córners, combos y combinaciones de parlays...")
    prompt_auditor = f"""
Eres "Risk Auditor", auditor senior de gestión de riesgo en apuestas deportivas.
Revisa las propuestas de Alpha Quant:

PROPUESTAS DE ALPHA QUANT:
{resp_quant}

DATOS REALES:
{datos_partidos_str}

TAREA DE AUDITORÍA:
1. Verifica que la taxonomía deportiva sea 100% precisa (Córners y Goles SOLO en Fútbol; Carreras y Ponches SOLO en Béisbol; Puntos y Yardas SOLO en NFL). Rechaza cualquier propuesta que confunda deportes.
2. Evalúa si las líneas de Tiros de Esquina, Totales y Combos son realistas según el estilo de juego de los equipos.
3. Audita los Parlays: Asegúrate de que las selecciones combinadas tengan correlación positiva o bajo riesgo de cruzarse.
4. Si un pick o combinación es arriesgado, sugiere un ajuste más inteligente.

Devuelve tu dictamen de aprobación y ajustes recomendados.
"""
    try:
        resp_auditor = ejecutar_groq_con_fallback(client, [{"role": "user", "content": prompt_auditor}], temperature=0.2)
        print("   ✅ [Risk Auditor] Auditoría de riesgo y correlación completada.")
    except Exception as e:
        print(f"   ⚠️ Error en IA Auditor; failure={type(e).__name__}")
        resp_auditor = "Auditoría no disponible."

    # -------------------------------------------------------------
    # RONDA 3: IA JUEZ SUPREMO ("Chief Arbiter")
    # Emite la selección definitiva multideporte + Tiros de Esquina + 2 Parlays.
    # -------------------------------------------------------------
    print("   ⚖️ [IA 3: Chief Arbiter] Emitiendo cartera definitiva (Córners, Combos y Parlays Múltiples)...")
    prompt_juez = f"""
Eres el "Chief Odds Arbiter" de Rey Taco Picks. Emite la cartera oficial del día tras evaluar el debate.

REGLAS CRÍTICAS ESTRICTAS (CERO TOLERANCIA):
1. SELECCIONA ÚNICAMENTE PARTIDOS QUE ESTÉN EN LA LISTA DE DATOS REALES EXTRAÍDOS HOY. ESTÁ TOTALMENTE PROHIBIDO INVENTAR O USAR PARTIDOS DE OTROS DÍAS.
2. Utiliza exactamente el horario y nombres de equipos que vienen en los datos reales.
3. DIVERSIDAD MULTIDEPORTE OBLIGATORIA:
   - Incluye al menos 1 o 2 selecciones de UEFA Champions League.
   - Incluye al menos 1 o 2 selecciones de Béisbol KBO (Corea del Sur para madrugadores).
   - Incluye al menos 1 o 2 selecciones de Béisbol MLB.
   - Incluye al menos 1 o 2 Parlays combinados de alto valor (+EV).
4. Cuotas estrictamente en formato decimal (ej: 1.85, 1.62, 2.18, 3.11).
5. Explica claramente en el campo "razonamiento" el por qué táctico/estadístico de cada elección.

DATOS REALES DISPONIBLES DE PLAYDOIT HOY:
{datos_partidos_str}

DEBATE DE LOS EXPERTOS:
--- ALPHA QUANT ---
{resp_quant}

--- AUDITORÍA DE RIESGO ---
{resp_auditor}

--- CUOTAS DE MERCADO GLOBAL ---
{market_context}

Devuelve ÚNICAMENTE un JSON array válido con este formato:
[
    {{
        "categoria": "UEFA Champions League",
        "partido": "Nombre Real Local vs Nombre Real Visitante",
        "horario": "19/08 • 13:00",
        "pick": "Nombre Equipo Gana Directo",
        "cuota": "1.85",
        "confianza": "90%",
        "razonamiento": "Explicación táctica y estadística del pick...",
        "es_parlay": false,
        "tiene_valor": true,
        "odds_mercado": "1.80"
    }}
]
"""
    try:
        resp_final = ejecutar_groq_con_fallback(client, [
            {"role": "system", "content": "Devuelves únicamente JSON puro sin bloques markdown ni texto extra."},
            {"role": "user", "content": prompt_juez}
        ], temperature=0.15)

        # Extractor ultra robusto de JSON tolerante a texto alrededor
        clean_resp = re.sub(r'```(?:json)?', '', resp_final).strip()
        raw_picks = []
        try:
            idx1 = clean_resp.find('[')
            idx2 = clean_resp.rfind(']')
            if idx1 != -1 and idx2 != -1:
                raw_picks = json.loads(clean_resp[idx1:idx2+1])
        except Exception:
            for m in re.finditer(r'\{[^{}]*\}', clean_resp, re.DOTALL):
                try:
                    obj = json.loads(m.group(0))
                    if 'pick' in obj or 'partido' in obj:
                        raw_picks.append(obj)
                except Exception:
                    pass
        
        # -------------------------------------------------------------
        # VALIDACIÓN Y FILTRADO DETERMINISTA ANTI-ALUCINACIONES (PYTHON)
        # -------------------------------------------------------------
        picks_validados = []
        for p in raw_picks:
            p_partido = p.get('partido', '').strip()
            p_pick = p.get('pick')
            if not p_partido or not p_pick or str(p_pick).strip().lower() in ('none', '', 'null'):
                continue
            
            # 1. Verificar existencia contra partidos reales escaneados
            match_encontrado = None
            for dp in (datos_profundos + partidos_data):
                dp_partido = dp.get('partido', '').lower()
                dp_local = dp.get('local', '').lower()
                dp_vis = dp.get('visitante', '').lower()
                
                if (dp_local and len(dp_local) > 3 and dp_local in p_partido.lower()) or \
                   (dp_vis and len(dp_vis) > 3 and dp_vis in p_partido.lower()) or \
                   (dp_partido and dp_partido in p_partido.lower()) or \
                   (p_partido.lower() in dp_partido):
                    match_encontrado = dp
                    break
            
            # Si es parlay, validar que TODAS las partes existan
            if p.get('es_parlay'):
                partes = re.split(r'[+&/]|(?:\s+y\s+)', p_partido, flags=re.IGNORECASE)
                parlay_matches = []
                for parte in partes:
                    parte = parte.strip()
                    if len(parte) < 3: continue
                    leg_match = next(
                        (dp for dp in (datos_profundos + partidos_data) if
                         (dp.get('local', '') and len(dp.get('local', '')) > 3 and dp.get('local', '').lower() in parte.lower()) or
                         (dp.get('visitante', '') and len(dp.get('visitante', '')) > 3 and dp.get('visitante', '').lower() in parte.lower()) or
                         (dp.get('partido', '').lower() in parte.lower()) or
                         (parte.lower() in dp.get('partido', '').lower())),
                        None,
                    )
                    if not leg_match:
                        parlay_matches = []
                        break
                    parlay_matches.append(leg_match)
                
                parlay_horarios = [leg.get('horario', 'Hoy') for leg in parlay_matches]
                fecha_base = datetime.now(ZoneInfo("America/Mexico_City")).date().isoformat()
                if len(parlay_matches) >= 2 and event_labels_share_date(parlay_horarios, fecha_base):
                    match_encontrado = parlay_matches[0]
                    p['horario'] = " / ".join(parlay_horarios)
                else:
                    match_encontrado = None
            
            if not match_encontrado:
                print(f"   🛑 DESCARTADO (Partido o pierna de parlay no existe en catálogo): {p_partido}")
                continue

            # 2. Asignar categoría exacta
            if p.get('es_parlay'):
                p['categoria'] = "Parlays +EV"
            else:
                p['categoria'] = inferir_categoria_deporte(
                    match_encontrado.get('local', ''), 
                    match_encontrado.get('visitante', ''), 
                    fallback=match_encontrado.get('categoria', 'Fútbol Internacional')
                )

            # 3. Corregir y forzar Horario Real y verificar que sea futuro en CDMX
            if not p.get('es_parlay') and match_encontrado and match_encontrado.get('horario'):
                p['horario'] = match_encontrado.get('horario')
            
            es_valido_tiempo, horario_limpio = es_partido_futuro_valido(p.get('horario', 'Hoy'))
            if not es_valido_tiempo:
                print(f"   🛑 DESCARTADO (El partido ya inició): {p_partido} [{p.get('horario')}]")
                continue
            p['horario'] = horario_limpio
            
            # 4. Limpieza y Normalización Matemática de Cuota
            p['cuota'] = normalizar_cuota_decimal(p.get('cuota', '1.85'))
            
            if not p.get('razonamiento') or len(p.get('razonamiento', '')) < 10:
                p['razonamiento'] = "Consenso IA: Ventaja matemática +EV detectada con alta probabilidad según métricas de Playdoit."

            picks_validados.append(p)

        if len(picks_validados) >= 3:
            picks = picks_validados
            print(f"\n   🏆 CARTERA APROBADA ({len(picks)} selecciones validadas):")
            for p in picks:
                print(f"      → [{p.get('categoria')}] {p.get('partido')} | {p.get('pick')} @ {p.get('cuota')}")
            return picks
        else:
            raise ValueError(f"Solo {len(picks_validados)} picks validados, activando generador de respaldo...")
            
    except Exception as e:
        print(f"   ⚠️ Nota en síntesis de debate IA; failure={type(e).__name__}. Activando generador de cartera cuantitativa...")
        
        # Generador de respaldo cuantitativo 100% DINÁMICO e infalible
        picks_fallback = []
        parlay_candidatos = []
        
        pool_partidos = list(datos_profundos) + [p for p in partidos_data if not any(x['partido'] == p['partido'] for x in datos_profundos)]
        
        for dp in pool_partidos:
            partido = dp.get('partido', '')
            local = dp.get('local', '')
            vis = dp.get('visitante', '')
            horario = dp.get('horario', 'Hoy')
            mercados = dp.get('mercados_profundos', '') or dp.get('info_texto', '')
            cuotas_sup = dp.get('cuotas_superficie', [])
            categoria = inferir_categoria_deporte(local, vis, fallback=dp.get('categoria', 'Fútbol Internacional'))
            
            es_valido, horario_limpio = es_partido_futuro_valido(horario)
            if not es_valido: continue
            
            # A) Totales Over/Under (Córners, Goles en fútbol o Carreras en MLB/KBO)
            match_totals = re.search(r'(?:más\s+de|over)\s*\(?\s*(\d+\.5)\s*\)?\s*(?:@\s*)?([+-]?\d+(?:\.\d+)?)', mercados, re.IGNORECASE)
            if match_totals and len(picks_fallback) < 8:
                linea = match_totals.group(1)
                raw_c = match_totals.group(2)
                c_val_str = normalizar_cuota_decimal(raw_c if raw_c else "1.75")
                c_val = float(c_val_str)
                
                f_linea = float(linea)
                if categoria in ["MLB", "KBO"] or "baseball" in categoria.lower() or "béisbol" in categoria.lower():
                    if not (6.5 <= f_linea <= 13.5): continue
                    unidad = "Carreras Totales"
                    cat_nombre = categoria
                elif "NFL" in categoria or "football" in categoria.lower():
                    if not (36.5 <= f_linea <= 58.5): continue
                    unidad = "Puntos Totales"
                    cat_nombre = "NFL"
                else:
                    # Fútbol (Champions, Liga MX, MLS, etc.)
                    if 7.5 <= f_linea <= 13.5:
                        unidad = "Tiros de Esquina"
                        cat_nombre = "Tiros de Esquina"
                    elif 1.5 <= f_linea <= 4.5:
                        unidad = "Goles Totales"
                        cat_nombre = categoria
                    else:
                        continue
                
                p_item = {
                    "categoria": cat_nombre,
                    "partido": partido,
                    "local": local or partido.split(' vs ')[0],
                    "horario": horario_limpio,
                    "pick": f"Más de {linea} {unidad}",
                    "cuota": f"{c_val:.2f}",
                    "confianza": "90%",
                    "razonamiento": "Consenso Quant: Ventaja estadística en ritmo ofensivo y promedio histórico proyectado en Playdoit.",
                    "es_parlay": False,
                    "tiene_valor": True,
                    "odds_mercado": f"{max(1.30, c_val - 0.05):.2f}"
                }
                picks_fallback.append(p_item)
                if c_val <= 1.85:
                    parlay_candidatos.append(p_item)
            
            # B) Buscar Línea de Dinero (ML) o Hándicap
            if len(cuotas_sup) >= 1 and len(picks_fallback) < 6:
                try:
                    c_local_str = normalizar_cuota_decimal(cuotas_sup[0])
                    c_local = float(c_local_str)
                    if 1.20 <= c_local <= 2.25:
                        p_ml = {
                            "categoria": categoria,
                            "partido": partido,
                            "local": local or partido.split(' vs ')[0],
                            "horario": horario_limpio,
                            "pick": f"{local or partido.split(' vs ')[0]} Gana Directo",
                            "cuota": f"{c_local:.2f}",
                            "confianza": "89%",
                            "razonamiento": "Consenso Quant: Ventaja táctica y solvencia proyectada respaldada por cuotas de mercado.",
                            "es_parlay": False,
                            "tiene_valor": True,
                            "odds_mercado": f"{max(1.20, c_local - 0.05):.2f}"
                        }
                        if not any(x['partido'] == partido for x in picks_fallback):
                            picks_fallback.append(p_ml)
                        if c_local <= 1.80 and not any(x['partido'] == partido for x in parlay_candidatos):
                            parlay_candidatos.append(p_ml)
                except:
                    pass

        # Garantizar SIEMPRE al menos 3 picks activos diarios (para días como viernes/lunes)
        if len(picks_fallback) < 3 and partidos_data:
            for p in partidos_data:
                if len(picks_fallback) >= 3:
                    break
                partido_nom = p.get('partido', '')
                if any(x['partido'] == partido_nom for x in picks_fallback):
                    continue
                cuotas = p.get('cuotas_superficie', [])
                if cuotas:
                    c_val = float(normalizar_cuota_decimal(cuotas[0]))
                    picks_fallback.append({
                        "categoria": p.get('categoria', 'Fútbol Global'),
                        "partido": partido_nom,
                        "local": p.get('local', partido_nom.split(' vs ')[0]),
                        "horario": p.get('horario', 'Hoy'),
                        "pick": f"{p.get('local', partido_nom.split(' vs ')[0])} Gana o Empata (1X)" if c_val < 1.60 else f"{p.get('local', partido_nom.split(' vs ')[0])} Gana Directo",
                        "cuota": f"{max(1.35, c_val):.2f}",
                        "confianza": "91%",
                        "razonamiento": "Consenso Quant: Selección calculada de alta probabilidad matemática y valor esperado positivo.",
                        "es_parlay": False,
                        "tiene_valor": True,
                        "odds_mercado": f"{max(1.25, c_val - 0.05):.2f}"
                    })

        # C) Construir Parlay Combinado Dinámico con piernas del mismo día CDMX.
        parlay_pair = None
        fecha_base = datetime.now(ZoneInfo("America/Mexico_City")).date().isoformat()
        for index, p1 in enumerate(parlay_candidatos):
            for p2 in parlay_candidatos[index + 1:]:
                if event_labels_share_date([p1.get('horario'), p2.get('horario')], fecha_base):
                    parlay_pair = (p1, p2)
                    break
            if parlay_pair:
                break

        if parlay_pair:
            p1, p2 = parlay_pair
            cuota_parlay = float(p1['cuota']) * float(p2['cuota'])
            loc1 = p1.get('local') or p1['partido'].split(' vs ')[0]
            loc2 = p2.get('local') or p2['partido'].split(' vs ')[0]
            picks_fallback.append({
                "categoria": "Parlay Seguro",
                "partido": f"{p1['partido']} + {p2['partido']}",
                "horario": f"{p1.get('horario', 'Hoy')} / {p2.get('horario', 'Hoy')}",
                "pick": f"{loc1} ({p1['pick']}) & {loc2} ({p2['pick']})",
                "cuota": f"{cuota_parlay:.2f}",
                "confianza": "93%",
                "razonamiento": "Combinada matemática de alta correlación positiva y riesgo controlado.",
                "es_parlay": True,
                "tiene_valor": True,
                "odds_mercado": f"{max(1.80, cuota_parlay - 0.10):.2f}"
            })

        print(f"\n   🏆 CARTERA APROBADA ({len(picks_fallback)} selecciones de alta credibilidad desde Playdoit):")
        for p in picks_fallback:
            valor = " 💎 VALOR" if p.get('tiene_valor') else ""
            parlay = " 🔗 PARLAY" if p.get('es_parlay') else ""
            horario = f" [{p.get('horario')}]" if p.get('horario') else ""
            print(f"      → [{p.get('categoria')}]{horario} {p.get('partido')} | {p.get('pick')} @ {p.get('cuota')}{valor}{parlay}")
            
        return picks_fallback

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
):
    """Publish one atomic batch, then deliver each Telegram destination independently."""
    print("\n" + "="*60)
    print("💾  FASE 7: GUARDANDO Y NOTIFICANDO")
    print("="*60)

    if not picks:
        print("   ❌ No hay picks para guardar.")
        return None, {}

    active_settings = settings or load_settings(dry_run=False)
    if repository is None:
        require_publish_backend()
        repository = SupabaseBatchRepository(supabase)

    hoy = datetime.now(ZoneInfo("America/Mexico_City")).date().isoformat()
    allowed_columns = {
        'categoria', 'partido', 'pick', 'cuota', 'confianza',
        'razonamiento', 'marcador', 'estado', 'es_parlay', 'liga', 'mercado',
        'riesgo', 'resultado_apuesta', 'ganancia_simulada', 'fecha_generacion',
        'fecha_evento', 'horario', 'odds_mercado', 'tiene_valor', 'visibility',
    }

    visible_picks = assign_visibility(picks)
    clean_picks = []
    for pick in visible_picks:
        prepared = dict(pick)
        prepared['fecha_generacion'] = hoy
        prepared['fecha_evento'] = scheduled_event_date(prepared.get('horario'), hoy)
        prepared['estado'] = 'pendiente'
        prepared['liga'] = prepared.get('liga') or prepared.get(
            'categoria', 'Fútbol Internacional'
        )
        prepared.setdefault('ganancia_simulada', 0)
        clean_picks.append(
            {key: value for key, value in prepared.items() if key in allowed_columns}
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
        publication = publish_batch(
            repository,
            picks,
            active_run_key,
            active_settings.public_picks_path,
        )
    except Exception:
        raise PersistenceFailure("scraper batch persistence failed") from None
    print(f"   ✅ Lote {publication.batch_id} publicado atómicamente.")

    destinations = [
        TelegramDestination("admin", active_settings.telegram_admin_id, "all")
        if active_settings.telegram_admin_id
        else None,
        TelegramDestination("vip", active_settings.telegram_vip_id, "all")
        if active_settings.telegram_vip_id
        else None,
        TelegramDestination("free", active_settings.telegram_free_id, "public")
        if active_settings.telegram_free_id
        else None,
    ]
    active_destinations = [destination for destination in destinations if destination]

    if not active_destinations:
        print("   ℹ️ No hay destinos de Telegram configurados.")
        return publication, {}

    completed = frozenset(
        name
        for name, status in publication.delivery_status.items()
        if status is True
        or (isinstance(status, dict) and status.get('success') is True)
    )
    if transport is None and not active_settings.telegram_token:
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
            transport = TelegramHttpTransport(active_settings.telegram_token)
        deliveries = deliver_batch(
            clean_picks,
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

    return publication, deliveries

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
    UNEXPECTED = 10


@dataclass(frozen=True)
class PipelineResult:
    event_count: int
    pick_count: int
    persisted: bool
    failed_deliveries: tuple[str, ...]

    def __post_init__(self):
        _check_pipeline_result_fields(
            self.event_count,
            self.pick_count,
            self.persisted,
            self.failed_deliveries,
        )
        object.__setattr__(
            self, "failed_deliveries", tuple(self.failed_deliveries)
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
        or status.get("version") != 1
        or status.get("public_picks") is not True
        or status.get("publish_pick_batch") is not True
    ):
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
    ):
        self.settings = settings
        self.repository = repository
        self.history_client = history_client
        self.driver_factory = driver_factory or get_chrome_driver

    def run(self):
        print("\n" + "=" * 60)
        print("🌮  REY TACO PICKS BOT v5.0  🌮")
        print(
            "   Arquitectura: Escáner → Mercado → Filtro → "
            "Inmersión → Memoria → IA → Picks"
        )
        print("=" * 60)
        print(f"dry_run={str(self.settings.dry_run).lower()}")

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
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def run_main(argv=None, *, values=None, pipeline=None):
    args = parse_args(argv)
    try:
        settings = load_settings(values, dry_run=args.dry_run)
        active_pipeline = pipeline or build_pipeline(settings)
        result = _validated_pipeline_result(
            active_pipeline.run(), dry_run=settings.dry_run
        )
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
