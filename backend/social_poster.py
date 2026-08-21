import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
IG_USER_ID = os.getenv("IG_USER_ID", "").strip()

def publicar_en_facebook_page(image_path="banner_hoy.png", mensaje=None):
    """
    Publica automáticamente el banner de picks en la Página oficial de Facebook de Rey Taco Picks.
    """
    if not FB_PAGE_ACCESS_TOKEN or not FB_PAGE_ID:
        print("   ℹ️ Meta Access Token no configurado aún en .env. (Listo para conectar con 1 clic).")
        return False

    if not mensaje:
        mensaje = (
            "🌮👑 ¡PRONÓSTICOS DEPORTIVOS DE HOY CON IA! 👑🌮\n\n"
            "Aquí tienes los 3 picks destacados del día con valor matemático (+EV) y ventaja estadística.\n\n"
            "📊 Consulta los análisis completos, el Parlay del Día y las cuotas en vivo en nuestra plataforma:\n"
            "👉 https://reytacopicks.com\n\n"
            "#ReyTacoPicks #LigaMX #ChampionsLeague #MLB #ApuestasDeportivas #PronosticosGratis #ParlayIA"
        )

    try:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
        with open(image_path, "rb") as img_file:
            payload = {
                "message": mensaje,
                "access_token": FB_PAGE_ACCESS_TOKEN
            }
            files = {"source": img_file}
            r = requests.post(url, data=payload, files=files, timeout=30)
            res = r.json()
            if "id" in res:
                print(f"   ✅ ¡Publicado exitosamente en Facebook Page! Post ID: {res['id']}")
                return True
            else:
                print(f"   ⚠️ Error en API de Facebook: {res}")
                return False
    except Exception as e:
        print(f"   ❌ Error publicando en Facebook: {e}")
        return False

def publicar_en_instagram(image_url, caption=None):
    """
    Publica automáticamente el banner en el feed de Instagram Business vía Meta Graph API.
    """
    if not FB_PAGE_ACCESS_TOKEN or not IG_USER_ID:
        print("   ℹ️ Instagram Business ID / Token pendiente en .env.")
        return False

    if not caption:
        caption = (
            "🌮👑 PICKS DEL DÍA CON INTELIGENCIA ARTIFICIAL 👑🌮\n\n"
            "🎯 3 Selecciones analizadas con modelos predictivos y valor matemático (+EV).\n\n"
            "🔗 Revisa todos los picks gratis y el Parlay del Día en el link de la bio 👇\n"
            "👉 https://reytacopicks.com\n\n"
            "#ReyTacoPicks #ApuestasDeportivas #LigaMX #MLB #Futbol #TipsDeportivos #IA"
        )

    try:
        # 1. Crear Media Container
        url_create = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media"
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": FB_PAGE_ACCESS_TOKEN
        }
        r = requests.post(url_create, data=payload, timeout=20)
        res = r.json()
        container_id = res.get("id")
        
        if not container_id:
            print(f"   ⚠️ Error creando contenedor de Instagram: {res}")
            return False

        # 2. Publicar Media Container
        url_publish = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish"
        r_pub = requests.post(url_publish, data={"creation_id": container_id, "access_token": FB_PAGE_ACCESS_TOKEN}, timeout=20)
        res_pub = r_pub.json()
        
        if "id" in res_pub:
            print(f"   ✅ ¡Publicado exitosamente en Instagram! Media ID: {res_pub['id']}")
            return True
        else:
            print(f"   ⚠️ Error publicando en Instagram: {res_pub}")
            return False
    except Exception as e:
        print(f"   ❌ Error en Instagram: {e}")
        return False

def ejecutar_auto_post_redes():
    """Genera el banner y lo publica en las redes sociales oficiales."""
    print("\n" + "="*60)
    print("📱 PUBLICACIÓN AUTOMÁTICA EN REDES SOCIALES (Meta Graph API)")
    print("="*60)
    
    try:
        from render_html_banner import renderizar_banner_estudio
        banner_file = os.path.join(os.path.dirname(__file__), "banner_hoy.png")
        renderizar_banner_estudio(output_path=banner_file)
    except Exception as e:
        print(f"Error renderizando banner estudio: {e}")
        from social_banner import generar_banner_redes
        banner_file = os.path.join(os.path.dirname(__file__), "banner_hoy.png")
        generar_banner_redes(output_path=banner_file)
    
    publicar_en_facebook_page(image_path=banner_file)

if __name__ == "__main__":
    ejecutar_auto_post_redes()
