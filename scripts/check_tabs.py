import sys
from pathlib import Path
import time
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080}
    )
    page = context.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.navigator.chrome = { runtime: {} };
    """)
    page.goto("https://www.playdoit.mx/es/", wait_until="domcontentloaded", timeout=25000)
    time.sleep(6)
    
    # List all available sport tabs in shadowRoot
    tabs_info = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        if (!host || !host.shadowRoot) {
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                if (all[i].shadowRoot) { host = all[i]; break; }
            }
        }
        if (!host || !host.shadowRoot) return { error: 'no shadow' };
        var shadow = host.shadowRoot;
        var tabs = Array.from(shadow.querySelectorAll('div[class*="SportItem"], button[class*="Tab"], div[class*="NavigationItem"]'));
        return tabs.map(t => (t.innerText || '').trim()).filter(Boolean);
    }""")
    print("Available tabs:", tabs_info[:25])
    browser.close()
