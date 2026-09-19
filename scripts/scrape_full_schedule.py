import sys
from pathlib import Path
import time
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

MEXICO_TZ = ZoneInfo("America/Mexico_City")
BASE_DIR = Path(__file__).resolve().parent.parent
SPORTS_DIR = BASE_DIR / "data" / "sports"
SPORTS_DIR.mkdir(parents=True, exist_ok=True)

SPORTS_TO_SCRAPE = [
    {"name": "Fútbol", "slug": "futbol"},
    {"name": "Béisbol", "slug": "beisbol"},
    {"name": "Baloncesto", "slug": "baloncesto"},
    {"name": "Tenis de mesa", "slug": "tenis_mesa"},
    {"name": "Tenis", "slug": "tenis"},
]

def clean_box(lines, odds, sport_name):
    if not lines or len(lines) < 2:
        return None
    full_text = " // ".join(lines)
    
    # Horario
    time_str = "EN VIVO"
    date_str = datetime.now(MEXICO_TZ).strftime("%d/%m")
    m = re.search(r'(\d{1,2}/\d{1,2})\s*•\s*(\d{1,2}:\d{2})', full_text)
    if m:
        date_str = m.group(1)
        time_str = m.group(2)
    else:
        m2 = re.search(r'\b(\d{1,2}:\d{2})\b', full_text)
        if m2:
            time_str = m2.group(1)

    # Nombres de equipos
    discard = {"sgp", "en vivo", "cuarto", "inning", "hándicap", "ganador", "totales", "tiempo regular", "•", "vs"}
    candidates = []
    league = sport_name
    for line in lines:
        s = line.strip()
        if not s or s.lower() in discard or re.match(r'^\d{1,2}/\d{1,2}$', s) or re.match(r'^\d{1,2}:\d{2}$', s):
            continue
        if re.match(r'^[+-]?\d+(\.\d+)?$', s):
            continue
        if "•" in s:
            league = s.replace("•", "").strip()
            continue
        if len(s) >= 3 and len(candidates) < 2:
            candidates.append(s)

    if len(candidates) < 2:
        vs_m = re.search(r'(.+?)\s+vs\s+(.+)', full_text, re.IGNORECASE)
        if vs_m:
            candidates = [vs_m.group(1).strip(), vs_m.group(2).strip()]

    home = candidates[0] if len(candidates) >= 1 else "Participante 1"
    away = candidates[1] if len(candidates) >= 2 else "Participante 2"
    
    return {
        "match": f"{home} vs {away}",
        "home_team": home,
        "away_team": away,
        "sport": sport_name,
        "league": league,
        "date": date_str,
        "time": time_str,
        "odds": odds,
        "raw_text": full_text
    }

print("Iniciando scraper integral de Playdoit...")
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
    page.goto("https://www.playdoit.mx/es/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(7)
    
    all_events = []
    
    for s_info in SPORTS_TO_SCRAPE:
        s_name = s_info["name"]
        s_slug = s_info["slug"]
        print(f"\nNavegando a: {s_name}...")
        
        clicked = page.evaluate("""(target) => {
            var host = document.querySelector('div#altenar > div');
            if (!host || !host.shadowRoot) {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    if (all[i].shadowRoot) { host = all[i]; break; }
                }
            }
            if (!host || !host.shadowRoot) return null;
            var shadow = host.shadowRoot;
            var tabs = Array.from(shadow.querySelectorAll('div[class*="SportItem"], button[class*="Tab"], div[class*="NavigationItem"]'));
            for (var t of tabs) {
                var txt = (t.innerText || '').trim();
                if (txt.toLowerCase() === target.toLowerCase() || txt.includes(target)) {
                    t.click();
                    return txt;
                }
            }
            return null;
        }""", s_name)
        
        print(f"   Tab click resultado: {clicked}")
        time.sleep(4)
        
        raw_boxes = page.evaluate("""() => {
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
                return { lines: lines, odds: btns };
            });
        }""")
        
        cleaned_list = []
        for box in raw_boxes:
            cleaned = clean_box(box["lines"], box["odds"], s_name)
            if cleaned and cleaned.get("odds"):
                cleaned_list.append(cleaned)
                
        print(f"   Eventos extraídos para {s_name}: {len(cleaned_list)}")
        with open(SPORTS_DIR / f"{s_slug}.json", "w", encoding="utf-8") as f:
            json.dump(cleaned_list, f, ensure_ascii=False, indent=2)
        all_events.extend(cleaned_list)
        
    browser.close()
    
with open(BASE_DIR / "data" / "cartelera_multisport.json", "w", encoding="utf-8") as f:
    json.dump(all_events, f, ensure_ascii=False, indent=2)

print(f"\nTOTAL CONSOLIDADO: {len(all_events)} eventos guardados.")
