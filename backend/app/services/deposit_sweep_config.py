"""Cold wallet & auto-sweep configuration (admin runtime file)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.deposit_chains import MONITORED_DEPOSIT_CHAINS, get_rpc_url, get_tron_api_url
from app.services.deposit_secrets import is_deposit_mnemonic_configured
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.services.payout_secrets import get_chain_private_key
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()

SWEEP_CHAINS = MONITORED_DEPOSIT_CHAINS


def _sweep_block() -> dict:
    return read_runtime_file().get("sweep") or {}


def _decrypt_key(enc: str | None) -> str:
    if not enc:
        return ""
    try:
        return decrypt_text(enc).strip()
    except Exception as e:
        logger.warning("Failed to decrypt sweep key: %s", e)
        return ""


def get_gas_funder_private_key(chain: str) -> str:
    """Gas funder for sub-address sweeps; falls back to payout hot wallet key."""
    chain = chain.upper()
    block = _sweep_block()
    keys = block.get("gas_funder_keys") or {}
    enc = keys.get(chain) or keys.get("EVM") if chain != "TRC20" else keys.get("TRC20")
    plain = _decrypt_key(enc)
    if plain:
        return plain
    return get_chain_private_key(chain)


def is_sweep_auto_enabled() -> bool:
    block = _sweep_block()
    if "auto_enabled" in block:
        return bool(block["auto_enabled"])
    return bool(getattr(settings, "DEPOSIT_SWEEP_AUTO_ENABLED", False))


def get_sweep_min_usdt() -> float:
    block = _sweep_block()
    if "min_usdt" in block:
        return float(block["min_usdt"])
    return float(getattr(settings, "DEPOSIT_SWEEP_MIN_USDT", 1.0))


def get_cold_wallet(chain: str) -> str:
    chain = chain.upper()
    block = _sweep_block()
    wallets = block.get("cold_wallets") or {}
    return (wallets.get(chain) or "").strip()


def get_sweep_settings() -> dict:
    cold = {c: bool(get_cold_wallet(c)) for c in SWEEP_CHAINS}
    gas = {c: bool(get_gas_funder_private_key(c)) for c in SWEEP_CHAINS}
    rpc_ready = {
        c: bool(get_rpc_url(c).strip()) if c != "TRC20" else bool(get_tron_api_url().strip())
        for c in SWEEP_CHAINS
    }
    return {
        "auto_enabled": is_sweep_auto_enabled(),
        "min_usdt": get_sweep_min_usdt(),
        "require_matched_deposit": bool(_sweep_block().get("require_matched_deposit", True)),
        "mnemonic_configured": is_deposit_mnemonic_configured(),
        "cold_wallets": {c: get_cold_wallet(c) for c in SWEEP_CHAINS},
        "cold_wallets_configured": cold,
        "gas_funder_configured": gas,
        "rpc_ready": rpc_ready,
        "ready_chains": [
            c for c in SWEEP_CHAINS
            if cold.get(c) and gas.get(c) and rpc_ready.get(c) and is_deposit_mnemonic_configured()
        ],
    }


def update_sweep_settings(
    *,
    auto_enabled: bool | None = None,
    min_usdt: float | None = None,
    require_matched_deposit: bool | None = None,
    cold_wallets: dict[str, str] | None = None,
    gas_funder_keys: dict[str, str] | None = None,
    clear_gas_funder: bool = False,
) -> dict:
    data = read_runtime_file()
    sweep = dict(data.get("sweep") or {})

    if auto_enabled is not None:
        sweep["auto_enabled"] = auto_enabled
    if min_usdt is not None:
        if min_usdt <= 0:
            raise ValueError("min_usdt 必须大于 0")
        sweep["min_usdt"] = round(min_usdt, 2)
    if require_matched_deposit is not None:
        sweep["require_matched_deposit"] = require_matched_deposit

    if cold_wallets:
        cw = dict(sweep.get("cold_wallets") or {})
        for chain, addr in cold_wallets.items():
            chain = chain.upper()
            if chain not in SWEEP_CHAINS:
                continue
            addr = (addr or "").strip()
            if addr:
                cw[chain] = addr
        sweep["cold_wallets"] = cw

    keys_map = dict(sweep.get("gas_funder_keys") or {})
    if clear_gas_funder:
        keys_map.clear()
    if gas_funder_keys:
        for chain, plain in gas_funder_keys.items():
            chain = chain.upper()
            if chain not in SWEEP_CHAINS and chain != "EVM":
                continue
            plain = (plain or "").strip()
            if not plain:
                continue
            store_key = "EVM" if chain in ("ERC20", "BEP20", "ARBITRUM", "POLYGON") else chain
            keys_map[store_key] = encrypt_text(plain)
    sweep["gas_funder_keys"] = keys_map

    data["sweep"] = sweep
    write_runtime_file(data)
    return get_sweep_settings()
