"""Sweep USDT from HD user deposit sub-addresses to admin cold wallet."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from web3 import Web3

from app.config import get_settings
from app.database import SessionLocal
from app.models import User, UserDepositAddress, SettlementDeposit, DepositSweepLog
from app.services.chain_payout import CHAIN_PAYOUT_CONFIG, ERC20_TRANSFER_ABI, _normalize_evm_key
from app.services.deposit_chains import MONITORED_DEPOSIT_CHAINS, get_rpc_url
from app.services.deposit_secrets import is_deposit_mnemonic_configured
from app.services.deposit_sweep_config import (
    get_cold_wallet,
    get_gas_funder_private_key,
    get_sweep_min_usdt,
    get_sweep_settings,
    is_sweep_auto_enabled,
)
from app.services.user_deposit_wallet import get_user_deposit_key_material

logger = logging.getLogger(__name__)
settings = get_settings()

BALANCE_OF_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]

TRC20_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# Per-chain native gas top-up (wei / sun). BSC/Polygon/L2 use lower amounts than ETH mainnet.
EVM_GAS_TOPUP_BY_CHAIN: dict[str, int] = {
    "ERC20": Web3.to_wei(0.002, "ether"),      # ~$5 on mainnet
    "BEP20": Web3.to_wei(0.0003, "ether"),   # ~0.3 BNB
    "ARBITRUM": Web3.to_wei(0.00015, "ether"),
    "POLYGON": Web3.to_wei(0.01, "ether"),    # ~0.01 MATIC
}
DEFAULT_EVM_GAS_TOPUP_WEI = Web3.to_wei(0.002, "ether")
TRON_GAS_TOPUP_SUN = 15_000_000  # 15 TRX


def _evm_gas_topup_wei(chain: str) -> int:
    return EVM_GAS_TOPUP_BY_CHAIN.get(chain.upper(), DEFAULT_EVM_GAS_TOPUP_WEI)


def _notify_sweep_result(db: Session, log: DepositSweepLog) -> None:
    if log.status not in ("success", "failed"):
        return
    try:
        from app.services.dingtalk_notify import push_sweep_alert

        user = db.query(User).filter(User.id == log.user_id).first()
        push_sweep_alert(
            success=log.status == "success",
            user_id=log.user_id,
            user_uid=user.uid if user else "",
            chain=log.chain,
            amount=log.amount,
            from_address=log.from_address,
            to_address=log.to_address,
            sweep_tx_hash=log.sweep_tx_hash,
            gas_tx_hash=log.gas_tx_hash,
            error_message=log.error_message,
        )
    except Exception as e:
        logger.warning("[Sweep] DingTalk notify failed: %s", e)


def _raw_to_amount(raw: int, decimals: int) -> float:
    return raw / (10 ** decimals)


def _recent_success_sweep(db: Session, from_address: str, chain: str) -> bool:
    since = datetime.utcnow() - timedelta(hours=6)
    row = (
        db.query(DepositSweepLog)
        .filter(
            DepositSweepLog.from_address == from_address,
            DepositSweepLog.chain == chain.upper(),
            DepositSweepLog.status == "success",
            DepositSweepLog.created_at >= since,
        )
        .first()
    )
    return row is not None


def _user_has_matched_deposit(db: Session, user_id: int, chain: str) -> bool:
    return db.query(SettlementDeposit).filter(
        SettlementDeposit.user_id == user_id,
        SettlementDeposit.chain == chain.upper(),
        SettlementDeposit.status == "matched",
    ).first() is not None


def _read_evm_usdt_balance(w3: Web3, contract_addr: str, holder: str, decimals: int) -> tuple[int, float]:
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_addr),
        abi=BALANCE_OF_ABI,
    )
    raw = contract.functions.balanceOf(Web3.to_checksum_address(holder)).call()
    return raw, _raw_to_amount(raw, decimals)


def _fund_evm_native(
    w3: Web3,
    funder_pk: str,
    to_address: str,
    amount_wei: int,
    *,
    min_balance_wei: int | None = None,
) -> str | None:
    threshold = min_balance_wei if min_balance_wei is not None else amount_wei // 2
    funder = w3.eth.account.from_key(_normalize_evm_key(funder_pk))
    balance = w3.eth.get_balance(Web3.to_checksum_address(to_address))
    if balance >= threshold:
        return None
    nonce = w3.eth.get_transaction_count(funder.address)
    tx = {
        "from": funder.address,
        "to": Web3.to_checksum_address(to_address),
        "value": amount_wei,
        "nonce": nonce,
        "gasPrice": w3.eth.gas_price,
        "chainId": w3.eth.chain_id,
        "gas": 21000,
    }
    signed = funder.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    hex_hash = tx_hash.hex()
    if not hex_hash.startswith("0x"):
        hex_hash = f"0x{hex_hash}"
    w3.eth.wait_for_transaction_receipt(hex_hash, timeout=120)
    logger.info("[Sweep] EVM gas funded %s wei to %s tx=%s", amount_wei, to_address, hex_hash)
    return hex_hash


def _sweep_evm_chain(
    db: Session,
    row: UserDepositAddress,
    chain: str,
    cold_address: str,
) -> DepositSweepLog | None:
    cfg = CHAIN_PAYOUT_CONFIG.get(chain.upper())
    if not cfg or cfg.get("kind") != "evm":
        return None

    keys = get_user_deposit_key_material(row.user_id)
    if not keys:
        return None

    rpc = cfg["rpc"](settings).strip()
    if not rpc:
        raise ValueError(f"{chain} RPC 未配置")

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        raise RuntimeError(f"无法连接 {chain} RPC")

    contract_addr = cfg["contract"]
    decimals = cfg["decimals"]
    from_addr = keys["evm_address"]
    amount_raw, amount_usd = _read_evm_usdt_balance(w3, contract_addr, from_addr, decimals)
    min_usdt = get_sweep_min_usdt()
    if amount_usd < min_usdt:
        return None

    log = DepositSweepLog(
        user_id=row.user_id,
        chain=chain.upper(),
        from_address=from_addr,
        to_address=cold_address,
        amount=round(amount_usd, 6),
        status="pending",
    )
    db.add(log)
    db.flush()

    try:
        funder_pk = get_gas_funder_private_key(chain)
        if not funder_pk:
            raise ValueError(f"{chain} Gas 资助钱包未配置")

        gas_wei = _evm_gas_topup_wei(chain)
        gas_tx = _fund_evm_native(
            w3, funder_pk, from_addr, gas_wei, min_balance_wei=gas_wei // 2,
        )
        if gas_tx:
            log.gas_tx_hash = gas_tx

        sub_acct = w3.eth.account.from_key(_normalize_evm_key(keys["evm_private_key"]))
        usdt = w3.eth.contract(
            address=Web3.to_checksum_address(contract_addr),
            abi=ERC20_TRANSFER_ABI,
        )
        nonce = w3.eth.get_transaction_count(sub_acct.address)
        tx = usdt.functions.transfer(
            Web3.to_checksum_address(cold_address),
            amount_raw,
        ).build_transaction({
            "from": sub_acct.address,
            "nonce": nonce,
            "gasPrice": w3.eth.gas_price,
            "chainId": cfg["chain_id"],
        })
        tx["gas"] = w3.eth.estimate_gas(tx)
        signed = sub_acct.sign_transaction(tx)
        sweep_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        hex_hash = sweep_hash.hex()
        if not hex_hash.startswith("0x"):
            hex_hash = f"0x{hex_hash}"

        log.sweep_tx_hash = hex_hash
        log.status = "success"
        logger.info(
            "[Sweep] %s swept $%.4f USDT user=%s from=%s tx=%s",
            chain, amount_usd, row.user_id, from_addr[:12], hex_hash,
        )
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)[:500]
        logger.warning("[Sweep] EVM %s user=%s failed: %s", chain, row.user_id, e)

    db.commit()
    db.refresh(log)
    _notify_sweep_result(db, log)
    return log


def _read_trc20_balance(address: str) -> tuple[int, float]:
    import requests

    url = f"{settings.TRON_API_URL.rstrip('/')}/v1/accounts/{address}"
    headers = {"Accept": "application/json"}
    if settings.TRON_API_KEY.strip():
        headers["TRON-PRO-API-KEY"] = settings.TRON_API_KEY.strip()
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    if not data:
        return 0, 0.0
    for item in data[0].get("trc20") or []:
        if isinstance(item, dict) and TRC20_USDT in item:
            raw = int(item[TRC20_USDT])
            return raw, _raw_to_amount(raw, 6)
    return 0, 0.0


def _fund_tron_trx(
    client,
    funder_pk_hex: str,
    to_address: str,
    amount_sun: int,
    *,
    min_balance_sun: int | None = None,
) -> str | None:
    from tronpy.keys import PrivateKey

    threshold = min_balance_sun if min_balance_sun is not None else amount_sun // 2
    if funder_pk_hex.startswith("0x"):
        funder_pk_hex = funder_pk_hex[2:]
    funder = PrivateKey(bytes.fromhex(funder_pk_hex))
    acct = client.get_account(to_address)
    balance = acct.get("balance", 0)
    if balance >= threshold:
        return None

    txn = (
        client.trx.transfer(funder.public_key.to_base58check_address(), to_address, amount_sun)
        .build()
        .sign(funder)
    )
    result = txn.broadcast()
    if not result.get("result"):
        raise RuntimeError(f"TRX fund failed: {result}")
    txid = result.get("txid") or txn.txid
    logger.info("[Sweep] TRX funded %s sun to %s tx=%s", amount_sun, to_address, txid)
    return txid


def _sweep_trc20(db: Session, row: UserDepositAddress, cold_address: str) -> DepositSweepLog | None:
    from tronpy import Tron
    from tronpy.keys import PrivateKey
    from tronpy.providers import HTTPProvider

    keys = get_user_deposit_key_material(row.user_id)
    if not keys:
        return None

    provider_url = settings.TRON_API_URL.strip() or "https://api.trongrid.io"
    api_key = settings.TRON_API_KEY.strip()
    if api_key:
        client = Tron(HTTPProvider(provider_url, api_key=api_key))
    else:
        client = Tron(HTTPProvider(provider_url))

    from_addr = keys["tron_address"]
    amount_raw, amount_usd = _read_trc20_balance(from_addr)
    if amount_usd < get_sweep_min_usdt():
        return None

    log = DepositSweepLog(
        user_id=row.user_id,
        chain="TRC20",
        from_address=from_addr,
        to_address=cold_address,
        amount=round(amount_usd, 6),
        status="pending",
    )
    db.add(log)
    db.flush()

    try:
        funder_pk = get_gas_funder_private_key("TRC20")
        if not funder_pk:
            raise ValueError("TRC20 Gas 资助钱包未配置")

        pk_hex = keys["tron_private_key_hex"]
        gas_tx = _fund_tron_trx(
            client, funder_pk, from_addr, TRON_GAS_TOPUP_SUN,
            min_balance_sun=TRON_GAS_TOPUP_SUN // 2,
        )
        if gas_tx:
            log.gas_tx_hash = gas_tx

        priv = PrivateKey(bytes.fromhex(pk_hex))
        contract = client.get_contract(TRC20_USDT)
        txn = (
            contract.functions.transfer(cold_address, amount_raw)
            .with_owner(from_addr)
            .fee_limit(50_000_000)
            .build()
            .sign(priv)
        )
        result = txn.broadcast()
        if not result.get("result"):
            raise RuntimeError(f"TRC20 sweep broadcast failed: {result}")
        txid = result.get("txid") or txn.txid
        log.sweep_tx_hash = txid
        log.status = "success"
        logger.info("[Sweep] TRC20 swept $%.4f user=%s tx=%s", amount_usd, row.user_id, txid)
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)[:500]
        logger.warning("[Sweep] TRC20 user=%s failed: %s", row.user_id, e)

    db.commit()
    db.refresh(log)
    _notify_sweep_result(db, log)
    return log


def sweep_deposit_address(db: Session, row: UserDepositAddress) -> DepositSweepLog | None:
    """Attempt sweep for one UserDepositAddress row."""
    chain = row.chain.upper()
    cold = get_cold_wallet(chain)
    if not cold:
        return None
    if not get_gas_funder_private_key(chain):
        return None

    if _recent_success_sweep(db, row.address, chain):
        return None

    block = get_sweep_settings()
    if block.get("require_matched_deposit", True):
        if not _user_has_matched_deposit(db, row.user_id, chain):
            return None

    if chain == "TRC20":
        return _sweep_trc20(db, row, cold)
    if chain in MONITORED_DEPOSIT_CHAINS and CHAIN_PAYOUT_CONFIG.get(chain, {}).get("kind") == "evm":
        return _sweep_evm_chain(db, row, chain, cold)
    return None


def run_deposit_sweep(db: Session, *, force: bool = False) -> dict:
    """Scan all user deposit addresses and sweep USDT to cold wallets."""
    stats = {"scanned": 0, "swept": 0, "skipped": 0, "failed": 0, "errors": []}

    if not is_deposit_mnemonic_configured():
        stats["errors"].append("deposit mnemonic not configured")
        return stats

    if not force and not is_sweep_auto_enabled():
        stats["errors"].append("auto sweep disabled")
        return stats

    ready = get_sweep_settings().get("ready_chains") or []
    if not ready:
        stats["errors"].append("no chain ready (cold wallet + gas funder + RPC)")
        return stats

    rows = db.query(UserDepositAddress).order_by(UserDepositAddress.user_id, UserDepositAddress.chain).all()
    seen: set[tuple[int, str]] = set()

    for row in rows:
        key = (row.user_id, row.chain.upper())
        if key in seen:
            continue
        seen.add(key)
        if row.chain.upper() not in ready:
            continue

        stats["scanned"] += 1
        try:
            result = sweep_deposit_address(db, row)
            if result is None:
                stats["skipped"] += 1
            elif result.status == "success":
                stats["swept"] += 1
            else:
                stats["failed"] += 1
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"user={row.user_id} chain={row.chain}: {e}")
            logger.exception("[Sweep] unexpected error user=%s chain=%s", row.user_id, row.chain)

    return stats


def run_deposit_sweep_once(*, force: bool = False) -> dict:
    db = SessionLocal()
    try:
        return run_deposit_sweep(db, force=force)
    finally:
        db.close()
