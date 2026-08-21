import os
import json
import sys
import urllib.request
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client, Client

try:
    from backend.results_domain import EventResult, find_matching_event, find_matching_parlay_events, grade_pick, match_event, unit_result
except ModuleNotFoundError:  # Allows `python backend/verificar_resultados.py`.
    from results_domain import EventResult, find_matching_event, find_matching_parlay_events, grade_pick, match_event, unit_result

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None

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


def obtener_resultados_api(event_dates=None):
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
                        
                        score_h = float(home_c.get('score', 0) or 0)
                        score_a = float(away_c.get('score', 0) or 0)
                        
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
    try:
        return EventResult(
            home=str(resultado.get('home_team', '')),
            away=str(resultado.get('away_team', '')),
            home_score=float(scores[0].get('score', 0) or 0),
            away_score=float(scores[1].get('score', 0) or 0),
            completed=bool(resultado.get('completed', False)),
            home_corners=resultado.get('home_corners'),
            away_corners=resultado.get('away_corners'),
            source=str(resultado.get('source', 'unknown')),
            source_id=str(resultado.get('source_id', '')),
            event_date=str(resultado.get('event_date', '')),
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
    estado = grade_pick(str(pick.get('pick', '')), event)
    if estado == 'pendiente':
        return None

    try:
        cuota = float(str(pick.get('cuota', '1')).replace(',', '.'))
    except (TypeError, ValueError):
        cuota = 1.0
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
        parlay_events = find_matching_parlay_events(
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
    event = find_matching_event(
        str(pick.get('partido', '')),
        events,
        str(pick.get('fecha_evento') or pick.get('fecha_generacion', '')),
    )
    return _decision_for_event(pick, event) if event else None


def _parlay_decision(pick, events, statuses):
    if 'perdido' in statuses:
        estado = 'perdido'
    elif statuses and all(status == 'ganado' for status in statuses):
        estado = 'ganado'
    else:
        estado = 'revision_pendiente'
    try:
        cuota = float(str(pick.get('cuota', '1')).replace(',', '.'))
    except (TypeError, ValueError):
        cuota = 1.0
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

def verificar_picks():
    """Verifica los picks pendientes contra resultados reales."""
    print("\n" + "="*60)
    print("🔍  VERIFICADOR DE RESULTADOS - Rey Taco Picks")
    print("="*60)
    
    if not supabase:
        print("❌ No hay conexión a Supabase.")
        return
    
    # Obtener picks pendientes
    try:
        res = supabase.table("picks").select("*").eq("estado", "pendiente").execute()
        picks_pendientes = res.data
    except Exception as e:
        print(f"❌ Error leyendo picks: {e}")
        return
    
    if not picks_pendientes:
        print("ℹ️ No hay picks pendientes por verificar.")
        return
    
    print(f"📋 {len(picks_pendientes)} picks pendientes encontrados.\n")
    
    # Obtener resultados de múltiples deportes (ESPN API pública)
    pick_dates = {
        str(pick.get('fecha_evento') or pick.get('fecha_generacion', ''))[:10]
        for pick in picks_pendientes
        if pick.get('fecha_evento') or pick.get('fecha_generacion')
    }
    todos_resultados = obtener_resultados_api(pick_dates)
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
    
    if actualizados > 0:
        _notificar_resultados_telegram(ganados, perdidos)
    
    print("="*60)

def _notificar_resultados_telegram(ganados, perdidos):
    """Envía resumen de resultados y recap de alto impacto para conversión por Telegram."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        vip_channel_id = os.getenv("TELEGRAM_VIP_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
        free_channel_id = os.getenv("TELEGRAM_FREE_CHANNEL_ID")
        
        if not token:
            return
        
        total = ganados + perdidos
        win_rate = round(ganados / total * 100, 1) if total > 0 else 0
        
        mensaje = "👑 REY TACO PICKS — RECAP OFICIAL DE LA JORNADA 👑\n\n"
        mensaje += f"🏆 Balance del Día: {ganados}W - {perdidos}L\n"
        mensaje += f"🔥 Efectividad / Win Rate: {win_rate}%\n"
        if ganados > perdidos:
            mensaje += "📊 Resultado: más aciertos que fallos en esta jornada.\n\n"
        elif perdidos > ganados:
            mensaje += "📊 Resultado: más fallos que aciertos en esta jornada.\n\n"
        else:
            mensaje += "📊 Resultado: jornada equilibrada en conteo.\n\n"
        mensaje += "💎 ¿Quieres recibir todas las combinadas, córners y picks exclusivos antes del inicio?\n"
        mensaje += "👉 Únete al VIP por solo $299 MXN al mes."

        keyboard_free = {
            "inline_keyboard": [
                [
                    {"text": "👑 Adquirir Pase VIP ($299 MXN)", "url": "https://wa.me/525639331102?text=Hola,%20quiero%20el%20Pase%20VIP%20de%20Rey%20Taco%20Picks"},
                    {"text": "🌐 Ver Historial en la Web", "url": "https://reytacopicks.com/"}
                ]
            ]
        }
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        for dest in [chat_id, vip_channel_id, free_channel_id]:
            if dest:
                try:
                    data = json.dumps({"chat_id": dest, "text": mensaje, "reply_markup": keyboard_free}).encode('utf-8')
                    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                    urllib.request.urlopen(req, timeout=10)
                except Exception:
                    pass
        
        print("   📱 ✅ Resultados y Recap VIP enviados por Telegram.")
    except Exception as e:
        print(f"   ⚠️ Error Telegram: {e}")

if __name__ == "__main__":
    verificar_picks()
