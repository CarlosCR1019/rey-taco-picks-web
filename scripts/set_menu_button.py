import os
import sys
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8684914807:AAHjNX6cz_sn1EUZVl0wt4v5iYWzJ8JU5UE"
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "5912533842"

def set_telegram_menu_button():
    # 1. Set for Admin chat
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setChatMenuButton"
    payload = {
        "chat_id": int(ADMIN_CHAT_ID),
        "menu_button": {
            "type": "web_app",
            "text": "🌮 Picks Privados",
            "web_app": {
                "url": "https://reytacopicks.com/mini-app.html?v=12"
            }
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("Resultado setChatMenuButton (Admin):", data)
    except Exception as e:
        print("Error setting admin menu button:", e)

    # 2. Set globally for all users
    payload_global = {
        "menu_button": {
            "type": "web_app",
            "text": "🌮 Picks Privados",
            "web_app": {
                "url": "https://reytacopicks.com/mini-app.html?v=12"
            }
        }
    }
    req_global = urllib.request.Request(
        url,
        data=json.dumps(payload_global).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req_global, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("Resultado setChatMenuButton (Global):", data)
    except Exception as e:
        print("Error setting global menu button:", e)

if __name__ == "__main__":
    set_telegram_menu_button()
