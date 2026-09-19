"""
backend/generate_instagram_carousel.py
======================================
Generador de Carruseles Educativos y Virales para Instagram Feed (1080x1350 px - Ratio 4:5).

Genera un set coherente de 4 diapositivas:
- Slide 1: Hook / Gancho viral de alta retención.
- Slide 2: Explicación didáctica del Valor Esperado (+EV) y ventaja matemática.
- Slide 3: Evidencia real de Playdoit y sellado criptográfico SHA-256.
- Slide 4: Llamado a la acción (CTA) para ingresar a reytacopicks.com.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional

from PIL import Image, ImageDraw, ImageFont

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

MEXICO_TZ = ZoneInfo("America/Mexico_City")

LOGO_PATH = REPO_ROOT / "frontend" / "public" / "logo.jpg"
CAROUSELS_DIR = REPO_ROOT / "data" / "carousels"
CAROUSELS_DIR.mkdir(parents=True, exist_ok=True)

# Paleta
COLOR_BG = (7, 16, 33)           # #071021
COLOR_CARD = (16, 27, 49)        # #101B31
COLOR_CARD_BORDER = (35, 50, 80)
COLOR_GOLD = (245, 207, 88)      # #F5CF58
COLOR_WHITE = (248, 250, 252)    # #F8FAFC
COLOR_MUTED = (170, 182, 202)    # #AAB6CA
COLOR_GREEN = (50, 213, 131)     # #32D583
COLOR_RED = (255, 107, 107)


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if sys.platform == "win32":
        if bold:
            candidates.extend(["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/seguiemb.ttf"])
        else:
            candidates.extend(["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf"])
    else:
        if bold:
            candidates.extend(["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"])
        else:
            candidates.extend(["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])

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


def _draw_header(draw: ImageDraw.Draw, img: Image.Image, slide_num: int, total_slides: int = 4):
    """Encabezado estandarizado con logo y paginación."""
    draw.rounded_rectangle((20, 20, 1060, 1330), radius=32, outline=COLOR_GOLD, width=3)

    logo_y = 60
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA")
            logo_img = logo_img.resize((80, 80), Image.Resampling.LANCZOS)
            mask = Image.new("L", (80, 80), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 80, 80), fill=255)
            img.paste(logo_img, (60, logo_y), mask)
        except Exception:
            pass

    font_brand = get_font(28, bold=True)
    font_page = get_font(22, bold=True)
    draw.text((160, logo_y + 10), "REY TACO PICKS", fill=COLOR_GOLD, font=font_brand)
    draw.text((160, logo_y + 45), "EDUCACIÓN CUANTITATIVA", fill=COLOR_MUTED, font=get_font(18))

    # Indicador de slide (ej. 1/4)
    draw.rounded_rectangle((920, logo_y + 15, 1010, logo_y + 60), radius=16, fill=COLOR_CARD, outline=COLOR_CARD_BORDER)
    draw.text((945, logo_y + 24), f"{slide_num}/{total_slides}", fill=COLOR_WHITE, font=font_page)


def render_slide_1_hook() -> Image.Image:
    img = Image.new("RGB", (1080, 1350), COLOR_BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, img, 1)

    # Badge de alerta
    draw.rounded_rectangle((60, 240, 480, 305), radius=18, fill=(69, 31, 42), outline=COLOR_RED, width=2)
    draw.text((90, 258), "⚠️ ALERTA DE ESTRATEGIA", fill=COLOR_RED, font=get_font(22, bold=True))

    # Título principal
    font_h1 = get_font(56, bold=True)
    draw.text((60, 350), "¿Por qué el 95% pierde", fill=COLOR_WHITE, font=font_h1)
    draw.text((60, 430), "dinero en los Parlays?", fill=COLOR_GOLD, font=font_h1)

    # Cuerpo
    font_body = get_font(30, bold=False)
    body_text = (
        "Las casas de apuestas como Playdoit aman los parlays\n"
        "porque multiplican el margen de la casa (vig) en cada selección.\n\n"
        "Si combinas 3 jugadas sin ventaja matemática (+EV),\n"
        "tus probabilidades reales se desploman exponencialmente.\n\n"
        "Desliza para ver la fórmula matemática con la que\n"
        "revertimos esta desventaja a nuestro favor ➔"
    )
    draw.text((60, 560), body_text, fill=COLOR_MUTED, font=font_body)

    # Footer swipe
    draw.rounded_rectangle((60, 1180, 1020, 1260), radius=20, fill=COLOR_CARD)
    draw.text((360, 1205), "👉 DESLIZA A LA IZQUIERDA ➔", fill=COLOR_GOLD, font=get_font(24, bold=True))
    return img


def render_slide_2_math() -> Image.Image:
    img = Image.new("RGB", (1080, 1350), COLOR_BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, img, 2)

    draw.text((60, 230), "LA FÓRMULA DEL +EV", fill=COLOR_GOLD, font=get_font(46, bold=True))
    draw.text((60, 290), "Valor Esperado: La ventaja de los profesionales", fill=COLOR_MUTED, font=get_font(24))

    # Caja 1: Fórmula
    draw.rounded_rectangle((60, 370, 1020, 550), radius=24, fill=COLOR_CARD, outline=COLOR_CARD_BORDER, width=2)
    draw.text((100, 400), "📐 FÓRMULA DE VALOR ESPERADO (+EV):", fill=COLOR_GOLD, font=get_font(24, bold=True))
    draw.text((100, 450), "EV = (Probabilidad Real × Momio) - 1", fill=COLOR_WHITE, font=get_font(38, bold=True))
    draw.text((100, 505), "Solo jugamos cuando el EV es positivo (+4.0% o superior).", fill=COLOR_GREEN, font=get_font(22))

    # Caja 2: Explicación de ventaja
    draw.rounded_rectangle((60, 590, 1020, 1120), radius=24, fill=COLOR_CARD, outline=COLOR_CARD_BORDER, width=2)
    draw.text((100, 630), "🎯 LAS 3 REGLAS REY TACO:", fill=COLOR_WHITE, font=get_font(30, bold=True))
    
    rules = [
        ("1. Cero Corazonadas", "Cada selección proviene de modelos de regresión y xG, no de fanatismo."),
        ("2. Margen de Cuota Mínima", "Si el momio cae por debajo de la cuota mínima calculada, NO SE APUESTA."),
        ("3. Gestión Kelly Adaptativa", "Nunca arriesgamos más del 1.5% del bankroll por jugada.")
    ]
    for i, (title, desc) in enumerate(rules):
        ry = 700 + i * 130
        draw.text((100, ry), title, fill=COLOR_GOLD, font=get_font(26, bold=True))
        draw.text((100, ry + 40), desc, fill=COLOR_MUTED, font=get_font(22))

    # Footer swipe
    draw.rounded_rectangle((60, 1180, 1020, 1260), radius=20, fill=COLOR_CARD)
    draw.text((360, 1205), "👉 MIRA LA EVIDENCIA REAL ➔", fill=COLOR_GOLD, font=get_font(24, bold=True))
    return img


def render_slide_3_evidence() -> Image.Image:
    img = Image.new("RGB", (1080, 1350), COLOR_BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, img, 3)

    draw.text((60, 230), "TRANSPARENCIA TOTAL", fill=COLOR_GREEN, font=get_font(46, bold=True))
    draw.text((60, 290), "Boleto oficial de Playdoit y Ledger Criptográfico", fill=COLOR_MUTED, font=get_font(24))

    # Tarjeta central simulando el boleto de Playdoit verificado
    draw.rounded_rectangle((60, 370, 1020, 940), radius=24, fill=COLOR_CARD, outline=COLOR_GREEN, width=3)
    
    # Barra verde de ganado oficial Playdoit
    draw.rounded_rectangle((60, 370, 1020, 440), radius=24, fill=(16, 58, 45))
    draw.text((100, 388), "✅ APUESTA GANADA • FOLIO PLAYDOIT 5379382766", fill=COLOR_GREEN, font=get_font(26, bold=True))

    draw.text((100, 480), "⚽ Celaya vs Tapachula — Liga de Expansión MX", fill=COLOR_WHITE, font=get_font(30, bold=True))
    draw.text((100, 530), "Resultado Final: 2-0 • Cobrado con cuota 1.64", fill=COLOR_MUTED, font=get_font(24))

    draw.rounded_rectangle((100, 600, 980, 780), radius=18, fill=(10, 20, 38))
    draw.text((130, 630), "🛡️ SELLO CRIPTOGRÁFICO SHA-256:", fill=COLOR_GOLD, font=get_font(22, bold=True))
    draw.text((130, 675), "Hash: 8b671a93b4f9...f042e", fill=COLOR_WHITE, font=get_font(26))
    draw.text((130, 725), "Registrado públicamente antes del silbatazo inicial.", fill=COLOR_MUTED, font=get_font(20))

    draw.text((100, 820), "⚠️ REGLA DE ORO: En Rey Taco Picks NUNCA borramos un pick.", fill=COLOR_WHITE, font=get_font(24, bold=True))
    draw.text((100, 860), "Mostramos tanto las victorias como las caídas con balance neto.", fill=COLOR_MUTED, font=get_font(22))

    # Footer swipe
    draw.rounded_rectangle((60, 1180, 1020, 1260), radius=20, fill=COLOR_CARD)
    draw.text((380, 1205), "👉 ÚNETE AL VIP HOY ➔", fill=COLOR_GOLD, font=get_font(24, bold=True))
    return img


def render_slide_4_cta() -> Image.Image:
    img = Image.new("RGB", (1080, 1350), COLOR_BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, img, 4)

    draw.text((60, 230), "DEJA DE APOSTAR", fill=COLOR_WHITE, font=get_font(50, bold=True))
    draw.text((60, 300), "A CIEGAS 🌮👑", fill=COLOR_GOLD, font=get_font(50, bold=True))

    draw.text((60, 390), "Accede a selecciones con ventaja matemática y gestión de banca.", fill=COLOR_MUTED, font=get_font(26))

    # Caja de beneficios VIP
    draw.rounded_rectangle((60, 480, 1020, 960), radius=24, fill=COLOR_CARD, outline=COLOR_CARD_BORDER, width=2)
    draw.text((100, 520), "💎 LO QUE RECIBES EN EL VIP:", fill=COLOR_GOLD, font=get_font(28, bold=True))

    benefits = [
        "🎯 Picks y Parlays cuantitativos con cuota mínima obligatoria.",
        "📸 Foto de boleto de Playdoit con cada jugada.",
        "📊 Alertas inmediatas de mercado y desajuste de líneas.",
        "🛡️ Acceso al Audit Ledger público SHA-256.",
        "💬 Soporte y orientación directa para proteger tu capital."
    ]
    for i, b in enumerate(benefits):
        draw.text((100, 590 + i * 65), f"• {b}", fill=COLOR_WHITE, font=get_font(24))

    # Botón de CTA final
    cta_y = 1010
    draw.rounded_rectangle((60, cta_y, 1020, cta_y + 130), radius=26, fill=COLOR_GOLD)
    draw.text((140, cta_y + 40), "👉 VISITA: reytacopicks.com (LINK EN BIO)", fill=COLOR_BG, font=get_font(34, bold=True))

    draw.text((360, 1210), "🌮👑 Síguenos en @reytacopicks", fill=COLOR_MUTED, font=get_font(22))
    return img


def generate_instagram_carousel(batch_name: Optional[str] = None) -> List[Path]:
    """Genera las 4 diapositivas del carrusel y las guarda en disco."""
    if not batch_name:
        batch_name = datetime.now(MEXICO_TZ).strftime("carousel_%Y%m%d_%H%M%S")

    batch_dir = CAROUSELS_DIR / batch_name
    batch_dir.mkdir(parents=True, exist_ok=True)

    slides = [
        ("slide_1_hook.jpg", render_slide_1_hook()),
        ("slide_2_math.jpg", render_slide_2_math()),
        ("slide_3_evidence.jpg", render_slide_3_evidence()),
        ("slide_4_cta.jpg", render_slide_4_cta()),
    ]

    saved_paths = []
    for filename, img in slides:
        p = batch_dir / filename
        img.save(str(p), "JPEG", quality=95)
        saved_paths.append(p)
        print(f"✅ Slide guardado: {p}")

    return saved_paths


if __name__ == "__main__":
    paths = generate_instagram_carousel()
    print(f"Carrusel de {len(paths)} slides generado con éxito.")
