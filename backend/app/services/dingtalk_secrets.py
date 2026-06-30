"""Encrypted DingTalk webhook config (admin-configurable, runtime file + env fallback)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()


def _dingtalk_block() -> dict:
    return read_runtime_file().get("dingtalk") or {}


def get_dingtalk_webhook() -> str:
    enc = _dingtalk_block().get("webhook")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt DingTalk webhook: %s", e)
    return settings.DINGTALK_WEBHOOK.strip()


def get_dingtalk_secret() -> str:
    enc = _dingtalk_block().get("secret")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt DingTalk secret: %s", e)
    return settings.DINGTALK_SECRET.strip()


def is_dingtalk_configured() -> bool:
    return bool(get_dingtalk_webhook())


def get_dingtalk_settings() -> dict:
    source = None
    if _dingtalk_block().get("webhook"):
        source = "runtime"
    elif settings.DINGTALK_WEBHOOK.strip():
        source = "env"
    return {
        "configured": is_dingtalk_configured(),
        "has_secret": bool(get_dingtalk_secret()),
        "source": source,
    }


def update_dingtalk_settings(
    *,
    webhook: str | None = None,
    secret: str | None = None,
    clear: bool = False,
) -> dict:
    data = read_runtime_file()
    block = dict(data.get("dingtalk") or {})

    if clear:
        block.clear()
    else:
        if webhook is not None:
            w = webhook.strip()
            if not w:
                raise ValueError("Webhook 不能为空")
            block["webhook"] = encrypt_text(w)
        if secret is not None:
            s = secret.strip()
            if s:
                block["secret"] = encrypt_text(s)
            else:
                block.pop("secret", None)

    data["dingtalk"] = block
    write_runtime_file(data)
    return get_dingtalk_settings()
