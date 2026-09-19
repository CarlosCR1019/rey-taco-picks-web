"""
backend/media_audio_engine.py
=============================
Motor multimedia unificado para Rey Taco Picks:
1. S?ntesis de voz Cloud Dual: ElevenLabs con fallback autom?tico a Edge-TTS (es-MX-JorgeNeural).
2. Mezcla y Muxing de Audio con FFmpeg: Fondo musical deportivo (bg_music.mp3) + locuci?n.
3. Conversi?n de Historias Est?ticas (1080x1920) a Micro-Videos MP4 con m?sica integrada para Instagram & Facebook.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
ASSETS_DIR = BASE_DIR / "assets"
DEFAULT_BG_MUSIC = ASSETS_DIR / "bg_music.mp3"

load_dotenv(BASE_DIR / ".env")
load_dotenv(REPO_ROOT / ".env")


def get_ffmpeg_exe() -> str:
    """Encuentra el ejecutable de FFmpeg del sistema o el integrado en imageio_ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe and Path(exe).is_file():
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def generate_tts_voiceover(
    text: str,
    output_path: Path,
    voice_id: Optional[str] = None
) -> Path:
    """
    Genera la narraci?n de audio en la nube.
    Intenta ElevenLabs primero; si se agotan los cr?ditos o falla,
    hace fallback instant?neo a Edge-TTS (Microsoft Azure es-MX-JorgeNeural, 100% gratuito e ilimitado).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    eleven_key = os.getenv("ELEVENLABS_API_KEY")
    default_voice = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
    
    # 1. Intento con ElevenLabs si hay API Key
    if eleven_key:
        try:
            import requests
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{default_voice}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": eleven_key
            }
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.50,
                    "similarity_boost": 0.75,
                    "style": 0.25,
                    "use_speaker_boost": True
                }
            }
            resp = requests.post(url, json=data, headers=headers, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 1000:
                output_path.write_bytes(resp.content)
                print(f"??? [ElevenLabs] Audio sintetizado ({len(resp.content)} bytes)")
                return output_path
            else:
                print(f"?? ElevenLabs respondi? {resp.status_code}: {resp.text[:120]}. Activando Fallback Edge-TTS...")
        except Exception as e:
            print(f"?? Error conectando con ElevenLabs: {e}. Activando Fallback Edge-TTS...")

    # 2. Fallback a Edge-TTS (Azure Neural: locutor deportivo mexicano de alta fidelidad)
    try:
        import edge_tts
        async def _run_edge():
            communicate = edge_tts.Communicate(text, "es-MX-JorgeNeural", rate="+6%", pitch="+0Hz")
            await communicate.save(str(output_path))
        asyncio.run(_run_edge())
        print(f"??? [Edge-TTS Cloud] Audio generado exitosamente con voz deportiva es-MX-JorgeNeural")
        return output_path
    except Exception as e:
        print(f"? Error en Fallback Edge-TTS: {e}")
        raise RuntimeError(f"No se pudo generar voz por ning?n servicio cloud: {e}")


def mux_music_to_video(
    video_path: Path,
    output_path: Path,
    bg_music_path: Optional[Path] = None,
    voiceover_path: Optional[Path] = None,
    music_volume: float = 0.85
) -> Path:
    """
    Incrusta la m?sica de fondo y opcionalmente voz en un video MP4.
    Asegura c?dec de audio AAC compatible 100% con Instagram y Facebook Stories/Reels.
    """
    ffmpeg = get_ffmpeg_exe()
    video_path = Path(video_path)
    output_path = Path(output_path)
    music_path = Path(bg_music_path) if bg_music_path else DEFAULT_BG_MUSIC

    if not music_path.exists():
        print(f"?? M?sica de fondo no encontrada en {music_path}, manteniendo video original.")
        shutil.copy(video_path, output_path)
        return output_path

    # Determinar si hay voz + m?sica o solo m?sica
    if voiceover_path and Path(voiceover_path).exists():
        # Filtro de mezcla: Voz a 1.0 (100%), m?sica a 0.18 (18%)
        filter_complex = (
            f"[1:a]volume=1.0[v_voice];"
            f"[2:a]volume=0.18[v_music];"
            f"[v_voice][v_music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-i", str(voiceover_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path)
        ]
    else:
        # Solo m?sica de fondo con fade-out al final
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", f"[1:a]volume={music_volume}[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path)
        ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"?? Video sonorizado exitosamente: {output_path.name}")
    except subprocess.CalledProcessError as e:
        print(f"?? Error muxing audio con FFmpeg: {e.stderr.decode('utf-8', errors='ignore')}")
        shutil.copy(video_path, output_path)

    return output_path


def convert_story_image_to_video_with_music(
    image_path: Path,
    output_path: Path,
    duration_sec: int = 7,
    bg_music_path: Optional[Path] = None
) -> Path:
    """
    Convierte una imagen est?tica 1080x1920 (Historia de FB/IG) en un micro-video vertical MP4
    con animaci?n sutil de zoom ken-burns y la m?sica deportiva de Rey Taco Picks.
    """
    ffmpeg = get_ffmpeg_exe()
    image_path = Path(image_path)
    output_path = Path(output_path)
    music_path = Path(bg_music_path) if bg_music_path else DEFAULT_BG_MUSIC

    total_frames = duration_sec * 30
    vf_filter = (
        f"zoompan=z='min(zoom+0.0007,1.05)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30,"
        f"format=yuv420p"
    )

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-stream_loop", "-1", "-i", str(music_path),
        "-vf", vf_filter,
        "-af", f"afade=t=out:st={duration_sec - 1.5}:d=1.5",
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(duration_sec),
        "-movflags", "+faststart",
        str(output_path)
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"?? Historia en video generada con m?sica: {output_path.name} ({duration_sec}s)")
    except subprocess.CalledProcessError as e:
        print(f"?? Error generando video de historia: {e.stderr.decode('utf-8', errors='ignore')}")
        raise

    return output_path