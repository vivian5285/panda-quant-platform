from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import User, Trade, Settlement, ReferralReward, PaymentStatus, ApiStatus
from app.services.wallet import credit_reward
from app.services.dispatcher import supervisor_pool
from app.config import get_settings

settings = get_settings()


def user_has_open_position(db: Session, user_id: int) -> bool:
    open_trade = db.query(Trade).filter(
        Trade.user_id == user_id,
        Trade.status == "open",
    ).first()
    if open_trade:
        return True

    supervisor = supervisor_pool.get(user_id)
    if supervisor:
        status = supervisor.position_manager.get_position_status()
        if status.get("has_position"):
            return True
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
    trades = db.query(Trade).filter(
        Trade.user_id == user.id,
        Trade.status == "closed",
        func.date(Trade.closed_at) >= period_start,
        func.date(Trade.closed_at) <= period_end,
    ).all()

    gross_profit = sum(t.realized_pnl for t in trades)
    if gross_profit <= 0:
        return None

    new_hwm = max(user.high_water_mark + gross_profit, user.high_water_mark)
    net_profit = max(0, new_hwm - user.high_water_mark)
    if net_profit <= 0:
        return None

    platform_fee = round(net_profit * settings.PLATFORM_FEE_RATE, 2)

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
    )
    db.add(settlement)
    db.flush()

    _create_referral_rewards(db, user, settlement, platform_fee)
    user.high_water_mark = new_hwm
    db.commit()
    db.refresh(settlement)
    return settlement


def _create_referral_rewards(db: Session, user: User, settlement: Settlement, platform_fee: float):
    if user.referrer_id:
        l1 = db.query(User).filter(User.id == user.referrer_id).first()
        if l1:
            amount = round(platform_fee * settings.REFERRAL_L1_RATE, 2)
            db.add(ReferralReward(
                referrer_id=l1.id,
                source_user_id=user.id,
                settlement_id=settlement.id,
                level=1,
                base_amount=platform_fee,
                reward_rate=settings.REFERRAL_L1_RATE,
                reward_amount=amount,
            ))
            if l1.referrer_id:
                l2 = db.query(User).filter(User.id == l1.referrer_id).first()
                if l2:
                    amount2 = round(platform_fee * settings.REFERRAL_L2_RATE, 2)
                    db.add(ReferralReward(
                        referrer_id=l2.id,
                        source_user_id=user.id,
                        settlement_id=settlement.id,
                        level=2,
                        base_amount=platform_fee,
                        reward_rate=settings.REFERRAL_L2_RATE,
                        reward_amount=amount2,
                    ))


def _reset_cycle(user: User, today: date):
    user.settlement_cycle_start = today
    user.settlement_target_days = settings.SETTLEMENT_PRIMARY_DAYS


def _extend_cycle(user: User):
    user.settlement_target_days = settings.SETTLEMENT_EXTENDED_DAYS


def process_user_settlement_cycle(db: Session, user: User, today: date | None = None) -> Settlement | None:
    today = today or date.today()
    _ensure_cycle_started(user, today)

    days_elapsed = (today - user.settlement_cycle_start).days
    if days_elapsed < user.settlement_target_days:
        return None

    if user_has_open_position(db, user.id):
        if user.settlement_target_days == settings.SETTLEMENT_PRIMARY_DAYS:
            _extend_cycle(user)
            db.commit()
        return None

    period_start = user.settlement_cycle_start
    period_end = today
    settlement = calculate_settlement(
        db, user, period_start, period_end, user.settlement_target_days
    )

    if settlement:
        _reset_cycle(user, today)
        db.commit()
        return settlement

    if user.settlement_target_days == settings.SETTLEMENT_PRIMARY_DAYS:
        _extend_cycle(user)
    else:
        _reset_cycle(user, today)
    db.commit()
    return None


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
    return run_scheduled_settlements(db)


def submit_settlement_payment(
    db: Session,
    settlement: Settlement,
    chain: str,
    tx_hash: str,
    amount: float,
) -> Settlement:
    settlement.payment_chain = chain.upper()
    settlement.payment_tx_hash = tx_hash.strip()
    settlement.payment_amount = round(amount, 2)
    settlement.payment_status = PaymentStatus.PAID.value
    settlement.paid_at = datetime.utcnow()
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
        reset_after_settlement_confirmed(db, user, settlement.id)

    db.commit()
    db.refresh(settlement)
    return settlement
