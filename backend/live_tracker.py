import os
import time
import json
import undetected_chromedriver as uc
from groq import Groq
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

def get_chrome_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    
    driver = uc.Chrome(options=options, version_main=151)
    return driver

def get_pending_picks():
    # The tracker only needs event labels; selections remain private.
    response = supabase.table('picks').select('id,partido').eq('estado', 'pendiente').execute()
    return response.data

def extract_live_text(driver):
    print("Navegando a la sección En Vivo...")
    driver.get("https://www.playdoit.mx/es/live")
    time.sleep(10) # Esperar a que carguen los websockets de resultados en vivo
    
    try:
        # Extraer todo el texto visible de los contenedores de eventos dentro del Shadow DOM
        script = """
        var host = document.querySelector('div#altenar > div');
        if(!host || !host.shadowRoot) return "";
        var shadow = host.shadowRoot;
        
        var containers = shadow.querySelectorAll('div[class*="EventBoxContainer"]');
        var text = "";
        containers.forEach(c => {
            text += c.innerText + "\\n---\\n";
        });
        return text;
        """
        raw_text = driver.execute_script(script)
        return raw_text
    except Exception as e:
        print(f"Error extrayendo texto en vivo: {e}")
        return ""

def update_scores_with_ai(raw_text, pending_picks):
    if not pending_picks or not raw_text:
        return

    print("Analizando resultados en vivo con Groq...")
    
    prompt = f"""
    Eres un analizador de resultados deportivos en tiempo real.
    Aquí tienes el texto crudo extraído de una página de apuestas en vivo:
    ---
    {raw_text[:8000]} # Limitamos para no exceder tokens
    ---
    
    Y aquí están los picks que estamos rastreando:
    {json.dumps(pending_picks, indent=2)}
    
    Tu tarea es buscar en el texto crudo si alguno de estos eventos se está jugando ahora mismo y cuál es su marcador actual.
    Si encuentras el marcador, devuelve un JSON array con las actualizaciones.
    Si no encuentras nada sobre un partido, ignóralo.
    
    Formato EXACTO de respuesta JSON:
    [
      {{
        "id": <id_del_pick>,
        "marcador": "América 2 - 1 Chivas (Min 75')"
      }}
    ]

    No evalúes apuestas ni cambies estados. La calificación final pertenece al verificador auditado.
    """

    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Solo devuelves JSON puro, sin markdown."
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
        )
        
        response_text = chat_completion.choices[0].message.content.strip()
        
        inicio = response_text.find('[')
        fin = response_text.rfind(']') + 1
        
        if inicio != -1 and fin != 0:
            clean_json = response_text[inicio:fin]
            updates = json.loads(clean_json)
        else:
            updates = json.loads(response_text)
        
        allowed_ids = {str(pick.get('id')) for pick in pending_picks}
        # Store display-only scores for the pending rows supplied to the model.
        for update in updates:
            update_id = str(update.get('id', ''))
            score = str(update.get('marcador', '')).strip()[:160]
            if update_id not in allowed_ids or not score:
                continue
            supabase.table('picks').update({'marcador': score}).eq(
                'id', update_id
            ).eq('estado', 'pendiente').execute()
            print(f"Marcador en vivo actualizado para Pick ID {update_id}: {score}")
            
    except Exception as e:
        print(f"Error en el análisis de Groq para Live Tracker: {e}")

def main():
    print("Iniciando Live Tracker...")
    picks = get_pending_picks()
    if not picks:
        print("No hay picks pendientes por rastrear.")
        return
        
    driver = None
    try:
        driver = get_chrome_driver()
        raw_text = extract_live_text(driver)
        update_scores_with_ai(raw_text, picks)
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    main()
