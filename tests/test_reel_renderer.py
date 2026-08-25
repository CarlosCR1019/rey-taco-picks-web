from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil

from PIL import Image
import pytest

from backend.reel_renderer import ReelRenderer


def story_jpeg(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (1080, 1920), color).save(
        output,
        format="JPEG",
        quality=88,
    )
    return output.getvalue()


def media_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are not installed on this host")
    return ffmpeg, ffprobe


def test_reel_is_vertical_h264_and_between_eight_and_fifteen_seconds() -> None:
    ffmpeg, ffprobe = media_tools()
    video = ReelRenderer(ffmpeg=ffmpeg, ffprobe=ffprobe).render(
        (
            story_jpeg((7, 16, 33)),
            story_jpeg((16, 27, 49)),
            story_jpeg((245, 207, 88)),
            story_jpeg((7, 16, 33)),
        )
    )

    metadata = ReelRenderer.probe(ffprobe=ffprobe, mp4=video)
    stream = metadata["streams"][0]
    duration = float(metadata["format"]["duration"])
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert 8 <= duration <= 15
    assert stream["pix_fmt"] == "yuv420p"


@pytest.mark.parametrize("count", [0, 2, 6])
def test_reel_rejects_fewer_than_three_or_more_than_five_frames(
    tmp_path: Path,
    count: int,
) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.touch()
    ffprobe.touch()
    renderer = ReelRenderer(ffmpeg=str(ffmpeg), ffprobe=str(ffprobe))

    with pytest.raises(ValueError, match="three to five"):
        renderer.render(tuple(story_jpeg((0, 0, 0)) for _ in range(count)))


def test_reel_requires_existing_ffmpeg_and_ffprobe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="executables"):
        ReelRenderer(
            ffmpeg=str(tmp_path / "missing-ffmpeg.exe"),
            ffprobe=str(tmp_path / "missing-ffprobe.exe"),
        )
