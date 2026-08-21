import os
import json
import sys
import urllib.request
from datetime import datetime, date, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

try:
    from backend.results_domain import EventResult, grade_pick, match_event, unit_result
except ModuleNotFoundError:  # Allows `python backend/verificar_resultados.py`.
    from results_domain import EventResult, grade_pick, match_event, unit_result

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# ============================================================
#  VERIFICADOR AUTOMÁTICO DE RESULTADOS
#  Consulta APIs de resultados deportivos y marca picks como
#  ganado/perdido. Diseñado para correr al día siguiente.
# ============================================================

def obtener_resultados_api():
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
    
    for liga_nombre, url in espn_leagues:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
                            'completed': is_completed,
                            'scores': [{'name': home_c.get('team', {}).get('displayName', ''), 'score': score_h},
                                       {'name': away_c.get('team', {}).get('displayName', ''), 'score': score_a}]
                        })
        except Exception:
            continue
            
    print(f"   ✅ ESPN API: {len([j for j in todos_juegos if j.get('completed')])} partidos completados encontrados.")
    return todos_juegos

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
        'ganancia_simulada': round(unidades * 10, 2),
        'resultado_unidades': unidades,
        'resultado_fuente': event.source,
        'resultado_evento_id': event.source_id,
        'resultado_marcador': f'{event.home_score:g}-{event.away_score:g}',
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
    todos_resultados = obtener_resultados_api()
    print(f"\n📊 Total de resultados obtenidos: {len(todos_resultados)}")
    
    # Comparar cada pick contra resultados
    actualizados = 0
    ganados = 0
    perdidos = 0
    
    for pick in picks_pendientes:
        partido = pick.get('partido', '')
        for resultado in todos_resultados:
            decision = grade_pending_pick(pick, resultado)
            if not decision:
                continue
            try:
                try:
                    supabase.table("picks").update(decision).eq("id", pick['id']).execute()
                except Exception:
                    # Backward compatibility until the audit-column migration is deployed.
                    legacy = {
                        "estado": decision["estado"],
                        "ganancia_simulada": decision["ganancia_simulada"],
                    }
                    supabase.table("picks").update(legacy).eq("id", pick['id']).execute()

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
            break
    
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
        mensaje += f"📈 Rendimiento: Jornada Positiva +EV\n\n"
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
