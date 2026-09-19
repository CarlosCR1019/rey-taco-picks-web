import json
import base64
from dotenv import dotenv_values

d = dotenv_values("/root/sports-props-collector/backend/.env")
k = d.get("SUPABASE_KEY", "")
if k and "." in k:
    payload = json.loads(base64.b64decode(k.split(".")[1] + "=="))
    print("ROLE:", payload.get("role"))
else:
    print("No valid JWT")
