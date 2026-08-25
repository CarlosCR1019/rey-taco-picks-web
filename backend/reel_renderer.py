"""Deterministic, network-free FFmpeg rendering for vertical reels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import warnings

from PIL import Image, UnidentifiedImageError


_MAX_FRAME_BYTES = 5 * 1024 * 1024
_MAX_REEL_BYTES = 50 * 1024 * 1024
_MAX_PROBE_BYTES = 256 * 1024


class ReelRenderer:
    """Compose three to five audited story frames into one local MP4."""

    def __init__(self, *, ffmpeg: str, ffprobe: str) -> None:
        if (
            not isinstance(ffmpeg, str)
            or not isinstance(ffprobe, str)
            or not Path(ffmpeg).is_file()
            or not Path(ffprobe).is_file()
        ):
            raise ValueError("FFmpeg and FFprobe executables are required")
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def render(self, frames: Sequence[bytes]) -> bytes:
        if (
            not isinstance(frames, Sequence)
            or isinstance(frames, (str, bytes))
            or not 3 <= len(frames) <= 5
        ):
            raise ValueError("reel requires three to five story frames")
        with TemporaryDirectory(prefix="rey-taco-reel-") as directory:
            root = Path(directory)
            frame_paths: list[Path] = []
            for index, data in enumerate(frames):
                _validate_story_jpeg(data)
                path = root / f"frame-{index:02d}.jpg"
                path.write_bytes(data)
                frame_paths.append(path)
            duration = 10.0 / len(frame_paths)
            manifest = root / "frames.txt"
            lines: list[str] = []
            for path in frame_paths:
                lines.extend((f"file '{path.as_posix()}'\n", f"duration {duration:.6f}\n"))
            lines.append(f"file '{frame_paths[-1].as_posix()}'\n")
            manifest.write_text("".join(lines), encoding="utf-8", newline="\n")
            output = root / "reel.mp4"
            _run_checked(
                [
                    self._ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(manifest),
                    "-vf",
                    "fps=30,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-movflags",
                    "+faststart",
                    "-an",
                    str(output),
                ],
                timeout=90,
            )
            metadata = _probe(self._ffprobe, output)
            _validate_probe(metadata)
            value = output.read_bytes()
            _validate_mp4(value)
            return value

    @staticmethod
    def probe(*, ffprobe: str, mp4: bytes) -> Mapping[str, object]:
        if not isinstance(ffprobe, str) or not Path(ffprobe).is_file():
            raise ValueError("FFprobe executable is required")
        _validate_mp4(mp4)
        with TemporaryDirectory(prefix="rey-taco-probe-") as directory:
            path = Path(directory) / "reel.mp4"
            path.write_bytes(mp4)
            metadata = _probe(ffprobe, path)
            _validate_probe(metadata)
            return metadata


def _validate_story_jpeg(data: bytes) -> None:
    if not isinstance(data, bytes) or not data or len(data) > _MAX_FRAME_BYTES:
        raise ValueError("reel frame must be bounded JPEG bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image.load()
                valid = (
                    image.format == "JPEG"
                    and image.mode == "RGB"
                    and image.size == (1080, 1920)
                )
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("reel frame must be an RGB 1080x1920 JPEG") from None
    if not valid:
        raise ValueError("reel frame must be an RGB 1080x1920 JPEG")


def _validate_mp4(value: object) -> None:
    if (
        not isinstance(value, bytes)
        or len(value) < 12
        or len(value) > _MAX_REEL_BYTES
        or value[4:8] != b"ftyp"
    ):
        raise ValueError("reel must contain bounded MP4 bytes")


def _run_checked(arguments: list[str], *, timeout: int) -> None:
    try:
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("FFmpeg rendering failed") from None
    if result.returncode != 0:
        raise RuntimeError("FFmpeg rendering failed")


def _probe(ffprobe: str, path: Path) -> Mapping[str, object]:
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("FFprobe validation failed") from None
    if (
        result.returncode != 0
        or not isinstance(result.stdout, bytes)
        or len(result.stdout) > _MAX_PROBE_BYTES
    ):
        raise RuntimeError("FFprobe validation failed")
    try:
        value = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("FFprobe validation failed") from None
    if not isinstance(value, Mapping):
        raise RuntimeError("FFprobe validation failed")
    return value


def _validate_probe(metadata: Mapping[str, object]) -> None:
    streams = metadata.get("streams")
    form = metadata.get("format")
    if (
        not isinstance(streams, list)
        or len(streams) != 1
        or not isinstance(streams[0], Mapping)
        or not isinstance(form, Mapping)
    ):
        raise RuntimeError("reel video stream was invalid")
    video = streams[0]
    try:
        duration = float(form.get("duration", 0))
    except (TypeError, ValueError):
        raise RuntimeError("reel media contract failed") from None
    if (
        video.get("codec_name") != "h264"
        or video.get("codec_type") != "video"
        or video.get("pix_fmt") != "yuv420p"
        or (video.get("width"), video.get("height")) != (1080, 1920)
        or not 8 <= duration <= 15
    ):
        raise RuntimeError("reel media contract failed")
