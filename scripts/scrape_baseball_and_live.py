import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    
    # 1. Click on Béisbol
    bb_click = page.evaluate("""() => {
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
        for (var t of tabs) {
            var txt = (t.innerText || '').trim();
            if (txt.includes('Béisbol') || txt.includes('Beisbol')) {
                t.click();
                return { clicked: txt };
            }
        }
        return { not_found: true };
    }""")
    print("Baseball tab clicked:", bb_click)
    time.sleep(5)
    
    # 2. Extract all baseball events
    bb_boxes = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        if (!host || !host.shadowRoot) {
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                if (all[i].shadowRoot) { host = all[i]; break; }
            }
        }
        var shadow = host.shadowRoot;
        var boxes = Array.from(shadow.querySelectorAll('div[class*="EventBox"], div[class*="EventRow"], div[class*="BannerEventBox"]'));
        return boxes.map(b => {
            var lines = Array.from(b.innerText.split('\\n')).map(s => s.trim()).filter(Boolean);
            var btns = Array.from(b.querySelectorAll('button[class*="Odd"]')).map(btn => btn.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
            return { lines: lines, odds: btns, text: lines.join(' // ') };
        });
    }""")
    
    print(f"Extracted {len(bb_boxes)} baseball events")
    with open("data/baseball_playdoit.json", "w", encoding="utf-8") as f:
        json.dump(bb_boxes, f, ensure_ascii=False, indent=2)
        
    # 3. Also click Tenis de mesa (Ping Pong)
    tt_click = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        var shadow = host.shadowRoot;
        var tabs = Array.from(shadow.querySelectorAll('div[class*="SportItem"], button[class*="Tab"], div[class*="NavigationItem"]'));
        for (var t of tabs) {
            var txt = (t.innerText || '').trim();
            if (txt.includes('Tenis de mesa') || txt.includes('Table Tennis')) {
                t.click();
                return { clicked: txt };
            }
        }
        return { not_found: true };
    }""")
    print("Table tennis tab clicked:", tt_click)
    time.sleep(5)
    
    tt_boxes = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        var shadow = host.shadowRoot;
        var boxes = Array.from(shadow.querySelectorAll('div[class*="EventBox"], div[class*="EventRow"], div[class*="BannerEventBox"]'));
        return boxes.map(b => {
            var lines = Array.from(b.innerText.split('\\n')).map(s => s.trim()).filter(Boolean);
            var btns = Array.from(b.querySelectorAll('button[class*="Odd"]')).map(btn => btn.innerText.replace(/\\n/g, ' ').trim()).filter(Boolean);
            return { lines: lines, odds: btns, text: lines.join(' // ') };
        });
    }""")
    print(f"Extracted {len(tt_boxes)} table tennis events")
    with open("data/table_tennis_playdoit.json", "w", encoding="utf-8") as f:
        json.dump(tt_boxes, f, ensure_ascii=False, indent=2)

    browser.close()
