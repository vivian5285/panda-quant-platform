"""Chain RPC / Tron API config (admin UI + runtime file, env fallback)."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.services.platform_runtime import read_runtime_file, write_runtime_file
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()

EVM_RPC_FIELDS: dict[str, tuple[str, str]] = {
    "ERC20": ("eth_rpc_url", "ETH_RPC_URL"),
    "BEP20": ("bsc_rpc_url", "BSC_RPC_URL"),
    "ARBITRUM": ("arbitrum_rpc_url", "ARBITRUM_RPC_URL"),
    "POLYGON": ("polygon_rpc_url", "POLYGON_RPC_URL"),
}

DEFAULT_TRON_API_URL = "https://api.trongrid.io"


def _rpc_block() -> dict:
    return read_runtime_file().get("chain_rpc") or {}


def get_rpc_url(chain: str) -> str:
    chain = chain.upper()
    field_env = EVM_RPC_FIELDS.get(chain)
    if not field_env:
        return ""
    field, env_attr = field_env
    runtime = (_rpc_block().get(field) or "").strip()
    if runtime:
        return runtime
    return (getattr(settings, env_attr, "") or "").strip()


def get_tron_api_url() -> str:
    runtime = (_rpc_block().get("tron_api_url") or "").strip()
    if runtime:
        return runtime
    env = (settings.TRON_API_URL or "").strip()
    return env or DEFAULT_TRON_API_URL


def get_tron_api_key() -> str:
    enc = _rpc_block().get("tron_api_key")
    if enc:
        try:
            plain = decrypt_text(enc)
            if plain.strip():
                return plain.strip()
        except Exception as e:
            logger.warning("Failed to decrypt Tron API key: %s", e)
    return (settings.TRON_API_KEY or "").strip()


def _mask_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if len(u) <= 24:
        return u[:8] + "…"
    return u[:16] + "…" + u[-6:]


def get_chain_rpc_settings() -> dict:
    block = _rpc_block()
    chains: dict[str, dict] = {}
    for chain, (field, env_attr) in EVM_RPC_FIELDS.items():
        runtime_val = (block.get(field) or "").strip()
        env_val = (getattr(settings, env_attr, "") or "").strip()
        active = runtime_val or env_val
        if runtime_val:
            source = "runtime"
        elif env_val:
            source = "env"
        else:
            source = None
        chains[chain] = {
            "configured": bool(active),
            "source": source,
            "preview": _mask_url(active),
        }

    tron_runtime_url = (block.get("tron_api_url") or "").strip()
    tron_env_url = (settings.TRON_API_URL or "").strip()
    tron_key_runtime = bool(block.get("tron_api_key"))
    tron_key_env = bool((settings.TRON_API_KEY or "").strip())
    if tron_runtime_url or tron_key_runtime:
        tron_source = "runtime"
    elif tron_env_url or tron_key_env:
        tron_source = "env"
    else:
        tron_source = None

    return {
        "chains": chains,
        "tron_api_url_configured": bool(get_tron_api_url()),
        "tron_api_key_configured": bool(get_tron_api_key()),
        "tron_api_url_preview": _mask_url(get_tron_api_url()),
        "tron_source": tron_source,
        "has_runtime": bool(block),
    }


def update_chain_rpc_settings(
    *,
    rpc_urls: dict[str, str] | None = None,
    tron_api_url: str | None = None,
    tron_api_key: str | None = None,
    clear: bool = False,
) -> dict:
    data = read_runtime_file()
    block = dict(data.get("chain_rpc") or {})

    if clear:
        block.clear()
    else:
        if rpc_urls:
            for chain, url in rpc_urls.items():
                chain = chain.upper()
                field_env = EVM_RPC_FIELDS.get(chain)
                if not field_env:
                    continue
                field, _ = field_env
                url = (url or "").strip()
                if url:
                    block[field] = url
                else:
                    block.pop(field, None)
        if tron_api_url is not None:
            u = tron_api_url.strip()
            if u:
                block["tron_api_url"] = u
            else:
                block.pop("tron_api_url", None)
        if tron_api_key is not None:
            k = tron_api_key.strip()
            if k:
                block["tron_api_key"] = encrypt_text(k)
            else:
                block.pop("tron_api_key", None)

    data["chain_rpc"] = block
    write_runtime_file(data)
    return get_chain_rpc_settings()
