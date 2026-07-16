from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, ReferralReward, Trade, TradeLog, PaymentStatus
from app.services.wallet import get_or_create_reward_account
from app.services.user_lookup import display_name
from app.services.referral import build_invite_url, commission_info
from app.services.referral_code import canonical_referral_code
from app.services.referral_stats import build_downline_stats, expected_referrer_reward
from app.schemas import (
    ReferralSummary, ReferralUserOut, ReferralInviteOut, ReferralCommissionOut,
    SettlementOut, TradeLogOut, ReferralDownlineDetailOut, TradeOut, ReferralBlockDetailOut,
    SettlementCycleStatusOut,
)
from app.api.deps import get_current_user
from app.config import get_settings
from app.services.pdf_export import settlement_pdf_bytes
from app.services.query_filters import parse_date_param, apply_log_date_filter, apply_trade_date_filter
from app.services.platform_analytics import enrich_trades

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
        position_entry=stats.get("position_entry", 0),
        position_mark=stats.get("position_mark", 0),
        position_symbol=stats.get("position_symbol"),
        all_positions=stats.get("all_positions") or [],
        trading_since=stats.get("trading_since"),
        settlement_status=stats["settlement_status"],
        api_status=stats["api_status"],
        exchange=stats.get("exchange", "binance"),
        pending_perf_fee=stats.get("pending_perf_fee", 0),
        pending_net_profit=stats.get("pending_net_profit", 0),
        settlement_period=stats.get("settlement_period"),
        settlement_id=stats.get("settlement_id"),
        expected_reward=expected_referrer_reward(stats.get("pending_net_profit", 0), level)
        if stats.get("pending_perf_fee", 0) > 0
        else 0.0,
    )


def _downline_level(db: Session, referrer_id: int, target_id: int) -> int | None:
    target = db.query(User).filter(User.id == target_id).first()
    if not target:
        return None
    if target.referrer_id == referrer_id:
        return 1
    if target.referrer_id:
        l1 = db.query(User).filter(User.id == target.referrer_id).first()
        if l1 and l1.referrer_id == referrer_id:
            return 2
    return None


def _assert_downline_access(db: Session, referrer: User, target_id: int) -> tuple[User, int]:
    level = _downline_level(db, referrer.id, target_id)
    if level is None:
        raise HTTPException(403, "Not authorized to view this user")
    target = db.query(User).filter(User.id == target_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    return target, level


@router.get("/referrals/invite", response_model=ReferralInviteOut)
def referral_invite(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.credit_control import get_referral_block_details, referral_block_reason
    from app.services.trading_control import get_user_control

    code = canonical_referral_code(user.referral_code)
    reason = referral_block_reason(db, user.id)
    ctrl = get_user_control(db, user.id)
    details = get_referral_block_details(db, user.id) if reason else []
    return ReferralInviteOut(
        referral_code=code,
        invite_url=build_invite_url(user.referral_code, user.uid),
        uid=user.uid,
        display_name=display_name(user),
        commission=_commission_out(),
        referral_blocked=reason is not None,
        referral_block_reason=reason,
        referral_invite_override=bool(ctrl.get("referral_invite_override")),
        referral_block_details=[ReferralBlockDetailOut(**d) for d in details],
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

    all_downline = l1_out + l2_out
    unpaid = [u for u in all_downline if (u.pending_perf_fee or 0) > 0]

    from app.services.credit_control import get_referral_block_details, referral_block_reason
    from app.services.trading_control import get_user_control

    blocked = referral_block_reason(db, user.id)
    ctrl = get_user_control(db, user.id)
    block_details = get_referral_block_details(db, user.id) if blocked else []

    return ReferralSummary(
        referral_code=canonical_referral_code(user.referral_code),
        invite_url=build_invite_url(user.referral_code, user.uid),
        uid=user.uid,
        display_name=display_name(user),
        l1_count=len(l1_users), l2_count=len(l2_users),
        total_rewards=float(total_rewards), pending_rewards=float(pending),
        l1_total_rewards=float(l1_total), l2_total_rewards=float(l2_total),
        reward_balance=account.balance,
        commission=_commission_out(),
        unpaid_fee_count=len(unpaid),
        total_unpaid_perf_fee=round(sum(u.pending_perf_fee for u in unpaid), 2),
        total_expected_reward=round(sum(u.expected_reward for u in unpaid), 2),
        referral_blocked=blocked is not None,
        referral_block_reason=blocked,
        referral_invite_override=bool(ctrl.get("referral_invite_override")),
        referral_block_details=[ReferralBlockDetailOut(**d) for d in block_details],
        l1_users=l1_out, l2_users=l2_out,
    )


@router.get("/settlements/cycle-status", response_model=SettlementCycleStatusOut)
def settlement_cycle_status(user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.settlement import build_settlement_cycle_status
    from app.services.user_deposit_wallet import ensure_user_deposit_addresses

    ensure_user_deposit_addresses(db, user)
    return build_settlement_cycle_status(db, user)


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


@router.get("/referrals/downline/{user_id}/account", response_model=ReferralDownlineDetailOut)
def downline_account(
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """推广者查看一级/二级下线的账户与实盘汇总。"""
    target, level = _assert_downline_access(db, user, user_id)
    open_trades = db.query(Trade).filter(Trade.user_id == target.id, Trade.status == "open").count()
    closed_trades = db.query(Trade).filter(Trade.user_id == target.id, Trade.status == "closed").count()
    return ReferralDownlineDetailOut(
        level=level,
        account=_referral_user_out(db, user.id, target, level),
        open_trades=open_trades,
        closed_trades=closed_trades,
    )


@router.get("/referrals/downline/{user_id}/logs", response_model=list[TradeLogOut])
def downline_logs(
    user_id: int,
    limit: int = 200,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    sync_exchange: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """推广者查看一级/二级下线的详细交易日志（实盘核实明细在 detail_json）。"""
    target, _level = _assert_downline_access(db, user, user_id)
    if sync_exchange:
        from app.services.binance_sync import sync_user_binance_fills
        sync_user_binance_fills(db, target)
    q = db.query(TradeLog).filter(TradeLog.user_id == target.id)
    q = apply_log_date_filter(q, parse_date_param(start), parse_date_param(end), TradeLog)
    rows = q.order_by(TradeLog.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    return [TradeLogOut.model_validate(r) for r in rows]


@router.get("/referrals/downline/{user_id}/trades", response_model=list[TradeOut])
def downline_trades(
    user_id: int,
    limit: int = 100,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target, _level = _assert_downline_access(db, user, user_id)
    q = db.query(Trade).filter(Trade.user_id == target.id)
    q = apply_trade_date_filter(q, parse_date_param(start), parse_date_param(end), Trade)
    rows = q.order_by(Trade.created_at.desc()).offset(offset).limit(min(limit, 200)).all()
    return [TradeOut(**row) for row in enrich_trades(db, rows)]
