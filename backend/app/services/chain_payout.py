"""On-chain USDT payout from platform hot wallet."""
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.services.payout_secrets import get_chain_private_key, is_payout_auto_enabled
from app.services.chain_rpc_config import get_rpc_url, get_tron_api_url, get_tron_api_key

logger = logging.getLogger(__name__)
settings = get_settings()

ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    }
]

TRC20_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

CHAIN_PAYOUT_CONFIG: dict[str, dict] = {
    "TRC20": {"kind": "tron", "contract": TRC20_USDT, "decimals": 6},
    "ERC20": {
        "kind": "evm",
        "contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
        "rpc": lambda s: s.ETH_RPC_URL,
        "chain_id": 1,
    },
    "BEP20": {
        "kind": "evm",
        "contract": "0x55d398326f99059fF775485246999027B3197955",
        "decimals": 18,
        "rpc": lambda s: s.BSC_RPC_URL,
        "chain_id": 56,
    },
    "ARBITRUM": {
        "kind": "evm",
        "contract": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
        "decimals": 6,
        "rpc": lambda s: s.ARBITRUM_RPC_URL,
        "chain_id": 42161,
    },
    "POLYGON": {
        "kind": "evm",
        "contract": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "decimals": 6,
        "rpc": lambda s: s.POLYGON_RPC_URL,
        "chain_id": 137,
    },
}


@dataclass
class PayoutStatus:
    enabled: bool
    configured_chains: list[str]
    missing_chains: list[str]


def _amount_to_raw(amount: float, decimals: int) -> int:
    return int(round(amount * (10 ** decimals)))


def get_payout_status() -> PayoutStatus:
    configured: list[str] = []
    missing: list[str] = []
    for chain, cfg in CHAIN_PAYOUT_CONFIG.items():
        if _chain_ready(chain, cfg):
            configured.append(chain)
        else:
            missing.append(chain)
    return PayoutStatus(
        enabled=is_payout_auto_enabled(),
        configured_chains=configured,
        missing_chains=missing,
    )


def _resolve_private_key(chain: str) -> str:
    chain = chain.upper()
    key = get_chain_private_key(chain)
    if key:
        return key
    if chain == "TRC20":
        return settings.PAYOUT_TRC20_PRIVATE_KEY.strip()
    return settings.PAYOUT_EVM_PRIVATE_KEY.strip()


def _chain_ready(chain: str, cfg: dict | None = None) -> bool:
    cfg = cfg or CHAIN_PAYOUT_CONFIG.get(chain.upper(), {})
    kind = cfg.get("kind")
    if kind == "tron":
        return bool(_resolve_private_key(chain).strip())
    if kind == "evm":
        rpc = get_rpc_url(chain)
        return bool(_resolve_private_key(chain).strip() and rpc.strip())
    return False


def execute_usdt_payout(chain: str, to_address: str, amount_net: float) -> str:
    """Send USDT on-chain; returns transaction hash."""
    chain = chain.upper()
    cfg = CHAIN_PAYOUT_CONFIG.get(chain)
    if not cfg:
        raise ValueError(f"Auto payout not supported for chain {chain}")

    if not settings.PAYOUT_AUTO_ENABLED and not is_payout_auto_enabled():
        raise ValueError("Auto payout is disabled (PAYOUT_AUTO_ENABLED=false)")

    if not _chain_ready(chain, cfg):
        raise ValueError(f"Hot wallet not configured for {chain}")

    amount_raw = _amount_to_raw(amount_net, cfg["decimals"])
    if amount_raw <= 0:
        raise ValueError("Payout amount too small")

    if cfg["kind"] == "tron":
        return _payout_trc20(to_address.strip(), amount_raw)
    if cfg["kind"] == "evm":
        return _payout_evm(chain, cfg, to_address.strip(), amount_raw)
    raise ValueError(f"Unsupported payout kind for {chain}")


def _normalize_evm_key(private_key: str) -> str:
    key = private_key.strip()
    if key.startswith("0x"):
        return key
    return f"0x{key}"


def _payout_trc20(to_address: str, amount_raw: int) -> str:
    from tronpy import Tron
    from tronpy.keys import PrivateKey
    from tronpy.providers import HTTPProvider

    key_hex = _resolve_private_key("TRC20")
    if key_hex.startswith("0x"):
        key_hex = key_hex[2:]

    provider_url = get_tron_api_url()
    api_key = get_tron_api_key()
    if api_key:
        client = Tron(HTTPProvider(provider_url, api_key=api_key))
    else:
        client = Tron(HTTPProvider(provider_url))
    priv_key = PrivateKey(bytes.fromhex(key_hex))
    contract = client.get_contract(TRC20_USDT)
    txn = (
        contract.functions.transfer(to_address, amount_raw)
        .with_owner(priv_key.public_key.to_base58check_address())
        .fee_limit(50_000_000)
        .build()
        .sign(priv_key)
    )
    result = txn.broadcast()
    if not result.get("result"):
        raise RuntimeError(f"TRC20 broadcast failed: {result}")
    txid = result.get("txid") or txn.txid
    if not txid:
        raise RuntimeError("TRC20 broadcast returned no txid")
    logger.info("TRC20 payout sent txid=%s to=%s amount_raw=%s", txid, to_address, amount_raw)
    return txid


def _payout_evm(chain: str, cfg: dict, to_address: str, amount_raw: int) -> str:
    from web3 import Web3

    rpc_url = get_rpc_url(chain).strip()
    if not rpc_url:
        raise ValueError(f"RPC URL not configured for {chain}")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"Cannot connect to {chain} RPC")

    private_key = _resolve_private_key(chain)
    account = w3.eth.account.from_key(_normalize_evm_key(private_key))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(cfg["contract"]),
        abi=ERC20_TRANSFER_ABI,
    )
    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    tx = contract.functions.transfer(
        Web3.to_checksum_address(to_address),
        amount_raw,
    ).build_transaction({
        "from": account.address,
        "nonce": nonce,
        "gasPrice": gas_price,
        "chainId": cfg["chain_id"],
    })
    tx["gas"] = w3.eth.estimate_gas(tx)
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    hex_hash = tx_hash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = f"0x{hex_hash}"
    logger.info("%s payout sent tx=%s to=%s amount_raw=%s", chain, hex_hash, to_address, amount_raw)
    return hex_hash
