"""
backend/auto_reel_producer.py
=============================
Productor 100% Automático de Reels con IA (Voz Neuronal + Subtítulos Dinámicos
Palabra por Palabra + Fondos de Google Flow + HUD Glassmorphism + Audio Mix).

Se ejecuta automáticamente desde:
1. Despacho de Picks Estelares / Reto Escalera (`multisport_cadence_engine.py` / `ladder_challenge_engine.py`)
2. Liquidación de Victorias Caja Verde (`victory_content_verifier.py`)
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

MEXICO_TZ = ZoneInfo("America/Mexico_City")
ASSETS_FLOW_DIR = REPO_ROOT / "assets" / "flow_broll"
TEMPLATE_PATH = REPO_ROOT / "lab" / "reels" / "template_ai_auto_reel.html"
OUT_REELS_DIR = REPO_ROOT / "data" / "reels"


def _file_to_data_uri(path: Path, mime: str = "image/webp") -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_broll_frames_b64(media_path: Path) -> List[str]:
    """Extrae hasta 32 fotogramas JPEG en base64 de un video/GIF de Google Flow para reproducción fluida."""
    if not media_path or not media_path.exists():
        return []
    frames_b64: List[str] = []
    try:
        with tempfile.TemporaryDirectory() as fdir:
            out_pattern = str(Path(fdir) / "f_%03d.jpg")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(media_path),
                    "-vf", "fps=8,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
                    "-frames:v", "40", "-q:v", "3", out_pattern
                ],
                check=True, capture_output=True, timeout=15
            )
            for jpg_file in sorted(Path(fdir).glob("f_*.jpg")):
                b64 = base64.b64encode(jpg_file.read_bytes()).decode("ascii")
                frames_b64.append(f"data:image/jpeg;base64,{b64}")
    except Exception as e:
        print(f"ℹ️ No se pudieron extraer frames de {media_path.name}: {e}")
    return frames_b64


def detect_sport_key(pick_or_str: Any) -> str:
    """Detecta la clave deportiva ('nba', 'nfl', 'tennis', 'mlb', 'futbol') desde cualquier diccionario o string."""
    if isinstance(pick_or_str, dict):
        s = " ".join(
            str(pick_or_str.get(k) or "")
            for k in ("sport", "sport_name", "league", "champ_name", "match", "event_name", "pick", "selection")
        ).lower()
    else:
        s = str(pick_or_str or "").lower()

    if any(k in s for k in ("nba", "basket", "baloncesto", "lakers", "celtics", "raptors", "pistons", "warriors", "rebote", "triple", "67")):
        return "nba"
    if any(k in s for k in ("nfl", "americano", "touchdown", "yardas", "chiefs", "ravens", "cowboys", "75")):
        return "nfl"
    if any(k in s for k in ("tenis", "tennis", "atp", "wta", "sets", "games", "juegos", "68")):
        return "tennis"
    if any(k in s for k in ("mlb", "beisbol", "béisbol", "home run", "carreras", "entradas", "yankees", "dodgers")):
        return "mlb"
    if any(k in s for k in ("futbol", "fútbol", "liga mx", "premier", "laliga", "champions", "serie a", "córner", "esquina", "goles", "remates", "66")):
        return "futbol"
    return "futbol"


SPORT_THEME_META: Dict[str, Dict[str, str]] = {
    "nba": {"icon": "🏀", "label": "NBA BASKETBALL", "chip": "🏀 NBA • RADAR CUANTITATIVO IA", "accent": "#F59E0B"},
    "nfl": {"icon": "🏈", "label": "NFL FOOTBALL", "chip": "🏈 NFL • GRIDIRON ANALYTICS IA", "accent": "#10B981"},
    "futbol": {"icon": "⚽", "label": "FÚTBOL SOCCER", "chip": "⚽ FÚTBOL • CÓRNERS & GOLES IA", "accent": "#10B981"},
    "tennis": {"icon": "🎾", "label": "TENIS ATP/WTA", "chip": "🎾 TENIS • HARDCOURT AI PRO", "accent": "#38BDF8"},
    "mlb": {"icon": "⚾", "label": "BÉISBOL MLB", "chip": "⚾ MLB • DIAMANTE ANALYTICS IA", "accent": "#FACC15"},
}


def _select_flow_broll(sport_or_pick: Any, mode: str) -> Tuple[Optional[Path], Optional[Path], str]:
    """
    Devuelve (video_or_gif_path, image_webp_path, sport_key) desde assets/flow_broll/ según el deporte y modo:
      - mode == 'ladder'  -> prioriza flow_ladder.{mp4,gif}, con fallback al deporte
      - mode == 'victory' -> prioriza flow_victory_{sport}.{mp4,gif}, con fallback a flow_victory.{mp4,gif}
      - mode == 'pick'    -> prioriza flow_{sport}.{mp4,gif}
    """
    sport_key = detect_sport_key(sport_or_pick)

    candidate_keys: List[str] = []
    if mode == "ladder":
        candidate_keys = ["ladder", sport_key, "nba"]
    elif mode == "victory":
        candidate_keys = [f"victory_{sport_key}", "victory", sport_key, "nba"]
    else:
        candidate_keys = [sport_key, "nba"]

    vid_candidate: Optional[Path] = None
    for k in candidate_keys:
        for ext in (".mp4", ".gif"):
            p = ASSETS_FLOW_DIR / f"flow_{k}{ext}"
            if p.exists():
                vid_candidate = p
                break
        if vid_candidate:
            break

    img_keys = ["victory", sport_key, "nba"] if mode == "victory" else [sport_key, "nba"]
    img_candidate: Optional[Path] = None
    for k in img_keys:
        p = ASSETS_FLOW_DIR / f"bg_{k}.webp"
        if p.exists():
            img_candidate = p
            break

    return vid_candidate, img_candidate, sport_key


def generate_voice_script(pick: Dict[str, Any], mode: str = "pick") -> str:
    """
    Genera el guion hablado de 10-12 segundos para el Reel.
    Intenta usar Groq para darle variedad fresca; si no, usa plantilla de alta retención.
    """
    match_name = str(pick.get("match") or pick.get("event_name") or "Partido Estelar").replace(" vs. ", " contra ").replace(" vs ", " contra ").replace(" @ ", " contra ")
    selection = str(pick.get("pick") or pick.get("selection") or "Selección Oficial")
    odds_am = str(pick.get("odds_american") or pick.get("market_odds_american") or "-110")
    odds_dec = str(pick.get("odds_decimal") or pick.get("market_odds_decimal") or "1.90")
    step = int(pick.get("step") or pick.get("ladder_step") or 1)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            if mode == "victory":
                prompt = (
                    f"Escribe un guion de locución de máximo 32 palabras en español mexicano muy energético para un Reel de TikTok celebrando una apuesta ganada (Caja Verde). "
                    f"Partido: {match_name}. Pronóstico ganado: {selection} con momio {odds_am}. "
                    f"Cierra invitando a entrar gratis al Telegram en el perfil de Rey Taco Picks. Sin emojis ni acotaciones, solo el texto hablado."
                )
            elif mode == "ladder":
                if step >= 2:
                    prompt = (
                        f"Escribe un guion de locución de máximo 32 palabras en español mexicano muy energético anunciando que ya ganamos el Paso 1 gratis del Reto Escalera de fin de semana "
                        f"y hoy jugamos el Paso {step} en {match_name} a cuota {odds_dec} exclusivo en el Canal VIP de Rey Taco Picks. NO reveles la selección. Sin emojis ni acotaciones."
                    )
                else:
                    prompt = (
                        f"Escribe un guion de locución de máximo 32 palabras en español mexicano muy energético para el Reto Escalera de fin de semana Paso 1 100% gratis. "
                        f"Partido: {match_name}. Selección abierta: {selection} con cuota {odds_dec}. "
                        f"Cierra invitando a seguir el reto en el Telegram del perfil de Rey Taco Picks. Sin emojis ni acotaciones, solo el texto hablado."
                    )
            else:
                prompt = (
                    f"Escribe un guion de locución de máximo 34 palabras en español mexicano muy energético para un Reel de TikTok revelando un pick deportivo con ventaja de IA. "
                    f"Partido: {match_name}. Selección: {selection} con momio {odds_am}. "
                    f"Cierra invitando a entrar gratis al Telegram en el perfil de Rey Taco Picks. Sin emojis ni acotaciones, solo el texto hablado."
                )
            resp = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=150,
            )
            txt = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
            if len(txt.split()) >= 10:
                return txt
        except Exception as e:
            print(f"ℹ️ Groq script fallback: {e}")

    if mode == "victory":
        return (
            f"¡Otra Caja Verde cobrada para la tribu de Rey Taco Picks! "
            f"En el duelo {match_name}, cobramos {selection} con momio {odds_am}. "
            f"¡Entra gratis a nuestro Telegram en el link del perfil!"
        )
    if mode == "ladder":
        if step >= 2:
            return (
                f"¡Atención tribu! Ya cobramos el Paso 1 gratis del Reto Escalera "
                f"y hoy jugamos el Paso {step} en {match_name} a cuota {odds_dec}. "
                f"¡Desbloquéalo ya en el Canal VIP desde el link del perfil!"
            )
        return (
            f"¡Atención tribu! Arranca el Paso 1 gratis del Reto Escalera de fin de semana en {match_name}. "
            f"Vamos con {selection} a cuota {odds_dec}. "
            f"¡Síguenos gratis en el Telegram del perfil!"
        )
    return (
        f"¡Ojo a esta línea con valor detectada por inteligencia artificial! "
        f"En {match_name}, entramos con {selection} a momio {odds_am}. "
        f"¡Únete gratis a nuestro Telegram en el link del perfil!"
    )


async def _edge_tts_synthesize(text: str, out_mp3: Path) -> List[Dict[str, Any]]:
    import email.utils
    import requests as std_requests
    import edge_tts
    import edge_tts.drm

    try:
        r = std_requests.head("https://www.bing.com", timeout=5)
        if "Date" in r.headers:
            srv_ts = email.utils.mktime_tz(email.utils.parsedate_tz(r.headers["Date"]))
            edge_tts.drm.clock_skew_seconds = srv_ts - time.time()
    except Exception:
        pass

    voice = "es-MX-JorgeNeural"
    communicate = edge_tts.Communicate(text, voice=voice, rate="+13%", pitch="-2Hz", boundary="WordBoundary")
    words: List[Dict[str, Any]] = []
    audio_chunks: List[bytes] = []

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start_s = chunk["offset"] / 10_000_000.0
            dur_s = max(0.12, chunk["duration"] / 10_000_000.0)
            words.append({
                "text": str(chunk["text"]).strip(),
                "start": round(start_s, 3),
                "end": round(start_s + dur_s, 3),
            })

    if not audio_chunks:
        raise RuntimeError("Edge-TTS returned empty audio")
    out_mp3.write_bytes(b"".join(audio_chunks))
    return words


def _fallback_tts_synthesize(text: str, out_mp3: Path) -> None:
    """Fallback neuronal usando Gemini 2.5 Flash TTS o Google Translate TTS acelerado a 1.18x."""
    import urllib.parse
    import requests as std_requests

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={gemini_key}"
            body = {
                "contents": [{"parts": [{"text": f"Lee con voz de comentarista deportivo mexicano muy energético y rápido: {text}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Orus"}}},
                },
            }
            resp = std_requests.post(url, json=body, timeout=20)
            if resp.status_code == 200:
                b64_pcm = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                raw_pcm = base64.b64decode(b64_pcm)
                pcm_file = out_mp3.with_suffix(".pcm")
                pcm_file.write_bytes(raw_pcm)
                subprocess.run(
                    ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(pcm_file), str(out_mp3)],
                    check=True, capture_output=True
                )
                return
        except Exception as e:
            print(f"ℹ️ Gemini TTS note: {e}")

    # Google TTS multi-chunk para que NUNCA se corte la frase final
    raw_mp3 = out_mp3.with_suffix(".raw.mp3")
    words_list = text.split()
    chunks: List[str] = []
    cur: List[str] = []
    for w in words_list:
        cand = " ".join(cur + [w])
        if len(cand) > 175 and cur:
            chunks.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        chunks.append(" ".join(cur))

    combined = bytearray()
    for ch in chunks:
        q = urllib.parse.quote(ch)
        tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=es-MX&q={q}"
        r = std_requests.get(tts_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200 and r.content:
            combined.extend(r.content)
    raw_mp3.write_bytes(bytes(combined))
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(raw_mp3), "-filter:a", "atempo=1.18", str(out_mp3)],
        check=True, capture_output=True
    )


def _probe_audio_duration(audio_path: Path) -> float:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, text=True, timeout=10
        )
        return float(res.stdout.strip())
    except Exception:
        return 10.5


def synthesize_voice_and_words(script_text: str, out_mp3: Path) -> Tuple[float, List[Dict[str, Any]]]:
    """Genera el MP3 con voz neuronal y devuelve (duracion_segundos, lista_palabras_con_timestamps)."""
    words: List[Dict[str, Any]] = []
    try:
        words = asyncio.run(_edge_tts_synthesize(script_text, out_mp3))
    except Exception as e:
        print(f"ℹ️ Usando motor TTS alternativo ({e})...")
        _fallback_tts_synthesize(script_text, out_mp3)

    duration = _probe_audio_duration(out_mp3)

    if not words:
        raw_tokens = [w.strip(".,!¡?¿\"'") for w in script_text.split() if w.strip()]
        n = max(1, len(raw_tokens))
        step = max(0.14, (duration - 0.15) / n)
        for idx, tok in enumerate(raw_tokens):
            words.append({
                "text": tok,
                "start": round(0.06 + idx * step, 3),
                "end": round(0.06 + (idx + 1) * step, 3),
            })

    return duration, words


def generate_backing_track_wav(duration_sec: float, out_wav: Path) -> None:
    """
    Sintetiza una pista instrumental deportiva (Dark Trap Sub-Bass + Hi-Hats + Whoosh + Cash Chime)
    en WAV 44.1kHz para mezclar detrás de la locución IA.
    """
    sr = 44100
    total_samples = int(sr * duration_sec)
    bpm = 124.0
    beat_sec = 60.0 / bpm

    buf = bytearray()
    for i in range(total_samples):
        t = i / sr
        beat_pos = (t % beat_sec) / beat_sec

        # 1. Deep 808 Sub-Bass Kick on beat 0 and 2.5
        kick_env = math.exp(-beat_pos * 9.5) if (int(t / beat_sec) % 2 == 0) else 0.0
        freq_808 = 55.0 + 65.0 * math.exp(-beat_pos * 28.0)
        sub = math.sin(2.0 * math.pi * freq_808 * t) * kick_env * 0.48

        # 2. Crisp Trap Hi-Hat (16th notes)
        hh_pos = (t % (beat_sec / 4.0)) / (beat_sec / 4.0)
        hh_env = math.exp(-hh_pos * 35.0)
        noise = ((i * 1103515245 + 12345) & 0x7FFFFFFF) / 0x7FFFFFFF * 2.0 - 1.0
        hihat = noise * hh_env * 0.10

        # 3. Minor Dark Synth Pad (E minor: E2 + G2 + B2)
        pad = (
            math.sin(2.0 * math.pi * 82.41 * t) * 0.12
            + math.sin(2.0 * math.pi * 123.47 * t) * 0.08
            + math.sin(2.0 * math.pi * 164.81 * t) * 0.06
        ) * (0.7 + 0.3 * math.sin(2.0 * math.pi * 0.5 * t))

        # 4. Whoosh impact at t=0.25s and t=0.80s
        chime = 0.0
        if 0.75 <= t <= 1.35:
            dt = t - 0.75
            chime = (
                math.sin(2.0 * math.pi * 1046.5 * dt) * math.exp(-dt * 8.0) * 0.22
                + math.sin(2.0 * math.pi * 1318.5 * dt) * math.exp(-dt * 6.0) * 0.22
            )

        rem = duration_sec - t
        fade = min(1.0, max(0.0, rem / 0.6)) if rem < 0.6 else 1.0

        sample = max(-0.95, min(0.95, (sub + hihat + pad + chime) * fade))
        val = int(sample * 32767.0)
        buf.extend(struct.pack("<h", val))

    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))


def mix_voice_and_beat(voice_mp3: Path, beat_wav: Path, out_aac: Path, total_duration: float) -> None:
    """Mezcla la voz neuronal (100% vol + silencio final apad) con el beat deportivo (18% vol) en AAC."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(voice_mp3),
        "-i", str(beat_wav),
        "-filter_complex",
        f"[0:a]volume=1.30,apad=whole_dur={total_duration:.2f}[v];[1:a]volume=0.18[b];[v][b]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "[aout]",
        "-t", f"{total_duration:.2f}",
        "-c:a", "aac", "-b:a", "192k",
        str(out_aac)
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def build_reel_payload(pick: Dict[str, Any], words: List[Dict[str, Any]], mode: str = "pick") -> Dict[str, Any]:
    vid_path, img_path, sport_key = _select_flow_broll(pick, mode)
    theme = SPORT_THEME_META.get(sport_key, SPORT_THEME_META["futbol"])

    logo_path = ASSETS_FLOW_DIR / "logo_flow.webp"
    logo_mime = "image/webp"
    if not logo_path.exists():
        logo_path = REPO_ROOT / "frontend" / "public" / "logo.jpg"
        logo_mime = "image/jpeg"

    match_name = str(pick.get("match") or pick.get("event_name") or "Partido Oficial").upper()
    raw_league = str(pick.get("league") or pick.get("champ_name") or theme["label"]).upper()
    if theme["icon"] not in raw_league:
        league_name = f"{theme['icon']} {raw_league}"
    else:
        league_name = raw_league
    time_str = str(pick.get("time_cdmx") or "HOY")
    selection = str(pick.get("pick") or pick.get("selection") or "SELECCIÓN OFICIAL").upper()
    odds_am = str(pick.get("odds_american") or pick.get("market_odds_american") or "-110")
    odds_dec = str(pick.get("odds_decimal") or pick.get("market_odds_decimal") or "1.90")
    stake_val = f"{pick.get('stake', 1.0)} UNIDAD"

    if mode == "victory":
        badge_text = f"✅ CAJA VERDE • {theme['label']}"
        sel_label = f"{theme['icon']} APUESTA LIQUIDADA GANADORA"
        m2_label = "RESULTADO OFICIAL"
        m2_val = str(pick.get("score") or "COBRADO 💰").upper()
        conf_val = 96
    elif mode == "ladder":
        step = int(pick.get("step") or pick.get("ladder_step") or 1)
        if step == 1:
            badge_text = "🪜 RETO ESCALERA • PASO 1 GRATIS"
            sel_label = f"{theme['icon']} PASO 1 ABIERTO (VIERNES A DOMINGO)"
            m2_label = "META ESCALERA"
            m2_val = "PASO 1 GRATIS 🟢"
        else:
            badge_text = f"🪜 RETO ESCALERA • PASO {step} VIP"
            sel_label = "🔒 EXCLUSIVO MIEMBROS CANAL VIP"
            selection = "🔒 DISPONIBLE EN CANAL VIP ($129)"
            m2_label = "ACCESO ESCALERA"
            m2_val = f"PASO {step} VIP 👑"
        conf_val = 91
    else:
        badge_text = f"🔥 PICK ESTELAR • {theme['label']}"
        sel_label = theme["chip"]
        m2_label = "STAKE RECOMENDADO"
        m2_val = stake_val
        conf_val = int(pick.get("confidence") or 89)

    broll_frames = _extract_broll_frames_b64(vid_path) if vid_path else []

    return {
        "mode": mode,
        "sport_key": sport_key,
        "sport_icon": theme["icon"],
        "sport_chip": theme["chip"],
        "sport_accent": theme["accent"],
        "logo_url": _file_to_data_uri(logo_path, logo_mime),
        "broll_img_url": _file_to_data_uri(img_path, "image/webp") if img_path else "",
        "broll_frames": broll_frames,
        "broll_video_url": "",
        "broll_video_file": str(vid_path) if vid_path else "",
        "badge_text": badge_text,
        "league_text": f"{league_name} • {time_str} CDMX",
        "match_text": match_name,
        "selection_label": sel_label,
        "selection_text": selection,
        "metric1_label": "CUOTA PLAYDOIT",
        "metric1_val": f"{odds_am} ({odds_dec})",
        "metric2_label": m2_label,
        "metric2_val": m2_val,
        "conf_label": "CONFIANZA ALGORÍTMICA IA",
        "confidence": conf_val,
        "words": words,
    }


def render_ai_reel(pick: Dict[str, Any], mode: str = "pick", output_mp4: Optional[Path] = None) -> Path:
    """
    Orquesta todo el pipeline:
    1. Guion IA
    2. Locución Edge-TTS + Word Timestamps
    3. Pista de audio mezclada (Voz + Beat + SFX) con +1.85s de margen final
    4. Renderizado de fotogramas 1080x1920 con Playwright Headless + FFmpeg H.264
    """
    OUT_REELS_DIR.mkdir(parents=True, exist_ok=True)
    now_tag = datetime.now(MEXICO_TZ).strftime("%Y%m%d_%H%M%S")
    if output_mp4 is None:
        output_mp4 = OUT_REELS_DIR / f"reytaco_ai_reel_{mode}_{now_tag}.mp4"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        voice_mp3 = tmp / "voice.mp3"
        beat_wav = tmp / "beat.wav"
        mixed_aac = tmp / "mixed.m4a"
        rendered_html = tmp / "reel.html"

        print(f"✍️ [1/4] Generando guion con IA para modo '{mode}'...")
        script_text = generate_voice_script(pick, mode=mode)
        print(f"   🗣️ Guion: {script_text}")

        print("🎙️ [2/4] Sintetizando voz neuronal y timestamps palabra por palabra...")
        voice_dur, words = synthesize_voice_and_words(script_text, voice_mp3)
        # +1.85s de margen después de que termina la voz para que jamás se corte
        total_dur = max(8.5, voice_dur + 1.85)
        print(f"   ⏱️ Duración voz: {voice_dur:.2f}s -> Duración total Reel: {total_dur:.2f}s ({len(words)} palabras sincronizadas)")

        print("🔊 [3/4] Generando mezcla de audio deportiva (Voz + Sub-Bass Beat + SFX)...")
        generate_backing_track_wav(total_dur, beat_wav)
        mix_voice_and_beat(voice_mp3, beat_wav, mixed_aac, total_dur)

        payload = build_reel_payload(pick, words, mode=mode)
        tpl_html = TEMPLATE_PATH.read_text(encoding="utf-8")
        tpl_html = tpl_html.replace("__REEL_PAYLOAD_JSON__", json.dumps(payload, ensure_ascii=False))
        rendered_html.write_text(tpl_html, encoding="utf-8")

        fps = 24
        total_frames = int(total_dur * fps)
        frames_dir = tmp / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        print(f"🎬 [4/4] Renderizando {total_frames} frames (1080x1920 @ {fps} FPS) con Playwright + FFmpeg...")

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"]
            )
            page = browser.new_page(viewport={"width": 1080, "height": 1920, "device_scale_factor": 1})
            page.goto(rendered_html.as_uri(), wait_until="domcontentloaded")
            page.wait_for_timeout(500)

            for f in range(total_frames):
                t_sec = f / fps
                page.evaluate(f"window.setTime({t_sec:.4f})")
                page.screenshot(path=str(frames_dir / f"frame_{f:04d}.jpg"), type="jpeg", quality=88)

            browser.close()

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%04d.jpg"),
            "-i", str(mixed_aac),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "copy",
            "-shortest",
            "-movflags", "+faststart",
            str(output_mp4),
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, timeout=60)

    print(f"✅ Reel IA generado con éxito: {output_mp4} ({output_mp4.stat().st_size // 1024} KB)")
    return output_mp4


def produce_and_dispatch_ai_reel(
    pick: Dict[str, Any],
    mode: str = "pick",
    send_telegram: bool = True,
    publish_social: bool = True,
) -> Optional[str]:
    """
    Produce el Reel MP4 con IA, lo sube a Cloudflare R2, lo envía al Telegram de Carlos
    (y Lleny) y lo publica en Instagram/Facebook Reels si las credenciales están activas.
    """
    try:
        mp4_path = render_ai_reel(pick, mode=mode)
    except Exception as e:
        print(f"⚠️ Error produciendo Reel IA ({mode}): {e}")
        return None

    public_url = None
    try:
        from lab.r2_storage import upload_to_r2
        public_url = upload_to_r2(str(mp4_path), f"reels/{mp4_path.name}")
        print(f"☁️ Reel subido a Cloudflare R2: {public_url}")
    except Exception as e:
        print(f"ℹ️ Subida R2 omitida: {e}")

    match_name = pick.get("match") or pick.get("event_name") or "Partido Oficial"
    selection = pick.get("pick") or pick.get("selection") or "Selección IA"
    odds_am = pick.get("odds_american") or pick.get("market_odds_american") or "-110"

    if mode == "victory":
        caption = (
            f"✅ ¡OTRA CAJA VERDE COBRADA! 🌮👑\n\n"
            f"🏟️ {match_name}\n"
            f"🎯 {selection} ({odds_am}) 💰\n\n"
            f"Entra gratis a nuestro canal de Telegram en el link del perfil 👉 @reytaco_picks\n\n"
            f"#ReyTacoPicks #ApuestasDeportivas #CajaVerde #PicksDeportivos #Playdoit #Parlay"
        )
    elif mode == "ladder":
        step = int(pick.get("step") or pick.get("ladder_step") or 1)
        sel_display = "🔒 [EXCLUSIVO CANAL VIP - $129 MXN]" if step >= 2 else f"{selection} ({odds_am})"
        caption = (
            f"🪜 RETO ESCALERA FIN DE SEMANA • PASO {step} DE 3 ({'GRATIS' if step == 1 else 'EXCLUSIVO VIP'}) 🌮👑\n\n"
            f"🏟️ {match_name}\n"
            f"🎯 {sel_display}\n\n"
            f"🟢 Paso 1 (Viernes): SIEMPRE GRATIS\n"
            f"🔒 Paso 2 y Paso 3 (Sábado y Domingo): EXCLUSIVOS CANAL VIP ($129/sem)\n\n"
            f"Entra desde el link del perfil 👉 @reytaco_picks\n\n"
            f"#RetoEscalera #ReyTacoPicks #ApuestasDeportivas #PicksGratis #Playdoit"
        )
    else:
        caption = (
            f"🔥 PICK ESTELAR DETECTADO POR IA 🌮👑\n\n"
            f"🏟️ {match_name}\n"
            f"🎯 {selection} ({odds_am})\n\n"
            f"Todos los picks gratis en nuestro Telegram (Link en Bio) 👉 @reytaco_picks\n\n"
            f"#ReyTacoPicks #ApuestasDeportivas #NBA #NFL #LigaMX #PicksDeportivos"
        )

    if send_telegram:
        try:
            import requests as std_requests
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
            admin_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "5912533842"
            gf_id = os.getenv("TELEGRAM_GF_CHAT_ID", "8996443105").strip()
            team_group_id = os.getenv("TIKTOK_EDITORIAL_GROUP_ID", "-5369214121").strip()
            free_channel_id = (
                os.getenv("TELEGRAM_FREE_CHANNEL_ID")
                or os.getenv("TELEGRAM_CHANNEL_ID")
                or "-1003537080446"
            ).strip()

            targets = []
            for t in (str(admin_id).strip(), gf_id, team_group_id, free_channel_id):
                if t and t not in targets:
                    targets.append(t)

            for cid in targets:
                with open(mp4_path, "rb") as vf:
                    std_requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendVideo",
                        data={
                            "chat_id": cid,
                            "caption": caption,
                            "supports_streaming": "true",
                        },
                        files={"video": (mp4_path.name, vf, "video/mp4")},
                        timeout=60,
                    )
                if cid in (gf_id, team_group_id):
                    std_requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        data={
                            "chat_id": cid,
                            "text": (
                                "📋 <b>COPY LISTO PARA TIKTOK / REELS (Toca para copiar):</b>\n\n"
                                f"<code>{caption}</code>"
                            ),
                            "parse_mode": "HTML",
                        },
                        timeout=20,
                    )
            print(f"📲 Reel MP4 despachado en Telegram a {len(targets)} destinos (Privados, Grupo y Canal).")
        except Exception as e:
            print(f"⚠️ Error enviando Reel a Telegram: {e}")

    if publish_social:
        try:
            from backend.social_publisher import publish_reel_to_meta
            publish_reel_to_meta(public_url, caption, mp4_path=mp4_path)
        except Exception as e_soc:
            print(f"⚠️ Error publicando Reel en Meta: {e_soc}")

    return str(mp4_path)


if __name__ == "__main__":
    sample_pick = {
        "sport": "NBA",
        "league": "🏀 NBA",
        "match": "Toronto Raptors vs Detroit Pistons",
        "time_cdmx": "17:30",
        "pick": "Toronto Raptors Ganador",
        "odds_american": "-118",
        "odds_decimal": "1.85",
        "stake": 1.0,
        "confidence": 91,
        "step": 1,
    }
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "pick"
    send_tg = "--telegram" in sys.argv
    produce_and_dispatch_ai_reel(sample_pick, mode=mode_arg, send_telegram=send_tg)
