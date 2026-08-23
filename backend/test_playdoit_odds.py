import sys
import time
import json
import undetected_chromedriver as uc

sys.stdout.reconfigure(encoding='utf-8')

def inspect_shadow_playdoit():
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')

    driver = uc.Chrome(options=options, version_main=151)
    try:
        print("Cargando Playdoit...")
        driver.get("https://www.playdoit.mx/es/")
        time.sleep(8)
        
        # Inspeccionar todos los elementos con shadowRoot o iframes
        js_inspect = """
        var elements = Array.from(document.querySelectorAll('*'));
        var shadowHosts = elements.filter(el => el.shadowRoot).map(el => ({
            tag: el.tagName,
            id: el.id,
            className: el.className,
            shadowChildren: el.shadowRoot.children.length,
            shadowHTMLSample: el.shadowRoot.innerHTML.slice(0, 500)
        }));
        
        var iframes = Array.from(document.querySelectorAll('iframe')).map(i => ({
            id: i.id,
            src: i.src
        }));
        
        return {
            shadowHosts: shadowHosts,
            iframes: iframes
        };
        """
        data = driver.execute_script(js_inspect)
        print("Estructura encontrada:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    finally:
        driver.quit()

if __name__ == '__main__':
    inspect_shadow_playdoit()
