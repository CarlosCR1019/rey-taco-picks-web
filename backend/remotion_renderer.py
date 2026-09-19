"""Optional Remotion bridge with the existing FFmpeg renderer as fallback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Protocol

from backend.reel_renderer import ReelRenderer
from backend.remotion_input import ReelInput


_SAFE_REMOTION_ENV_KEYS = frozenset({
    "PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "NODE_ENV", "LANG", "LC_ALL",
})


def remotion_child_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if source is None else source
    return {
        key: str(value)
        for key, value in values.items()
        if key in _SAFE_REMOTION_ENV_KEYS and value
    }


class _FallbackRenderer(Protocol):
    def render(self, frames: Sequence[bytes]) -> bytes: ...


def render_with_fallback(
    package: ReelInput,
    *,
    remotion_command: list[str],
    fallback_renderer: _FallbackRenderer,
    fallback_frames: Sequence[bytes],
    enabled: bool,
) -> bytes:
    if not enabled:
        return fallback_renderer.render(fallback_frames)
    try:
        return _run_remotion_and_validate(package, remotion_command)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return fallback_renderer.render(fallback_frames)


def _run_remotion_and_validate(package: ReelInput, command: list[str]) -> bytes:
    if not isinstance(package, ReelInput) or not isinstance(command, list) or not command:
        raise ValueError("remotion package or command is invalid")
    if any(not isinstance(part, str) or not part for part in command):
        raise ValueError("remotion command is invalid")
    with TemporaryDirectory(prefix="rey-taco-remotion-") as directory:
        root = Path(directory)
        input_path = root / "input.json"
        output_path = root / "output.mp4"
        input_path.write_text(package.to_json(), encoding="utf-8", newline="\n")
        try:
            subprocess.run(
                [*command, "--input", str(input_path), "--output", str(output_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
                check=True,
                env=remotion_child_environment(),
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            raise RuntimeError("Remotion rendering failed") from None
        if not output_path.is_file():
            raise RuntimeError("Remotion output is missing")
        value = output_path.read_bytes()
    if len(value) < 12 or len(value) > 50 * 1024 * 1024 or value[4:8] != b"ftyp":
        raise RuntimeError("Remotion output is invalid")
    return value
