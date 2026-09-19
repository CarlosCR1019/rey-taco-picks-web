"""
backend/generate_daily_stories.py
=================================
Generador de Historias Verticales (1080x1920 px - 9:16) para Instagram Stories & Facebook Stories.

Diseño profesional con paleta oficial de Rey Taco Picks:
- Fondo profundo: #071021
- Acentos dorados: #F5CF58
- Tarjetas translúcidas: #101B31
- Tipografía clara con horarios CDMX y cuotas de Playdoit.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

MEXICO_TZ = ZoneInfo("America/Mexico_City")

LOGO_PATH = REPO_ROOT / "frontend" / "public" / "logo.jpg"
STORIES_DIR = REPO_ROOT / "data" / "stories"
STORIES_DIR.mkdir(parents=True, exist_ok=True)

# Paleta de colores
COLOR_BG = (7, 16, 33)           # #071021
COLOR_CARD = (16, 27, 49)        # #101B31
COLOR_CARD_BORDER = (35, 50, 80) # Sutil borde
COLOR_GOLD = (245, 207, 88)      # #F5CF58
COLOR_WHITE = (248, 250, 252)    # #F8FAFC
COLOR_MUTED = (170, 182, 202)    # #AAB6CA
COLOR_GREEN = (50, 213, 131)     # #32D583
COLOR_ORANGE = (255, 140, 50)


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Busca fuentes compatibles en Windows o Linux."""
    candidates = []
    if sys.platform == "win32":
        if bold:
            candidates.extend([
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/seguiemb.ttf",
                "C:/Windows/Fonts/DejaVuSans-Bold.ttf"
            ])
        else:
            candidates.extend([
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/DejaVuSans.ttf"
            ])
    else:
        # Linux (Ubuntu)
        if bold:
            candidates.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            ])
        else:
            candidates.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ])

    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_daily_story(
    matches: Optional[List[Dict[str, Any]]] = None,
    output_filename: Optional[str] = None
) -> Path:
    """Renderiza la historia vertical de 1080x1920 con la cartelera de hoy."""
    now = datetime.now(MEXICO_TZ)
    today_display = now.strftime("%d de %B, %Y").capitalize()
    
    # Mapeo de meses en español
    meses = {
        "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
        "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
        "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
    }
    for en, es in meses.items():
        today_display = today_display.replace(en, es)

    if not matches:
        matches = [
            {
                "league": "LIGA MX",
                "home": "Cruz Azul",
                "away": "Guadalajara",
                "time": "21:05 CDMX",
                "highlight": "Tiros de Esquina (+EV)",
                "odds": "+105"
            },
            {
                "league": "LIGA MX",
                "home": "Tigres UANL",
                "away": "Toluca",
                "time": "19:00 CDMX",
                "highlight": "Gignac +1.5 Remates a Puerta",
                "odds": "+120"
            },
            {
                "league": "BUNDESLIGA",
                "home": "Bayern Múnich",
                "away": "B. Leverkusen",
                "time": "10:30 CDMX",
                "highlight": "Más de 3.0 Goles",
                "odds": "-110"
            },
            {
                "league": "PREMIER LEAGUE",
                "home": "Manchester City",
                "away": "Arsenal",
                "time": "09:30 CDMX",
                "highlight": "Ambos Anotan & +2.5 Goles",
                "odds": "+115"
            }
        ]

    # Crear lienzo 1080x1920
    img = Image.new("RGB", (1080, 1920), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Marco exterior decorativo sutil
    draw.rounded_rectangle((24, 24, 1056, 1896), radius=36, outline=COLOR_GOLD, width=3)

    # 1. HEADER (Logo + Título)
    logo_y = 70
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
            logo_img = logo_img.resize((120, 120), Image.Resampling.LANCZOS)
            # Mascara circular
            mask = Image.new("L", (120, 120), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, 120, 120), fill=255)
            img.paste(logo_img, (70, logo_y), mask)
        except Exception as e:
            print(f"Error pegando logo: {e}")

    font_title = get_font(42, bold=True)
    font_subtitle = get_font(24, bold=False)
    font_badge = get_font(22, bold=True)

    draw.text((210, logo_y + 10), "REY TACO PICKS 🌮👑", fill=COLOR_GOLD, font=font_title)
    draw.text((210, logo_y + 65), f"CARTELERA DEL DÍA • {today_display}", fill=COLOR_MUTED, font=font_subtitle)

    # 2. BANNER DE TITULAR
    banner_y = 230
    draw.rounded_rectangle((60, banner_y, 1020, banner_y + 90), radius=20, fill=COLOR_CARD, outline=COLOR_CARD_BORDER, width=2)
    font_banner = get_font(28, bold=True)
    draw.text((100, banner_y + 28), "🔥 PARTIDOS CLAVE CON VALOR MATEMÁTICO (+EV)", fill=COLOR_WHITE, font=font_banner)

    # 3. TARJETAS DE PARTIDOS (4 partidos)
    card_start_y = 350
    card_height = 270
    card_spacing = 30

    font_league = get_font(22, bold=True)
    font_time = get_font(20, bold=False)
    font_match = get_font(38, bold=True)
    font_pick = get_font(26, bold=True)
    font_odds = get_font(30, bold=True)

    for i, m in enumerate(matches[:4]):
        cy = card_start_y + i * (card_height + card_spacing)
        
        # Tarjeta contenedor
        draw.rounded_rectangle((60, cy, 1020, cy + card_height), radius=24, fill=COLOR_CARD, outline=COLOR_CARD_BORDER, width=2)
        
        # Franja lateral dorada de acento
        draw.rounded_rectangle((60, cy, 76, cy + card_height), radius=8, fill=COLOR_GOLD)

        # Liga y Horario
        draw.text((100, cy + 24), m["league"], fill=COLOR_GOLD, font=font_league)
        draw.text((800, cy + 24), f"⏰ {m['time']}", fill=COLOR_MUTED, font=font_time)

        # Equipos
        match_title = f"{m['home']} vs {m['away']}"
        draw.text((100, cy + 70), match_title, fill=COLOR_WHITE, font=font_match)

        # Subtarjeta de Selección / Highlight
        pick_box_y = cy + 150
        draw.rounded_rectangle((100, pick_box_y, 1020 - 40, pick_box_y + 85), radius=16, fill=(10, 20, 38))
        
        draw.text((125, pick_box_y + 24), f"🎯 {m['highlight']}", fill=COLOR_GREEN, font=font_pick)
        draw.text((830, pick_box_y + 22), f"Momio {m['odds']}", fill=COLOR_GOLD, font=font_odds)

    # 4. FOOTER & CALL TO ACTION (CTA para Stories)
    footer_y = 1600
    draw.rounded_rectangle((60, footer_y, 1020, footer_y + 240), radius=28, fill=(16, 58, 45), outline=COLOR_GREEN, width=3)
    
    font_cta_title = get_font(36, bold=True)
    font_cta_sub = get_font(24, bold=False)
    font_cta_url = get_font(32, bold=True)

    draw.text((110, footer_y + 35), "📲 ACCESO A LOS PICKS DEL DÍA EN PLAYDOIT", fill=COLOR_WHITE, font=font_cta_title)
    draw.text((110, footer_y + 95), "Auditados con hash SHA-256 e historial 100% verificable.", fill=COLOR_MUTED, font=font_cta_sub)
    draw.text((110, footer_y + 155), "👉 REVISA EL LINK EN NUESTRO PERFIL: reytacopicks.com", fill=COLOR_GOLD, font=font_cta_url)

    if not output_filename:
        output_filename = f"story_cartelera_{now.strftime('%Y%m%d_%H%M%S')}.jpg"

    output_path = STORIES_DIR / output_filename
    img.save(str(output_path), "JPEG", quality=95)
    print(f"✅ Historia vertical guardada: {output_path}")
    return output_path


if __name__ == "__main__":
    p = render_daily_story()
    print(f"Rendered at {p}")
