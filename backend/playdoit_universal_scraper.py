"""
backend/playdoit_universal_scraper.py
======================================
Extractor exhaustivo y particionado de todos los deportes en Playdoit (Altenar Sportsbook).
Extrae:
- Fútbol
- Béisbol (KBO, NPB, MLB, CPBL)
- Tenis de mesa (Setka Cup, TT Elite, Wincup)
- Dardos (Modus Super Series, PDC, Online Live Darts)
- Baloncesto (NBA, Euroliga, Ligas Asiáticas)
- Tenis, Voleibol, Hockey y Otros.

Guarda particionado en disco en `data/sports/<deporte>.json` para evitar sobrecarga de memoria
en el Quant Engine y agentes de IA, y un consolidado en `data/cartelera_multisport.json`.
"""

import os
import sys
import time
import json
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

MEXICO_TZ = ZoneInfo("America/Mexico_City")
SPORTS_DATA_DIR = REPO_ROOT / "data" / "sports"
SPORTS_DATA_DIR.mkdir(parents=True, exist_ok=True)

TARGET_SPORTS = [
    {"name": "Fútbol", "slug": "futbol", "keywords": ["fútbol", "futbol", "soccer"]},
    {"name": "Béisbol", "slug": "beisbol", "keywords": ["béisbol", "beisbol", "baseball", "kbo", "npb", "mlb"]},
    {"name": "Tenis de mesa", "slug": "tenis_mesa", "keywords": ["tenis de mesa", "table tennis", "ping pong", "setka"]},
    {"name": "Dardos", "slug": "dardos", "keywords": ["dardos", "darts", "modus"]},
    {"name": "Baloncesto", "slug": "baloncesto", "keywords": ["baloncesto", "basketball", "nba"]},
    {"name": "Tenis", "slug": "tenis", "keywords": ["tenis", "tennis", "atp", "wta", "itf"]},
    {"name": "Otros", "slug": "otros", "keywords": []}
]


def clean_event_box(raw_lines: List[str], odds: List[str], default_sport: str) -> Optional[Dict[str, Any]]:
    """Procesa y limpia las líneas de un contenedor de evento de Altenar."""
    if not raw_lines or len(raw_lines) < 2:
        return None

    full_text = " // ".join(raw_lines)

    # Identificar fecha y hora (ej. '18/09 • 03:30', '18/09 • 00:30', 'Hoy • 15:00', 'EN VIVO')
    time_str = "EN VIVO"
    date_str = datetime.now(MEXICO_TZ).strftime("%d/%m")

    time_match = re.search(r'(\d{1,2}/\d{1,2})\s*•\s*(\d{1,2}:\d{2})', full_text)
    if time_match:
        date_str = time_match.group(1)
        time_str = time_match.group(2)
    else:
        hour_match = re.search(r'\b(\d{1,2}:\d{2})\b', full_text)
        if hour_match:
            time_str = hour_match.group(1)

    # Extraer nombres de equipos/participantes
    # Descartar etiquetas de interfaz
    discard_tokens = {
        "sgp", "en vivo", "cuarto", "inning", "hándicap", "ganador", "totales",
        "tiempo regular", "resultado final", "1º set", "2º set", "3º set", "4º set", "5º set",
        "•", "vs"
    }

    candidates = []
    league_name = default_sport

    for line in raw_lines:
        s = line.strip()
        if not s or s.lower() in discard_tokens:
            continue
        if re.match(r'^\d{1,2}/\d{1,2}$', s) or re.match(r'^\d{1,2}:\d{2}$', s):
            continue
        if re.match(r'^[+-]?\d+(\.\d+)?$', s):
            continue
        if "•" in s:
            league_name = s.replace("•", "").strip()
            continue
        if len(s) >= 3 and len(candidates) < 2:
            candidates.append(s)

    if len(candidates) < 2:
        # Si solo detectó un nombre, tratar de dividir por 'vs'
        vs_match = re.search(r'(.+?)\s+vs\s+(.+)', full_text, re.IGNORECASE)
        if vs_match:
            candidates = [vs_match.group(1).strip(), vs_match.group(2).strip()]

    home_team = candidates[0] if len(candidates) >= 1 else "Participante 1"
    away_team = candidates[1] if len(candidates) >= 2 else "Participante 2"
    match_title = f"{home_team} vs {away_team}"

    return {
        "match": match_title,
        "home_team": home_team,
        "away_team": away_team,
        "sport": default_sport,
        "league": league_name,
        "date": date_str,
        "time": time_str,
        "raw_text": full_text,
        "odds": odds,
        "extracted_at": datetime.now(MEXICO_TZ).isoformat()
    }


def run_universal_scrape(headless: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """
    Ejecuta la extracción profunda de todos los deportes soportados por Altenar.
    Retorna un diccionario agrupado por slug del deporte.
    """
    print("=" * 80)
    print("🌮 REY TACO PICKS — SCRAPER UNIVERSAL MULTIDEPORTE (PLAYDOIT)")
    print("=" * 80)
    t0 = time.time()

    from playwright.sync_api import sync_playwright

    scraped_by_sport: Dict[str, List[Dict[str, Any]]] = {
        s["slug"]: [] for s in TARGET_SPORTS
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        # Evasión de detección de automatización
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
        """)

        print("📡 [1/3] Conectando a Playdoit México con evasión de Cloudflare...")
        page.goto("https://www.playdoit.mx/es/", wait_until="domcontentloaded", timeout=25000)

        # Esperar hidratación del Shadow Root de Altenar
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
                break
            time.sleep(1)

        time.sleep(3)
        print("⚡ [2/3] Sportsbook de Altenar montado. Navegando pestañas de deportes...")

        # Función auxiliar para extraer eventos actualmente visibles en pantalla
        def extract_current_boxes() -> List[Dict[str, Any]]:
            return page.evaluate("""() => {
                var host = document.querySelector('div#altenar > div');
                if (!host || !host.shadowRoot) {
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {
                        if (all[i].shadowRoot) { host = all[i]; break; }
                    }
                }
                if (!host || !host.shadowRoot) return [];
                var shadow = host.shadowRoot;
                var boxes = Array.from(shadow.querySelectorAll(
                    'div[class*="EventBox"], div[class*="EventRow"], div[class*="BannerEventBox"]'
                ));
                return boxes.map(b => {
                    var lines = Array.from(b.innerText.split('\\n')).map(s => s.trim()).filter(Boolean);
                    var btns = Array.from(b.querySelectorAll('button[class*="Odd"]')).map(
                        btn => btn.innerText.replace(/\\n/g, ' ').trim()
                    ).filter(Boolean);
                    return { lines: lines, odds: btns };
                });
            }""")

        # Recorrer cada deporte objetivo
        for sport_cfg in TARGET_SPORTS:
            s_name = sport_cfg["name"]
            s_slug = sport_cfg["slug"]
            print(f"   🔍 Explorando deporte: {s_name}...")

            # Intentar hacer clic en la pestaña o botón de ese deporte
            click_res = page.evaluate("""(targetNames) => {
                var host = document.querySelector('div#altenar > div');
                if (!host || !host.shadowRoot) {
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {
                        if (all[i].shadowRoot) { host = all[i]; break; }
                    }
                }
                if (!host || !host.shadowRoot) return { success: false, reason: "no_shadow" };
                var shadow = host.shadowRoot;

                // Buscar entre pestañas, botones e items de navegación
                var elements = Array.from(shadow.querySelectorAll(
                    'div[class*="SportItem"], button[class*="Tab"], div[class*="NavigationItem"], span'
                ));

                for (var el of elements) {
                    var txt = (el.innerText || '').trim().toLowerCase();
                    for (var t of targetNames) {
                        if (txt === t.toLowerCase() || txt.includes(t.toLowerCase())) {
                            el.click();
                            return { success: true, clicked: el.innerText.trim() };
                        }
                    }
                }
                return { success: false, reason: "not_found" };
            }""", [s_name] + sport_cfg["keywords"])

            # Dar tiempo a que Altenar cargue los datos del deporte
            time.sleep(3.5)

            raw_boxes = extract_current_boxes()
            seen_matches = set()
            count = 0

            for b in raw_boxes:
                cleaned = clean_event_box(b.get("lines", []), b.get("odds", []), s_name)
                if cleaned and cleaned["match"] not in seen_matches:
                    seen_matches.add(cleaned["match"])
                    scraped_by_sport[s_slug].append(cleaned)
                    count += 1

            print(f"      -> {count} eventos detectados para {s_name}")

        browser.close()

    total_events = sum(len(v) for v in scraped_by_sport.values())
    print(f"\n💾 [3/3] Particionando {total_events} eventos en disco...")

    # Guardar particionado por deporte
    all_consolidated = []
    for sport_cfg in TARGET_SPORTS:
        slug = sport_cfg["slug"]
        items = scraped_by_sport[slug]
        sport_file = SPORTS_DATA_DIR / f"{slug}.json"
        with open(sport_file, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        all_consolidated.extend(items)

    # Guardar consolidado global
    consolidated_file = REPO_ROOT / "data" / "cartelera_multisport.json"
    with open(consolidated_file, "w", encoding="utf-8") as f:
        json.dump(all_consolidated, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print("=" * 80)
    print(f"🎉 EXTRACCIÓN UNIVERSAL COMPLETADA EN {elapsed:.2f} SEGUNDOS")
    print(f"📁 Particionados guardados en: {SPORTS_DATA_DIR}")
    print(f"📊 Consolidado general: {consolidated_file} ({len(all_consolidated)} eventos)")
    print("=" * 80)

    return scraped_by_sport


if __name__ == "__main__":
    run_universal_scrape()
