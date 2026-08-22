"""Optional generic artwork for the deterministic social banner."""

from __future__ import annotations

import base64
from binascii import Error as Base64Error
from io import BytesIO
import logging
import re
from typing import Any

from PIL import Image, ImageEnhance, UnidentifiedImageError


LOGGER = logging.getLogger(__name__)


class _CloudflareBackgroundError(Exception):
    """Internal sentinel whose message is never logged."""


class CloudflareBackgroundProvider:
    """Return a normalized generic background or a local-fallback signal."""

    MODEL = "@cf/black-forest-labs/flux-2-dev"
    PROMPT = (
        "text-free, logo-free, generic sports atmosphere, cinematic empty "
        "arena lighting, abstract dark navy and warm gold ambience, no people, "
        "no uniforms, no brands, no emblems, no letters, no numbers"
    )
    _ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]+$")

    def __init__(self, *, account_id: str, api_token: str, session: object) -> None:
        """Store injected configuration without making a request."""

        self._account_id = account_id.strip() if isinstance(account_id, str) else ""
        self._api_token = api_token.strip() if isinstance(api_token, str) else ""
        self._session = session

    def create(self) -> bytes | None:
        """Return a safe square bitmap, or ``None`` for the local fallback."""

        if (
            not self._account_id
            or not self._api_token
            or self._ACCOUNT_ID.fullmatch(self._account_id) is None
        ):
            return None

        try:
            post = getattr(self._session, "post")
            response = post(
                (
                    "https://api.cloudflare.com/client/v4/accounts/"
                    f"{self._account_id}/ai/run/{self.MODEL}"
                ),
                headers={"Authorization": f"Bearer {self._api_token}"},
                files={
                    "prompt": (None, self.PROMPT),
                    "width": (None, "1080"),
                    "height": (None, "1080"),
                },
                timeout=20,
            )
            if getattr(response, "status_code", None) != 200:
                raise _CloudflareBackgroundError
            payload = response.json()
            encoded = self._encoded_image(payload)
            raw = base64.b64decode(encoded, validate=True)
            return self._normalize(raw)
        except Exception as exc:
            LOGGER.info(
                "cloudflare_background status=fallback exception=%s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _encoded_image(payload: Any) -> str:
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise _CloudflareBackgroundError
        result = payload.get("result")
        if not isinstance(result, dict):
            raise _CloudflareBackgroundError
        encoded = result.get("image")
        if not isinstance(encoded, str) or not encoded:
            raise _CloudflareBackgroundError
        return encoded

    @staticmethod
    def _normalize(raw: bytes) -> bytes:
        try:
            with Image.open(BytesIO(raw)) as source:
                source.load()
                if source.width < 512 or source.height < 512:
                    raise _CloudflareBackgroundError
                side = min(source.size)
                left = (source.width - side) // 2
                top = (source.height - side) // 2
                square = source.crop((left, top, left + side, top + side))
                square = square.resize((1080, 1080), Image.Resampling.LANCZOS)
                rgb = square.convert("RGB")
                darkened = ImageEnhance.Brightness(rgb).enhance(0.35)
                output = BytesIO()
                darkened.save(output, format="JPEG", quality=90)
                return output.getvalue()
        except (OSError, UnidentifiedImageError, ValueError, Base64Error):
            raise _CloudflareBackgroundError from None
