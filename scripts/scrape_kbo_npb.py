import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto("https://www.playdoit.mx/es/", wait_until="domcontentloaded", timeout=25000)
    
    # Wait for shadow host
    shadow_found = False
    for _ in range(25):
        has_shadow = page.evaluate("""() => {
            var host = document.querySelector('div#altenar > div');
            if (host && host.shadowRoot) return true;
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                if (all[i].shadowRoot) return true;
            }
            return false;
        }""")
        if has_shadow:
            shadow_found = True
            break
        time.sleep(1)
        
    print("Shadow host found:", shadow_found)
    time.sleep(3)
    
    # 1. Click Béisbol
    clicked_sport = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        if (!host || !host.shadowRoot) {
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                if (all[i].shadowRoot) { host = all[i]; break; }
            }
        }
        if (!host || !host.shadowRoot) return { error: 'no shadow' };
        var shadow = host.shadowRoot;
        var tabs = Array.from(shadow.querySelectorAll('div[class*="SportItem"], button[class*="Tab"], div[class*="NavigationItem"], span'));
        for (var t of tabs) {
            var txt = (t.innerText || '').trim();
            if (txt === 'Béisbol' || txt === 'Beisbol') {
                t.click();
                return { clicked: txt };
            }
        }
        return { not_found: true, available: tabs.map(x => x.innerText.trim()).filter(Boolean).slice(0, 20) };
    }""")
    print("Clicked Sport:", clicked_sport)
    time.sleep(5)
    
    # Extract
    boxes = page.evaluate("""() => {
        var host = document.querySelector('div#altenar > div');
        if (!host || !host.shadowRoot) {
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                if (all[i].shadowRoot) { host = all[i]; break; }
            }
        }
        var shadow = host.shadowRoot;
        var el = Array.from(shadow.querySelectorAll('div[class*="EventBox"], div[class*="EventRow"], div[class*="BannerEventBox"]'));
        return el.map(b => {
            return {
                text: b.innerText.replace(/\\n/g, ' // '),
                odds: Array.from(b.querySelectorAll('button[class*="Odd"]')).map(x => x.innerText.replace(/\\n/g, ' ').trim())
            };
        });
    }""")
    
    print(f"Total boxes after sport selection: {len(boxes)}")
    with open("data/baseball_live_scraped.json", "w", encoding="utf-8") as f:
        json.dump(boxes, f, ensure_ascii=False, indent=2)
        
    for ev in boxes[:20]:
        print("--------------------------------------------------")
        print("TEXT:", ev["text"][:120])
        print("ODDS:", " | ".join(ev["odds"][:4]))
        
    browser.close()
