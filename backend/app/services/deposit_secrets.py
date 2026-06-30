"""Encrypted HD deposit mnemonic (admin-configurable, runtime file + env fallback)."""

from __future__ import annotations

import logging

from eth_account import Account

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()

Account.enable_unaudited_hdwallet_features()


def _deposit_block() -> dict:
    return read_runtime_file().get("deposit") or {}


def _validate_mnemonic(mnemonic: str) -> None:
    words = mnemonic.strip().split()
    if len(words) not in (12, 15, 18, 21, 24):
        raise ValueError("助记词须为 12/15/18/21/24 个单词")
    try:
        Account.from_mnemonic(mnemonic.strip(), account_path="m/44'/60'/0'/0/0")
    except Exception as e:
        raise ValueError(f"助记词格式无效: {e}") from e


def get_deposit_hd_mnemonic() -> str:
    """Runtime encrypted mnemonic takes precedence over DEPOSIT_HD_MNEMONIC env."""
    enc = _deposit_block().get("hd_mnemonic")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt deposit HD mnemonic: %s", e)
    return settings.DEPOSIT_HD_MNEMONIC.strip()


def is_deposit_mnemonic_configured() -> bool:
    return bool(get_deposit_hd_mnemonic())


def get_deposit_mnemonic_source() -> str | None:
    if _deposit_block().get("hd_mnemonic"):
        return "runtime"
    if settings.DEPOSIT_HD_MNEMONIC.strip():
        return "env"
    return None


def get_deposit_wallet_settings() -> dict:
    source = get_deposit_mnemonic_source()
    return {
        "configured": is_deposit_mnemonic_configured(),
        "source": source,
        "derivation_offset": settings.DEPOSIT_DERIVATION_OFFSET,
    }


def update_deposit_mnemonic(*, mnemonic: str | None = None, clear: bool = False) -> dict:
    data = read_runtime_file()
    deposit = dict(data.get("deposit") or {})

    if clear:
        deposit.pop("hd_mnemonic", None)
    elif mnemonic is not None:
        plain = mnemonic.strip()
        if not plain:
            raise ValueError("助记词不能为空")
        _validate_mnemonic(plain)
        deposit["hd_mnemonic"] = encrypt_text(plain)

    data["deposit"] = deposit
    write_runtime_file(data)
    return get_deposit_wallet_settings()
