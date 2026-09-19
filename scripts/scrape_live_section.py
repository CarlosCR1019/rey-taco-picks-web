import time
import json
from pathlib import Path
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
    page.goto("https://www.playdoit.mx/es/apuestas-en-vivo", wait_until="domcontentloaded", timeout=25000)
    time.sleep(6)
    
    data = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        if (!host || !host.shadowRoot) return {error: 'no shadow'};
        var shadow = host.shadowRoot;
        var boxes = Array.from(shadow.querySelectorAll('div[class*="EventBox"], div[class*="EventRow"], div[class*="LiveNow"], div[class*="Table"]'));
        var events = boxes.map(b => {
            var lines = Array.from(b.innerText.split('\\n')).map(s => s.trim()).filter(Boolean);
            var btns = Array.from(b.querySelectorAll('button[class*="Odd"]')).map(btn => btn.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
            return { lines: lines, odds: btns };
        });
        return { count: boxes.length, events: events };
    }""")
    
    print("Live section boxes:", data.get("count"))
    with open("data/playdoit_en_vivo.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    browser.close()
