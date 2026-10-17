"""
backend/social_publisher.py
===========================
Publicador automático de Reels MP4 en Meta Graph API (Facebook Reels + Instagram Reels).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")


def _resolve_meta_token(page_id: str) -> str:
    candidates = [
        (os.getenv("META_SYSTEM_USER_ACCESS_TOKEN") or "").strip(),
        (os.getenv("FB_PAGE_ACCESS_TOKEN") or "").strip(),
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return ""
    if not page_id:
        return candidates[0]
    for tok in candidates:
        try:
            r = requests.get(
                f"https://graph.facebook.com/v20.0/{page_id}",
                params={"fields": "id,access_token", "access_token": tok},
                timeout=10,
            ).json()
            if r.get("access_token"):
                return str(r["access_token"]).strip()
            if r.get("id"):
                return tok
        except Exception:
            pass
    return candidates[0]


def _resolve_ig_user_id(page_id: str, token: str) -> str:
    ig_id = (os.getenv("IG_USER_ID") or "").strip()
    if ig_id:
        return ig_id
    if not page_id or not token:
        return ""
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v20.0/{page_id}",
            params={"fields": "instagram_business_account", "access_token": token},
            timeout=15,
        ).json()
        ig_obj = resp.get("instagram_business_account") or {}
        return str(ig_obj.get("id") or "").strip()
    except Exception:
        return ""


def publish_facebook_reel(mp4_path: str | Path, caption: str) -> Dict[str, Any]:
    """Sube y publica un Reel MP4 directamente en la Facebook Page de Rey Taco Picks."""
    page_id = (os.getenv("FB_PAGE_ID") or "").strip()
    token = _resolve_meta_token(page_id)
    path = Path(mp4_path)
    if not page_id or not token or not path.exists():
        return {"ok": False, "reason": "not_configured_or_missing_file"}

    try:
        file_size = path.stat().st_size
        init_url = f"https://graph.facebook.com/v20.0/{page_id}/video_reels"
        init_res = requests.post(
            init_url,
            data={"access_token": token, "upload_phase": "start"},
            timeout=30,
        ).json()
        video_id = init_res.get("video_id")
        if not video_id:
            print(f"⚠️ [FB REEL] Error en start: {init_res}")
            return {"ok": False, "error": init_res}

        upload_url = f"https://rupload.facebook.com/video-upload/v20.0/{video_id}"
        headers = {
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(file_size),
        }
        with open(path, "rb") as vf:
            up_res = requests.post(upload_url, headers=headers, data=vf, timeout=120).json()
        if not up_res.get("success"):
            print(f"⚠️ [FB REEL] Error en upload: {up_res}")
            return {"ok": False, "error": up_res}

        pub_res = requests.post(
            init_url,
            data={
                "access_token": token,
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
            },
            timeout=30,
        ).json()
        if pub_res.get("success"):
            print(f"✅ [FB REEL] Publicado exitosamente en Facebook Page ({video_id}).")
            return {"ok": True, "video_id": video_id}
        print(f"⚠️ [FB REEL] Error en finish: {pub_res}")
        return {"ok": False, "error": pub_res}
    except Exception as e:
        print(f"⚠️ [FB REEL] Excepción publicando en Facebook: {e}")
        return {"ok": False, "error": str(e)}


def publish_instagram_reel(public_video_url: str, caption: str) -> Dict[str, Any]:
    """Publica un Reel en Instagram Business (@reytaco_picks) usando la URL pública de Cloudflare R2."""
    page_id = (os.getenv("FB_PAGE_ID") or "").strip()
    token = _resolve_meta_token(page_id)
    ig_id = _resolve_ig_user_id(page_id, token)
    if not ig_id or not token or not public_video_url:
        return {"ok": False, "reason": "ig_not_configured_or_no_url"}

    try:
        create_res = requests.post(
            f"https://graph.facebook.com/v20.0/{ig_id}/media",
            data={
                "video_url": public_video_url,
                "media_type": "REELS",
                "share_to_feed": "true",
                "caption": caption,
                "access_token": token,
            },
            timeout=30,
        ).json()
        container_id = create_res.get("id")
        if not container_id:
            print(f"⚠️ [IG REEL] Error creando contenedor: {create_res}")
            return {"ok": False, "error": create_res}

        for _ in range(25):
            time.sleep(6)
            st = requests.get(
                f"https://graph.facebook.com/v20.0/{container_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=20,
            ).json()
            code = st.get("status_code")
            if code == "FINISHED":
                break
            if code in ("ERROR", "EXPIRED"):
                print(f"⚠️ [IG REEL] Contenedor falló ({code}): {st}")
                return {"ok": False, "error": st}

        pub_res: Dict[str, Any] = {}
        for _ in range(4):
            pub_res = requests.post(
                f"https://graph.facebook.com/v20.0/{ig_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=30,
            ).json()
            if pub_res.get("id"):
                print(f"✅ [IG REEL] Publicado exitosamente en Instagram ({pub_res['id']}).")
                return {"ok": True, "media_id": pub_res["id"]}
            err_code = (pub_res.get("error") or {}).get("code")
            if err_code == 9007:
                time.sleep(8)
                continue
            break

        print(f"⚠️ [IG REEL] Error en media_publish: {pub_res}")
        return {"ok": False, "error": pub_res}
    except Exception as e:
        print(f"⚠️ [IG REEL] Excepción publicando en Instagram: {e}")
        return {"ok": False, "error": str(e)}


def publish_reel_to_meta(
    public_url: Optional[str],
    caption: str,
    mp4_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Despacha el Reel a Facebook Page Reels, Instagram Reels y TikTok Studio (si hay sesión activa)."""
    results: Dict[str, Any] = {}
    if mp4_path and Path(mp4_path).exists():
        results["facebook"] = publish_facebook_reel(mp4_path, caption)
    if public_url:
        results["instagram"] = publish_instagram_reel(public_url, caption)
    if mp4_path and Path(mp4_path).exists():
        try:
            from backend.tiktok_auto_uploader import publish_tiktok_video
            results["tiktok"] = publish_tiktok_video(mp4_path, caption)
        except Exception as e_tt:
            results["tiktok"] = {"ok": False, "error": str(e_tt)}
    return results


if __name__ == "__main__":
    pid = (os.getenv("FB_PAGE_ID") or "").strip()
    tok = _resolve_meta_token(pid)
    ig = _resolve_ig_user_id(pid, tok)
    r = requests.get(
        f"https://graph.facebook.com/v20.0/{pid}",
        params={"fields": "id,name", "access_token": tok},
        timeout=10,
    ).json() if pid and tok else {}
    print("META_CHECK:", {"page_id": pid, "ig_user_id": ig, "graph_status": r})

