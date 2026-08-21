import os
import sys
import json
import time
from html import escape
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')


def _data_support_text(value):
    text = str(value or "Datos no disponibles").strip()
    if "respaldo de datos" in text.casefold():
        return text
    return f"{text} respaldo de datos" if text.endswith("%") else text


def build_cards_html(picks):
    """Render data-support labels without inventing probability or value."""

    if not picks:
        return """
        <div class="pick-card">
          <div class="card-left">
            <div class="match-title">Sin picks verificados disponibles</div>
            <div class="pick-selection">Vuelve más tarde</div>
          </div>
        </div>
        """

    cards = []
    for index, pick in enumerate(picks):
        hot_class = "hot" if index == 0 else ""
        category = escape(str(pick.get("categoria", "DEPORTES")).upper())
        match = escape(str(pick.get("partido", "Partido")))
        selection = escape(str(pick.get("pick", "Selección")))
        price = escape(str(pick.get("cuota", "—")))
        schedule = escape(str(pick.get("horario", "Por confirmar")))
        support = escape(_data_support_text(pick.get("confianza")))
        evidence_label = escape(str(pick.get("riesgo", "Datos limitados")))
        value_signal = (
            '<span class="value-signal">Señal de valor comparada</span>'
            if pick.get("tiene_valor") is True
            else ""
        )
        cards.append(f"""
        <div class="pick-card {hot_class}">
          <div class="card-left">
            <div class="meta-tags">
              <span class="tag-sport">{category}</span>
              <span class="tag-time">{schedule}</span>
            </div>
            <div class="match-title">{match}</div>
            <div class="pick-selection">🎯 {selection}</div>
          </div>
          <div class="card-right">
            <div class="odds-box">
              <div class="odds-label">Momio</div>
              <div class="odds-val">{price}</div>
            </div>
            <span class="conf-badge">📊 {support}</span>
            <span class="evidence-label">{evidence_label}</span>
            {value_signal}
          </div>
        </div>
        """)
    return "".join(cards)

def renderizar_banner_estudio(picks=None, output_path="banner_hoy.png"):
    """
    Renderiza un banner gráfico HD (1080x1080) con calidad de estudio EA Sports / ESPN
    capturando el elemento #banner-root para un encuadre perfecto.
    """
    if not picks:
        json_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "picks.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                picks = json.load(f)
        else:
            picks = []

    free_picks = [p for p in picks if not p.get('es_parlay')][:3]
    cards_html = build_cards_html(free_picks)

    fecha_actual = datetime.now().strftime("%d DE AGOSTO, %Y • CDMX")
    
    template_path = os.path.join(os.path.dirname(__file__), "banner_template.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Inyectar las tarjetas
    html_content = html_content.replace('<!-- Inject dynamically -->', cards_html)
    html_content = html_content.replace('ANÁLISIS MATEMÁTICO &amp; INTELIGENCIA ARTIFICIAL', f'ANÁLISIS MATEMÁTICO • {fecha_actual}')

    temp_html_path = os.path.join(os.path.dirname(__file__), "temp_banner.html")
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print("📸 Renderizando banner HD con Headless Chrome...")
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1080,1080")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--force-device-scale-factor=1")

    driver = uc.Chrome(version_main=151, options=options)
    try:
        driver.get(f"file:///{os.path.abspath(temp_html_path).replace(chr(92), '/')}")
        time.sleep(1.8) # Esperar fuentes de Google
        
        banner_element = driver.find_element(By.ID, "banner-root")
        banner_element.screenshot(output_path)
        print(f"🎉 ¡Banner HD de Calidad Estudio Generado!: {output_path}")
    finally:
        driver.quit()

    return output_path

if __name__ == "__main__":
    renderizar_banner_estudio()
