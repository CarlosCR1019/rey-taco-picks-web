import os
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

try:
    from backend.payment_review import classify_receipt
    from backend.membership_admin import is_active_subscription
except ModuleNotFoundError:  # Allows `python backend/ticket_listener.py`.
    from payment_review import classify_receipt
    from membership_admin import is_active_subscription

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
VIP_CHANNEL_ID = os.getenv("TELEGRAM_VIP_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
FREE_CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID", "")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID") or "0")
SUPABASE_ADMIN_USER_ID = os.getenv("SUPABASE_ADMIN_USER_ID", "")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TICKETS_DIR = PROJECT_ROOT / "frontend" / "public" / "tickets"
RECEIPTS_DIR = Path(
    os.getenv("PRIVATE_RECEIPTS_DIR", PROJECT_ROOT / "backend" / "private_receipts")
)
TICKETS_DIR.mkdir(parents=True, exist_ok=True)
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

OFFSET_FILE = os.path.join(os.path.dirname(__file__), ".telegram_offset")

def get_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except Exception:
                return 0
    return 0

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def telegram_api(method, payload):
    """Llamada genérica segura a la API de Telegram."""
    if not TELEGRAM_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error Telegram API ({method}): {e}")
        return None

def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=30"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode())
            return data.get('result', [])
    except Exception as e:
        print(f"Error obteniendo updates: {e}")
        return []

def download_photo(file_id, save_path):
    """Descarga una foto de Telegram usando el file_id."""
    try:
        res = telegram_api("getFile", {"file_id": file_id})
        if res and res.get('ok'):
            file_path = res['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            urllib.request.urlretrieve(download_url, save_path)
            return True
        return False
    except Exception as e:
        print(f"Error descargando foto: {e}")
        return False

def reenviar_a_canal(file_id, caption=""):
    """Reenvía la foto a AMBOS canales: Canal VIP y Canal Gratuito."""
    canales = list(set([c for c in [VIP_CHANNEL_ID, FREE_CHANNEL_ID, CHANNEL_ID] if c]))
    for cid in canales:
        try:
            telegram_api("sendPhoto", {
                "chat_id": cid,
                "photo": file_id,
                "caption": caption or "🏆 ¡Ticket Ganador! Otra victoria más para Rey Taco Picks 👑🌮"
            })
            print(f"   📢 Foto de ticket enviada exitosamente a canal {cid}.")
        except Exception as e:
            print(f"   ⚠️ Error enviando a canal {cid}: {e}")

def responder(chat_id, texto, reply_markup=None):
    payload = {"chat_id": chat_id, "text": texto}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    telegram_api("sendMessage", payload)

def responder_publico(chat_id):
    """Envía mensaje comercial / bienvenida automático a cualquier usuario que no sea el admin."""
    texto = (
        "🌮👑 ¡Hola! Bienvenido al bot oficial de *Rey Taco Picks*.\n\n"
        "📢 Para recibir nuestros análisis y picks gratuitos del día, entra a nuestro canal:\n"
        "👉 @ReyTacoPicksFree\n\n"
        "👑 Para recibir la cartera completa, córners y combinadas exclusivas antes de cada partido, adquiere tu *Pase VIP ($299 MXN)*:\n"
        "👉 Escríbenos por WhatsApp: https://wa.me/525639331102\n\n"
        "🌐 Web Oficial: https://reytacopicks.com"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "👑 Adquirir VIP ($299 MXN)", "url": "https://wa.me/525639331102?text=Hola,%20quiero%20el%20Pase%20VIP%20de%20Rey%20Taco%20Picks"},
                {"text": "📢 Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"}
            ],
            [
                {"text": "🌐 Visitar Web Oficial", "url": "https://reytacopicks.com/"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def procesar_vinculacion_telegram(message, raw_text):
    """Consume a short-lived web token and binds this Telegram account once."""
    if not raw_text.startswith("/start link_"):
        return False
    if not supabase:
        responder(message.get("chat", {}).get("id"), "⚠️ La vinculación no está disponible en este momento.")
        return True
    user = message.get("from", {})
    token = raw_text.removeprefix("/start link_").strip()
    try:
        result = supabase.rpc("consume_telegram_link_token", {
            "raw_token": token,
            "new_telegram_id": str(user.get("id", "")),
            "new_telegram_username": user.get("username"),
        }).execute()
        linked = bool(result.data)
        responder(
            message.get("chat", {}).get("id"),
            "✅ Tu cuenta de Telegram quedó vinculada a Rey Taco Picks." if linked
            else "⚠️ El enlace expiró o ya fue utilizado. Genera uno nuevo desde tu cuenta web.",
        )
    except Exception as error:
        print(f"Error vinculando Telegram: {error}")
        responder(message.get("chat", {}).get("id"), "⚠️ No pudimos vincular la cuenta. Genera un enlace nuevo.")
    return True

def buscar_usuario_auth_por_correo(email):
    """Resolve an Auth user with the server-only admin API, not a profile column."""
    if not supabase:
        return None
    target = str(email).strip().lower()
    for page in range(1, 101):
        users = supabase.auth.admin.list_users(page=page, per_page=100)
        match = next((user for user in users if str(user.email or "").lower() == target), None)
        if match:
            return str(match.id)
        if len(users) < 100:
            break
    return None

def verificar_usuario_vip(telegram_id=None, username=None):
    """Verifica en Supabase si el usuario tiene suscripción VIP activa."""
    if not supabase:
        return False
    try:
        profile = None
        if telegram_id:
            res = supabase.table("profiles").select("id").eq("telegram_id", str(telegram_id)).limit(1).execute()
            profile = res.data[0] if res.data else None
        if profile:
            sub = supabase.rpc("is_active_subscriber", {"check_user": profile["id"]}).execute()
            return sub.data is True
    except Exception as e:
        print(f"Error verificando usuario VIP en Supabase: {e}")
    return False

def procesar_solicitud_union(join_req):
    """Procesa una solicitud de usuario para unirse al canal VIP con aprobación obligatoria."""
    user = join_req.get('from', {})
    chat = join_req.get('chat', {})
    user_id = user.get('id')
    username = user.get('username', 'Sin username')
    first_name = user.get('first_name', 'Usuario')
    chat_id = chat.get('id')

    print(f"\n🚪 [SOLICITUD DE UNIÓN] Usuario: {first_name} (@{username}, ID: {user_id}) en Canal {chat_id}")

    # Verificar si es VIP en Supabase
    es_vip = verificar_usuario_vip(telegram_id=user_id, username=username)

    if es_vip:
        # APROBAR AUTOMÁTICAMENTE
        telegram_api("approveChatJoinRequest", {"chat_id": chat_id, "user_id": user_id})
        responder(user_id, "👑 ¡Felicidades! Tu suscripción VIP fue verificada. Bienvenido al Canal VIP Oficial de Rey Taco Picks 🌮.")
        responder(ADMIN_CHAT_ID, f"✅ [VIP AUTO-APROBADO] @{username} ({first_name}, ID: {user_id}) fue aceptado automáticamente en el Canal VIP.")
        print(f"   ✅ Usuario {user_id} aprobado automáticamente.")
    else:
        # RECHAZAR O MANTENER PENDIENTE Y MANDARLE MENSAJE DE PAGO
        telegram_api("declineChatJoinRequest", {"chat_id": chat_id, "user_id": user_id})
        
        # Enviar mensaje privado con datos de pago
        msg_pago = (
            f"👑 ¡Hola {first_name}! Para ingresar al *Canal VIP Oficial de Rey Taco Picks*, requieres una suscripción activa ($299 MXN/mes).\n\n"
            "💳 *PAGO DIRECTO SPEI (BBVA)*:\n"
            "• Banco: BBVA México\n"
            "• CLABE: `012 180 01522813375 9`\n"
            "• Titular: Rey Taco Picks\n\n"
            "📲 Al realizar tu transferencia, envía tu comprobante a nuestro WhatsApp para activarte de inmediato:\n"
            "👉 https://wa.me/525639331102"
        )
        responder(user_id, msg_pago)
        
        # Notificar a Carlos en privado
        responder(ADMIN_CHAT_ID, 
            f"⚠️ [ACCESO VIP DENEGADO]\n\n"
            f"👤 Usuario: {first_name} (@{username})\n"
            f"🆔 ID Telegram: `{user_id}`\n"
            f"❌ Motivo: No tiene suscripción activa en Supabase.\n"
            f"🤖 Se le enviaron los datos de transferencia SPEI y WhatsApp."
        )
        print(f"   🚫 Solicitud de {user_id} denegada por falta de pago.")

def procesar_nuevo_miembro(message):
    """Detecta si alguien entra al canal VIP sin autorización y lo expulsa."""
    chat = message.get('chat', {})
    chat_id = chat.get('id')
    
    # Solo auditar si es en el canal VIP
    if str(chat_id) == str(VIP_CHANNEL_ID):
        new_members = message.get('new_chat_members', [])
        for m in new_members:
            user_id = m.get('id')
            username = m.get('username', 'Sin username')
            first_name = m.get('first_name', 'Usuario')
            
            if user_id == ADMIN_CHAT_ID:
                continue
                
            es_vip = verificar_usuario_vip(telegram_id=user_id, username=username)
            if not es_vip:
                print(f"🚨 [EXPULSIÓN] Usuario no autorizado en canal VIP: {first_name} (@{username})")
                # Expulsar
                telegram_api("banChatMember", {"chat_id": chat_id, "user_id": user_id})
                telegram_api("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})
                
                responder(ADMIN_CHAT_ID, 
                    f"🚫 [USUARIO EXPULSADO DEL CANAL VIP]\n\n"
                    f"👤 {first_name} (@{username}, ID: `{user_id}`)\n"
                    f"Fue expulsado automáticamente porque no tiene suscripción VIP pagada."
                )

def procesar_comprobante_cliente(update):
    """Procesa un comprobante bancario enviado por un cliente en Telegram."""
    message = update.get('message', {})
    user = message.get('from', {})
    chat_id = message.get('chat', {}).get('id')
    user_id = user.get('id', chat_id)
    username = user.get('username', 'Sin username')
    first_name = user.get('first_name', 'Usuario')
    photos = message.get('photo', [])
    
    if not photos:
        return
        
    best_photo = photos[-1]
    file_id = best_photo['file_id']
    save_path = RECEIPTS_DIR / f"comprobante_{user_id}_{int(time.time())}.jpg"
    
    print(f"\n💳 [COMPROBANTE RECIBIDO] de {first_name} (@{username}, ID: {user_id})")
    
    if download_photo(file_id, str(save_path)):
        texto_ocr = ""
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(save_path)
            texto_ocr = pytesseract.image_to_string(img).lower()
            print(f"   🔍 OCR detectado: {texto_ocr[:120]}...")
        except Exception as e:
            print(f"   ⚠️ OCR no disponible o error: {e}")
            
        review = classify_receipt(texto_ocr)
        review_id = None
        if supabase:
            try:
                linked_profile = supabase.table("profiles").select("id").eq(
                    "telegram_id", str(user_id)
                ).limit(1).execute()
                review_record = supabase.table("payment_reviews").insert({
                    "user_id": linked_profile.data[0]["id"] if linked_profile.data else None,
                    "telegram_id": str(user_id),
                    "telegram_username": username.replace("@", "").lower(),
                    "status": review.status,
                    "detected_amount": review.detected_amount,
                    "detected_bank": review.detected_bank,
                    "receipt_filename": save_path.name,
                }).execute()
                review_id = review_record.data[0]["id"] if review_record.data else None
            except Exception as e:
                print(f"   ⚠️ No se pudo registrar payment_reviews: {e}")

        if ADMIN_CHAT_ID:
            telegram_api("sendPhoto", {
                "chat_id": ADMIN_CHAT_ID,
                "photo": file_id,
                "caption": (
                    "📩 [COMPROBANTE PENDIENTE DE REVISIÓN]\n"
                    f"👤 {first_name} (@{username}, ID: `{user_id}`)\n"
                    f"💵 OCR detectó $299: {'sí' if review.detected_amount else 'no'}\n"
                    f"🏦 OCR detectó banco/SPEI: {'sí' if review.detected_bank else 'no'}\n\n"
                    f"📝 Revisión: `{review_id or 'no registrada'}`\n\n"
                    "El OCR no activa membresías. Verifica el movimiento y usa /vip REVISION_UUID correo."
                ),
            })
        responder(
            user_id,
            "📨 Recibimos tu comprobante. Está pendiente de revisión manual; te avisaremos cuando el pago sea confirmado.",
        )

def procesar_foto(update):
    """Procesa una foto recibida del admin."""
    message = update.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    caption = message.get('caption', '')
    photos = message.get('photo', [])
    
    if not photos:
        return
    
    best_photo = photos[-1]
    file_id = best_photo['file_id']
    
    timestamp = int(time.time())
    filename = f"ticket_{timestamp}.jpg"
    save_path = os.path.join(TICKETS_DIR, filename)
    
    print(f"\n📸 Foto recibida de chat {chat_id}")
    
    if download_photo(file_id, save_path):
        print(f"   ✅ Guardada: {save_path}")
        
        manifest_path = os.path.join(TICKETS_DIR, "manifest.json")
        manifest_list = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_list = json.load(f)
            except Exception:
                manifest_list = []
        if filename not in manifest_list:
            manifest_list.insert(0, filename)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_list, f, indent=2)
            print("   📁 manifest.json actualizado.")
        
        if supabase:
            try:
                supabase.table("tickets_ganadores").insert({
                    "archivo": filename,
                    "caption": caption or "Ticket Ganador",
                    "file_id": file_id,
                    "file_unique_id": best_photo.get("file_unique_id", ""),
                    "telegram_chat_id": chat_id,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
                print("   ✅ Registrado en Supabase.")
            except Exception as e:
                print(f"   ⚠️ Error en Supabase (tabla opcional): {e}")
        
        reenviar_a_canal(file_id, caption)
        responder(chat_id, f"✅ ¡Ticket guardado y publicado en el canal!\nArchivo: {filename}")
    else:
        responder(chat_id, "❌ Error al descargar la foto. Intenta de nuevo.")

def main():
    print("="*60)
    print("🛡️  REY TACO PICKS — Guardian & Ticket Listener 24/7")
    print("   Protección VIP: Rechazo automático de no-pagados activo")
    print("   Admin ID:", ADMIN_CHAT_ID)
    print("="*60)
    
    offset = get_offset()
    
    while True:
        try:
            updates = get_updates(offset)
            
            for update in updates:
                offset = update['update_id'] + 1
                save_offset(offset)
                
                # 1. EVENTO: Solicitud de entrada a canal privado (Request Admin Approval)
                if 'chat_join_request' in update:
                    procesar_solicitud_union(update['chat_join_request'])
                    continue

                # 2. EVENTO: Mensajes normales o fotos
                message = update.get('message', {})
                if not message:
                    continue

                # Detectar si alguien entró al canal
                if 'new_chat_members' in message:
                    procesar_nuevo_miembro(message)
                    continue

                chat_id = message.get('chat', {}).get('id')
                if not chat_id:
                    continue
                
                # Si NO es Carlos (Admin)
                if chat_id != ADMIN_CHAT_ID:
                    if 'photo' in message:
                        procesar_comprobante_cliente(update)
                    elif procesar_vinculacion_telegram(message, message.get('text', '').strip()):
                        pass
                    else:
                        print(f"👤 Mensaje de usuario {chat_id}. Enviando respuesta comercial...")
                        responder_publico(chat_id)
                    continue
                
                # SI ES CARLOS (ADMIN MASTER):
                if 'photo' in message:
                    procesar_foto(update)
                elif 'text' in message:
                    raw_text = message.get('text', '').strip()
                    texto = raw_text.lower()
                    
                    if texto == '/start':
                        responder(chat_id, 
                            "👑 ¡Bienvenido Administrador Carlos!\n\n"
                            "📸 Envíame cualquier foto de ticket ganador y la publicaré en el canal y en la web.\n\n"
                            "🛡️ GUARDIÁN DEL CANAL VIP:\n"
                            "• El bot rechaza automáticamente a quienes intenten entrar sin suscripción.\n"
                            "• /aprobar 123456789 ➔ Aprueba manualmente a un usuario por su ID\n"
                            "• /expulsar 123456789 ➔ Expulsa a un usuario del Canal VIP\n"
                            "• /vip REVISION_UUID correo@ejemplo.com ➔ Aprueba SPEI y activa VIP\n"
                            "• /rechazar REVISION_UUID ➔ Rechaza un comprobante\n"
                            "• /usuarios ➔ Ver clientes registrados"
                        )
                    elif texto.startswith('/aprobar '):
                        partes = raw_text.split()
                        if len(partes) >= 2:
                            target_id = int(partes[1].strip())
                            if verificar_usuario_vip(telegram_id=target_id):
                                telegram_api("approveChatJoinRequest", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                                responder(chat_id, f"✅ Usuario {target_id} APROBADO: membresía verificada.")
                            else:
                                responder(chat_id, f"⚠️ Usuario {target_id} no tiene una membresía activa; no fue aprobado.")
                    elif texto.startswith('/expulsar '):
                        partes = raw_text.split()
                        if len(partes) >= 2:
                            target_id = int(partes[1].strip())
                            telegram_api("banChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                            telegram_api("unbanChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                            responder(chat_id, f"🚫 Usuario {target_id} EXPULSADO del Canal VIP.")
                    elif texto.startswith('/vip '):
                        partes = raw_text.split()
                        if len(partes) == 3:
                            review_id = partes[1].strip()
                            target_email = partes[2].strip().lower()
                            if supabase and SUPABASE_ADMIN_USER_ID:
                                try:
                                    user_id = buscar_usuario_auth_por_correo(target_email)
                                    if not user_id:
                                        responder(chat_id, f"⚠️ No existe una cuenta para {target_email}.")
                                        continue
                                    result = supabase.rpc("approve_spei_review", {
                                        "review_id": review_id,
                                        "review_user": user_id,
                                        "reviewer": SUPABASE_ADMIN_USER_ID,
                                    }).execute()
                                    responder(chat_id, f"✅ SPEI aprobado y membresía activa para {target_email} hasta {result.data}.")
                                except Exception as e:
                                    responder(chat_id, f"⚠️ Error: {e}")
                            else:
                                responder(chat_id, "⚠️ Configura Supabase y SUPABASE_ADMIN_USER_ID antes de aprobar pagos.")
                        else:
                            responder(chat_id, "Uso: /vip REVISION_UUID correo@ejemplo.com")
                    elif texto.startswith('/rechazar '):
                        partes = raw_text.split()
                        if len(partes) == 2 and supabase and SUPABASE_ADMIN_USER_ID:
                            try:
                                result = supabase.rpc("reject_spei_review", {
                                    "review_id": partes[1].strip(),
                                    "reviewer": SUPABASE_ADMIN_USER_ID,
                                }).execute()
                                responder(chat_id, "✅ Comprobante rechazado." if result.data else "⚠️ La revisión no estaba pendiente.")
                            except Exception as e:
                                responder(chat_id, f"⚠️ Error: {e}")
                    elif texto == '/usuarios':
                        if supabase:
                            try:
                                res = supabase.table("subscriptions").select("user_id,status,current_period_end,provider").order("current_period_end", desc=True).limit(20).execute()
                                if res.data:
                                    msg_users = "📋 MEMBRESÍAS RECIENTES:\n\n"
                                    for u in res.data:
                                        vip_icon = "👑 Activa" if is_active_subscription(u) else "⚪ Inactiva"
                                        msg_users += f"• {u.get('user_id')} · {u.get('provider')} ➔ {vip_icon}\n"
                                    responder(chat_id, msg_users)
                                else:
                                    responder(chat_id, "No hay membresías registradas aún.")
                            except Exception as e:
                                responder(chat_id, f"Error: {e}")
                    elif texto == '/tickets':
                        archivos = os.listdir(TICKETS_DIR)
                        fotos = [f for f in archivos if f.endswith(('.jpg', '.png', '.jpeg'))]
                        responder(chat_id, f"📸 Tickets guardados: {len(fotos)}")
                        
        except KeyboardInterrupt:
            print("\n🛑 Listener detenido.")
            break
        except Exception as e:
            print(f"Error en loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
