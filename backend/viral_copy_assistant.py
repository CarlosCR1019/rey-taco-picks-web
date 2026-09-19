"""
backend/viral_copy_assistant.py
===============================
Asistente de Textos (Copies), Ganchos Virales y Hashtags para Redes Sociales.
Optimizado para TikTok, Instagram Reels y Facebook Stories de Rey Taco Picks.
"""

from typing import Dict, List, Any


COPIES_BY_THEME: Dict[str, Dict[str, Any]] = {
    "ligamx": {
        "title": "⚽ LIGA MX • VALOR CUANTITATIVO",
        "hooks": [
            "¿Sabías que apostar a tu equipo favorito en la Liga MX es el error número 1?",
            "El dato oculto de tiros de esquina en el partido de hoy de la Liga MX...",
            "Por qué este momio de Playdoit en la Liga MX tiene más valor del que parece:"
        ],
        "body": (
            "En Rey Taco Picks no apostamos con el corazón, usamos modelos cuantitativos de xG "
            "y ventaja estadística (+EV). Si la cuota no cumple con el margen mínimo que calculamos, "
            "simplemente no se juega.\n\n"
            "Todos nuestros boletos son de Playdoit y quedan sellados con hash SHA-256 antes del silbatazo inicial."
        ),
        "hashtags": "#LigaMX #Playdoit #ApuestasMexico #PicksLigaMX #ReyTacoPicks #EstadisticaDeportiva #FutbolMexicano #PicksDeportivos"
    },
    "parlay": {
        "title": "🎰 PARLAYS • CÓMO JUGAR CON VENTAJA",
        "hooks": [
            "La razón por la que las casas de apuestas aman que metas parlays de 10 selecciones...",
            "Cómo armamos parlays con ventaja matemática (+EV) sin regalar nuestro dinero:",
            "¿Vale la pena meter parlays? Esta es la regla institucional:"
        ],
        "body": (
            "Los parlays multiplican el margen de la casa si combinas jugadas al azar. "
            "Pero si combinas selecciones donde cada una tiene ventaja estadística (+EV), "
            "el retorno esperado es masivo.\n\n"
            "En Rey Taco Picks limitamos los combinados a 2 o 3 selecciones de alto valor y publicamos "
            "el boleto real en cada jugada."
        ),
        "hashtags": "#Parlay #Playdoit #ApuestasDeportivas #ReyTacoPicks #GestionDeBanca #ApuestasResponsables #InversionesDeportivas"
    },
    "transparencia": {
        "title": "🛡️ TRANSPARENCIA RADICAL • CERO HUMO",
        "hooks": [
            "¿Alguna vez has visto a un canal de picks publicar sus boletos perdidos?",
            "La verdad que los tipsters de Telegram no quieren que sepas sobre los fallos...",
            "En Rey Taco Picks NUNCA borramos un pick. Esta es la razón:"
        ],
        "body": (
            "La varianza en el deporte existe. Quien te prometa 100% de aciertos te está engañando. "
            "Nosotros mostramos cada victoria y cada caída con boleto oficial de Playdoit y hash criptográfico SHA-256.\n\n"
            "Lo único que genera ganancias a largo plazo es la disciplina matemática y el control de unidades."
        ),
        "hashtags": "#Transparencia #ReyTacoPicks #ApuestasReales #SinCensura #Playdoit #Varianza #ApuestasResponsables"
    },
    "champions": {
        "title": "🏆 UEFA CHAMPIONS LEAGUE • ANÁLISIS IA",
        "hooks": [
            "El modelo detectó un desfase enorme en las líneas de Champions League de hoy...",
            "Por qué este partido de Champions tiene las cuotas desbalanceadas en Playdoit:",
            "Así analizamos la jornada europea con Inteligencia Artificial:"
        ],
        "body": (
            "Analizamos volumen global, alineaciones tácticas y métricas avanzadas de presión ofensiva. "
            "Las mejores oportunidades de valor ocurren cuando el mercado sobrevalora a los gigantes europeos."
        ),
        "hashtags": "#ChampionsLeague #UCL #Playdoit #PicksChampions #ReyTacoPicks #ApuestasDeportivas #FutbolEuropeo"
    }
}


def get_copy_for_theme(theme: str) -> str:
    """Retorna el paquete completo de copy listo para publicar."""
    key = theme.lower().strip()
    if "parlay" in key:
        data = COPIES_BY_THEME["parlay"]
    elif "liga" in key or "mx" in key:
        data = COPIES_BY_THEME["ligamx"]
    elif "champ" in key or "ucl" in key:
        data = COPIES_BY_THEME["champions"]
    else:
        data = COPIES_BY_THEME["transparencia"]

    hooks_text = "\n".join([f"  {i+1}. <i>\"{h}\"</i>" for i, h in enumerate(data["hooks"])])

    return f"""📋 <b>PACK DE CONTENIDO: {data['title']}</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎣 <b>GANCHOS VIRALES (Elige 1 para los primeros 3 seg):</b>
{hooks_text}

📝 <b>TEXTO DE COPIA RÁPIDA (TikTok / Reels / Facebook):</b>
<code>{data['body']}

👉 Revisa el historial auditado y únete en el link del perfil: reytacopicks.com

{data['hashtags']}</code>

#️⃣ <b>HASHTAGS RECOMENDADOS:</b>
<code>{data['hashtags']}</code>"""


def get_general_hashtags() -> str:
    return (
        "🌮👑 <b>HASHTAGS DE MÁXIMO ALCANCE EN MÉXICO:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Para TikTok / Reels de Fútbol:</b>\n"
        "<code>#LigaMX #Playdoit #ApuestasMexico #PicksLigaMX #ReyTacoPicks #EstadisticaDeportiva #FutbolMexicano #PicksDeportivos #Chivas #ClubAmerica #CruzAzul #Tigres</code>\n\n"
        "<b>Para Parlays y Estrategia:</b>\n"
        "<code>#Parlay #Playdoit #ApuestasDeportivas #ReyTacoPicks #GestionDeBanca #ApuestasResponsables #InversionesDeportivas #CeroHumo #Transparencia</code>"
    )
