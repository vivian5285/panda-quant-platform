"""Encrypted hot-wallet payout keys (admin-configurable, runtime file)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()

PAYOUT_CHAINS = ("TRC20", "ERC20", "BEP20", "ARBITRUM", "POLYGON")


def _payout_block() -> dict:
    return read_runtime_file().get("payout") or {}


def is_payout_auto_enabled() -> bool:
    block = _payout_block()
    if "auto_enabled" in block:
        return bool(block["auto_enabled"])
    return bool(settings.PAYOUT_AUTO_ENABLED)


def set_payout_auto_enabled(enabled: bool) -> bool:
    data = read_runtime_file()
    payout = dict(data.get("payout") or {})
    payout["auto_enabled"] = enabled
    data["payout"] = payout
    write_runtime_file(data)
    return enabled


def chain_key_configured(chain: str) -> bool:
    return bool(get_chain_private_key(chain))


def get_chain_private_key(chain: str) -> str:
    chain = chain.upper()
    block = _payout_block()
    keys = block.get("keys") or {}
    enc = keys.get(chain) or keys.get("EVM") if chain != "TRC20" else keys.get("TRC20")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt payout key for %s: %s", chain, e)

    if chain == "TRC20":
        return settings.PAYOUT_TRC20_PRIVATE_KEY.strip()
    if chain in PAYOUT_CHAINS:
        return settings.PAYOUT_EVM_PRIVATE_KEY.strip()
    return ""


def get_payout_keys_status() -> dict[str, bool]:
    return {chain: chain_key_configured(chain) for chain in PAYOUT_CHAINS}


def update_payout_keys(
    *,
    auto_enabled: bool | None = None,
    keys: dict[str, str] | None = None,
    clear_chains: list[str] | None = None,
) -> dict:
    data = read_runtime_file()
    payout = dict(data.get("payout") or {})
    keys_map = dict(payout.get("keys") or {})

    if keys:
        for chain, plain in keys.items():
            chain = chain.upper()
            if chain not in PAYOUT_CHAINS:
                continue
            plain = (plain or "").strip()
            if not plain:
                continue
            keys_map[chain] = encrypt_text(plain)

    if clear_chains:
        for chain in clear_chains:
            keys_map.pop(chain.upper(), None)

    payout["keys"] = keys_map
    if auto_enabled is not None:
        payout["auto_enabled"] = auto_enabled
    data["payout"] = payout
    write_runtime_file(data)
    return get_payout_settings()


def get_payout_settings() -> dict:
    return {
        "auto_enabled": is_payout_auto_enabled(),
        "chains": get_payout_keys_status(),
    }
