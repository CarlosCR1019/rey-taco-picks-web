import os
import sys
import json
import urllib.request
import urllib.parse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from backend.evidence_messaging import format_evidence_support
from backend.spanish_dates import cdmx_banner_date

_reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(_reconfigure_stdout):
    _reconfigure_stdout(encoding="utf-8")


def banner_date_label(generated_at=None):
    return cdmx_banner_date(generated_at)

def descargar_fondo_ia(prompt=None):
    """
    Genera y descarga un fondo hiperrealista de estadio deportivo usando la API gratuita de Pollinations FLUX.
    """
    if not prompt:
        prompts = [
            "cinematic empty modern football stadium at night with golden stadium lights, dramatic dark atmospheric volumetric smoke, 8k ultra detailed sports background",
            "hyperrealistic modern soccer arena floodlights at night, dark luxury aesthetic, golden bokeh lights, championship atmosphere, 8k",
            "dramatic baseball stadium at night with emerald grass, bright floodlights, dark volumetric stadium smoke, 8k cinematic",
            "futuristic dark sports stadium interior, golden neon accents, ultra realistic cinematic lighting, 8k wallpaper"
        ]
        # Seleccionar según el día
        import random
        prompt = random.choice(prompts)

    bg_path = os.path.join(os.path.dirname(__file__), "ai_stadium_bg.jpg")
    try:
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&model=flux&nologo=true"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            with open(bg_path, "wb") as f:
                f.write(resp.read())
        if os.path.exists(bg_path) and os.path.getsize(bg_path) > 5000:
            return bg_path
    except Exception as e:
        print(f"   ℹ️ Usando fondo oscuro de respaldo: {e}")
    return None

def generar_banner_redes(
    picks=None,
    output_path="banner_hoy.png",
    usar_ia=True,
    *,
    generated_at=None,
):
    """
    Genera un banner gráfico profesional de 1080x1080 px para Instagram / Facebook
    combinando fondos generados por Inteligencia Artificial con tipografía de alto impacto.
    """
    if not picks:
        json_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "picks.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                picks = json.load(f)
        else:
            picks = []

    free_picks = [p for p in picks if not p.get('es_parlay')][:3]

    width = 1080
    height = 1080

    # 1. Base / Fondo IA o Degradado
    ai_bg_file = descargar_fondo_ia() if usar_ia else None
    if ai_bg_file and os.path.exists(ai_bg_file):
        try:
            base_img = Image.open(ai_bg_file).resize((width, height)).convert("RGBA")
            # Oscurecer y contrastar para legibilidad óptima
            enhancer = ImageEnhance.Brightness(base_img)
            base_img = enhancer.enhance(0.35)
            # Capa de tinte azul/oscuro
            overlay = Image.new("RGBA", (width, height), (8, 12, 20, 160))
            img = Image.alpha_composite(base_img, overlay).convert("RGB")
        except Exception:
            img = Image.new("RGB", (width, height), color="#080c14")
    else:
        img = Image.new("RGB", (width, height), color="#080c14")

    draw = ImageDraw.Draw(img)

    # 2. Fuentes
    try:
        font_title = ImageFont.truetype("arialbd.ttf", 52)
        font_subtitle = ImageFont.truetype("arialbd.ttf", 34)
        font_card_title = ImageFont.truetype("arialbd.ttf", 32)
        font_card_pick = ImageFont.truetype("arialbd.ttf", 38)
        font_card_meta = ImageFont.truetype("arial.ttf", 26)
        font_footer = ImageFont.truetype("arialbd.ttf", 28)
    except:
        font_title = ImageFont.load_default()
        font_subtitle = font_title
        font_card_title = font_title
        font_card_pick = font_title
        font_card_meta = font_title
        font_footer = font_title

    # 3. Marco Dorado Exterior
    draw.rectangle([(20, 20), (width - 20, height - 20)], outline="#D4AF37", width=3)
    draw.rectangle([(26, 26), (width - 26, height - 26)], outline="#AA8C2C", width=1)

    # 4. Header
    draw.text((width // 2, 70), "🌮👑 REY TACO PICKS 👑🌮", fill="#D4AF37", font=font_title, anchor="mt")
    fecha_str = banner_date_label(generated_at)
    draw.text((width // 2, 135), f"PRONÓSTICOS DEPORTIVOS IA • {fecha_str.upper()}", fill="#CBD5E1", font=font_subtitle, anchor="mt")

    # 5. Tarjetas de los 3 Picks
    start_y = 200
    card_height = 230
    card_margin = 25
    card_width = width - 120
    card_x = 60

    for i, p in enumerate(free_picks):
        cy = start_y + (i * (card_height + card_margin))
        
        # Fondo translúcido de Tarjeta
        draw.rounded_rectangle([(card_x, cy), (card_x + card_width, cy + card_height)], radius=18, fill="#0F172A", outline="#334155", width=2)
        
        # Acento lateral rojo/carmesí
        draw.rounded_rectangle([(card_x, cy), (card_x + 12, cy + card_height)], radius=6, fill="#EF4444")

        # Categoría Tag
        cat = p.get('categoria', 'Deportes').upper()
        draw.text((card_x + 35, cy + 25), f"⚽ [{cat}]", fill="#38BDF8", font=font_card_meta)
        
        # Respaldo observable de datos (no probabilidad de ganar)
        conf = p.get('confianza', 'Datos no disponibles')
        draw.text((card_x + card_width - 35, cy + 25), format_evidence_support(conf), fill="#22C55E", font=font_card_meta, anchor="ra")

        # Partido
        partido = p.get('partido', 'Partido Destacado')
        draw.text((card_x + 35, cy + 68), partido, fill="#FFFFFF", font=font_card_title)

        # Selección / Pick (Dorado Brillante)
        pick_text = p.get('pick', 'Más de 2.5 Goles')
        draw.text((card_x + 35, cy + 120), f"🎯 {pick_text}", fill="#FACC15", font=font_card_pick)

        # Cuota y Horario
        cuota = p.get('cuota', '1.75')
        horario = p.get('horario', 'Hoy')
        value_text = "  |  💎 Señal de valor comparada" if p.get('tiene_valor') is True else ""
        draw.text((card_x + 35, cy + 175), f"📊 Momio: {cuota}  |  🕒 {horario}{value_text}", fill="#94A3B8", font=font_card_meta)

    # 6. Footer & Call To Action
    footer_y = height - 90
    draw.rectangle([(30, footer_y - 25), (width - 30, height - 30)], fill="#020617", outline="#D4AF37", width=1)
    draw.text((width // 2, footer_y - 12), "🌐 DESBLOQUEA ANÁLISIS PREMIUM EN: reytacopicks.com", fill="#FACC15", font=font_footer, anchor="mt")

    # Guardar
    img.save(output_path, "PNG", quality=95)
    print(f"🎉 Banner gráfico con IA generado exitosamente: {output_path} ({width}x{height} px)")
    return output_path

if __name__ == "__main__":
    generar_banner_redes()
