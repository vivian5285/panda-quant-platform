from datetime import date, datetime, timedelta
import logging

from sqlalchemy.orm import Session
from app.models import User, Trade, Settlement, ReferralReward, PaymentStatus, ApiStatus
from app.services.wallet import credit_reward
from app.services.dispatcher import supervisor_pool
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_UNSETTLED_STATUSES = (PaymentStatus.PENDING.value, PaymentStatus.PAID.value)


def get_pending_settlement(db: Session, user_id: int) -> Settlement | None:
    """Return the active settlement awaiting user payment or admin confirmation."""
    return (
        db.query(Settlement)
        .filter(
            Settlement.user_id == user_id,
            Settlement.payment_status.in_(_UNSETTLED_STATUSES),
        )
        .order_by(Settlement.created_at.desc())
        .first()
    )


def user_has_unsettled_payment(db: Session, user_id: int) -> bool:
    return get_pending_settlement(db, user_id) is not None


def user_has_open_position(db: Session, user_id: int) -> bool:
    open_trade = db.query(Trade).filter(
        Trade.user_id == user_id,
        Trade.status == "open",
    ).first()
    if open_trade:
        return True

    for supervisor in supervisor_pool.get_all_for_user(user_id):
        try:
            if hasattr(supervisor, "position_manager"):
                status = supervisor.position_manager.get_position_status()
                if status.get("has_position"):
                    return True
            elif float(getattr(supervisor, "watched_qty", 0) or 0) > 0:
                return True
        except Exception:
            continue
    return False


def _ensure_cycle_started(user: User, today: date):
    if not user.settlement_cycle_start:
        user.settlement_cycle_start = today - timedelta(days=settings.SETTLEMENT_PRIMARY_DAYS)
    if not user.settlement_target_days:
        user.settlement_target_days = settings.SETTLEMENT_PRIMARY_DAYS


def calculate_settlement(
    db: Session,
    user: User,
    period_start: date,
    period_end: date,
    cycle_days: int,
) -> Settlement | None:
    from app.services.profit_audit import settlement_profit_from_trades

    gross_profit, audit = settlement_profit_from_trades(db, user, period_start, period_end)
    if gross_profit <= 0:
        return None

    new_hwm = max(user.high_water_mark + gross_profit, user.high_water_mark)
    net_profit = max(0, new_hwm - user.high_water_mark)
    if net_profit <= 0:
        return None

    new_hwm = max(user.high_water_mark, user.high_water_mark + net_profit)
    platform_fee = round(net_profit * settings.PLATFORM_FEE_RATE, 2)

    admin_note = (
        f"profit_source=trades;"
        f"trade_profit={audit['trade_profit']};"
        f"binance_fill_pnl={audit['binance_fill_pnl']};"
        f"equity_delta={audit['equity_delta']};"
        f"divergence={audit['divergence']};"
        f"estimated_net_transfer={audit.get('estimated_net_transfer')};"
        f"transfer_suspected={audit.get('transfer_suspected')};"
        f"fee_basis=exchange_trading_fill_realized_pnl_hwm"
    )

    settlement = Settlement(
        user_id=user.id,
        period_start=period_start,
        period_end=period_end,
        gross_profit=gross_profit,
        net_profit=net_profit,
        high_water_mark=new_hwm,
        platform_fee=platform_fee,
        user_payable=platform_fee,
        cycle_days=cycle_days,
        payment_status=PaymentStatus.PENDING.value,
        admin_note=admin_note,
    )
    db.add(settlement)
    db.flush()

    _create_referral_rewards(db, user, settlement, net_profit)
    user.high_water_mark = new_hwm
    db.commit()
    db.refresh(settlement)

    from app.services.trade_logger import TradeLogger

    TradeLogger(db).log_event(
        user.id,
        "SETTLEMENT",
        f"AI 绩效服务费账单已生成，应付 ${platform_fee:.2f} USDT，AI 执行已暂停直至确认到账",
        {"settlement_id": settlement.id, "user_payable": platform_fee},
    )
    return settlement


def _create_referral_rewards(db: Session, user: User, settlement: Settlement, net_profit: float):
    """L1/L2 奖励基数 = 周期净盈利（非绩效费本身）。例：盈利 $1000 → 用户付 $250 绩效费，L1 $100 + L2 $50，平台留存 $100。"""
    base = round(float(net_profit or 0), 2)
    if base <= 0:
        return
    if user.referrer_id:
        l1 = db.query(User).filter(User.id == user.referrer_id).first()
        if l1:
            amount = round(base * settings.REFERRAL_L1_RATE, 2)
            db.add(ReferralReward(
                referrer_id=l1.id,
                source_user_id=user.id,
                settlement_id=settlement.id,
                level=1,
                base_amount=base,
                reward_rate=settings.REFERRAL_L1_RATE,
                reward_amount=amount,
            ))
            if l1.referrer_id:
                l2 = db.query(User).filter(User.id == l1.referrer_id).first()
                if l2:
                    amount2 = round(base * settings.REFERRAL_L2_RATE, 2)
                    db.add(ReferralReward(
                        referrer_id=l2.id,
                        source_user_id=user.id,
                        settlement_id=settlement.id,
                        level=2,
                        base_amount=base,
                        reward_rate=settings.REFERRAL_L2_RATE,
                        reward_amount=amount2,
                    ))


def _reset_cycle(user: User, today: date):
    user.settlement_cycle_start = today
    user.settlement_target_days = settings.SETTLEMENT_PRIMARY_DAYS


def _rollover_cycle(user: User):
    """Loss at period end: extend window by 30d; PnL still accumulates from cycle_start."""
    base = user.settlement_target_days or settings.SETTLEMENT_PRIMARY_DAYS
    user.settlement_target_days = base + settings.SETTLEMENT_PRIMARY_DAYS


def _cycle_net_profit_preview(db: Session, user: User, period_start: date, period_end: date) -> float:
    from app.services.profit_audit import settlement_profit_from_trades

    gross, _ = settlement_profit_from_trades(db, user, period_start, period_end)
    new_hwm = max(float(user.high_water_mark or 0) + gross, float(user.high_water_mark or 0))
    return max(0.0, new_hwm - float(user.high_water_mark or 0))


def try_settlement_on_flat(db: Session, user: User, today: date | None = None) -> Settlement | None:
    """Cycle due + profitable + was holding: bill immediately once flat."""
    from app.services.trading_control import clear_settlement_awaiting_flat, get_user_control

    today = today or date.today()
    ctrl = get_user_control(db, user.id)
    if not ctrl.get("settlement_awaiting_flat"):
        return None
    if get_pending_settlement(db, user.id):
        clear_settlement_awaiting_flat(db, user.id)
        return None
    if user_has_open_position(db, user.id):
        return None

    clear_settlement_awaiting_flat(db, user.id)
    period_start = user.settlement_cycle_start or today
    settlement = calculate_settlement(
        db, user, period_start, today, user.settlement_target_days or settings.SETTLEMENT_PRIMARY_DAYS
    )
    if settlement:
        _reset_cycle(user, today)
    db.commit()
    return settlement


def build_settlement_cycle_status(db: Session, user: User, today: date | None = None) -> dict:
    """Real-time in-cycle stats for user settlement page."""
    from app.services.profit_audit import settlement_profit_from_trades

    today = today or date.today()
    _ensure_cycle_started(user, today)

    period_start = user.settlement_cycle_start
    target_days = user.settlement_target_days or settings.SETTLEMENT_PRIMARY_DAYS
    days_elapsed = max(0, (today - period_start).days)
    days_remaining = max(0, target_days - days_elapsed)
    progress_pct = min(100.0, round(days_elapsed / target_days * 100, 1)) if target_days > 0 else 0.0
    rollover_count = max(0, (target_days - settings.SETTLEMENT_PRIMARY_DAYS) // settings.SETTLEMENT_PRIMARY_DAYS)

    gross_profit, audit = settlement_profit_from_trades(db, user, period_start, today)
    new_hwm = max(float(user.high_water_mark or 0) + gross_profit, float(user.high_water_mark or 0))
    net_profit = max(0.0, new_hwm - float(user.high_water_mark or 0))
    estimated_fee = round(net_profit * settings.PLATFORM_FEE_RATE, 2) if net_profit > 0 else 0.0

    has_position = user_has_open_position(db, user.id)
    pending = get_pending_settlement(db, user.id)
    initial = float(user.initial_principal or 0)
    from app.services.trading_control import get_user_control

    awaiting_flat = bool(get_user_control(db, user.id).get("settlement_awaiting_flat"))

    if pending:
        phase = "pending_payment"
    elif awaiting_flat and has_position:
        phase = "awaiting_flat"
    elif days_elapsed < target_days:
        phase = "active"
    elif has_position:
        phase = "due_holding"
    elif net_profit > 0:
        phase = "due_flat_profit"
    else:
        phase = "due_flat_loss"

    historical_settled = (
        db.query(Settlement)
        .filter(Settlement.user_id == user.id, Settlement.payment_status == PaymentStatus.CONFIRMED.value)
        .count()
    )

    return {
        "cycle_start": period_start.isoformat(),
        "cycle_end_scheduled": (period_start + timedelta(days=target_days)).isoformat(),
        "target_days": target_days,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "progress_pct": progress_pct,
        "rollover_count": rollover_count,
        "phase": phase,
        "has_open_position": has_position,
        "initial_principal": round(initial, 2),
        "high_water_mark": round(float(user.high_water_mark or 0), 2),
        "cycle_trade_pnl": round(float(audit.get("trade_profit", gross_profit) or 0), 2),
        "cycle_equity_delta": round(float(audit.get("equity_delta", 0) or 0), 2),
        "cycle_net_profit": round(net_profit, 2),
        "estimated_fee": estimated_fee,
        "is_profitable": net_profit > 0,
        "requires_flat": days_elapsed >= target_days and net_profit > 0,
        "pending_settlement_id": pending.id if pending else None,
        "pending_payable": round(float(pending.user_payable or 0), 2) if pending else 0.0,
        "historical_settled_cycles": historical_settled,
        "settlement_awaiting_flat": awaiting_flat,
        "profit_audit": audit,
    }


def process_user_settlement_cycle(db: Session, user: User, today: date | None = None) -> Settlement | None:
    today = today or date.today()
    _ensure_cycle_started(user, today)

    # Keep principal aligned with live equity when cashflow/other-symbol gap is large.
    try:
        from app.services.profit_audit import build_dual_profit_report
        from app.services.principal import maybe_rebase_principal_on_divergence

        report = build_dual_profit_report(db, user)
        if report.get("should_rebase_principal") or report.get("transfer_suspected"):
            snap = maybe_rebase_principal_on_divergence(db, user, report)
            if snap:
                db.commit()
                logger.info(
                    "[Settlement] principal rebased user=%s → %.2f before cycle check",
                    user.id, float(snap.amount),
                )
    except Exception:
        logger.exception("[Settlement] principal rebase skipped user=%s", user.id)

    if get_pending_settlement(db, user.id):
        return None

    billed = try_settlement_on_flat(db, user, today)
    if billed:
        return billed

    days_elapsed = (today - user.settlement_cycle_start).days
    if days_elapsed < user.settlement_target_days:
        return None

    period_start = user.settlement_cycle_start

    if user_has_open_position(db, user.id):
        if _cycle_net_profit_preview(db, user, period_start, today) > 0:
            from app.services.trading_control import set_settlement_awaiting_flat

            set_settlement_awaiting_flat(db, user.id, True)
            db.commit()
            return None
        _rollover_cycle(user)
        db.commit()
        return None

    period_end = today
    settlement = calculate_settlement(
        db, user, period_start, period_end, user.settlement_target_days
    )

    if settlement:
        _reset_cycle(user, today)
        db.commit()
        return settlement

    _rollover_cycle(user)
    db.commit()
    return None


def run_awaiting_flat_settlements(db: Session) -> list[Settlement]:
    """Frequent scan: bill users flagged awaiting_flat once position is zero."""
    from app.models import UserTradingState
    import json

    created: list[Settlement] = []
    rows = db.query(UserTradingState).all()
    for row in rows:
        if not row.state_json:
            continue
        try:
            state = json.loads(row.state_json)
        except json.JSONDecodeError:
            continue
        if not state.get("settlement_awaiting_flat"):
            continue
        user = db.query(User).filter(User.id == row.user_id, User.is_active == True).first()
        if not user:
            continue
        s = try_settlement_on_flat(db, user)
        if s:
            created.append(s)
    return created


def run_scheduled_settlements(db: Session) -> list[Settlement]:
    users = db.query(User).filter(
        User.is_active == True,
        User.api_status == ApiStatus.ACTIVE.value,
    ).all()
    created = []
    for user in users:
        pending = db.query(Settlement).filter(
            Settlement.user_id == user.id,
            Settlement.payment_status.in_([
                PaymentStatus.PENDING.value,
                PaymentStatus.PAID.value,
            ]),
        ).first()
        if pending:
            continue
        s = process_user_settlement_cycle(db, user)
        if s:
            created.append(s)
    return created


def run_weekly_settlements(db: Session) -> list[Settlement]:
    """Legacy alias — settlement cycle is monthly (see SETTLEMENT_PRIMARY_DAYS)."""
    return run_scheduled_settlements(db)


def run_monthly_settlements(db: Session) -> list[Settlement]:
    return run_scheduled_settlements(db)


def submit_settlement_payment(
    db: Session,
    settlement: Settlement,
    chain: str,
    tx_hash: str,
    amount: float,
) -> Settlement:
    from app.models import SettlementDeposit

    normalized = tx_hash.strip()
    if not normalized or len(normalized) < 8:
        raise ValueError("Invalid transaction hash")

    dup_variants = {normalized, normalized.lower()}
    if normalized.startswith("0x") or normalized.startswith("0X"):
        dup_variants.add(normalized.lower())
        dup_variants.add(normalized[2:].lower())

    existing_dep = db.query(SettlementDeposit).filter(
        SettlementDeposit.tx_hash.in_(list(dup_variants))
    ).first()
    if existing_dep:
        same_user = existing_dep.user_id == settlement.user_id
        unlinked = existing_dep.settlement_id is None
        same_settlement = existing_dep.settlement_id == settlement.id
        if not (same_user and (unlinked or same_settlement)):
            raise ValueError("该 TxHash 已被使用")

    existing_settlement = db.query(Settlement).filter(
        Settlement.id != settlement.id,
        Settlement.payment_tx_hash.isnot(None),
        Settlement.payment_tx_hash.in_(list(dup_variants)),
    ).first()
    if existing_settlement:
        raise ValueError("该 TxHash 已被其他结算单使用")

    settlement.payment_chain = chain.upper()
    settlement.payment_tx_hash = normalized
    settlement.payment_amount = round(amount, 2)
    settlement.payment_status = PaymentStatus.PAID.value
    settlement.paid_at = datetime.utcnow()
    db.commit()
    db.refresh(settlement)
    return settlement


def reject_settlement_payment(db: Session, settlement: Settlement, admin_note: str = "") -> Settlement:
    if settlement.payment_status == PaymentStatus.CONFIRMED.value:
        raise ValueError("Settlement already confirmed")

    user = db.query(User).filter(User.id == settlement.user_id).first()
    if user:
        user.high_water_mark = max(0.0, float(settlement.high_water_mark or 0) - float(settlement.net_profit or 0))

    db.query(ReferralReward).filter(
        ReferralReward.settlement_id == settlement.id,
        ReferralReward.status == PaymentStatus.PENDING.value,
    ).delete(synchronize_session=False)

    settlement.payment_status = PaymentStatus.REJECTED.value
    settlement.admin_note = admin_note or settlement.admin_note or "rejected"
    settlement.payment_chain = None
    settlement.payment_tx_hash = None
    settlement.payment_amount = None
    settlement.paid_at = None

    if user:
        from app.services.trade_logger import TradeLogger
        from app.services.trading_control import clear_settlement_fee_deferred

        clear_settlement_fee_deferred(db, user.id)
        TradeLogger(db).log_event(
            user.id,
            "SETTLEMENT",
            f"绩效结算单 #{settlement.id} 已被驳回，AI 执行限制已解除",
            {"settlement_id": settlement.id},
        )

    db.commit()
    db.refresh(settlement)
    return settlement


def confirm_settlement_payment(db: Session, settlement: Settlement, admin_note: str = "") -> Settlement:
    settlement.payment_status = PaymentStatus.CONFIRMED.value
    settlement.confirmed_at = datetime.utcnow()
    settlement.admin_note = admin_note or settlement.admin_note

    rewards = db.query(ReferralReward).filter(
        ReferralReward.settlement_id == settlement.id
    ).all()
    for r in rewards:
        credit_reward(
            db, r.referrer_id, r.reward_amount,
            reference_type="referral_reward",
            reference_id=r.id,
            note=f"L{r.level} referral from settlement #{settlement.id}",
        )
        r.status = PaymentStatus.CONFIRMED.value

    user = db.query(User).filter(User.id == settlement.user_id).first()
    if user:
        from app.services.principal import reset_after_settlement_confirmed
        from app.services.trading_control import clear_settlement_fee_deferred, clear_settlement_awaiting_flat

        reset_after_settlement_confirmed(db, user, settlement.id)
        clear_settlement_fee_deferred(db, user.id)
        clear_settlement_awaiting_flat(db, user.id)
        from app.services.trade_logger import TradeLogger

        TradeLogger(db).log_event(
            user.id,
            "SETTLEMENT",
            "绩效结算已确认到账，初始本金已重置，AI 执行已恢复",
            {"settlement_id": settlement.id},
        )

    db.commit()
    db.refresh(settlement)
    return settlement
