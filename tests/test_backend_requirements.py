from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "backend" / "requirements.txt"


def test_windows_runtime_installs_iana_timezone_database():
    packages = {
        line.strip().split("==", 1)[0].split(">=", 1)[0].lower()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "tzdata" in packages


def test_reels_use_local_ffmpeg_without_paid_or_generative_video_sdk():
    packages = {
        line.strip().split("==", 1)[0].split(">=", 1)[0].lower()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert packages.isdisjoint(
        {
            "runwayml",
            "replicate",
            "fal-client",
            "moviepy",
            "imageio-ffmpeg",
        }
    )
