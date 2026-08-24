"""Deterministic, self-contained social artwork renderer."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from backend.social_content import SocialContent, demo_social_content
from backend.spanish_dates import cdmx_banner_date


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = Path(__file__).with_name("banner_template.html")
LOGO_PATH = ROOT / "frontend" / "public" / "logo.jpg"
_MEXICO_CITY = ZoneInfo("America/Mexico_City")
_DOM_METRICS_SCRIPT = """
return (() => {
  const root = document.getElementById('banner-root');
  const selectors = [
    '.header', '.pick-card', '.event', '.selection', '.odds',
    '.evidence', '.observation', '.footer', '.site', '.notice'
  ];
  const required = selectors.map((selector) => root.querySelector(selector));
  const rootRect = root.getBoundingClientRect();
  const allRequiredInside = required.every((element) => {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    return rect.left >= rootRect.left && rect.top >= rootRect.top &&
      rect.right <= rootRect.right && rect.bottom <= rootRect.bottom;
  });
  const hasTextOverflow = required.some((element) => element &&
    element.scrollWidth > element.clientWidth + 2
  );
  return {
    viewportWidth: Math.round(window.innerWidth),
    viewportHeight: Math.round(window.innerHeight),
    rootWidth: Math.round(rootRect.width),
    rootHeight: Math.round(rootRect.height),
    rootScrollWidth: root.scrollWidth,
    rootScrollHeight: root.scrollHeight,
    allRequiredInside,
    hasTextOverflow
  };
})();
"""


def banner_date_label(generated_at: datetime | None = None) -> str:
    return cdmx_banner_date(generated_at)


def _observation_label(observed_at: datetime) -> str:
    if not isinstance(observed_at, datetime):
        raise ValueError("observed_at must be timezone-aware")
    try:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError
        local = observed_at.astimezone(_MEXICO_CITY)
    except (OverflowError, ValueError):
        raise ValueError("observed_at must be timezone-aware") from None
    return f"Observado: {local:%d/%m/%Y %H:%M} CDMX"


def _logo_data_uri() -> str:
    return "data:image/jpeg;base64," + base64.b64encode(
        LOGO_PATH.read_bytes()
    ).decode("ascii")


def _background_style(background_bytes: bytes | None) -> str:
    if background_bytes is None:
        return ""
    if not isinstance(background_bytes, bytes) or not background_bytes:
        raise ValueError("background_bytes must be valid image bytes")
    try:
        with Image.open(BytesIO(background_bytes)) as source:
            source.load()
            if source.size != (1080, 1080):
                raise ValueError("background must be exactly 1080x1080")
            image = source.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=90)
    except (OSError, UnidentifiedImageError):
        raise ValueError("background_bytes must be valid image bytes") from None
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return (
        "background-image: linear-gradient(145deg, rgba(8,16,42,.76), "
        "rgba(4,6,16,.91)), url('data:image/jpeg;base64,"
        f"{encoded}')"
    )


def _fact_font_size(value: str, *, ordinary_size: int) -> int:
    length = len(value)
    if length > 240:
        return 16
    if length > 180:
        return 20
    if length > 120:
        return 24
    if length > 70:
        return 30
    return ordinary_size


def _card_html(content: SocialContent) -> str:
    if content.is_demo is True:
        value_signal = ""
    elif content.has_value_signal is True:
        value_signal = '<div class="value">Señal de valor comparada</div>'
    else:
        value_signal = ""
    event_size = _fact_font_size(content.event, ordinary_size=48)
    selection_size = _fact_font_size(content.selection, ordinary_size=39)
    dense = len(content.event) + len(content.selection) > 360
    card_padding = "24px 28px" if dense else "40px 42px"
    card_gap = "10px" if dense else "18px"
    return f"""
    <article class="pick-card" style="--event-size: {event_size}px; --selection-size: {selection_size}px; --card-padding: {card_padding}; --card-gap: {card_gap}">
      <div class="meta-row">
        <span class="tag">{escape(content.category)}</span>
        <span class="schedule">{escape(content.schedule)}</span>
      </div>
      <div class="event">{escape(content.event)}</div>
      <div class="selection">{escape(content.selection)}</div>
      <div class="facts-row">
        <div class="odds">
          <div class="odds-label">Momio observado</div>
          <div class="odds-value">{escape(content.odds_text)}</div>
        </div>
        <div class="evidence">
          <div>{escape(content.evidence_label)}</div>
          <div>{escape(content.risk_label)}</div>
          {value_signal}
        </div>
      </div>
      <div class="observation">{escape(_observation_label(content.observed_at))}</div>
    </article>
    """


def build_social_html(
    content: SocialContent,
    *,
    generated_at: datetime,
    background_bytes: bytes | None = None,
) -> str:
    """Build one escaped, self-contained banner document."""

    if not isinstance(content, SocialContent):
        raise TypeError("content must be SocialContent")
    if not isinstance(generated_at, datetime):
        raise TypeError("generated_at must be datetime")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{BACKGROUND_STYLE}}": _background_style(background_bytes),
        "{{LOGO_DATA_URI}}": _logo_data_uri(),
        "{{DATE_LABEL}}": escape(banner_date_label(generated_at)),
        "{{DEMO_LABEL}}": "DEMO NO VIGENTE" if content.is_demo is True else "",
        "{{CARD_HTML}}": _card_html(content),
    }
    invalid_markers = [
        marker for marker in replacements if template.count(marker) != 1
    ]
    if invalid_markers:
        raise ValueError("banner template markers must each appear exactly once")
    for marker, value in replacements.items():
        template = template.replace(marker, value, 1)
    return template


def _chrome_options() -> webdriver.ChromeOptions:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--force-device-scale-factor=1")
    options.add_argument("--window-size=1080,1080")
    return options


def _validate_dom_metrics(metrics: object) -> None:
    if not isinstance(metrics, dict):
        raise ValueError("DOM layout overflow")
    dimensions = (
        "viewportWidth",
        "viewportHeight",
        "rootWidth",
        "rootHeight",
        "rootScrollWidth",
        "rootScrollHeight",
    )
    if any(type(metrics.get(key)) is not int for key in dimensions):
        raise ValueError("DOM layout overflow")
    if any(metrics[key] != 1080 for key in dimensions[:4]):
        raise ValueError("DOM layout overflow")
    if metrics["rootScrollWidth"] > 1080 or metrics["rootScrollHeight"] > 1080:
        raise ValueError("DOM layout overflow")
    if metrics.get("allRequiredInside") is not True:
        raise ValueError("DOM layout overflow")
    if metrics.get("hasTextOverflow") is not False:
        raise ValueError("DOM layout overflow")


def render_social_jpeg(
    content: SocialContent,
    *,
    generated_at: datetime,
    background_bytes: bytes | None = None,
    driver_factory: Callable[[webdriver.ChromeOptions], WebDriver] | None = None,
) -> bytes:
    """Render one self-contained branded square and return JPEG bytes."""

    if not isinstance(content, SocialContent):
        raise TypeError("content must be SocialContent")
    html = build_social_html(
        content,
        generated_at=generated_at,
        background_bytes=background_bytes,
    )
    options = _chrome_options()
    make_driver = driver_factory or (lambda opts: webdriver.Chrome(options=opts))
    driver: WebDriver | None = None
    with TemporaryDirectory(prefix="rey-taco-social-") as temporary:
        directory = Path(temporary)
        html_path = directory / "social.html"
        png_path = directory / "social.png"
        html_path.write_text(html, encoding="utf-8")
        primary_error: BaseException | None = None
        try:
            driver = make_driver(options)
            driver.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": 1080,
                    "height": 1080,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
            )
            driver.get(html_path.resolve().as_uri())
            WebDriverWait(driver, 5).until(
                lambda active: active.execute_script(
                    "return document.readyState"
                )
                == "complete"
            )
            _validate_dom_metrics(driver.execute_script(_DOM_METRICS_SCRIPT))
            png_path.write_bytes(driver.get_screenshot_as_png())
            with Image.open(png_path) as screenshot:
                screenshot.load()
                if screenshot.size != (1080, 1080):
                    raise ValueError("screenshot must be exactly 1080x1080")
                rgb = screenshot.convert("RGB")
                output = BytesIO()
                rgb.save(output, format="JPEG", quality=92)
                return output.getvalue()
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except BaseException:
                    if primary_error is None:
                        raise


def renderizar_banner_estudio(
    content: SocialContent,
    output_path: str | Path,
    *,
    generated_at: datetime,
    background_bytes: bytes | None = None,
    driver_factory: Callable[[webdriver.ChromeOptions], WebDriver] | None = None,
) -> Path:
    """Compatibility wrapper that still requires one explicit public package."""

    destination = Path(output_path)
    destination.write_bytes(
        render_social_jpeg(
            content,
            generated_at=generated_at,
            background_bytes=background_bytes,
            driver_factory=driver_factory,
        )
    )
    return destination


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a safe social preview")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.demo is not True:
        parser.error("--demo is required; this command never loads a live pick")
    generated_at = datetime.now(timezone.utc)
    destination = renderizar_banner_estudio(
        demo_social_content(reference_at=generated_at),
        Path(args.output),
        generated_at=generated_at,
    )
    print(f"demo_social_banner status=rendered output={destination}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
