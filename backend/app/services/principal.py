import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PrincipalSnapshot, User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.dispatcher import supervisor_pool

logger = logging.getLogger(__name__)
settings = get_settings()


def fetch_live_equity(user: User) -> float:
    """Read current U 本位合约权益（含未实现盈亏）。"""
    supervisor = supervisor_pool.get(user.id)
    if supervisor:
        summary = supervisor.client.get_futures_account_summary()
        return float(summary.get("total_margin_balance", 0))

    if user.api_key_enc and user.api_secret_enc:
        from app.utils.crypto import decrypt_text

        client = BinanceClient(
            decrypt_text(user.api_key_enc),
            decrypt_text(user.api_secret_enc),
            user.id,
        )
        summary = client.get_futures_account_summary()
        return float(summary.get("total_margin_balance", 0))

    return float(user.initial_principal or 0)


def record_initial_principal(
    db: Session,
    user: User,
    amount: float,
    snapshot_type: str,
    settlement_id: int | None = None,
    note: str = "",
) -> PrincipalSnapshot:
    amount = round(float(amount), 2)
    user.initial_principal = amount
    user.initial_principal_at = datetime.utcnow()

    snap = PrincipalSnapshot(
        user_id=user.id,
        amount=amount,
        snapshot_type=snapshot_type,
        settlement_id=settlement_id,
        note=note or snapshot_type,
    )
    db.add(snap)
    logger.info(
        "[Principal] user=%s type=%s amount=%.2f settlement=%s",
        user.id, snapshot_type, amount, settlement_id,
    )
    return snap


def start_new_profit_cycle(
    db: Session,
    user: User,
    snapshot_type: str = "api_bind",
    settlement_id: int | None = None,
    equity: float | None = None,
    note: str = "",
) -> PrincipalSnapshot:
    """记载初始本金并重置分润周期基准（周而复始）。"""
    if equity is None:
        equity = fetch_live_equity(user)

    snap = record_initial_principal(db, user, equity, snapshot_type, settlement_id, note)
    user.high_water_mark = 0.0
    user.settlement_cycle_start = date.today()
    user.settlement_target_days = settings.SETTLEMENT_PRIMARY_DAYS
    return snap


def reset_after_settlement_confirmed(db: Session, user: User, settlement_id: int) -> PrincipalSnapshot:
    """用户分润到账确认后，以当前权益作为新周期初始本金。"""
    equity = fetch_live_equity(user)
    return start_new_profit_cycle(
        db,
        user,
        snapshot_type="settlement_reset",
        settlement_id=settlement_id,
        equity=equity,
        note=f"结算 #{settlement_id} 确认到账，新周期初始本金",
    )
