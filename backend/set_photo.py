import os
from pathlib import Path
import urllib.request
import uuid

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
PHOTO_PATH = Path(
    os.getenv(
        "TELEGRAM_CHAT_PHOTO",
        Path(__file__).resolve().parents[1] / "frontend" / "public" / "logo.jpg",
    )
)

if not TOKEN or not CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID are required")

boundary = uuid.uuid4().hex
headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}

body = []
body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{CHAT_ID}\r\n'.encode('utf-8'))
with PHOTO_PATH.open('rb') as f:
    photo_data = f.read()
body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="photo.png"\r\nContent-Type: image/png\r\n\r\n'.encode('utf-8'))
body.append(photo_data)
body.append(f'\r\n--{boundary}--\r\n'.encode('utf-8'))

payload = b''.join(body)
url = f'https://api.telegram.org/bot{TOKEN}/setChatPhoto'

req = urllib.request.Request(url, data=payload, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        print('RESULTADO:', resp.read().decode())
except Exception as e:
    print('ERROR:', e)
    if hasattr(e, 'read'):
        print(e.read().decode())
