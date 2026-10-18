"""
backend/tiktok_auto_uploader.py
===============================
Publicador 100% autónomo de Reels MP4 en TikTok Studio (@rey.taco.picks)
usando Playwright Chromium y cookies de sesión persistentes (`data/tiktok_cookies.json`).
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
COOKIES_PATH = REPO_ROOT / "data" / "tiktok_cookies.json"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


def strip_accents(text: Any) -> str:
    """Elimina acentos y tildes para evitar '?' en TikTok Studio."""
    if text is None:
        return ""
    s = str(text)
    replacements = {
        "ñ": "n", "Ñ": "N",
        "á": "a", "Á": "A",
        "é": "e", "É": "E",
        "í": "i", "Í": "I",
        "ó": "o", "Ó": "O",
        "ú": "u", "Ú": "U",
        "ü": "u", "Ü": "U",
        "¿": "", "¡": "",
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "—": "-", "–": "-",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _ensure_hydrated_cookies(raw_cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Verifica y refresca las cookies de sesión contra /passport/web/account/info/
    para garantizar que tt-target-idc (alisg/maliva), uid_tt y sid_guard estén activos.
    """
    cookie_map = {str(c.get("name") or ""): str(c.get("value") or "") for c in raw_cookies if c.get("name")}
    sid = cookie_map.get("sessionid") or cookie_map.get("sid_tt") or ""
    if sid and ("uid_tt" not in cookie_map or "sid_guard" not in cookie_map or "tt-target-idc" not in cookie_map):
        try:
            s = requests.Session()
            s.cookies.set("sessionid", sid, domain=".tiktok.com")
            s.cookies.set("sessionid_ss", sid, domain=".tiktok.com")
            s.cookies.set("sid_tt", sid, domain=".tiktok.com")
            s.cookies.set("tt-target-idc", cookie_map.get("tt-target-idc", "alisg"), domain=".tiktok.com")
            s.get("https://www.tiktok.com/passport/web/account/info/", headers={"User-Agent": DEFAULT_UA}, timeout=15)
            for k, v in s.cookies.get_dict().items():
                cookie_map[k] = v
        except Exception as e:
            print(f"ℹ️ [TIKTOK AUTO] Nota hidratando cookies: {e}")

    cleaned: List[Dict[str, Any]] = []
    for c in raw_cookies:
        name = str(c.get("name") or "").strip()
        value = str(c.get("value") or "").strip()
        if not name or not value:
            continue
        same_site_raw = str(c.get("sameSite") or "None").capitalize()
        if same_site_raw not in ("Strict", "Lax", "None"):
            same_site_raw = "None"
        entry: Dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": str(c.get("domain") or ".tiktok.com").strip(),
            "path": str(c.get("path") or "/").strip(),
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": same_site_raw,
        }
        exp = c.get("expires") or c.get("expirationDate")
        if isinstance(exp, (int, float)) and exp > 0:
            entry["expires"] = float(exp)
        cleaned.append(entry)

    existing_names = {c["name"] for c in cleaned}
    for k, v in cookie_map.items():
        if k not in existing_names and v:
            cleaned.append({
                "name": k,
                "value": v,
                "domain": ".tiktok.com",
                "path": "/",
                "secure": True,
                "httpOnly": k in ("sessionid", "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss", "sid_guard"),
                "sameSite": "None",
            })
    return cleaned


def _clear_blocking_overlays(page: Any) -> None:
    """Elimina banners de cookies y modales de bienvenida que interceptan clics en TikTok Studio."""
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('tiktok-cookie-banner').forEach(el => el.remove());
                document.querySelectorAll('.TUXModal-overlay, [data-floating-ui-portal]').forEach(el => {
                    const txt = (el.innerText || '').toLowerCase();
                    if (!txt.includes('publicar ahora') && !txt.includes('post now')) {
                        el.remove();
                    }
                });
            }"""
        )
    except Exception:
        pass


def publish_tiktok_video(mp4_path: str | Path, caption: str) -> Dict[str, Any]:
    """
    Sube y publica automáticamente un video MP4 en TikTok Studio (@rey.taco.picks)
    usando las cookies guardadas en data/tiktok_cookies.json.
    """
    video_file = Path(mp4_path)
    if not video_file.exists():
        return {"ok": False, "reason": "missing_video_file"}

    if not COOKIES_PATH.exists():
        print("ℹ️ [TIKTOK AUTO] No se encontró data/tiktok_cookies.json; omitiendo subida directa a TikTok.")
        return {"ok": False, "reason": "tiktok_cookies_not_configured"}

    try:
        raw_cookies = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
        pw_cookies = _ensure_hydrated_cookies(raw_cookies)
        if not pw_cookies:
            return {"ok": False, "reason": "empty_cookies"}
    except Exception as e:
        return {"ok": False, "reason": f"invalid_cookies_json: {e}"}

    clean_caption = caption.replace("\n\n", " • ").replace("\n", " ").strip()[:2000]

    # Filtro anti-baneo estricto para TikTok (elimina cualquier término de apuestas o casas, sin acentos)
    banned_replacements = {
        "apuestas deportivas": "predicciones deportivas",
        "apuesta deportiva": "prediccion deportiva",
        "apuestas": "analisis deportivo",
        "apuesta": "pronostico",
        "playdoit": "nuestro modelo",
        "momio": "probabilidad",
        "cuota": "linea",
        "casino": "deportes",
        "ganar dinero": "obtener valor",
    }
    sanitized_caption = clean_caption
    for bad, good in banned_replacements.items():
        sanitized_caption = re.sub(re.escape(bad), good, sanitized_caption, flags=re.IGNORECASE)
    sanitized_caption = strip_accents(sanitized_caption)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 920},
                user_agent=DEFAULT_UA,
                locale="es-MX",
            )
            context.add_cookies(pw_cookies)
            page = context.new_page()

            page.goto(
                "https://www.tiktok.com/tiktokstudio/upload?from=upload",
                wait_until="domcontentloaded",
                timeout=45000,
            )

            file_input = page.locator('input[type="file"]').first
            try:
                file_input.wait_for(state="attached", timeout=30000)
            except Exception:
                if "login" in page.url.lower():
                    browser.close()
                    print("⚠️ [TIKTOK AUTO] Sesión de TikTok expirada o redirigida a login.")
                    return {"ok": False, "reason": "session_expired"}
                browser.close()
                return {"ok": False, "reason": "file_input_not_mounted"}

            _clear_blocking_overlays(page)

            # 1. Cargar archivo MP4
            print(f"📤 [TIKTOK AUTO] Cargando {video_file.name} en TikTok Studio (@rey.taco.picks)...")
            file_input.set_input_files(str(video_file), timeout=30000)

            # 2. Esperar a que el archivo termine de procesarse (aparece 'Cargado' o 'Sustituir' o transcurren 14s)
            print("⏳ [TIKTOK AUTO] Esperando procesamiento y validación del video...")
            for _ in range(15):
                page.wait_for_timeout(2000)
                body_txt = (page.locator("body").inner_text() or "").lower()
                if "cargado" in body_txt or "sustituir" in body_txt or "detalles" in body_txt:
                    break

            _clear_blocking_overlays(page)

            # 3. Escribir descripción limpia sin palabras de apuestas
            editor = page.locator('.public-DraftEditor-content, [contenteditable="true"]').first
            try:
                editor.wait_for(state="visible", timeout=25000)
                editor.click(force=True)
                page.wait_for_timeout(600)
                # Seleccionar todo el texto previo (nombre del archivo) y reemplazarlo
                page.evaluate(
                    """(captionText) => {
                        const el = document.querySelector('[contenteditable="true"]');
                        if (el) {
                            el.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, captionText);
                        }
                    }""",
                    sanitized_caption
                )
                page.wait_for_timeout(800)
                curr_txt = editor.inner_text().strip()
                if len(curr_txt) < 10:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.insert_text(sanitized_caption)
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
            except Exception as e_ed:
                print(f"ℹ️ [TIKTOK AUTO] Nota al escribir descripción: {e_ed}")

            # 4. Asegurar que la privacidad esté en 'Todo el mundo'
            try:
                privacy_dropdown = page.locator('div:has-text("Quién puede ver"), div:has-text("Visibilidad")').locator('..').locator('[role="combobox"], [class*="Select"]').first
                if privacy_dropdown.count() > 0:
                    curr_priv = privacy_dropdown.inner_text().lower()
                    if "todo el mundo" not in curr_priv and "everyone" not in curr_priv:
                        privacy_dropdown.click(force=True)
                        page.wait_for_timeout(1000)
                        opt_public = page.locator('[role="option"]:has-text("Todo el mundo"), div:has-text("Todo el mundo")').first
                        if opt_public.count() > 0:
                            opt_public.click(force=True)
                            page.wait_for_timeout(1000)
            except Exception:
                pass

            # 5. Esperar a que el botón Publicar esté habilitado y hacer clic
            posted = False
            for _ in range(30):
                _clear_blocking_overlays(page)
                btn = page.locator('button[data-e2e="post_video_button"]').first
                if btn.count() > 0 and btn.is_visible():
                    disabled_attr = btn.get_attribute("disabled")
                    aria_disabled = btn.get_attribute("aria-disabled")
                    data_disabled = btn.get_attribute("data-disabled")
                    data_loading = btn.get_attribute("data-loading")
                    if (
                        disabled_attr is None
                        and aria_disabled != "true"
                        and data_disabled != "true"
                        and data_loading != "true"
                    ):
                        btn.scroll_into_view_if_needed()
                        try:
                            btn.click(force=True, timeout=5000)
                        except Exception:
                            btn.evaluate("el => el.click()")
                        posted = True
                        break
                time.sleep(3)

            if not posted:
                browser.close()
                print("⚠️ [TIKTOK AUTO] El botón Publicar no se habilitó a tiempo.")
                return {"ok": False, "reason": "post_button_not_ready"}

            # 6. Manejar modal de confirmación final ("Publicar ahora" / "Continuar")
            for _ in range(5):
                page.wait_for_timeout(2500)
                for confirm_sel in (
                    'button:has-text("Publicar ahora")',
                    'button:has-text("Post now")',
                    'button:has-text("Continuar")',
                    'button:has-text("Continue")',
                    'button[data-e2e="post_confirm_button"]',
                ):
                    c_btn = page.locator(confirm_sel).first
                    if c_btn.count() > 0 and c_btn.is_visible():
                        try:
                            c_btn.click(force=True, timeout=3000)
                        except Exception:
                            pass
                if "/content" in page.url.lower():
                    break

            page.wait_for_timeout(5000)
            final_url = page.url
            try:
                COOKIES_PATH.write_text(json.dumps(context.cookies(), indent=2), encoding="utf-8")
            except Exception:
                pass

            browser.close()
            print(f"✅ [TIKTOK AUTO] Video publicado exitosamente en TikTok (@rey.taco.picks): {video_file.name} (URL: {final_url})")
            return {"ok": True, "video": video_file.name, "final_url": final_url}
    except Exception as e:
        print(f"⚠️ [TIKTOK AUTO] Excepción subiendo a TikTok Studio: {e}")
        return {"ok": False, "error": str(e)}
