"""Admin referral and reward oversight."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, ReferralReward, PaymentStatus, Settlement
from app.services.wallet import get_or_create_reward_account
from app.services.user_lookup import display_name


def build_user_referral_stats(db: Session, user: User) -> dict:
    l1_count = db.query(User).filter(User.referrer_id == user.id).count()
    l1_ids = [r[0] for r in db.query(User.id).filter(User.referrer_id == user.id).all()]
    l2_count = db.query(User).filter(User.referrer_id.in_(l1_ids)).count() if l1_ids else 0

    total_earned = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id
    ).scalar() or 0
    settled_earned = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id,
        ReferralReward.status == PaymentStatus.CONFIRMED.value,
    ).scalar() or 0
    pending_earned = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id,
        ReferralReward.status == PaymentStatus.PENDING.value,
    ).scalar() or 0

    account = get_or_create_reward_account(db, user.id)

    referrer = None
    if user.referrer_id:
        ref = db.query(User).filter(User.id == user.referrer_id).first()
        if ref:
            referrer = {"id": ref.id, "uid": ref.uid, "display_name": display_name(ref)}

    rewards = (
        db.query(ReferralReward)
        .filter(ReferralReward.referrer_id == user.id)
        .order_by(ReferralReward.created_at.desc())
        .limit(100)
        .all()
    )
    reward_rows = []
    for r in rewards:
        source = db.query(User).filter(User.id == r.source_user_id).first()
        reward_rows.append({
            "id": r.id,
            "level": r.level,
            "reward_amount": r.reward_amount,
            "reward_rate": r.reward_rate,
            "base_amount": r.base_amount,
            "status": r.status,
            "settlement_id": r.settlement_id,
            "source_uid": source.uid if source else None,
            "source_display_name": display_name(source) if source else None,
            "created_at": r.created_at.isoformat(),
        })

    return {
        "user_id": user.id,
        "uid": user.uid,
        "referral_code": user.referral_code,
        "referrer": referrer,
        "l1_count": l1_count,
        "l2_count": l2_count,
        "total_earned": float(total_earned),
        "settled_earned": float(settled_earned),
        "pending_earned": float(pending_earned),
        "reward_balance": float(account.balance),
        "rewards": reward_rows,
    }


def build_admin_referral_overview(db: Session) -> dict:
    total_paid = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.status == PaymentStatus.CONFIRMED.value
    ).scalar() or 0
    total_pending = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.status == PaymentStatus.PENDING.value
    ).scalar() or 0
    referrer_ids = db.query(ReferralReward.referrer_id).distinct().count()

    rows = (
        db.query(ReferralReward)
        .order_by(ReferralReward.created_at.desc())
        .limit(200)
        .all()
    )
    items = []
    for r in rows:
        referrer = db.query(User).filter(User.id == r.referrer_id).first()
        source = db.query(User).filter(User.id == r.source_user_id).first()
        settlement = db.query(Settlement).filter(Settlement.id == r.settlement_id).first()
        items.append({
            "id": r.id,
            "level": r.level,
            "reward_amount": r.reward_amount,
            "reward_rate": r.reward_rate,
            "base_amount": r.base_amount,
            "status": r.status,
            "settlement_id": r.settlement_id,
            "referrer_uid": referrer.uid if referrer else None,
            "referrer_display_name": display_name(referrer) if referrer else None,
            "source_uid": source.uid if source else None,
            "source_display_name": display_name(source) if source else None,
            "settlement_period": (
                f"{settlement.period_start} ~ {settlement.period_end}" if settlement else None
            ),
            "created_at": r.created_at.isoformat(),
        })

    top_referrers = (
        db.query(
            ReferralReward.referrer_id,
            func.sum(ReferralReward.reward_amount).label("total"),
            func.count(ReferralReward.id).label("cnt"),
        )
        .filter(ReferralReward.status == PaymentStatus.CONFIRMED.value)
        .group_by(ReferralReward.referrer_id)
        .order_by(func.sum(ReferralReward.reward_amount).desc())
        .limit(20)
        .all()
    )
    leaderboard = []
    for ref_id, total, cnt in top_referrers:
        u = db.query(User).filter(User.id == ref_id).first()
        if not u:
            continue
        l1 = db.query(User).filter(User.referrer_id == u.id).count()
        leaderboard.append({
            "user_id": u.id,
            "uid": u.uid,
            "display_name": display_name(u),
            "l1_count": l1,
            "reward_count": int(cnt),
            "total_earned": float(total or 0),
            "reward_balance": float(get_or_create_reward_account(db, u.id).balance),
        })

    return {
        "total_rewards_paid": float(total_paid),
        "total_rewards_pending": float(total_pending),
        "active_referrers": referrer_ids,
        "rewards": items,
        "leaderboard": leaderboard,
    }
