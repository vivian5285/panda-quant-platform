"""Encrypted TradingView webhook secret (admin-configurable, runtime file + env fallback)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.services.security_constants import INSECURE_SECRET_MARKERS
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()


def _webhook_block() -> dict:
    return read_runtime_file().get("webhook") or {}


def get_webhook_secret() -> str:
    enc = _webhook_block().get("secret")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt webhook secret: %s", e)
    return (settings.WEBHOOK_SECRET or "").strip()


def is_webhook_secret_configured() -> bool:
    return bool(get_webhook_secret())


def _secret_insecure(secret: str) -> bool:
    low = (secret or "").lower()
    if not secret or len(secret) < 12:
        return True
    return any(m in low for m in INSECURE_SECRET_MARKERS)


def get_webhook_public_url() -> str:
    base = (settings.API_PUBLIC_URL or "").rstrip("/")
    port = int(settings.WEBHOOK_PORT or 6010)
    if not base:
        return f"http://localhost:{port}/webhook"
    # If API_PUBLIC_URL already includes port, use as-is path only
    return f"{base}:{port}/webhook" if ":6010" not in base and port != 443 and port != 80 else f"{base}/webhook"


def get_webhook_settings() -> dict:
    secret = get_webhook_secret()
    source = None
    if _webhook_block().get("secret"):
        source = "runtime"
    elif settings.WEBHOOK_SECRET.strip():
        source = "env"
    preview = ""
    if len(secret) >= 4:
        preview = "*" * max(0, len(secret) - 4) + secret[-4:]
    elif secret:
        preview = "****"
    return {
        "configured": bool(secret),
        "secret_length": len(secret),
        "secret_preview": preview,
        "source": source,
        "webhook_url": get_webhook_public_url(),
        "insecure": _secret_insecure(secret),
        "min_length": 12,
    }


def update_webhook_settings(*, secret: str | None = None, clear: bool = False) -> dict:
    data = read_runtime_file()
    block = dict(data.get("webhook") or {})

    if clear:
        block.clear()
    elif secret is not None:
        s = secret.strip()
        if not s:
            raise ValueError("Webhook Secret 不能为空")
        if len(s) < 12:
            raise ValueError("Webhook Secret 至少 12 位")
        if _secret_insecure(s):
            raise ValueError("Secret 过于简单或为默认值，请使用随机字符串")
        block["secret"] = encrypt_text(s)

    data["webhook"] = block
    write_runtime_file(data)
    return get_webhook_settings()
