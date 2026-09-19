"""Manual VIP channel entry. No scraper, database or membership mutations."""
import json
import os
import re
from urllib.request import Request, urlopen

MINI_APP_URL = "https://reytacopicks.com/?view=telegram"
ENTRY_TEXT = (
    "REY TACO PICKS · MINI APP\n\n"
    "Consulta tu cartelera y las ventanas del día desde Telegram.\n\n"
    "1. Pulsa «Abrir bot y Mini App».\n"
    "2. Dentro del bot, pulsa «Abrir Rey Taco Picks» en el menú.\n\n"
    "Para ver los picks VIP necesitas tu cuenta vinculada y membresía activa. "
    "Si no aparecen, revisa la vinculación de tu cuenta en la web.\n\n"
    "18+ · Juego responsable · Sin promesas de ganancias."
)


def ensure_entry(api, channel, *, publish=False):
    if not re.fullmatch(r"-100\d+", channel):
        raise ValueError("VIP channel ID is invalid")
    bot = api("getMe", {})
    username = bot.get("username", "")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise ValueError("bot username is invalid")
    chat = api("getChat", {"chat_id": channel})
    if chat.get("type") != "channel" or str(chat.get("id")) != channel:
        raise ValueError("configured destination is not the expected channel")
    member = api("getChatMember", {"chat_id": channel, "user_id": bot["id"]})
    if member.get("status") != "creator" and not (
        member.get("status") == "administrator"
        and member.get("can_post_messages") and member.get("can_edit_messages")
    ):
        raise ValueError("bot needs channel post and pin permissions")
    menu = api("getChatMenuButton", {})
    if menu.get("type") != "web_app" or menu.get("web_app", {}).get("url") != MINI_APP_URL:
        raise ValueError("Mini App menu is not configured")
    markup = {"inline_keyboard": [[{"text": "Abrir bot y Mini App", "url": f"https://t.me/{username}"}]]}
    pinned = chat.get("pinned_message") or {}
    if pinned.get("text") == ENTRY_TEXT and pinned.get("reply_markup") == markup:
        return {"status": "already_pinned", "message_id": pinned["message_id"]}
    if not publish:
        return {"status": "preview", "channel_title": chat.get("title"), "bot": username, "text": ENTRY_TEXT}
    # Never retry an ambiguous send: inspect the channel before another dispatch.
    message = api("sendMessage", {"chat_id": channel, "text": ENTRY_TEXT,
        "reply_markup": markup, "disable_notification": True,
        "link_preview_options": {"is_disabled": True}})
    message_id = message.get("message_id")
    if not isinstance(message_id, int) or message_id <= 0:
        raise RuntimeError("send outcome unknown; inspect channel before retry")
    print(json.dumps({"sent_message_id": message_id}), flush=True)
    if api("pinChatMessage", {"chat_id": channel, "message_id": message_id,
                             "disable_notification": True}) is not True:
        raise RuntimeError("message sent but not pinned; do not resend")
    verified = api("getChat", {"chat_id": channel}).get("pinned_message") or {}
    if verified.get("message_id") != message_id:
        raise RuntimeError("pin confirmation missing; do not resend")
    return {"status": "pinned", "message_id": message_id}


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("bot secret missing")
    def api(method, payload):
        request = Request(f"https://api.telegram.org/bot{token}/{method}",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=25) as response:
                body = json.load(response)
        except Exception:
            raise RuntimeError(f"Telegram {method} failed; inspect before retry") from None
        if body.get("ok") is not True:
            raise RuntimeError(f"Telegram {method} rejected")
        return body["result"]
    result = ensure_entry(api, os.environ.get("TELEGRAM_VIP_CHANNEL_ID", ""),
                          publish=os.environ.get("PUBLISH_ENTRY") == "true")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
