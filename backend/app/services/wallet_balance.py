"""On-chain USDT + native balance reads for admin wallet overview."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from web3 import Web3

from app.config import get_settings
from app.services.chain_payout import CHAIN_PAYOUT_CONFIG, _normalize_evm_key
from app.services.deposit_chains import EVM_USDT_CONFIG, MONITORED_DEPOSIT_CHAINS, get_rpc_url
from app.services.chain_rpc_config import get_tron_api_url, get_tron_api_key
from app.services.deposit_sweep import (
    BALANCE_OF_ABI,
    TRC20_USDT,
    _evm_gas_topup_wei,
    _raw_to_amount,
    TRON_GAS_TOPUP_SUN,
)

logger = logging.getLogger(__name__)
settings = get_settings()

NATIVE_SYMBOLS: dict[str, str] = {
    "TRC20": "TRX",
    "ERC20": "ETH",
    "BEP20": "BNB",
    "ARBITRUM": "ETH",
    "POLYGON": "MATIC",
}

TRC20_USDT_CONTRACT = TRC20_USDT


@dataclass
class AddressBalance:
    chain: str
    address: str
    usdt: float | None = None
    native: float | None = None
    native_symbol: str = ""
    rpc_ready: bool = False
    error: str | None = None
    gas_topup_hint: str | None = None
    native_low: bool = False

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "address": self.address,
            "usdt": self.usdt,
            "native": self.native,
            "native_symbol": self.native_symbol,
            "rpc_ready": self.rpc_ready,
            "error": self.error,
            "gas_topup_hint": self.gas_topup_hint,
            "native_low": self.native_low,
        }


def _gas_topup_hint(chain: str) -> str:
    chain = chain.upper()
    sym = NATIVE_SYMBOLS.get(chain, "")
    if chain == "TRC20":
        return f"{TRON_GAS_TOPUP_SUN / 1_000_000:.0f} {sym}/次归集"
    if chain in EVM_USDT_CONFIG:
        wei = _evm_gas_topup_wei(chain)
        amt = float(Web3.from_wei(wei, "ether"))
        return f"{amt:g} {sym}/次归集"
    return ""


def derive_evm_address(private_key: str) -> str:
    w3 = Web3()
    acct = w3.eth.account.from_key(_normalize_evm_key(private_key))
    return acct.address


def derive_tron_address(private_key: str) -> str:
    from tronpy.keys import PrivateKey

    key_hex = private_key.strip()
    if key_hex.startswith("0x"):
        key_hex = key_hex[2:]
    return PrivateKey(bytes.fromhex(key_hex)).public_key.to_base58check_address()


def _evm_w3(chain: str) -> Web3 | None:
    cfg = CHAIN_PAYOUT_CONFIG.get(chain.upper())
    if not cfg or cfg.get("kind") != "evm":
        return None
    rpc = get_rpc_url(chain).strip()
    if not rpc:
        return None
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    return w3 if w3.is_connected() else None


def _read_evm_usdt(w3: Web3, chain: str, holder: str) -> float:
    cfg = CHAIN_PAYOUT_CONFIG[chain.upper()]
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(cfg["contract"]),
        abi=BALANCE_OF_ABI,
    )
    raw = contract.functions.balanceOf(Web3.to_checksum_address(holder)).call()
    return _raw_to_amount(raw, cfg["decimals"])


def _tron_headers() -> dict:
    headers = {"Accept": "application/json"}
    key = get_tron_api_key()
    if key:
        headers["TRON-PRO-API-KEY"] = key
    return headers


def _read_tron_usdt(address: str) -> float:
    url = f"{get_tron_api_url().rstrip('/')}/v1/accounts/{address}"
    resp = requests.get(url, headers=_tron_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    if not data:
        return 0.0
    for item in data[0].get("trc20") or []:
        if isinstance(item, dict) and TRC20_USDT_CONTRACT in item:
            return _raw_to_amount(int(item[TRC20_USDT_CONTRACT]), 6)
    return 0.0


def _read_tron_native(address: str) -> float:
    url = f"{get_tron_api_url().rstrip('/')}/v1/accounts/{address}"
    resp = requests.get(url, headers=_tron_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    if not data:
        return 0.0
    return (data[0].get("balance") or 0) / 1_000_000


def _native_low(chain: str, native: float | None) -> bool:
    if native is None:
        return False
    chain = chain.upper()
    if chain == "TRC20":
        return native < (TRON_GAS_TOPUP_SUN / 1_000_000) * 3
    if chain in EVM_USDT_CONFIG:
        wei = _evm_gas_topup_wei(chain)
        threshold = float(Web3.from_wei(wei, "ether")) * 3
        return native < threshold
    return False


def fetch_address_balance(chain: str, address: str) -> AddressBalance:
    """Read USDT + native balance for a single address on a supported chain."""
    chain = chain.upper()
    address = (address or "").strip()
    sym = NATIVE_SYMBOLS.get(chain, "")
    hint = _gas_topup_hint(chain)

    if not address:
        return AddressBalance(chain=chain, address="", native_symbol=sym, gas_topup_hint=hint)

    try:
        if chain == "TRC20":
            if not get_tron_api_url().strip():
                return AddressBalance(
                    chain=chain, address=address, native_symbol=sym,
                    gas_topup_hint=hint, rpc_ready=False, error="TRON_API_URL 未配置",
                )
            usdt = _read_tron_usdt(address)
            native = _read_tron_native(address)
            bal = AddressBalance(
                chain=chain, address=address, usdt=round(usdt, 4), native=round(native, 6),
                native_symbol=sym, rpc_ready=True, gas_topup_hint=hint,
            )
            bal.native_low = _native_low(chain, native)
            return bal

        if chain in MONITORED_DEPOSIT_CHAINS and chain in EVM_USDT_CONFIG:
            w3 = _evm_w3(chain)
            if not w3:
                return AddressBalance(
                    chain=chain, address=address, native_symbol=sym,
                    gas_topup_hint=hint, rpc_ready=False, error=f"{chain} RPC 不可用",
                )
            usdt = _read_evm_usdt(w3, chain, address)
            native_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
            native = float(Web3.from_wei(native_wei, "ether"))
            bal = AddressBalance(
                chain=chain, address=address, usdt=round(usdt, 4), native=round(native, 8),
                native_symbol=sym, rpc_ready=True, gas_topup_hint=hint,
            )
            bal.native_low = _native_low(chain, native)
            return bal

        return AddressBalance(
            chain=chain, address=address, native_symbol=sym,
            error="该链暂不支持链上余额查询",
        )
    except Exception as e:
        logger.warning("[WalletBalance] %s %s failed: %s", chain, address[:12], e)
        return AddressBalance(
            chain=chain, address=address, native_symbol=sym,
            gas_topup_hint=hint, error=str(e)[:200],
        )
