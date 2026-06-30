"""Deposit chain configuration: monitored vs display-only."""
from app.config import get_settings
from app.services.deposit_secrets import is_deposit_mnemonic_configured

# Chains with on-chain deposit monitoring (auto-match settlement)
MONITORED_DEPOSIT_CHAINS = ("TRC20", "ERC20", "BEP20", "ARBITRUM", "POLYGON")

# EVM USDT contract, decimals, settings RPC attribute name
EVM_USDT_CONFIG: dict[str, tuple[str, int, str]] = {
    "ERC20": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6, "ETH_RPC_URL"),
    "BEP20": ("0x55d398326f99059fF775485246999027B3197955", 18, "BSC_RPC_URL"),
    "ARBITRUM": ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6, "ARBITRUM_RPC_URL"),
    "POLYGON": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6, "POLYGON_RPC_URL"),
}


def get_rpc_url(chain: str) -> str:
    cfg = EVM_USDT_CONFIG.get(chain.upper())
    if not cfg:
        return ""
    return getattr(get_settings(), cfg[2], "") or ""


def is_chain_monitored(chain: str) -> bool:
    return chain.upper() in MONITORED_DEPOSIT_CHAINS


def monitored_chains_status() -> list[dict]:
    """Return monitored chains with RPC/config readiness for admin health."""
    s = get_settings()
    out = []
    if is_deposit_mnemonic_configured():
        out.append({"chain": "TRC20", "monitored": True, "ready": bool(s.TRON_API_URL.strip())})
    else:
        return []
    for chain in ("ERC20", "BEP20", "ARBITRUM", "POLYGON"):
        rpc = get_rpc_url(chain)
        out.append({"chain": chain, "monitored": True, "ready": bool(rpc.strip())})
    return out
