"""
backend/tiktok_video_generator.py
=================================
Generador Dinámico de Video Vertical 9:16 (1080x1920) para TikTok / Reels.
Utiliza exclusivamente Pillow, NumPy e ImageIO (acelerado por libx264).
Cero dependencia de navegadores headless o software externo pesado.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import numpy as np
import imageio
from PIL import Image, ImageDraw, ImageFont

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
OUTPUT_DIR = REPO_ROOT / "data" / "reels"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGO_PATH = REPO_ROOT / "frontend" / "public" / "logo.jpg"


def render_pick_tiktok_reel(
    pick: Dict[str, Any],
    output_path: Optional[Path] = None,
    duration_sec: int = 7,
    fps: int = 24
) -> Path:
    """
    Renderiza un video MP4 vertical (1080x1920) con estética institucional de Rey Taco Picks.
    Incluye animación progresiva de tarjetas, resplandor dorado, escaneo láser y sellado de Ticket ID.
    """
    ticket_id = pick.get("ticket_id", "RT-VERIFIED")
    home = pick.get("home_team", "Equipo Local")
    away = pick.get("away_team", "Equipo Visitante")
    league = pick.get("league", "Liga Principal")
    selection = pick.get("pick", "Selección Cuantitativa")
    odds = str(pick.get("market_odds_american") or pick.get("market_odds_decimal", "-110"))
    min_odds = str(pick.get("minimum_odds_american") or pick.get("minimum_odds_decimal", "-120"))
    ev = float(pick.get("ev_percent", 5.5))
    edge = float(pick.get("model_edge_pp", 4.2))
    game_time = pick.get("time", "20:00")

    if output_path is None:
        safe_tid = ticket_id.replace(":", "_").replace("/", "_")
        output_path = OUTPUT_DIR / f"reel_{safe_tid}.mp4"

    width, height = 1080, 1920
    total_frames = fps * duration_sec

    # Cargar logo institucional si existe
    logo_img = None
    if LOGO_PATH.exists():
        try:
            logo_img = Image.open(LOGO_PATH).convert("RGBA").resize((200, 200))
        except Exception:
            pass

    writer = imageio.get_writer(str(output_path), fps=fps, codec="libx264", quality=8)

    for f in range(total_frames):
        t = f / fps

        # 1. Fondo negro espacial con gradiente sutil
        frame = Image.new("RGBA", (width, height), (7, 11, 22, 255))
        draw = ImageDraw.Draw(frame)

        # 2. Resplandor radial dorado en cabecera
        glow_radius = int(320 + 30 * np.sin(t * 3.5))
        glow_center = (width // 2, 380)
        for r in range(glow_radius, 0, -25):
            alpha = int(16 * (1 - r / glow_radius))
            draw.ellipse(
                [
                    (glow_center[0] - r, glow_center[1] - r),
                    (glow_center[0] + r, glow_center[1] + r)
                ],
                fill=(234, 179, 8, alpha)
            )

        # 3. Marco institucional dorado doble
        draw.rounded_rectangle([(30, 30), (width - 30, height - 30)], radius=32, outline=(212, 175, 55, 180), width=3)
        draw.rounded_rectangle([(42, 42), (width - 42, height - 42)], radius=24, outline=(212, 175, 55, 80), width=1)

        # 4. Logo Institucional
        if logo_img:
            frame.paste(logo_img, (width // 2 - 100, 140), logo_img)

        # 5. Título y Badge de Cadencia
        draw.text((width // 2, 360), "REY TACO PICKS", fill=(254, 240, 138), anchor="mm", font_size=42)
        draw.text((width // 2, 410), "INTELIGENCIA CUANTITATIVA • +EV", fill=(203, 213, 225), anchor="mm", font_size=24)

        # 6. Tarjeta Principal del Partido (Aparece de 0.4s en adelante)
        if t >= 0.4:
            y_card = 490
            draw.rounded_rectangle([(70, y_card), (width - 70, y_card + 230)], radius=24, fill=(15, 23, 42, 240), outline=(212, 175, 55, 160), width=2)
            draw.text((105, y_card + 35), f"🏆 {league.upper()} • {game_time} CDMX", fill=(253, 224, 71), font_size=20)
            draw.text((105, y_card + 85), f"{home} vs {away}", fill=(255, 255, 255), font_size=32)
            draw.text((105, y_card + 145), f"🎯 Selección: {selection}", fill=(74, 222, 128), font_size=26)
            draw.text((105, y_card + 185), f"💰 Momio Playdoit: {odds}", fill=(226, 232, 240), font_size=22)

        # 7. Tarjeta de Ventaja Algorítmica (+EV & Edge) (Aparece a partir de 1.5s)
        if t >= 1.5:
            y_ev = 760
            draw.rounded_rectangle([(70, y_ev), (width - 70, y_ev + 210)], radius=24, fill=(20, 27, 45, 240), outline=(74, 222, 128, 160), width=2)
            draw.text((105, y_ev + 35), "📊 ANÁLISIS MATEMÁTICO SHARP", fill=(74, 222, 128), font_size=22)
            draw.text((105, y_ev + 85), f"📈 Valor Esperado: +{ev:.1f}% EV", fill=(255, 255, 255), font_size=28)
            draw.text((105, y_ev + 130), f"⚡ Ventaja sobre Mercado: +{edge:.1f} pp", fill=(255, 255, 255), font_size=26)
            draw.text((105, y_ev + 170), f"🛡️ Cuota Mínima Aceptable: {min_odds}", fill=(251, 146, 60), font_size=22)

        # 8. Regla de Oro / Filosofía Anti-Tipster (Aparece a partir de 2.6s)
        if t >= 2.6:
            y_rule = 1010
            draw.rounded_rectangle([(70, y_rule), (width - 70, y_rule + 180)], radius=22, fill=(30, 27, 75, 240), outline=(234, 179, 8, 220), width=2)
            draw.text((105, y_rule + 35), "⚠️ REGLA INSTITUCIONAL DE PRECIO", fill=(253, 224, 71), font_size=22)
            draw.text((105, y_rule + 80), f"Si la cuota cae de {min_odds}, la orden es NO APOSTAR.", fill=(226, 232, 240), font_size=24)
            draw.text((105, y_rule + 125), "No existen 'fijas'. Solo decisiones con valor esperado.", fill=(148, 163, 184), font_size=20)

        # 9. Badge de Ticket Criptográfico (Aparece a partir de 3.8s)
        if t >= 3.8:
            y_hash = 1230
            pulse_gold = int(210 + 35 * np.sin(t * 6))
            draw.rounded_rectangle([(70, y_hash), (width - 70, y_hash + 130)], radius=20, fill=(15, 23, 42, 250), outline=(pulse_gold, 179, 8, 255), width=2)
            draw.text((105, y_hash + 35), "🔒 AUDIT LEDGER SHA-256", fill=(250, 204, 21), font_size=22)
            draw.text((105, y_hash + 80), f"Ticket ID: {ticket_id}", fill=(255, 255, 255), font_size=24)

        # 10. Botón CTA y Redes (Aparece a partir de 4.8s)
        if t >= 4.8:
            y_cta = 1400
            pulse_btn = int(220 + 35 * np.sin(t * 7))
            draw.rounded_rectangle([(70, y_cta), (width - 70, y_cta + 100)], radius=20, fill=(pulse_btn, 179, 8, 255))
            draw.text((width // 2, y_cta + 50), "VERIFICA EL TICKET EN EL LINK DEL PERFIL", fill=(15, 23, 42), anchor="mm", font_size=28)

            y_foot = 1540
            draw.text((width // 2, y_foot + 40), "🌐 reytacopicks.com  •  📲 @ReyTacoPicksFree", fill=(203, 213, 225), anchor="mm", font_size=26)

        # 11. Efecto de Escáner Láser de Auditoría
        laser_y = int((t * 350) % (height + 250)) - 120
        if 0 <= laser_y < height:
            draw.rectangle([(50, laser_y), (width - 50, laser_y + 4)], fill=(250, 204, 21, 150))

        frame_rgb = frame.convert("RGB")
        frame_np = np.array(frame_rgb)
        writer.append_data(frame_np)

    writer.close()

    # Mux música de fondo deportiva
    try:
        try:
            from backend.media_audio_engine import mux_music_to_video
        except ModuleNotFoundError:
            from media_audio_engine import mux_music_to_video
        temp_audio = output_path.with_name(f"audio_{output_path.name}")
        mux_music_to_video(output_path, temp_audio, music_volume=0.85)
        if temp_audio.exists() and temp_audio.stat().st_size > 1000:
            temp_audio.replace(output_path)
    except Exception as e:
        print(f"⚠️ Nota de audio: {e}")


    return output_path



if __name__ == "__main__":
    test_pick = {
        "ticket_id": "RT-20260918-KBO-0001",
        "home_team": "Doosan Bears",
        "away_team": "Kiwoom Heroes",
        "league": "KBO Corea",
        "pick": "Más de 7.0 Carreras",
        "time": "03:30",
        "market_odds_american": "-135",
        "market_odds_decimal": 1.74,
        "minimum_odds_american": "-142",
        "model_edge_pp": 7.39,
        "ev_percent": 6.38
    }
    print("🎬 Renderizando prueba de reel vertical...")
    p = render_pick_tiktok_reel(test_pick, duration_sec=5)
    print(f"✅ Video generado: {p} ({p.stat().st_size / 1024:.1f} KB)")
