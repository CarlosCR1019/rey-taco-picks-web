from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from backend import social_banner
from backend.social_content import SocialContent


def _content() -> SocialContent:
    return SocialContent(
        pick_id="1780000000000000",
        category="Liga MX",
        event="América vs Tigres",
        selection="América gana",
        odds_text="1.80",
        schedule="21 AGO · 20:00 CDMX",
        observed_at=datetime(2026, 8, 21, 17, 30, tzinfo=timezone.utc),
        starts_at=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
        league="Liga MX",
        market="Ganador del partido",
        risk_label="Datos limitados",
        evidence_label="Respaldo de datos: medio",
        has_value_signal=False,
    )


def _jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1080, 1080), "navy").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_social_banner_compatibility_wrapper_accepts_only_social_content(
    monkeypatch, tmp_path
):
    calls = []

    def fake_render(content, **kwargs):
        calls.append((content, kwargs))
        return _jpeg()

    monkeypatch.setattr(social_banner, "render_social_jpeg", fake_render)
    output = tmp_path / "social.jpg"
    result = social_banner.generar_banner_redes(
        _content(),
        output_path=output,
        generated_at=datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc),
    )

    assert result == output
    assert output.read_bytes() == _jpeg()
    assert len(calls) == 1
    assert isinstance(calls[0][0], SocialContent)


def test_social_banner_has_no_remote_or_random_background_path():
    source = Path(social_banner.__file__).read_text(encoding="utf-8")

    assert "pollinations" not in source.casefold()
    assert "urllib.request" not in source
    assert "random" not in source
    assert "picks.json" not in source
