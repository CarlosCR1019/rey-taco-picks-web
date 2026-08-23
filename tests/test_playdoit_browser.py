import pytest

import backend.scraper as scraper
from backend.playdoit_browser import (
    BrowserMode,
    InteractiveBrowserUnavailable,
    configure_chrome_options,
    gate_interactive_driver,
    resolve_browser_mode,
)


class FakeOptions:
    def __init__(self):
        self.arguments = []

    def add_argument(self, value):
        self.arguments.append(value)


class FakeDriver:
    def __init__(self, hidden=True):
        self.hidden = hidden
        self.calls = []

    def minimize_window(self):
        self.calls.append("minimize")

    def execute_script(self, script):
        self.calls.append(script)
        return self.hidden

    def get(self, url):
        self.calls.append(("get", url))

    def quit(self):
        self.calls.append("quit")


def test_interactive_override_wins_over_github_ci():
    mode = resolve_browser_mode(
        {"REY_TACO_BROWSER_MODE": "interactive", "GITHUB_ACTIONS": "true"}
    )
    assert mode is BrowserMode.INTERACTIVE


def test_interactive_options_start_minimized_without_headless():
    options = configure_chrome_options(FakeOptions(), BrowserMode.INTERACTIVE)
    assert "--start-minimized" in options.arguments
    assert "--headless=new" not in options.arguments


def test_interactive_gate_minimizes_and_requires_hidden_document():
    driver = FakeDriver(hidden=True)
    gate_interactive_driver(driver, BrowserMode.INTERACTIVE)
    assert driver.calls[:2] == ["minimize", "return document.hidden === true"]


def test_interactive_gate_closes_failed_window():
    driver = FakeDriver(hidden=False)
    with pytest.raises(InteractiveBrowserUnavailable):
        gate_interactive_driver(driver, BrowserMode.INTERACTIVE)
    assert driver.calls[-1] == "quit"


def test_scraper_factory_gates_interactive_driver_before_navigation(monkeypatch):
    driver = FakeDriver(hidden=True)
    captured_options = []

    def fake_chrome(*, options, **_kwargs):
        captured_options.append(options)
        return driver

    monkeypatch.setenv("REY_TACO_BROWSER_MODE", "interactive")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(scraper, "get_chrome_version", lambda: None)
    monkeypatch.setattr(scraper.uc, "ChromeOptions", FakeOptions)
    monkeypatch.setattr(scraper.uc, "Chrome", fake_chrome)

    returned = scraper.get_chrome_driver()
    returned.get("https://www.playdoit.mx/es/")

    assert returned is driver
    assert driver.calls[:2] == ["minimize", "return document.hidden === true"]
    assert driver.calls[2] == ("get", "https://www.playdoit.mx/es/")
    assert "--headless=new" not in captured_options[0].arguments
