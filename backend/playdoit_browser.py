from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class BrowserMode(str, Enum):
    LOCAL = "local"
    INTERACTIVE = "interactive"
    HEADLESS = "headless"


class InteractiveBrowserUnavailable(RuntimeError):
    pass


def resolve_browser_mode(env: Mapping[str, str] | None = None) -> BrowserMode:
    source = dict(env or {})
    explicit = str(source.get("REY_TACO_BROWSER_MODE") or "").strip().lower()
    if explicit:
        try:
            return BrowserMode(explicit)
        except ValueError as error:
            raise InteractiveBrowserUnavailable("invalid browser mode") from error
    if source.get("CI") or source.get("GITHUB_ACTIONS"):
        return BrowserMode.HEADLESS
    return BrowserMode.LOCAL


def configure_chrome_options(options, mode: BrowserMode):
    for argument in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--disable-gpu",
    ):
        options.add_argument(argument)
    if mode is BrowserMode.HEADLESS:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-minimized")
    return options


def gate_interactive_driver(driver, mode: BrowserMode) -> None:
    if mode is not BrowserMode.INTERACTIVE:
        return
    driver.minimize_window()
    if driver.execute_script("return document.hidden === true") is not True:
        driver.quit()
        raise InteractiveBrowserUnavailable("interactive minimization failed")
