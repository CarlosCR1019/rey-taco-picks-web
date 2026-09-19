"""
backend/generate_quiniela_reel.py
=================================
Genera el Reel Oficial de Adquisición para Rey Taco Picks y la Quiniela Semanal Liga MX.
Formato: Vertical 9:16 (1080x1920 MP4 libx264).
Entrega directa opcional al Telegram del Administrador.
"""

import os
import sys
import time
from pathlib import Path
import numpy as np
import imageio
from PIL import Image, ImageDraw, ImageFont
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "data" / "reels"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGO_PATH = REPO_ROOT / "frontend" / "public" / "logo.jpg"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8684914807:AAHjNX6cz_sn1EUZVl0wt4v5iYWzJ8JU5UE")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_ID", "5912533842")


def render_quiniela_promo_reel(
    output_path: Path,
    duration_sec: int = 10,
    fps: int = 24
) -> Path:
    """
    Renderiza un reel cinemático vertical 9:16 estructurado en 3 fases:
    1. QUÉ ES REY TACO (Anti-humo, IA, datos reales)
    2. LO QUE HACEMOS (Modelos matemáticos, +EV, SHA-256)
    3. RETO QUINIELA LIGA MX (Participa gratis, gana 7 días VIP)
    """
    width, height = 1080, 1920
    total_frames = fps * duration_sec

    logo_img = None
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA").resize((190, 190))
        except Exception:
            pass

    writer = imageio.get_writer(str(output_path), fps=fps, codec="libx264", quality=8)

    for f in range(total_frames):
        t = f / fps

        # Fondo azul marino profundo espacial
        frame = Image.new("RGBA", (width, height), (8, 14, 28, 255))
        draw = ImageDraw.Draw(frame)

        # Gradiente radial dinámico de luz dorada en cabecera
        glow_radius = int(360 + 40 * np.sin(t * 3.0))
        glow_y = 350
        for r in range(glow_radius, 0, -30):
            alpha = int(22 * (1 - r / glow_radius))
            draw.ellipse(
                [(width // 2 - r, glow_y - r), (width // 2 + r, glow_y + r)],
                fill=(212, 168, 55, alpha)
            )

        # Marco institucional doble oro
        draw.rounded_rectangle([(32, 32), (width - 32, height - 32)], radius=36, outline=(212, 175, 55, 170), width=3)
        draw.rounded_rectangle([(44, 44), (width - 44, height - 44)], radius=26, outline=(212, 175, 55, 75), width=1)

        # Logo
        if logo_img:
            frame.paste(logo_img, (width // 2 - 95, 120), logo_img)

        # Cabecera fija
        draw.text((width // 2, 335), "REY TACO PICKS", fill=(254, 240, 138), anchor="mm", font_size=42)
        draw.text((width // 2, 385), "ANÁLISIS DEPORTIVO CUANTITATIVO CON IA", fill=(203, 213, 225), anchor="mm", font_size=23)

        # FASE 1: (0.0s - 3.2s) QUÉ HACE REY TACO (Romper el humo)
        if t < 3.2:
            card_y = 520
            draw.rounded_rectangle([(70, card_y), (width - 70, card_y + 440)], radius=24, fill=(15, 23, 42, 245), outline=(239, 68, 68, 200), width=2)
            draw.text((width // 2, card_y + 60), "🚫 CERO TIPSTERS DE HUMO", fill=(252, 165, 165), anchor="mm", font_size=32)
            draw.text((width // 2, card_y + 130), "No te vendemos billetes falsos.", fill=(255, 255, 255), anchor="mm", font_size=28)
            draw.text((width // 2, card_y + 180), "No prometemos milagros del 100%.", fill=(255, 255, 255), anchor="mm", font_size=28)
            
            draw.rounded_rectangle([(100, card_y + 240), (width - 100, card_y + 390)], radius=18, fill=(30, 41, 59, 230))
            draw.text((width // 2, card_y + 290), "🌮👑 IDENTIDAD REY TACO", fill=(254, 240, 138), anchor="mm", font_size=26)
            draw.text((width // 2, card_y + 340), "Frialdad matemática y datos en México.", fill=(226, 232, 240), anchor="mm", font_size=26)

            # Barra de progreso fase 1
            draw.rounded_rectangle([(120, 1020), (width - 120, 1030)], radius=5, fill=(30, 41, 59, 255))
            fill_w = int((width - 240) * (t / 3.2))
            draw.rounded_rectangle([(120, 1020), (120 + fill_w, 1030)], radius=5, fill=(239, 68, 68, 255))

        # FASE 2: (3.2s - 6.5s) LO QUE HACEMOS SIN SECRETOS
        elif t < 6.5:
            card_y = 500
            draw.rounded_rectangle([(70, card_y), (width - 70, card_y + 480)], radius=24, fill=(15, 23, 42, 245), outline=(59, 130, 246, 200), width=2)
            draw.text((width // 2, card_y + 55), "⚡ MODELOS DE INTELIGENCIA ARTIFICIAL", fill=(147, 197, 253), anchor="mm", font_size=30)
            
            puntos = [
                "📊 Escaneo de miles de cuotas en vivo",
                "🎯 Detección de Valor Esperado (+EV)",
                "🛡️ Filtro estricto de Cuota Mínima Aceptable",
                "🔗 Registro Criptográfico SHA-256"
            ]
            for idx, p in enumerate(puntos):
                py = card_y + 130 + (idx * 65)
                draw.rounded_rectangle([(100, py - 20), (width - 100, py + 35)], radius=12, fill=(30, 41, 59, 220))
                draw.text((125, py + 8), p, fill=(241, 245, 249), anchor="lm", font_size=25)

            draw.text((width // 2, card_y + 430), "🔒 Cada pick sellado antes del silbatazo. Cero trampas.", fill=(254, 240, 138), anchor="mm", font_size=22)

            # Barra de progreso fase 2
            draw.rounded_rectangle([(120, 1040), (width - 120, 1050)], radius=5, fill=(30, 41, 59, 255))
            fill_w = int((width - 240) * ((t - 3.2) / 3.3))
            draw.rounded_rectangle([(120, 1040), (120 + fill_w, 1050)], radius=5, fill=(59, 130, 246, 255))

        # FASE 3: (6.5s - 10.0s) EL RETO QUINIELA LIGA MX
        else:
            card_y = 470
            draw.rounded_rectangle([(70, card_y), (width - 70, card_y + 580)], radius=24, fill=(15, 23, 42, 250), outline=(234, 179, 8, 230), width=3)
            
            # Badge Quiniela
            draw.rounded_rectangle([(width // 2 - 220, card_y + 35), (width // 2 + 220, card_y + 85)], radius=15, fill=(212, 175, 55, 240))
            draw.text((width // 2, card_y + 60), "⚽ QUINIELA SEMANAL LIGA MX", fill=(15, 23, 42), anchor="mm", font_size=24)
            
            draw.text((width // 2, card_y + 135), "¿CREES QUE LE SABES MÁS A LA LIGA MX?", fill=(255, 255, 255), anchor="mm", font_size=28)
            draw.text((width // 2, card_y + 185), "Demuéstralo contra nuestra comunidad.", fill=(203, 213, 225), anchor="mm", font_size=24)
            
            # Tarjeta de Premio VIP
            py = card_y + 240
            draw.rounded_rectangle([(100, py), (width - 100, py + 160)], radius=18, fill=(88, 28, 135, 200), outline=(168, 85, 247, 180), width=2)
            draw.text((width // 2, py + 45), "🏆 PREMIO AL GANADOR:", fill=(245, 208, 254), anchor="mm", font_size=24)
            draw.text((width // 2, py + 95), "7 DÍAS DE PASE VIP COMPLETO", fill=(254, 240, 138), anchor="mm", font_size=32)
            draw.text((width // 2, py + 135), "100% GRATIS · SIN APUESTAS O PAGOS", fill=(233, 213, 255), anchor="mm", font_size=20)

            # Llamado a la acción
            draw.text((width // 2, card_y + 445), "👉 Participa gratis en segundos en:", fill=(241, 245, 249), anchor="mm", font_size=25)
            draw.text((width // 2, card_y + 495), "reytacopicks.com/quiniela", fill=(250, 204, 21), anchor="mm", font_size=34)
            draw.text((width // 2, card_y + 545), "O toca el enlace de nuestra Biografía 📲", fill=(148, 163, 184), anchor="mm", font_size=22)

            # Barra de progreso fase 3
            draw.rounded_rectangle([(120, 1100), (width - 120, 1110)], radius=5, fill=(30, 41, 59, 255))
            fill_w = int((width - 240) * ((t - 6.5) / 3.5))
            draw.rounded_rectangle([(120, 1100), (120 + fill_w, 1110)], radius=5, fill=(234, 179, 8, 255))

        # Tarjeta Inferior Permanente: Link en Bio
        y_bot = 1680
        draw.rounded_rectangle([(70, y_bot), (width - 70, y_bot + 160)], radius=24, fill=(11, 19, 38, 230), outline=(212, 175, 55, 120), width=2)
        draw.text((width // 2, y_bot + 50), "🌮👑 REY TACO PICKS • MÉXICO", fill=(254, 240, 138), anchor="mm", font_size=26)
        draw.text((width // 2, y_bot + 105), "Picks Gratuitos y Quiniela Semanal en reytacopicks.com", fill=(226, 232, 240), anchor="mm", font_size=22)

        # Escaneo láser institucional animado
        laser_y = int((t * 400) % height)
        draw.line([(50, laser_y), (width - 50, laser_y)], fill=(212, 175, 55, 90), width=3)

        frame_np = np.array(frame.convert("RGB"))
        writer.append_data(frame_np)

    writer.close()
    return output_path


def send_reel_to_telegram(video_path: Path, video_caption: str, detailed_message: str) -> bool:
    """Envía el video a Telegram y luego el pack detallado de instrucciones y copy."""
    url_video = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    url_msg = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        with open(video_path, "rb") as vf:
            files = {"video": vf}
            data = {
                "chat_id": ADMIN_CHAT_ID,
                "caption": video_caption,
                "parse_mode": "HTML"
            }
            resp = requests.post(url_video, files=files, data=data, timeout=60)
            if resp.status_code == 200:
                print("✅ Video enviado exitosamente a Telegram.")
            else:
                print(f"⚠️ Error enviando video: {resp.status_code} - {resp.text}")
                return False

        # Mensaje de seguimiento con el texto copiable
        msg_data = {
            "chat_id": ADMIN_CHAT_ID,
            "text": detailed_message,
            "parse_mode": "HTML"
        }
        resp_msg = requests.post(url_msg, json=msg_data, timeout=30)
        if resp_msg.status_code == 200:
            print("✅ Pack de copy e instrucciones enviado a Telegram.")
            return True
        else:
            print(f"⚠️ Error enviando mensaje de copy: {resp_msg.status_code} - {resp_msg.text}")
            return False
    except Exception as e:
        print(f"⚠️ Error en despacho: {e}")
        return False


if __name__ == "__main__":
    out_file = OUTPUT_DIR / "reel_quiniela_rey_taco.mp4"
    print(f"🎬 Renderizando Reel Oficial de Quiniela y Presentación...")
    t0 = time.time()
    rendered = render_quiniela_promo_reel(out_file, duration_sec=10, fps=24)
    print(f"✅ Reel generado en {time.time() - t0:.2f}s en: {rendered}")

    short_caption = (
        "🎬 <b>REEL OFICIAL: ¿QUÉ ES REY TACO & QUINIELA LIGA MX?</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📱 <b>Formato:</b> Vertical 9:16 (1080x1920 HD)\n"
        "🎯 <b>Objetivo:</b> Atraer clientes y usuarios a la web con la Quiniela Gratis."
    )

    creator_pack = (
        "📋 <b>COPY VIRAL LISTO PARA PEGAR EN TIKTOK / REELS:</b>\n"
        "(Toca el texto dentro del recuadro para copiar en 1 toque)\n\n"
        "<code>¿Cansado de tipsters que te venden milagros falsos? 🤦‍♂️\n\n"
        "En Rey Taco Picks no vendemos humo: usamos Inteligencia Artificial y modelos matemáticos para encontrar selecciones con valor real (+EV). Y cada pick se sella antes del partido en un registro público SHA-256.\n\n"
        "¿Crees que le sabes más al fútbol mexicano? ⚽🇲🇽\n\n"
        "👉 Llena tu QUINIELA GRATIS esta semana en reytacopicks.com/quiniela\n"
        "🏆 El que más aciertos tenga se lleva 7 DÍAS DE PASE VIP gratis.\n\n"
        "🔗 Enlace directo en mi biografía / perfil.\n\n"
        "#LigaMX #FutbolMexicano #QuinielaLigaMX #PronosticosDeportivos #ApuestasDeportivas #ReyTacoPicks #Chivas #ClubAmerica #CruzAzul</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎙️ <b>GUION DE VOZ EN OFF (Por si quieres grabarte hablando o usar voz de CapCut / TikTok):</b>\n\n"
        "• <b>[0:00 - 0:03]</b> <i>«¿Por qué el 95% de los tipsters solo te venden humo y capturas dudosas? En Rey Taco Picks hicimos las cosas al revés.»</i>\n"
        "• <b>[0:03 - 0:06]</b> <i>«Creamos modelos matemáticos de Inteligencia Artificial que auditan miles de cuotas buscando valor esperado real, y sellamos cada pick en un registro criptográfico antes del silbatazo.»</i>\n"
        "• <b>[0:06 - 0:10]</b> <i>«¿Crees que le sabes más a la Liga MX? Entra a reytacopicks.com/quiniela, llena tu quiniela 100% gratis y llévate 7 días de acceso VIP de regalo. Link en la bio.»</i>\n\n"
        "⏱️ <b>Instrucciones de publicación (45 segundos):</b>\n"
        "1. Descarga el video adjunto al carrete de tu celular.\n"
        "2. Ábrelo en TikTok o Instagram Reels.\n"
        "3. Pega el copy arriba en la descripción.\n"
        "4. Elige un audio en tendencia y bájale el volumen al 10-15%.\n"
        "5. ¡Publicar!"
    )

    print("📲 Despachando video y pack completo a Telegram...")
    send_reel_to_telegram(rendered, short_caption, creator_pack)
