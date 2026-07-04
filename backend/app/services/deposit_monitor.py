"""Scan unique user deposit addresses and auto-match settlement payments."""
from __future__ import annotations

import logging
from datetime import datetime

import requests
from sqlalchemy.orm import Session
from web3 import Web3

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    UserDepositAddress, SettlementDeposit, Settlement, PaymentStatus, User,
)
from app.services.settlement import submit_settlement_payment, get_pending_settlement, confirm_settlement_payment
from app.services.deposit_monitor_state import record_scan_result, get_deposit_monitor_status
from app.services.deposit_chains import EVM_USDT_CONFIG, get_rpc_url, MONITORED_DEPOSIT_CHAINS
from app.services.chain_rpc_config import get_tron_api_url, get_tron_api_key
from app.services.deposit_secrets import is_deposit_mnemonic_configured

logger = logging.getLogger(__name__)
settings = get_settings()

USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()


def _headers_tron() -> dict:
    h = {"Accept": "application/json"}
    key = get_tron_api_key()
    if key:
        h["TRON-PRO-API-KEY"] = key
    return h


def _record_deposit(
    db: Session,
    user_id: int,
    chain: str,
    tx_hash: str,
    amount: float,
    from_address: str | None = None,
    deposit_address: str | None = None,
    source: str = "auto",
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
        deposit_address=deposit_address,
        source=source,
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

    try:
        submit_settlement_payment(
            db, pending, dep.chain, dep.tx_hash, min(dep.amount, payable),
        )
    except ValueError as e:
        logger.warning("[DepositMonitor] match blocked tx=%s: %s", dep.tx_hash, e)
        return False

    dep.settlement_id = pending.id
    dep.status = "matched"
    dep.matched_at = datetime.utcnow()

    auto_confirmed = False
    if settings.SETTLEMENT_AUTO_CONFIRM:
        db.refresh(pending)
        confirm_settlement_payment(db, pending, admin_note="auto-deposit-detect")
        auto_confirmed = True
    else:
        db.commit()

    from app.services.trade_logger import TradeLogger
    msg = (
        f"检测到专属充值地址到账 ${dep.amount:.2f} USDT，结算单 #{pending.id} 已确认，本金已重置"
        if auto_confirmed
        else f"检测到专属充值地址到账 ${dep.amount:.2f} USDT，已自动关联结算单 #{pending.id}"
    )
    TradeLogger(db).log_event(
        user.id,
        "SETTLEMENT",
        msg,
        {"settlement_id": pending.id, "tx_hash": dep.tx_hash, "chain": dep.chain, "auto_confirmed": auto_confirmed},
    )
    logger.info(
        "[DepositMonitor] matched settlement #%s user=%s tx=%s auto_confirm=%s",
        pending.id, user.id, dep.tx_hash, auto_confirmed,
    )
    return True


def scan_trc20_deposits(db: Session) -> int:
    if not is_deposit_mnemonic_configured():
        return 0
    rows = db.query(UserDepositAddress).filter(UserDepositAddress.chain == "TRC20").all()
    if not rows:
        return 0

    matched = 0
    for row in rows:
        url = f"{get_tron_api_url().rstrip('/')}/v1/accounts/{row.address}/transactions/trc20"
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
            dep = _record_deposit(
                db, user.id, "TRC20", tx_hash, amount, from_addr, deposit_address=row.address,
            )
            if not dep:
                continue
            db.commit()
            if _try_match_settlement(db, user, dep):
                matched += 1
    return matched


def _scan_evm_chain(db: Session, chain: str) -> int:
    cfg = EVM_USDT_CONFIG.get(chain.upper())
    if not cfg:
        return 0
    usdt_contract, decimals, _ = cfg
    rpc_url = get_rpc_url(chain)
    if not rpc_url.strip():
        return 0

    rows = db.query(UserDepositAddress).filter(UserDepositAddress.chain == chain.upper()).all()
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
    addr_to_address = {Web3.to_checksum_address(r.address): r.address for r in rows}

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
        dep = _record_deposit(
            db, user.id, chain.upper(), tx_hash, amount,
            deposit_address=addr_to_address.get(to_addr),
        )
        if not dep:
            continue
        db.commit()
        if _try_match_settlement(db, user, dep):
            matched += 1
    return matched


def scan_all_deposits(db: Session) -> dict:
    stats: dict[str, int] = {"matched_total": 0}
    if not is_deposit_mnemonic_configured():
        return stats
    stats["trc20"] = scan_trc20_deposits(db)
    stats["matched_total"] += stats["trc20"]
    for chain in ("ERC20", "BEP20", "ARBITRUM", "POLYGON"):
        key = chain.lower()
        matched = _scan_evm_chain(db, chain)
        stats[key] = matched
        stats["matched_total"] += matched
    return stats


def run_deposit_monitor_once() -> dict:
    db = SessionLocal()
    try:
        stats = scan_all_deposits(db)
        record_scan_result(stats)
        if stats.get("matched_total", 0) > 0:
            from app.services.alert_service import notify_system
            notify_system(
                "info",
                "DEPOSIT_MATCH",
                f"链上扫描匹配 {stats['matched_total']} 笔绩效费到账",
                str(stats),
                stats,
            )
        return stats
    except Exception as e:
        logger.exception("[DepositMonitor] scan failed: %s", e)
        record_scan_result({"error": str(e)}, error=str(e))
        if get_deposit_monitor_status().get("consecutive_errors", 0) >= 2:
            from app.services.alert_service import notify_system
            notify_system(
                "error",
                "DEPOSIT_SCAN_FAIL",
                "绩效费链上扫描连续失败",
                str(e)[:300],
                {"error": str(e)},
            )
        return {"error": str(e)}
    finally:
        db.close()
