import time
from playwright.sync_api import sync_playwright

def capture():
    print("Conectando a Playdoit en vivo...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        try:
            page.goto("https://www.playdoit.mx/es/", wait_until="domcontentloaded", timeout=40000)
            time.sleep(10)
            page.screenshot(path="/root/sports-props-collector/playdoit_live_now.png")
            print("Title:", page.title())
            print("URL:", page.url)
            
            # Buscar el shadow root de Altenar
            altenar_info = page.evaluate("""() => {
                var host = document.querySelector('div#altenar > div');
                if (!host || !host.shadowRoot) {
                    var all = document.querySelectorAll('*');
                    for (var i = 0; i < all.length; i++) {
                        if (all[i].shadowRoot) { host = all[i]; break; }
                    }
                }
                if (!host || !host.shadowRoot) return { error: "No shadow root" };
                var shadow = host.shadowRoot;
                var text = shadow.innerText || "";
                var lines = text.split(/\\r?\\n/).map(l => l.trim()).filter(Boolean);
                return {
                    total_lines: lines.length,
                    sample_lines: lines.slice(0, 50)
                };
            }""")
            print("ALTENAR INFO:", altenar_info)
        except Exception as e:
            print("Error capturando:", e)
        finally:
            browser.close()

if __name__ == "__main__":
    capture()
