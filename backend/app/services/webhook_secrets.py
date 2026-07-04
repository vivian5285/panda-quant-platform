"""Encrypted TradingView webhook secret (admin-configurable, runtime file + env fallback)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
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


def _normalize_public_path(path: str) -> str:
    p = (path or "/gemini/webhook").strip()
    return p if p.startswith("/") else f"/{p}"


def get_webhook_public_url() -> str:
    """Public TV alert URL — production uses https://twinstar.pro/gemini/webhook via nginx."""
    path = _normalize_public_path(settings.WEBHOOK_PUBLIC_PATH)
    base = (settings.API_PUBLIC_URL or "").strip().rstrip("/")
    if base and not base.startswith("http://0000"):
        parsed = urlparse(base)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{path}"

    domain = (settings.PLATFORM_DOMAIN or "").strip()
    if domain:
        return f"https://{domain}{path}"

    port = int(settings.WEBHOOK_PORT or 6010)
    return f"http://127.0.0.1:{port}/webhook"


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
    configured = bool(secret)
    return {
        "configured": configured,
        "production_ready": configured,
        "secret_length": len(secret),
        "secret_preview": preview,
        "source": source,
        "webhook_url": get_webhook_public_url(),
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
        block["secret"] = encrypt_text(s)

    data["webhook"] = block
    write_runtime_file(data)
    return get_webhook_settings()
