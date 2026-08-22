from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse

import pytest
from PIL import Image

from backend import render_html_banner, social_banner
from backend.render_html_banner import build_social_html, render_social_jpeg
from backend.social_content import SocialContent


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)


def _content(*, is_demo: bool = False, has_value: bool = False) -> SocialContent:
    return SocialContent(
        pick_id="1780000000000000",
        category="Liga MX",
        event="América < Tigres & Atlas",
        selection='América "gana" > empate',
        odds_text="1.80",
        schedule="21 AGO · 20:00 CDMX",
        observed_at=datetime(2026, 8, 21, 17, 30, tzinfo=timezone.utc),
        starts_at=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
        league="Liga MX",
        market="Ganador del partido",
        risk_label="Datos limitados",
        evidence_label="Respaldo de datos: medio",
        has_value_signal=has_value,
        is_demo=is_demo,
    )


def _png_bytes(size: tuple[int, int] = (1080, 1080)) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", size, (12, 18, 32, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeDriver:
    def __init__(self, screenshot: bytes | None = None, *, fail: bool = False):
        self.screenshot = screenshot or _png_bytes()
        self.fail = fail
        self.quit_called = False
        self.cdp_calls: list[tuple[str, dict[str, object]]] = []
        self.loaded_html_path: Path | None = None
        self.ready_state_checks = 0

    def execute_cdp_cmd(self, command: str, params: dict[str, object]):
        self.cdp_calls.append((command, params))

    def get(self, uri: str):
        parsed = urlparse(uri)
        self.loaded_html_path = Path(unquote(parsed.path.lstrip("/")))
        if self.fail:
            raise RuntimeError("driver failed with private provider body")

    def execute_script(self, script: str):
        assert script == "return document.readyState"
        self.ready_state_checks += 1
        return "complete"

    def get_screenshot_as_png(self) -> bytes:
        return self.screenshot

    def quit(self):
        self.quit_called = True


def test_build_social_html_is_self_contained_escaped_and_one_card():
    html = build_social_html(_content(), generated_at=NOW)

    assert html.count('class="pick-card"') == 1
    assert "América &lt; Tigres &amp; Atlas" in html
    assert "América &quot;gana&quot; &gt; empate" in html
    assert "Momio observado" in html
    assert "1.80" in html
    assert "Observado:" in html
    assert "reytacopicks.com" in html
    assert "18+" in html
    assert "Apuesta con responsabilidad" in html
    assert "Desbloquea" not in html
    assert "data:image/jpeg;base64," in html
    assert "http://" not in html
    assert "https://" not in html
    assert "fonts.googleapis" not in html
    assert "../frontend/public/logo.jpg" not in html


def test_build_social_html_marks_demo_before_any_value_signal():
    demo_html = build_social_html(
        _content(is_demo=True, has_value=True), generated_at=NOW
    )
    ordinary_html = build_social_html(_content(), generated_at=NOW)

    assert "DEMO NO VIGENTE" in demo_html
    assert "Señal de valor comparada" not in demo_html
    assert "DEMO NO VIGENTE" not in ordinary_html


def test_renderer_requires_an_explicit_social_content():
    with pytest.raises(TypeError, match="SocialContent"):
        render_social_jpeg([], generated_at=NOW)  # type: ignore[arg-type]


def test_render_social_jpeg_returns_exact_rgb_square_and_configures_chrome():
    driver = _FakeDriver()
    received_options = []

    def factory(options):
        received_options.append(options)
        return driver

    jpeg = render_social_jpeg(
        _content(), generated_at=NOW, driver_factory=factory
    )

    with Image.open(BytesIO(jpeg)) as image:
        assert image.size == (1080, 1080)
        assert image.mode == "RGB"
        assert image.format == "JPEG"
    assert driver.quit_called is True
    assert driver.ready_state_checks >= 1
    assert driver.cdp_calls == [
        (
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1080,
                "height": 1080,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
    ]
    arguments = received_options[0].arguments
    assert "--headless=new" in arguments
    assert "--hide-scrollbars" in arguments
    assert "--force-device-scale-factor=1" in arguments


def test_renderer_cleans_temporary_files_after_success(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    driver = _FakeDriver()

    render_social_jpeg(
        _content(), generated_at=NOW, driver_factory=lambda _options: driver
    )

    assert driver.loaded_html_path is not None
    assert not driver.loaded_html_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_renderer_quits_and_cleans_temporary_files_after_failure(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    driver = _FakeDriver(fail=True)

    with pytest.raises(RuntimeError, match="driver failed"):
        render_social_jpeg(
            _content(), generated_at=NOW, driver_factory=lambda _options: driver
        )

    assert driver.quit_called is True
    assert driver.loaded_html_path is not None
    assert not driver.loaded_html_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_renderer_rejects_wrong_screenshot_dimensions():
    driver = _FakeDriver(_png_bytes((1080, 1079)))

    with pytest.raises(ValueError, match="1080x1080"):
        render_social_jpeg(
            _content(), generated_at=NOW, driver_factory=lambda _options: driver
        )

    assert driver.quit_called is True


def test_banner_dates_use_dynamic_spanish_months():
    september = datetime(2026, 9, 3, 12, 0)

    assert render_html_banner.banner_date_label(september) == (
        "03 DE SEPTIEMBRE, 2026 • CDMX"
    )
    assert social_banner.banner_date_label(september) == (
        "03 DE SEPTIEMBRE, 2026 • CDMX"
    )


def test_production_banner_sources_do_not_load_json_or_write_tracked_temp_file():
    sources = "\n".join(
        (ROOT / "backend" / name).read_text(encoding="utf-8")
        for name in ("render_html_banner.py", "social_banner.py")
    )

    assert "picks.json" not in sources
    assert "temp_banner.html" not in sources
    assert "undetected_chromedriver" not in sources
    assert "time.sleep" not in sources


def test_social_and_html_banner_modules_resolve_from_repository_root():
    probe = (
        "import runpy; "
        "runpy.run_module('backend.render_html_banner', run_name='render_probe'); "
        "runpy.run_module('backend.social_poster', run_name='social_probe')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
