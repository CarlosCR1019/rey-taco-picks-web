"""
Draftea Mobile API Integration Module
Rey Taco Picks Autonomous Sportsbook Engine
"""

import os
import requests
from typing import List, Dict, Any

DRAFTEA_BASE_URL = os.getenv("DRAFTEA_API_URL", "https://api.draftea.com")
DRAFTEA_AUTH_TOKEN = os.getenv("DRAFTEA_AUTH_TOKEN", "")

class DrafteaClient:
    def __init__(self, auth_token: str = None):
        self.base_url = DRAFTEA_BASE_URL
        self.token = auth_token or DRAFTEA_AUTH_TOKEN
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Draftea/5.16 (Android; Linux; es-MX)",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-device-platform": "android",
            "x-app-version": "5.16.3"
        })
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def set_token(self, token: str):
        """Actualiza el token de autenticación JWT de la sesión de Draftea."""
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def fetch_player_props(self, sport: str = "soccer", tournament_id: str = None) -> List[Dict[str, Any]]:
        """
        Extrae las líneas activas de Remates a Puerta (Shots on Target) desde Draftea.
        """
        endpoints_to_try = [
            f"{self.base_url}/v1/props?sport={sport}",
            f"{self.base_url}/v1/sports/{sport}/props",
            f"{self.base_url}/v1/lobbies/props",
            f"{self.base_url}/props"
        ]
        
        for ep in endpoints_to_try:
            try:
                r = self.session.get(ep, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    print(f"✅ Draftea API Props obtenidas desde {ep}: {len(data) if isinstance(data, list) else len(data.get('items', []))} elementos")
                    return self._parse_props(data)
            except Exception as e:
                print(f"⚠️ Intento fallido en {ep}: {e}")
                
        return []

    def _parse_props(self, raw_data: Any) -> List[Dict[str, Any]]:
        parsed = []
        items = raw_data if isinstance(raw_data, list) else raw_data.get("items", raw_data.get("data", []))
        for item in items:
            player_name = item.get("player_name") or item.get("name")
            team = item.get("team") or item.get("team_name")
            match = item.get("match") or item.get("game_name")
            line = item.get("line") or item.get("value", 0.5)
            multiplier = item.get("multiplier") or item.get("odds", 1.50)
            
            if player_name:
                parsed.append({
                    "jugador": player_name,
                    "equipo": team,
                    "partido": match or f"{player_name} ({team})",
                    "mercado": "Remates a Puerta (BANCA+)",
                    "linea": f"Más de {line} Remates",
                    "multiplicador": multiplier,
                    "suplente_activo": True
                })
        return parsed

if __name__ == "__main__":
    client = DrafteaClient()
    print("Probando cliente Draftea API...")
    props = client.fetch_player_props()
    print(f"Resultado: {props}")
