from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, ReferralReward, Trade, PaymentStatus
from app.services.wallet import get_or_create_reward_account
from app.services.user_lookup import display_name
from app.services.referral import build_invite_url, commission_info
from app.services.referral_stats import build_downline_stats
from app.schemas import ReferralSummary, ReferralUserOut, ReferralInviteOut, ReferralCommissionOut, SettlementOut
from app.api.deps import get_current_user
from app.config import get_settings
from app.services.pdf_export import settlement_pdf_bytes

router = APIRouter(tags=["referrals"])
settings = get_settings()


def _mask_identity(user: User) -> str:
    if user.email:
        parts = user.email.split("@")
        return parts[0][:3] + "***@" + parts[1] if len(parts) == 2 else user.email
    if user.phone:
        return user.phone[:3] + "****" + user.phone[-4:] if len(user.phone) >= 7 else "****"
    return f"UID:{user.uid}"


def _commission_out() -> ReferralCommissionOut:
    info = commission_info()
    return ReferralCommissionOut(**info)


def _user_reward(db: Session, referrer_id: int, uid: int, level: int) -> float:
    return db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == referrer_id,
        ReferralReward.source_user_id == uid,
        ReferralReward.level == level,
    ).scalar() or 0


def _referral_user_out(db: Session, referrer_id: int, u: User, level: int) -> ReferralUserOut:
    stats = build_downline_stats(db, u)
    reward = _user_reward(db, referrer_id, u.id, level)
    return ReferralUserOut(
        id=u.id,
        uid=stats["uid"],
        email=stats["email"],
        display_name=stats["display_name"],
        level=level,
        created_at=u.created_at,
        total_pnl=stats["total_pnl"],
        week_pnl=stats["total_pnl"],
        total_reward=float(reward),
        initial_principal=stats["initial_principal"],
        live_equity=stats["live_equity"],
        available_balance=stats["available_balance"],
        cycle_pnl=stats["cycle_pnl"],
        unrealized_pnl=stats["unrealized_pnl"],
        has_open_position=stats["has_open_position"],
        position_side=stats["position_side"],
        position_qty=stats["position_qty"],
        settlement_status=stats["settlement_status"],
        api_status=stats["api_status"],
    )


@router.get("/referrals/invite", response_model=ReferralInviteOut)
def referral_invite(user: User = Depends(get_current_user)):
    return ReferralInviteOut(
        referral_code=user.referral_code,
        invite_url=build_invite_url(user.referral_code, user.uid),
        uid=user.uid,
        display_name=display_name(user),
        commission=_commission_out(),
    )


@router.get("/referrals", response_model=ReferralSummary)
def referral_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    l1_users = db.query(User).filter(User.referrer_id == user.id).all()
    l1_ids = [u.id for u in l1_users]
    l2_users = db.query(User).filter(User.referrer_id.in_(l1_ids)).all() if l1_ids else []

    l1_out = [_referral_user_out(db, user.id, u, 1) for u in l1_users]
    l2_out = [_referral_user_out(db, user.id, u, 2) for u in l2_users]

    total_rewards = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id
    ).scalar() or 0
    pending = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id, ReferralReward.status == PaymentStatus.PENDING.value
    ).scalar() or 0
    l1_total = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id, ReferralReward.level == 1
    ).scalar() or 0
    l2_total = db.query(func.coalesce(func.sum(ReferralReward.reward_amount), 0)).filter(
        ReferralReward.referrer_id == user.id, ReferralReward.level == 2
    ).scalar() or 0

    account = get_or_create_reward_account(db, user.id)
    db.commit()

    return ReferralSummary(
        referral_code=user.referral_code,
        invite_url=build_invite_url(user.referral_code, user.uid),
        uid=user.uid,
        display_name=display_name(user),
        l1_count=len(l1_users), l2_count=len(l2_users),
        total_rewards=float(total_rewards), pending_rewards=float(pending),
        l1_total_rewards=float(l1_total), l2_total_rewards=float(l2_total),
        reward_balance=account.balance,
        commission=_commission_out(),
        l1_users=l1_out, l2_users=l2_out,
    )


@router.get("/settlements", response_model=list[SettlementOut])
def my_settlements(user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Settlement
    return db.query(Settlement).filter(Settlement.user_id == user.id).order_by(Settlement.created_at.desc()).all()


@router.get("/settlements/{settlement_id}/pdf")
def settlement_pdf(settlement_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Settlement
    s = db.query(Settlement).filter(Settlement.id == settlement_id, Settlement.user_id == user.id).first()
    if not s:
        raise HTTPException(404, "Not found")
    data = {
        "id": s.id,
        "period_start": str(s.period_start),
        "period_end": str(s.period_end),
        "gross_profit": s.gross_profit,
        "high_water_mark": s.high_water_mark,
        "net_profit": s.net_profit,
        "platform_fee": s.platform_fee,
        "user_payable": s.user_payable,
        "payment_status": s.payment_status,
    }
    pdf = settlement_pdf_bytes(data, display_name(user))
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=settlement-{s.id}.pdf"})


@router.get("/referrals/tree")
@router.get("/tree")
def referral_tree(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Referral relationship tree for visualization."""
    l1 = db.query(User).filter(User.referrer_id == user.id).all()
    nodes = [{"id": user.id, "uid": user.uid, "label": display_name(user), "level": 0, "children": []}]
    for u in l1:
        l2 = db.query(User).filter(User.referrer_id == u.id).all()
        child = {"id": u.id, "uid": u.uid, "label": display_name(u), "level": 1, "children": [
            {"id": c.id, "uid": c.uid, "label": display_name(c), "level": 2, "children": []} for c in l2
        ]}
        nodes[0]["children"].append(child)
    return {"root": nodes[0], "l1_count": len(l1), "l2_count": sum(len(n["children"]) for n in nodes[0]["children"])}
