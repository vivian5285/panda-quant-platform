"""Scan unique user deposit addresses and auto-match settlement payments."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session
from web3 import Web3

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    UserDepositAddress, SettlementDeposit, Settlement, PaymentStatus, User,
)
from app.services.settlement import submit_settlement_payment, get_pending_settlement

logger = logging.getLogger(__name__)
settings = get_settings()

USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_ERC20 = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()


def _headers_tron() -> dict:
    h = {"Accept": "application/json"}
    if settings.TRON_API_KEY.strip():
        h["TRON-PRO-API-KEY"] = settings.TRON_API_KEY.strip()
    return h


def _record_deposit(
    db: Session,
    user_id: int,
    chain: str,
    tx_hash: str,
    amount: float,
    from_address: str | None = None,
) -> SettlementDeposit | None:
    exists = db.query(SettlementDeposit).filter(SettlementDeposit.tx_hash == tx_hash).first()
    if exists:
        return None
    dep = SettlementDeposit(
        user_id=user_id,
        chain=chain,
        tx_hash=tx_hash,
        amount=round(amount, 6),
        from_address=from_address,
        status="detected",
    )
    db.add(dep)
    db.flush()
    return dep


def _try_match_settlement(db: Session, user: User, dep: SettlementDeposit) -> bool:
    pending = get_pending_settlement(db, user.id)
    if not pending or pending.payment_status not in (
        PaymentStatus.PENDING.value,
        PaymentStatus.REJECTED.value,
    ):
        return False
    payable = float(pending.user_payable or 0)
    if dep.amount + 0.01 < payable * 0.98:
        logger.info(
            "[DepositMonitor] user=%s amount=%.4f < payable=%.2f tx=%s",
            user.id, dep.amount, payable, dep.tx_hash,
        )
        return False

    submit_settlement_payment(
        db, pending, dep.chain, dep.tx_hash, min(dep.amount, payable),
    )
    dep.settlement_id = pending.id
    dep.status = "matched"
    dep.matched_at = datetime.utcnow()
    db.commit()

    from app.services.trade_logger import TradeLogger
    TradeLogger(db).log_event(
        user.id,
        "SETTLEMENT",
        f"检测到专属充值地址到账 ${dep.amount:.2f} USDT，已自动关联结算单 #{pending.id}",
        {"settlement_id": pending.id, "tx_hash": dep.tx_hash, "chain": dep.chain},
    )
    logger.info("[DepositMonitor] matched settlement #%s user=%s tx=%s", pending.id, user.id, dep.tx_hash)
    return True


def scan_trc20_deposits(db: Session) -> int:
    if not settings.DEPOSIT_HD_MNEMONIC.strip():
        return 0
    rows = db.query(UserDepositAddress).filter(UserDepositAddress.chain == "TRC20").all()
    if not rows:
        return 0

    matched = 0
    for row in rows:
        url = f"{settings.TRON_API_URL.rstrip('/')}/v1/accounts/{row.address}/transactions/trc20"
        try:
            resp = requests.get(
                url,
                params={"limit": 20, "contract_address": USDT_TRC20, "only_to": "true"},
                headers=_headers_tron(),
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
        except Exception as e:
            logger.warning("[DepositMonitor] TRC20 scan failed %s: %s", row.address[:12], e)
            continue

        for tx in data:
            if tx.get("token_info", {}).get("symbol") != "USDT":
                continue
            tx_hash = tx.get("transaction_id") or tx.get("txID")
            if not tx_hash:
                continue
            decimals = int(tx.get("token_info", {}).get("decimals", 6))
            raw = int(tx.get("value", 0))
            amount = raw / (10 ** decimals)
            from_addr = (tx.get("from") or "")[:128] or None

            user = db.query(User).filter(User.id == row.user_id).first()
            if not user:
                continue
            dep = _record_deposit(db, user.id, "TRC20", tx_hash, amount, from_addr)
            if not dep:
                continue
            db.commit()
            if _try_match_settlement(db, user, dep):
                matched += 1
    return matched


def _scan_evm_chain(db: Session, chain: str, rpc_url: str, usdt_contract: str) -> int:
    if not rpc_url.strip():
        return 0
    rows = db.query(UserDepositAddress).filter(UserDepositAddress.chain == chain).all()
    if not rows:
        return 0

    w3 = Web3(Web3.HTTPProvider(rpc_url.strip(), request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        logger.warning("[DepositMonitor] RPC not connected chain=%s", chain)
        return 0

    latest = w3.eth.block_number
    from_block = max(0, latest - settings.DEPOSIT_EVM_SCAN_BLOCKS)
    contract = Web3.to_checksum_address(usdt_contract)
    matched = 0

    addr_set = {Web3.to_checksum_address(r.address) for r in rows}
    addr_to_user = {Web3.to_checksum_address(r.address): r.user_id for r in rows}

    try:
        logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": latest,
            "address": contract,
            "topics": [TRANSFER_TOPIC],
        })
    except Exception as e:
        logger.warning("[DepositMonitor] EVM logs failed chain=%s: %s", chain, e)
        return 0

    decimals = 6 if chain == "ERC20" else 18
    for log in logs:
        if len(log["topics"]) < 3:
            continue
        to_addr = Web3.to_checksum_address("0x" + log["topics"][2].hex()[-40:])
        if to_addr not in addr_set:
            continue
        raw = int(log["data"].hex(), 16)
        amount = raw / (10 ** decimals)
        tx_hash = log["transactionHash"].hex()
        user_id = addr_to_user[to_addr]
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            continue
        dep = _record_deposit(db, user.id, chain, tx_hash, amount)
        if not dep:
            continue
        db.commit()
        if _try_match_settlement(db, user, dep):
            matched += 1
    return matched


def scan_all_deposits(db: Session) -> dict:
    stats = {"trc20": 0, "erc20": 0, "bep20": 0}
    stats["trc20"] = scan_trc20_deposits(db)
    stats["erc20"] = _scan_evm_chain(db, "ERC20", settings.ETH_RPC_URL, USDT_ERC20)
    stats["bep20"] = _scan_evm_chain(db, "BEP20", settings.BSC_RPC_URL, USDT_BEP20)
    return stats


def run_deposit_monitor_once() -> dict:
    db = SessionLocal()
    try:
        return scan_all_deposits(db)
    except Exception as e:
        logger.exception("[DepositMonitor] scan failed: %s", e)
        return {"error": str(e)}
    finally:
        db.close()
