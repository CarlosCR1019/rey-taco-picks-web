import os
import json
import math
import re
import sys
import urllib.request
from pathlib import Path
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client, Client

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.football_result_source import ApiFootballResultsClient, SupabaseResultStore
from backend.result_report_publisher import (
    SupabaseResultArtifactStore,
    publish_result_report,
    require_healthy_result_reports,
)
from backend.result_report_repository import SupabaseResultReportRepository
from backend.result_reporting import build_result_report
from backend.results_domain import EventResult, PlayerResult, find_matching_event, grade_pick, match_event, parse_market_identity, unit_result
from backend.social_poster import MetaHttpTransport, MetaSettings
from backend.telegram_publisher import TelegramHttpTransport
from backend.vertical_publisher import (
    publish_final_stories_from_runtime,
    require_healthy_vertical_outcomes,
)

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None
_AMBIGUOUS_MATCH = object()

# ============================================================
#  VERIFICADOR AUTOMÁTICO DE RESULTADOS
#  Consulta APIs de resultados deportivos y marca picks como
#  ganado/perdido. Diseñado para correr al día siguiente.
# ============================================================

def espn_scoreboard_url(base_url, event_date):
    query_date = str(event_date)[:10].replace("-", "")
    return f"{base_url}?dates={query_date}" if len(query_date) == 8 else base_url


def event_date_cdmx(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo('America/Mexico_City')).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def _finite_nonnegative(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _decimal_odds(pick):
    raw = pick.get('cuota')
    if isinstance(raw, bool):
        return None
    try:
        parsed = float(str(raw).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and 1.01 <= parsed <= 1000 else None


def obtener_resultados_api(event_dates=None, pending_picks=None):
    """Consulta múltiples fuentes (ESPN API pública y The Odds API) para obtener resultados de partidos finalizados."""
    todos_juegos = []
    
    # 1. ESPN Scoreboards (100% público, gratuito y sin límite)
    espn_leagues = [
        ("UEFA Champions", "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard"),
        ("Liga MX", "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard"),
        ("La Liga", "https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/scoreboard"),
        ("Premier League", "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"),
        ("Serie A", "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/scoreboard"),
        ("MLS", "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard"),
        ("MLB", "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"),
        ("KBO", "https://site.api.espn.com/apis/site/v2/sports/baseball/kbo/scoreboard"),
        ("NFL", "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard")
    ]
    
    cdmx_today = datetime.now(ZoneInfo('America/Mexico_City')).date().isoformat()
    requested_dates = sorted({str(value)[:10] for value in (event_dates or [cdmx_today]) if value})
    for liga_nombre, url in espn_leagues:
        for requested_date in requested_dates:
            try:
                req = urllib.request.Request(
                    espn_scoreboard_url(url, requested_date),
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                for ev in data.get('events', []):
                    comp = ev.get('competitions', [{}])[0]
                    status_type = ev.get('status', {}).get('type', {})
                    is_completed = status_type.get('completed', False) or 'final' in status_type.get('description', '').lower()
                    
                    competitors = comp.get('competitors', [])
                    if len(competitors) >= 2:
                        home_c = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
                        away_c = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
                        
                        score_h = _finite_nonnegative(home_c.get('score'))
                        score_a = _finite_nonnegative(away_c.get('score'))
                        if score_h is None or score_a is None:
                            continue
                        
                        todos_juegos.append({
                            'source': 'espn',
                            'source_id': str(ev.get('id', '')),
                            'home_team': home_c.get('team', {}).get('displayName', ''),
                            'away_team': away_c.get('team', {}).get('displayName', ''),
                            'event_date': event_date_cdmx(ev.get('date', '')),
                            'completed': is_completed,
                            'scores': [{'name': home_c.get('team', {}).get('displayName', ''), 'score': score_h},
                                       {'name': away_c.get('team', {}).get('displayName', ''), 'score': score_a}]
                        })
            except Exception:
                continue

    if API_FOOTBALL_KEY and supabase and pending_picks:
        try:
            detailed_results = ApiFootballResultsClient(
                API_FOOTBALL_KEY,
                store=SupabaseResultStore(supabase),
            ).results_for_picks(pending_picks)
            todos_juegos.extend(detailed_results)
            print(
                "   ✅ API-Football: "
                f"{len(detailed_results)} partidos finales auditados."
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            print("   ⚠️ API-Football no aportó detalle verificable en esta ejecución.")

    unique_results = {}
    for result in todos_juegos:
        key = (
            result.get('source'),
            result.get('source_id') or (
                result.get('event_date'), result.get('home_team'), result.get('away_team')
            ),
        )
        unique_results[key] = result
    results = list(unique_results.values())
    print(f"   ✅ ESPN API: {len([j for j in results if j.get('completed')])} partidos completados encontrados.")
    return results

def _event_from_api(resultado):
    """Convert an API dictionary into the audited domain representation."""
    scores = resultado.get('scores') or []
    if len(scores) < 2:
        return None
    def optional_number(field):
        value = resultado.get(field)
        return None if value is None else _finite_nonnegative(value)

    players = []
    for raw_player in resultado.get('players') or []:
        if not isinstance(raw_player, dict):
            continue
        try:
            players.append(PlayerResult(
                name=str(raw_player['name']),
                team=str(raw_player['team']),
                minutes=(None if raw_player.get('minutes') is None else float(raw_player['minutes'])),
                shots_total=(None if raw_player.get('shots_total') is None else float(raw_player['shots_total'])),
                shots_on=(None if raw_player.get('shots_on') is None else float(raw_player['shots_on'])),
                goals=(None if raw_player.get('goals') is None else float(raw_player['goals'])),
                assists=(None if raw_player.get('assists') is None else float(raw_player['assists'])),
                yellow_cards=(None if raw_player.get('yellow_cards') is None else float(raw_player['yellow_cards'])),
                red_cards=(None if raw_player.get('red_cards') is None else float(raw_player['red_cards'])),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    try:
        completed = resultado.get('completed')
        source = str(resultado.get('source', '')).strip()
        source_id = str(resultado.get('source_id', '')).strip()
        event_date = str(resultado.get('event_date', '')).strip()
        home = str(resultado.get('home_team', '')).strip()
        away = str(resultado.get('away_team', '')).strip()
        home_score = _finite_nonnegative(scores[0].get('score'))
        away_score = _finite_nonnegative(scores[1].get('score'))
        if (
            type(completed) is not bool
            or not source
            or not source_id
            or not home
            or not away
            or home_score is None
            or away_score is None
            or date.fromisoformat(event_date).isoformat() != event_date
        ):
            return None
        return EventResult(
            home=home,
            away=away,
            home_score=home_score,
            away_score=away_score,
            completed=completed,
            home_corners=optional_number('home_corners'),
            away_corners=optional_number('away_corners'),
            source=source,
            source_id=source_id,
            event_date=event_date,
            home_first_half_score=optional_number('home_first_half_score'),
            away_first_half_score=optional_number('away_first_half_score'),
            home_shots_total=optional_number('home_shots_total'),
            away_shots_total=optional_number('away_shots_total'),
            home_shots_on=optional_number('home_shots_on'),
            away_shots_on=optional_number('away_shots_on'),
            home_fouls=optional_number('home_fouls'),
            away_fouls=optional_number('away_fouls'),
            home_offsides=optional_number('home_offsides'),
            away_offsides=optional_number('away_offsides'),
            home_yellow_cards=optional_number('home_yellow_cards'),
            away_yellow_cards=optional_number('away_yellow_cards'),
            home_red_cards=optional_number('home_red_cards'),
            away_red_cards=optional_number('away_red_cards'),
            players=tuple(players),
        )
    except (TypeError, ValueError):
        return None


def grade_pending_pick(pick, resultado):
    """Return an update payload only for a unique, matching final event."""
    event = _event_from_api(resultado)
    if not event or not event.completed:
        return None
    if not match_event(str(pick.get('partido', '')), event):
        return None

    return _decision_for_event(pick, event)


def _decision_for_event(pick, event):
    estado = grade_pick(
        str(pick.get('pick', '')),
        event,
        market_name=str(pick.get('mercado', '')),
        market_identity=parse_market_identity(pick.get('source_market_key')),
    )
    if estado == 'pendiente':
        return None

    cuota = _decimal_odds(pick)
    if cuota is None:
        return None
    unidades = unit_result(estado, cuota)
    return {
        'estado': estado,
        'visibility': 'public',
        'ganancia_simulada': round(unidades * 10, 2),
        'resultado_unidades': unidades,
        'resultado_fuente': event.source,
        'resultado_evento_id': event.source_id,
        'resultado_marcador': f'{event.home_score:g}-{event.away_score:g}',
        'resultado_verificado_at': datetime.now(timezone.utc).isoformat(),
    }


def grade_pending_pick_from_results(pick, resultados):
    events = [event for event in (_event_from_api(item) for item in resultados) if event]
    if pick.get('es_parlay'):
        parlay_events = _find_preferred_parlay_events(
            str(pick.get('partido', '')),
            events,
            str(pick.get('fecha_evento') or pick.get('fecha_generacion', '')),
        )
        if not parlay_events:
            return None
        legs = [leg.strip() for leg in str(pick.get('pick', '')).split('&') if leg.strip()]
        if len(legs) != len(parlay_events):
            return _parlay_decision(pick, parlay_events, ['revision_pendiente'])
        statuses = [grade_pick(leg, event) for leg, event in zip(legs, parlay_events)]
        return _parlay_decision(pick, parlay_events, statuses)
    event = _find_preferred_event(
        str(pick.get('partido', '')),
        events,
        str(pick.get('fecha_evento') or pick.get('fecha_generacion', '')),
    )
    return _decision_for_event(pick, event) if isinstance(event, EventResult) else None


def _find_preferred_event(label, events, expected_date=''):
    detailed_matches = [
        event for event in events
        if event.source == 'api_football'
        and event.completed
        and match_event(label, event)
        and (
            not expected_date
            or event.event_date[:10] == expected_date[:10]
        )
    ]
    if len(detailed_matches) == 1:
        return detailed_matches[0]
    if len(detailed_matches) > 1:
        return _AMBIGUOUS_MATCH
    return find_matching_event(
        label,
        [event for event in events if event.source != 'api_football'],
        expected_date,
    )


def _find_preferred_parlay_events(label, events, expected_date=''):
    legs = [
        part.strip()
        for part in re.split(r'\s+\+\s+', str(label))
        if part.strip()
    ]
    if len(legs) < 2:
        return None
    matched = [
        _find_preferred_event(leg, events, expected_date)
        for leg in legs
    ]
    if any(not isinstance(event, EventResult) for event in matched):
        return None
    resolved = [event for event in matched if isinstance(event, EventResult)]
    identities = {(event.source, event.source_id) for event in resolved}
    return resolved if len(identities) == len(resolved) else None


def _parlay_decision(pick, events, statuses):
    if 'perdido' in statuses:
        estado = 'perdido'
    elif statuses and all(status == 'ganado' for status in statuses):
        estado = 'ganado'
    else:
        estado = 'revision_pendiente'
    cuota = _decimal_odds(pick)
    if cuota is None:
        return None
    unidades = unit_result(estado, cuota)
    return {
        'estado': estado,
        'visibility': 'public',
        'ganancia_simulada': round(unidades * 10, 2),
        'resultado_unidades': unidades,
        'resultado_fuente': ','.join(dict.fromkeys(event.source for event in events)),
        'resultado_evento_id': ','.join(event.source_id for event in events),
        'resultado_marcador': ' | '.join(
            f'{event.home_score:g}-{event.away_score:g}' for event in events
        ),
        'resultado_verificado_at': datetime.now(timezone.utc).isoformat(),
    }

def load_active_pending_picks(client):
    """Return only current active picks that are still awaiting a result."""
    response = (
        client.table("picks")
        .select("*")
        .eq("estado", "pendiente")
        .eq("active", True)
        .execute()
    )
    return response.data


def verificar_picks() -> int:
    """Verifica los picks pendientes contra resultados reales."""
    print("\n" + "="*60)
    print("🔍  VERIFICADOR DE RESULTADOS - Rey Taco Picks")
    print("="*60)
    
    if not supabase:
        print("❌ No hay conexión a Supabase.")
        return 1
    
    # Obtener picks pendientes
    try:
        picks_pendientes = load_active_pending_picks(supabase)
    except Exception as e:
        print(f"❌ Error leyendo picks: {e}")
        return 1
    
    if not picks_pendientes:
        print("ℹ️ No hay picks pendientes por verificar.")
        publish_available_result_reports()
        return 0
    
    print(f"📋 {len(picks_pendientes)} picks pendientes encontrados.\n")
    
    # Obtener resultados de múltiples deportes (ESPN API pública)
    pick_dates = sorted({
        str(pick.get('fecha_evento') or pick.get('fecha_generacion', ''))[:10]
        for pick in picks_pendientes
        if pick.get('fecha_evento') or pick.get('fecha_generacion')
    }, reverse=True)[:7]
    todos_resultados = obtener_resultados_api(pick_dates, picks_pendientes)
    print(f"\n📊 Total de resultados obtenidos: {len(todos_resultados)}")
    
    # Comparar cada pick contra resultados
    actualizados = 0
    ganados = 0
    perdidos = 0
    
    for pick in picks_pendientes:
        partido = pick.get('partido', '')
        decision = grade_pending_pick_from_results(pick, todos_resultados)
        if not decision:
            continue
        try:
            result = supabase.table("picks").update(decision).eq(
                "id", pick['id']
            ).eq("estado", "pendiente").execute()
            if not result.data:
                print(f"   ℹ️ Pick {pick['id']} cambió en otra ejecución; no se sobrescribió.")
                continue

            estado = decision['estado']
            emoji = '✅' if estado == 'ganado' else ('❌' if estado == 'perdido' else '🟡')
            print(f"   {emoji} {partido} → {pick.get('pick')} → {estado.upper()} ({decision['resultado_unidades']:+.2f}u)")
            actualizados += 1
            if estado == 'ganado':
                ganados += 1
            elif estado == 'perdido':
                perdidos += 1
        except Exception as e:
            print(f"   ⚠️ Error actualizando pick {pick['id']}: {e}")
    
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN: {actualizados} verificados | ✅ {ganados} ganados | ❌ {perdidos} perdidos")
    
    publish_available_result_reports()
    
    print("="*60)
    return 0

def publish_available_result_reports():
    """Publish one evidence-backed partial or final report without duplicates."""
    mode = os.getenv("RESULT_REPORT_MODE", "auto").strip().casefold()
    if mode not in {"auto", "evening", "final_only"}:
        print("   ⚠️ RESULT_REPORT_MODE inválido; reportes omitidos.")
        return {}
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not supabase:
        print("   ℹ️ Reportes omitidos: Supabase no está configurado.")
        return {}
    try:
        repository = SupabaseResultReportRepository(
            url=SUPABASE_URL,
            service_role_key=SUPABASE_SERVICE_ROLE_KEY,
        )
        batches = repository.batches()
    except Exception:
        print("   ⚠️ No se pudieron cargar los lotes para reportes.")
        return {}

    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    telegram_transport = TelegramHttpTransport(token) if token else None
    telegram_chats = {
        "admin": (os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip(),
        "vip": (os.getenv("TELEGRAM_VIP_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID") or "").strip(),
        "free": (os.getenv("TELEGRAM_FREE_CHANNEL_ID") or "").strip(),
    }
    try:
        meta_settings = MetaSettings.from_mapping(os.environ)
        meta_transport = MetaHttpTransport()
    except ValueError:
        meta_settings = None
        meta_transport = None
    artifact_store = SupabaseResultArtifactStore(
        client=supabase,
        supabase_url=SUPABASE_URL,
        bucket=(os.getenv("SUPABASE_STORAGE_BUCKET") or "social-media").strip(),
    )

    published: dict[str, dict[str, str]] = {}
    vertical_published: list[dict[str, str]] = []
    for rows in batches:
        report = _report_for_mode(rows, mode=mode)
        if report is None:
            continue
        outcomes = publish_result_report(
            report,
            repository=repository,
            telegram_transport=telegram_transport,
            telegram_chats=telegram_chats,
            meta_transport=meta_transport,
            meta_settings=meta_settings,
            artifact_store=artifact_store,
        )
        published[f"{report.batch_id}:{report.kind}"] = outcomes
        summary = ", ".join(f"{name}={status}" for name, status in outcomes.items())
        print(f"   📣 Reporte {report.kind}: {summary}")
        if report.kind == "final":
            try:
                vertical = publish_final_stories_from_runtime(report)
            except Exception:
                vertical = {"final_results_story": "delivery_failed"}
            vertical_published.append(vertical)
            vertical_summary = ", ".join(
                f"{name}={status}" for name, status in vertical.items()
            )
            print(f"   📱 Historias finales: {vertical_summary or 'sin evidencia'}")
    require_healthy_result_reports(published)
    if meta_settings is not None:
        for outcomes in vertical_published:
            require_healthy_vertical_outcomes(outcomes, settings=meta_settings)
    return published


def _report_for_mode(rows, *, mode):
    if mode in {"auto", "final_only"}:
        try:
            return build_result_report(rows, kind="final")
        except ValueError:
            if mode == "final_only":
                return None
    if mode in {"auto", "evening"}:
        try:
            return build_result_report(rows, kind="evening")
        except ValueError:
            return None
    return None

if __name__ == "__main__":
    raise SystemExit(verificar_picks())
