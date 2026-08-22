"""Compatibility facade for deterministic social banner rendering."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

from backend.render_html_banner import render_social_jpeg
from backend.social_content import SocialContent
from backend.spanish_dates import cdmx_banner_date


def banner_date_label(generated_at: datetime | None = None) -> str:
    return cdmx_banner_date(generated_at)


def generar_banner_redes(
    content: SocialContent,
    output_path: str | Path,
    *,
    generated_at: datetime,
    background_bytes: bytes | None = None,
    driver_factory: Callable[[webdriver.ChromeOptions], WebDriver] | None = None,
) -> Path:
    """Write the exact local 1080-square JPEG for one public package."""

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
