import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import PrincipalSnapshot, User
from app.utils.crypto import decrypt_text
from app.core.exchange_factory import create_exchange_client
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
        passphrase = decrypt_text(user.passphrase_enc) if user.passphrase_enc else ""
        client = create_exchange_client(
            user,
            decrypt_text(user.api_key_enc),
            decrypt_text(user.api_secret_enc),
            passphrase,
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


def maybe_rebase_principal_on_divergence(
    db: Session,
    user: User,
    reconcile: dict,
    *,
    force: bool = False,
) -> PrincipalSnapshot | None:
    """When equity gap is explained by withdraw/other-symbol PnL, rebase initial_principal.

    Does NOT reset settlement_cycle_start or high_water_mark — performance fees stay
    based on closed platform Trade PnL under HWM.
    """
    if not reconcile or not (force or reconcile.get("should_rebase_principal") or reconcile.get("transfer_suspected")):
        return None

    suggested = float(reconcile.get("suggested_principal") or 0)
    old = float(user.initial_principal or 0)
    warn = float(reconcile.get("divergence_warn_usd") or settings.PROFIT_DIVERGENCE_WARN_USD or 10)
    if suggested <= 0 or abs(suggested - old) < warn:
        return None

    cooldown_h = float(getattr(settings, "PRINCIPAL_REBASE_COOLDOWN_HOURS", 6) or 6)
    if cooldown_h > 0:
        latest = (
            db.query(PrincipalSnapshot)
            .filter(
                PrincipalSnapshot.user_id == user.id,
                PrincipalSnapshot.snapshot_type == "cashflow_rebase",
            )
            .order_by(PrincipalSnapshot.created_at.desc())
            .first()
        )
        if latest and latest.created_at:
            age_h = (datetime.utcnow() - latest.created_at).total_seconds() / 3600.0
            if age_h < cooldown_h and abs(float(latest.amount or 0) - suggested) < warn:
                logger.info(
                    "[Principal] skip rebase user=%s cooldown=%.1fh last=%.2f suggested=%.2f",
                    user.id, age_h, float(latest.amount or 0), suggested,
                )
                return None

    hy = ",".join(reconcile.get("hypotheses") or []) or "equity_divergence"
    note = (
        f"对账校正本金 {old:.2f}→{suggested:.2f} | "
        f"权益 {float(reconcile.get('live_equity') or 0):.2f} | "
        f"合约盈亏 {float(reconcile.get('trade_cycle_pnl') or 0):.2f} | "
        f"划转净额 {float(reconcile.get('estimated_net_transfer') or 0):.2f} | "
        f"{hy} | 结算仍以交易订单盈亏为准"
    )
    user.initial_principal = suggested
    user.initial_principal_at = datetime.utcnow()
    snap = PrincipalSnapshot(
        user_id=user.id,
        amount=suggested,
        snapshot_type="cashflow_rebase",
        note=note,
        live_equity=float(reconcile.get("live_equity") or 0),
        trade_pnl_cycle=float(reconcile.get("trade_cycle_pnl") or 0),
        trade_pnl_total=float(reconcile.get("trade_pnl_total") or 0),
        equity_delta=float(reconcile.get("equity_delta") or 0),
    )
    db.add(snap)
    logger.warning(
        "[Principal] cashflow_rebase user=%s exchange=%s %.2f → %.2f | %s",
        user.id,
        user.exchange,
        old,
        suggested,
        hy,
    )
    return snap
