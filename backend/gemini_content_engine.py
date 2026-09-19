"""
backend/gemini_content_engine.py
================================
Motor de Creación de Contenido y Narrativa Anti-Tipster con Gemini 2.5 Flash.

Principio Institucional de Arquitectura:
- LLM = Exclusivamente Analista Cualitativo, Hooks de Retención y Copywriting.
- Backend = Inyección determinista de datos numéricos (Ticket ID, Cuota, Mínima Válida, EV %, Hash).
- CERO Alucinación Numérica: Gemini solo devuelve texto cualitativo (hook, contexto táctico, CTA).
  El renderer une los datos matemáticos auditados del backend con la narrativa de la IA.

Series de Video Prioritarias (Formato Vertical 9:16 para Reels/Shorts):
- Formato A: "GANÓ, PERO ERA UNA MALA APUESTA" (Destruye la trampa de cuotas desinfladas).
- Formato B: "ESTA APUESTA NUNCA EXISTIÓ" (El veto algorítmico por alineación/precio).
- Formato C: "EL TICKET EXISTÍA ANTES DEL RESULTADO" (La prueba criptográfica pre-match).
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("GeminiContentEngine")

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

VIP_LINK = "https://reytacopicks.com"


def call_gemini(prompt: str, temperature: float = 0.6, max_tokens: int = 800) -> Optional[str]:
    """Realiza una llamada directa a Gemini 2.5 Flash con la API Key configurada."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY no configurada.")
        return None

    url = f"{GEMINI_ENDPOINT}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens
        }
    }
    headers = {"Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates and candidates[0].get("content", {}).get("parts"):
                text = candidates[0]["content"]["parts"][0].get("text", "").strip()
                # Limpiar bloques markdown ```json si existen
                text = re.sub(r"^```[a-zA-Z]*\n", "", text)
                text = re.sub(r"\n```$", "", text)
                return text.strip()
    except Exception as e:
        logger.error(f"Error en llamada a Gemini API: {e}")

    return None


# =====================================================================
# 1. GENERACIÓN DE MENSAJES TELEGRAM FREE (ANTI-TIPSTER)
# =====================================================================

def generate_free_pick_message(
    home_team: str,
    away_team: str,
    league: str,
    pick: str,
    cuota: float,
    min_odds: float,
    ticket_id: str,
    ev_percent: float,
    tactical_rationale: str
) -> str:
    """
    Genera el mensaje del pick gratuito para Telegram.
    Los números se inyectan directamente desde el backend; Gemini solo aporta el hook y contexto.
    """
    prompt = f"""Eres el analista jefe de Rey Taco Picks. Tu filosofía es 100% ANTI-TIPSTER tradicional:
- No vendemos fijas. Medimos valor (+EV).
- No borramos picks perdidos. Todo está sellado con Ticket ID antes del inicio.
- Si la cuota cae por debajo de la Cuota Mínima ({min_odds}), la instrucción es NO APOSTAR.

Genera un JSON con:
{{
  "hook_anti_tipster": "Frase contundente de 1-2 líneas que desmonte las 'fijas' y hable de ventaja de precio",
  "tactical_context": "Breve explicación cualitativa de por qué hay valor táctico en este partido",
  "cta_institucional": "Llamado a la acción sobrio hacia el canal VIP o Mini App para ver la cartera completa"
}}

Partido: {home_team} vs {away_team} ({league})
Selección: {pick}"""

    raw = call_gemini(prompt, temperature=0.5)
    hook = "No existen fijas del 99%. Existen precios con ventaja matemática."
    context = tactical_rationale
    cta = "En el canal VIP y la Mini App monitoreamos cuotas en tiempo real con alertas de veto si el precio colapsa."

    if raw:
        try:
            parsed = json.loads(raw)
            hook = parsed.get("hook_anti_tipster", hook)
            context = parsed.get("tactical_context", context)
            cta = parsed.get("cta_institucional", cta)
        except Exception:
            pass

    # Ensamblado determinista sin posibilidad de alucinación numérica
    return (
        f"🌮👑 *REY TACO PICKS — INTELIGENCIA AUDITABLE* 👑🌮\n\n"
        f"🎫 *Ticket ID:* `{ticket_id}`\n"
        f"🏆 *{league}*\n"
        f"⚽ *{home_team} vs {away_team}*\n\n"
        f"🎯 *SELECCIÓN AUDITADA:* `{pick}`\n"
        f"💰 *Momio Playdoit Actual:* `{cuota:.2f}`\n"
        f"🛡️ *Cuota Mínima Aceptable:* `{min_odds:.2f}`\n"
        f"📈 *Valor Esperado (+EV):* `+{ev_percent:.1f}%`\n\n"
        f"⚠️ *REGLA DE ORO DE PRECIO:*\n"
        f"Si al momento de colocar tu jugada el momio ya cayó por debajo de `{min_odds:.2f}`, la orden matemática es *NO APOSTAR*. La ventaja habrá desaparecido.\n\n"
        f"🧠 *Tesis del Modelo:*\n"
        f"_{hook}_\n\n"
        f"📋 *Análisis Táctico:*\n"
        f"{context}\n\n"
        f"👑 *Pase VIP & Auditoría en Vivo:*\n"
        f"{cta}\n\n"
        f"🌐 Web Oficial: {VIP_LINK}\n"
        f"🌮 _No nos creas. Verifica el Ticket._"
    )


# =====================================================================
# 2. SERIES DE VIDEO VERTICAL (REELS / SHORTS 9:16)
# =====================================================================

def generate_reel_bad_price_win(
    match: str,
    selection: str,
    original_odds: float,
    min_odds: float,
    decayed_odds: float,
    ticket_id: str
) -> Dict[str, str]:
    """
    Formato A — 'GANÓ, PERO ERA UNA MALA APUESTA'
    Narrativa deconstructiva: enseña al usuario que acertar a cuota desinflada destruye la banca a largo plazo.
    """
    return {
        "format": "BAD_PRICE_WIN",
        "duration_seconds": 35,
        "screen_0_3s": {
            "badge": "GANÓ, PERO FUE UN ERROR",
            "visual": "WIN_TRANSFORM_TO_BAD_PRICE",
            "voiceover": "Ganó. Y nuestro sistema dice que NO debiste tomarla."
        },
        "screen_3_15s": {
            "metric_title": "CUOTA MÍNIMA ACEPTABLE",
            "metric_value": f"{min_odds:.2f}",
            "voiceover": f"Para {match}, nuestro modelo cuantitativo exigía una cuota mínima de {min_odds:.2f} para tener valor esperado positivo."
        },
        "screen_15_25s": {
            "decay_graphic": f"{original_odds:.2f} ➔ {min_odds:.2f} ➔ {decayed_odds:.2f}",
            "voiceover": f"Cuando el mercado la desplomó a {decayed_odds:.2f}, el valor desapareció por completo. El resultado fue bueno; la decisión fue perdedora."
        },
        "screen_25_35s": {
            "ticket_chip": ticket_id,
            "cta_title": "NO VENDEMOS CERTEZAS. MEDIMOS PRECIO.",
            "voiceover": "En Rey Taco auditamos el proceso antes de conocer el resultado. El ledger está en el perfil."
        }
    }


def generate_reel_lineup_veto(
    match: str,
    candidate_selection: str,
    offered_odds: float,
    benched_player: str,
    initial_ev: float
) -> Dict[str, str]:
    """
    Formato B — 'ESTA APUESTA NUNCA EXISTIÓ' (Veto del Rey por alineaciones)
    Enseña cómo un sistema cuantitativo gana al no apostar cuando cambia la formación.
    """
    return {
        "format": "LINEUP_VETO",
        "duration_seconds": 35,
        "screen_0_3s": {
            "badge": "VETO DEL REY",
            "visual": "RED_ALERT_STAMP",
            "voiceover": f"Nuestra IA encontró +{initial_ev:.1f}% de valor. Y la prohibimos."
        },
        "screen_3_15s": {
            "match": match,
            "selection": candidate_selection,
            "odds": f"{offered_odds:.2f}",
            "voiceover": f"Teníamos una operación aprobada para {match} a cuota {offered_odds:.2f} con una probabilidad favorable."
        },
        "screen_15_25s": {
            "incident": f"ALINEACIÓN CONFIRMADA: {benched_player} A LA BANCA",
            "ev_recalc": f"+{initial_ev:.1f}% EV ➔ NEGATIVO",
            "voiceover": f"Pero salió la alineación oficial: {benched_player} a la banca. El modelo recalculó al instante y el valor desapareció. VETO INMEDIATO."
        },
        "screen_25_35s": {
            "takeaway": "UN SISTEMA SERIO TAMBIÉN GANA CUANDO DECIDE NO JUGAR",
            "cta": "Revisa nuestros descartes auditados en el link del perfil.",
            "voiceover": "Un sistema profesional también gana cuando protege tu banca. Revisa los descartes auditados en el perfil."
        }
    }


def generate_reel_pre_match_hash(
    match: str,
    selection: str,
    offered_odds: float,
    ticket_id: str,
    block_hash: str
) -> Dict[str, str]:
    """
    Formato C — 'EL TICKET EXISTÍA ANTES DEL RESULTADO'
    Muestra la prueba criptográfica del Audit Ledger con sellado previo al juego.
    """
    return {
        "format": "PRE_MATCH_HASH",
        "duration_seconds": 35,
        "screen_0_3s": {
            "badge": "TRAZABILIDAD CRIPTOGRÁFICA",
            "visual": "TICKET_ID_HERO",
            "voiceover": f"Este código demuestra que no editamos la captura después del partido."
        },
        "screen_3_15s": {
            "ticket_id": ticket_id,
            "details": f"{match} | {selection} @ {offered_odds:.2f}",
            "voiceover": f"Ticket {ticket_id}. Publicado y sellado antes del silbatazo inicial."
        },
        "screen_15_25s": {
            "hash_animation": f"SHA-256: {block_hash[:16]}... ➔ HASH-CHAIN LOCKED",
            "voiceover": "Cada pick entra a una cadena de bloques interna con SHA-256. Alterar un dato después invalida toda la cadena."
        },
        "screen_25_35s": {
            "takeaway": "DESPUÉS PUEDE GANAR O PERDER. LO QUE NO CAMBIA ES LA DECISIÓN.",
            "cta": "No nos creas. Verifica el Ticket.",
            "voiceover": "Después puede ganar o perder. Lo que ya no puede cambiar es nuestra decisión. No nos creas, verifica el ticket."
        },
        "audio_track": "institutional_cinematic.mp3"
    }


def generate_reel_asian_kbo_radar(
    match: str,
    league: str,
    selection: str,
    odds_american: str,
    edge_pp: float,
    ev_percent: float,
    ticket_id: str
) -> Dict[str, Any]:
    """
    Formato D — 'EL MERCADO DE MADRUGADA TIENE VALOR' (KBO / NPB / Asia)
    Atrae al usuario nocturno enseñando que ligas asiáticas tienen menos liquidez y más ineficiencias.
    """
    return {
        "format": "ASIAN_KBO_RADAR",
        "duration_seconds": 35,
        "audio_track": "cyberpunk_synth.mp3",
        "screen_0_3s": {
            "badge": "RADAR 03:00 AM",
            "visual": "NIGHT_RADAR_SCAN",
            "voiceover": "Mientras todos duermen, las casas de apuestas cometen sus peores errores de precio."
        },
        "screen_3_15s": {
            "match": f"{match} ({league})",
            "selection": selection,
            "odds": odds_american,
            "voiceover": f"En {league}, nuestro algoritmo detectó un desajuste severo en la línea de {match}."
        },
        "screen_15_25s": {
            "edge_badge": f"+{edge_pp:.1f} pp EDGE | +{ev_percent:.1f}% EV",
            "voiceover": f"Con un edge de {edge_pp:.1f} puntos porcentuales sobre la cuota de Playdoit, la matemática exige operar."
        },
        "screen_25_35s": {
            "ticket_chip": ticket_id,
            "cta": "Revisa los picks de la madrugada en Telegram.",
            "voiceover": f"Ticket {ticket_id} sellado en el ledger. El canal de Telegram tiene las alertas de cada bloque de 6 horas."
        }
    }


def generate_reel_market_psychology(
    match: str,
    league: str,
    popular_pick: str,
    sharp_pick: str,
    sharp_odds: str,
    edge_pp: float,
    ticket_id: str
) -> Dict[str, Any]:
    """
    Formato E — 'EL ERROR DEL 99% EN EL PARTIDO ESTELAR' (Liga MX / Clásicos)
    Desmonta el sesgo de la masa que infla cuotas y crea valor en el lado opuesto.
    """
    return {
        "format": "MARKET_PSYCHOLOGY",
        "duration_seconds": 35,
        "audio_track": "tension_trap_beat.mp3",
        "screen_0_3s": {
            "badge": "EL SESGO DE LA MASA",
            "visual": "SPLIT_SCREEN_HERO",
            "voiceover": "El 90% del dinero del público va a una sola jugada. Y ahí está la trampa."
        },
        "screen_3_15s": {
            "match": match,
            "popular": f"MASA: {popular_pick} (Precio Inflado)",
            "voiceover": f"En {match}, el aficionado promedio infló artificialmente {popular_pick} por fanatismo."
        },
        "screen_15_25s": {
            "sharp": f"MODELO QUANT: {sharp_pick} @ {sharp_odds}",
            "edge": f"+{edge_pp:.1f} pp de Ventaja Real",
            "voiceover": f"Nuestro modelo no tiene equipo favorito. Midió el precio real y encontró un valor masivo en {sharp_pick} a cuota {sharp_odds}."
        },
        "screen_25_35s": {
            "ticket_chip": ticket_id,
            "cta": "No apuestes con el corazón. Mide el precio.",
            "voiceover": "Dejamos de ser aficionados para ser analistas de valor. Ficha técnica completa en el link."
        }
    }


def generate_social_post(
    home_team: str,
    away_team: str,
    league: str,
    pick: str,
    cuota: Any,
    ticket_id: Optional[str] = None,
    min_odds: Optional[Any] = None,
    platform: str = "instagram"
) -> Dict[str, str]:
    """Genera posts para redes sociales basados en datos deterministas."""
    t_str = f"🎫 Ticket: {ticket_id}\n" if ticket_id else ""
    m_str = f"🛡️ Cuota Mínima: {min_odds}\n" if min_odds else ""
    return {
        "instagram": (
            f"🌮👑 ¡Inteligencia Deportiva Verificable! 👑🌮\n\n"
            f"{t_str}"
            f"🏆 {league}: {home_team} vs {away_team}\n"
            f"🎯 Selección: {pick} @ {cuota}\n"
            f"{m_str}\n"
            f"Análisis cuantitativo con trazabilidad en blockchain interna.\n"
            f"👉 Verifica el ticket en: {VIP_LINK}\n\n"
            f"#ReyTacoPicks #SportsIntelligence #+EV #Futbol"
        ),
        "facebook": (
            f"🌮👑 REY TACO PICKS — ANÁLISIS AUDITADO\n\n"
            f"Partido: {home_team} vs {away_team} ({league})\n"
            f"Selección: {pick} @ {cuota}\n\n"
            f"Decisión cuantitativa basada en valor esperado y cuota mínima.\n"
            f"👉 Accede a la cartelera completa en: {VIP_LINK}"
        )
    }


def generate_reel_script(
    home_team: str,
    away_team: str,
    league: str,
    pick: str,
    cuota: Any
) -> Dict[str, str]:
    """Genera guión para video corto."""
    return {
        "hook": f"Atento a este desajuste en {league}...",
        "script_voz": f"En el encuentro de {home_team} contra {away_team}, el modelo detectó valor positivo en {pick} a cuota {cuota}.",
        "cta": f"No vendemos certezas, medimos valor. Consulta el ticket en el perfil."
    }

