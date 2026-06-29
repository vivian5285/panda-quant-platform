"""Background auto-payout for instant (≤ threshold) withdrawals."""
import logging

from app.database import SessionLocal
from app.models import WithdrawalRequest, WithdrawalStatus
from app.services.audit import log_audit
from app.services.chain_payout import execute_usdt_payout, get_payout_status
from app.services.chain_explorer import tx_explorer_url
from app.services.notification import notify_user
from app.services.wallet import complete_withdrawal
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def process_auto_payout(withdrawal_id: int) -> None:
    db = SessionLocal()
    try:
        req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
        if not req or not req.auto_approved:
            return
        if req.status not in (
            WithdrawalStatus.AUTO_APPROVED.value,
            WithdrawalStatus.PROCESSING.value,
        ):
            return
        if req.tx_hash:
            return

        payout_status = get_payout_status()
        if not payout_status.enabled:
            logger.debug("Auto payout disabled; withdrawal #%s stays in queue", withdrawal_id)
            return
        if req.chain.upper() not in payout_status.configured_chains:
            logger.warning(
                "Auto payout skipped for withdrawal #%s: chain %s not configured",
                withdrawal_id,
                req.chain,
            )
            return

        req.status = WithdrawalStatus.PROCESSING.value
        db.commit()

        try:
            tx_hash = execute_usdt_payout(req.chain, req.address, req.amount_net)
            complete_withdrawal(db, req, tx_hash, admin_note="auto_payout")
            explorer = tx_explorer_url(req.chain, tx_hash)
            log_audit(
                db,
                "withdrawal.auto_payout",
                user_id=req.user_id,
                actor_id=None,
                resource_type="withdrawal",
                resource_id=str(req.id),
                detail={
                    "chain": req.chain,
                    "amount_net": req.amount_net,
                    "tx_hash": tx_hash,
                    "explorer_url": explorer,
                },
            )
            notify_user(
                db,
                req.user_id,
                title="提现已到账",
                message=(
                    f"您的 {req.amount_net:.2f} USDT ({req.chain}) 已自动链上打款。"
                    f" TxHash: {tx_hash}"
                ),
                category="withdrawal",
            )
            logger.info("Auto payout completed withdrawal #%s tx=%s", withdrawal_id, tx_hash)
        except Exception as e:
            logger.exception("Auto payout failed for withdrawal #%s", withdrawal_id)
            req.status = WithdrawalStatus.AUTO_APPROVED.value
            req.admin_note = f"auto_payout_failed: {e}"
            db.commit()
            log_audit(
                db,
                "withdrawal.auto_payout_failed",
                user_id=req.user_id,
                actor_id=None,
                resource_type="withdrawal",
                resource_id=str(req.id),
                detail={"chain": req.chain, "error": str(e)},
            )
    finally:
        db.close()
