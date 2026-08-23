import undetected_chromedriver as uc
import time

print("Iniciando Chrome...")
options = uc.ChromeOptions()
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument("--start-maximized")
driver = uc.Chrome(options=options, version_main=151)

print("Navegando a playdoit...")
driver.get("https://www.playdoit.mx/es/")
time.sleep(10) # wait for react to load

print("Guardando HTML...")
html = driver.page_source
with open("playdoit_source.html", "w", encoding="utf-8") as f:
    f.write(html)
    
driver.quit()
print("Terminado.")
