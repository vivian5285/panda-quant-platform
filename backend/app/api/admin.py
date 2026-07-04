from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, UserRole, Trade, TradeLog, Settlement, ReferralReward, PaymentStatus, ApiStatus,
    PlatformDepositAddress, WithdrawalRequest, WithdrawalStatus, SUPPORTED_CHAINS,
    AdminAlert, PrincipalSnapshot, SettlementDeposit, SettlementPaymentAppeal, DepositSweepLog,
)
from app.schemas import (
    AdminUserOut, AdminOverview, AdminSettlementOut, SettlementOut,
    DepositAddressOut, DepositAddressCreate, DepositAddressUpdate,
    PayoutSettingsOut, PayoutSettingsUpdate,
    DepositWalletSettingsOut, DepositWalletSettingsUpdate, DepositWalletSettingsUpdateResult,
    DepositSweepSettingsOut, DepositSweepSettingsUpdate, DepositSweepLogOut,
    WalletOverviewOut,
    WebhookReceiveLogOut, WebhookReceiveLogDetailOut,
    DingTalkSettingsOut, DingTalkSettingsUpdate, ChainRpcSettingsOut, ChainRpcSettingsUpdate, AdminPasswordChange,
    PlatformPublicSettingsOut, PlatformPublicSettingsUpdate,
    AdminSettlementDepositOut, AdminSettlementAppealOut, SettlementAppealReview,
    WithdrawThresholdsUpdate,
    WithdrawalOut, WithdrawalComplete, WithdrawalReject,
    AdminAlertOut, AdminUserDetailOut, TradeOut, TradeLogOut, PrincipalSnapshotOut,
    AdminBatchNotify, AdminBatchTradingControl,
    AdminManagedAccountsOut, AdminUserTradeStatsOut, AdminForceCloseAllOut,
)
from app.services.admin_user_stats import (
    mask_api_key, user_cumulative_pnl, user_execution_success_rate, user_risk_flag,
)
from app.services.notification import notify_users
from app.services.query_filters import parse_date_param, apply_trade_date_filter, apply_log_date_filter
from app.services.admin_referral import build_user_referral_stats, build_admin_referral_overview
from app.services.binance_sync import sync_user_binance_fills
from app.services.platform_runtime import get_withdraw_thresholds, set_withdraw_thresholds
from app.services.deposit_qr import save_deposit_qr, delete_deposit_qr, resolve_deposit_qr_path
from app.api.deps import get_admin_user
from app.services.dispatcher import supervisor_pool
from app.services.trade_logger import TradeLogger
from app.services.settlement import run_scheduled_settlements, confirm_settlement_payment, reject_settlement_payment
from app.services.wallet import complete_withdrawal, reject_withdrawal
from app.services.payout_secrets import (
    get_payout_settings, update_payout_keys, is_payout_auto_enabled,
)
from app.services.deposit_secrets import (
    get_deposit_wallet_settings, update_deposit_mnemonic, is_deposit_mnemonic_configured,
)
from app.services.user_deposit_wallet import backfill_all_user_deposit_addresses
from app.services.dingtalk_secrets import get_dingtalk_settings, update_dingtalk_settings
from app.services.chain_rpc_config import get_chain_rpc_settings, update_chain_rpc_settings
from app.services.settlement_deposit_log import build_admin_deposit_row, build_admin_appeal_row
from app.services.settlement_appeal import approve_payment_appeal, reject_payment_appeal
from app.services.deposit_sweep_config import get_sweep_settings, update_sweep_settings
from app.services.deposit_sweep import run_deposit_sweep
from app.services.wallet_overview import get_wallet_overview
from app.services.webhook_receive_log import webhook_log_to_dict, get_webhook_log_detail
from app.models.platform import WebhookReceiveLog
from app.utils.auth import verify_password, hash_password
from app.services.chain_payout import get_payout_status
from app.models.platform import Strategy
from app.services.audit import log_audit
from app.services.alert_service import list_alerts, mark_alert_read, mark_all_read
from app.services.trading_control import (
    get_user_control,
    set_user_control,
    build_trading_control_response,
    count_settlement_gate_stats,
)
from app.services.settlement import get_pending_settlement, user_has_unsettled_payment
from app.models.platform import TvSignalTemplate
from app.services.signal_admin import (
    template_to_dict, build_test_payload, run_signal_dispatch,
)
import json
import threading

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverview)
def overview(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_trades = db.query(Trade).filter(Trade.created_at >= today_start).all()
    closed_today = [t for t in today_trades if t.status == "closed"]
    wins = sum(1 for t in closed_today if (t.realized_pnl or 0) > 0)
    success_rate = round((wins / len(closed_today) * 100), 1) if closed_today else 0.0
    gate_stats = count_settlement_gate_stats(db)
    return AdminOverview(
        total_users=db.query(User).count(),
        active_api_users=db.query(User).filter(User.api_status == ApiStatus.ACTIVE.value).count(),
        total_trades=db.query(Trade).count(),
        today_executions=len(today_trades),
        today_success_rate=success_rate,
        active_supervisors=len(supervisor_pool.get_all()),
        pending_settlements=db.query(Settlement).filter(
            Settlement.payment_status == PaymentStatus.PENDING.value
        ).count(),
        pending_payments=db.query(Settlement).filter(
            Settlement.payment_status == PaymentStatus.PAID.value
        ).count(),
        pending_withdrawals=db.query(WithdrawalRequest).filter(
            WithdrawalRequest.status.in_([
                WithdrawalStatus.PENDING.value,
                WithdrawalStatus.AUTO_APPROVED.value,
                WithdrawalStatus.APPROVED.value,
            ])
        ).count(),
        unread_alerts=db.query(AdminAlert).filter(
            AdminAlert.is_read == False,
            AdminAlert.user_id.is_(None),
        ).count(),
        settlement_blocked_users=gate_stats["blocked"],
        settlement_deferred_users=gate_stats["deferred"],
    )


def _admin_user_row(user: User, db: Session) -> AdminUserOut:
    ctrl = get_user_control(db, user.id)
    trading_paused = ctrl.get("trading_paused", False)
    cumulative_pnl = user_cumulative_pnl(db, user.id)
    exec_rate = user_execution_success_rate(db, user.id)
    flagged, flag_reason = user_risk_flag(
        user,
        trading_paused=trading_paused,
        cumulative_pnl=cumulative_pnl,
        exec_rate=exec_rate,
    )
    return AdminUserOut(
        id=user.id,
        uid=user.uid,
        email=user.email,
        phone=user.phone,
        nickname=user.nickname,
        role=user.role,
        api_status=user.api_status,
        exchange=user.exchange or "binance",
        api_account_mode=user.api_account_mode or "master",
        exchange_uid=user.exchange_uid,
        master_exchange_uid=user.master_exchange_uid,
        is_active=user.is_active,
        referrer_id=user.referrer_id,
        trading_paused=trading_paused,
        risk_level=ctrl.get("risk_level", "balanced"),
        created_at=user.created_at,
        cumulative_pnl=cumulative_pnl,
        execution_success_rate=exec_rate,
        risk_flag=flagged,
        risk_flag_reason=flag_reason,
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    q: str | None = None,
    api_status: str | None = None,
    trading_paused: bool | None = None,
    risk_level: str | None = None,
    risk_flag: bool | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    rows = db.query(User).order_by(User.created_at.desc()).all()
    out: list[AdminUserOut] = []
    for user in rows:
        item = _admin_user_row(user, db)
        if q:
            needle = q.strip().lower()
            hay = " ".join(filter(None, [user.uid, user.email, user.phone, user.nickname])).lower()
            if needle not in hay:
                continue
        if api_status and user.api_status != api_status:
            continue
        if trading_paused is not None and item.trading_paused != trading_paused:
            continue
        if risk_level and item.risk_level != risk_level:
            continue
        if risk_flag is not None and item.risk_flag != risk_flag:
            continue
        out.append(item)
    return out


def _initiate_force_close(db: Session, user: User, *, reason: str) -> dict:
    if user.api_status != ApiStatus.ACTIVE.value or not user.api_key_enc:
        return {"user_id": user.id, "uid": user.uid, "status": "skipped", "message": "api_inactive"}

    sup = supervisor_pool.get(user.id)
    if not sup:
        sup = supervisor_pool.add_user(user, db=db)
    if not sup:
        return {"user_id": user.id, "uid": user.uid, "status": "error", "message": "supervisor_unavailable"}

    uid = user.id

    def _run():
        from app.database import SessionLocal
        try:
            active = supervisor_pool.get(uid)
            if active:
                active._close_all(reason)
        except Exception as e:
            err_db = SessionLocal()
            try:
                TradeLogger(err_db).log_event(uid, "ERROR", f"Admin force close failed: {e}")
            finally:
                err_db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"user_id": user.id, "uid": user.uid, "status": "closing"}


@router.get("/users/managed-accounts", response_model=AdminManagedAccountsOut)
def list_managed_accounts(
    api_status: str | None = None,
    has_position: bool | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.admin_portfolio import list_managed_accounts as build_list, portfolio_summary

    rows = build_list(db, api_status=api_status, has_position=has_position)
    return AdminManagedAccountsOut(
        summary=portfolio_summary(rows),
        accounts=rows,
    )


@router.get("/users/{user_id}/trade-stats", response_model=AdminUserTradeStatsOut)
def admin_user_trade_stats(
    user_id: int,
    start: str | None = None,
    end: str | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    from app.services.admin_portfolio import user_trade_stats

    return user_trade_stats(db, user_id, start, end)


@router.post("/users/force-close-all", response_model=AdminForceCloseAllOut)
def admin_force_close_all(
    request: Request,
    only_with_position: bool = False,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.admin_portfolio import list_managed_accounts as build_list

    rows = build_list(db, api_status=ApiStatus.ACTIVE.value)
    if only_with_position:
        rows = [r for r in rows if r.get("has_position")]

    results = []
    for row in rows:
        user = db.query(User).filter(User.id == row["user_id"]).first()
        if not user:
            continue
        results.append(_initiate_force_close(db, user, reason="Admin batch force close all"))

    initiated = sum(1 for r in results if r.get("status") == "closing")
    failed = sum(1 for r in results if r.get("status") == "error")
    log_audit(
        db,
        "admin.force_close_all",
        actor_id=admin.id,
        resource_type="users",
        detail={"initiated": initiated, "failed": failed, "only_with_position": only_with_position},
        request=request,
    )
    return AdminForceCloseAllOut(initiated=initiated, failed=failed, results=results)


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    if not user.is_active:
        supervisor_pool.remove_user(user_id)
    elif user.api_key_enc and user.api_status == ApiStatus.ACTIVE.value:
        supervisor_pool.add_user(user, db=db)
    return {"id": user.id, "is_active": user.is_active}


@router.post("/users/batch-notify")
def batch_notify_users(body: AdminBatchNotify, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.id.in_(body.user_ids)).all()
    if not users:
        raise HTTPException(404, "No users found")
    notify_users(db, [u.id for u in users], body.title, body.message, category="admin")
    log_audit(
        db,
        "admin.batch_notify",
        actor_id=admin.id,
        resource_type="users",
        detail={"count": len(users), "title": body.title},
    )
    return {"sent": len(users)}


@router.post("/users/batch-trading-control")
def batch_trading_control(body: AdminBatchTradingControl, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    if body.trading_paused is None and not body.risk_level:
        raise HTTPException(400, "trading_paused or risk_level required")
    users = db.query(User).filter(User.id.in_(body.user_ids)).all()
    if not users:
        raise HTTPException(404, "No users found")
    updated = 0
    applied: dict = {}
    for user in users:
        patch: dict = {}
        if body.trading_paused is not None:
            patch["trading_paused"] = body.trading_paused
        if body.risk_level:
            patch["risk_level"] = body.risk_level
        if patch:
            set_user_control(db, user.id, **patch)
            applied = patch
            updated += 1
    log_audit(
        db,
        "admin.batch_trading_control",
        actor_id=admin.id,
        resource_type="users",
        detail={"count": updated, **applied},
    )
    return {"updated": updated}


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
def get_user_detail(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    from app.services.user_account import build_user_profile, build_dashboard_stats

    trade_count = db.query(Trade).filter(Trade.user_id == user.id).count()
    log_count = db.query(TradeLog).filter(TradeLog.user_id == user.id).count()
    ctrl = get_user_control(db, user.id)
    trading_paused = ctrl.get("trading_paused", False)
    cumulative_pnl = user_cumulative_pnl(db, user.id)
    exec_rate = user_execution_success_rate(db, user.id)
    flagged, flag_reason = user_risk_flag(
        user,
        trading_paused=trading_paused,
        cumulative_pnl=cumulative_pnl,
        exec_rate=exec_rate,
    )
    return AdminUserDetailOut(
        profile=build_user_profile(user),
        dashboard=build_dashboard_stats(db, user),
        trade_count=trade_count,
        log_count=log_count,
        supervisor_active=supervisor_pool.get(user.id) is not None,
        api_key_mask=mask_api_key(user),
        trading_paused=trading_paused,
        risk_level=ctrl.get("risk_level", "balanced"),
        risk_flag=flagged,
        risk_flag_reason=flag_reason,
        cumulative_pnl=cumulative_pnl,
        execution_success_rate=exec_rate,
    )


@router.get("/users/{user_id}/trades", response_model=list[TradeOut])
def get_user_trades(
    user_id: int,
    limit: int = 200,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    q = db.query(Trade).filter(Trade.user_id == user.id)
    q = apply_trade_date_filter(q, parse_date_param(start), parse_date_param(end), Trade)
    rows = q.order_by(Trade.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    from app.services.platform_analytics import enrich_trades

    return enrich_trades(db, rows)


@router.get("/users/{user_id}/logs", response_model=list[TradeLogOut])
def get_user_logs(
    user_id: int,
    limit: int = 200,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    sync_exchange: bool = False,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if sync_exchange:
        sync_user_binance_fills(db, user)
    q = db.query(TradeLog).filter(TradeLog.user_id == user.id)
    q = apply_log_date_filter(q, parse_date_param(start), parse_date_param(end), TradeLog)
    rows = q.order_by(TradeLog.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    return [TradeLogOut.model_validate(r) for r in rows]


@router.get("/users/{user_id}/principal-history", response_model=list[PrincipalSnapshotOut])
def admin_user_principal_history(
    user_id: int,
    limit: int = 50,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return (
        db.query(PrincipalSnapshot)
        .filter(PrincipalSnapshot.user_id == user.id)
        .order_by(PrincipalSnapshot.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )


@router.get("/users/{user_id}/referral-stats")
def admin_user_referral_stats(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return build_user_referral_stats(db, user)


@router.get("/users/{user_id}/linked-exchange-accounts")
def admin_linked_exchange_accounts(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    """List platform users sharing the same master exchange UID."""
    from app.services.sub_account_service import get_linked_accounts_for_master

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    master_uid = user.master_exchange_uid or user.exchange_uid
    if not master_uid:
        return {"master_uid": None, "accounts": []}
    exchange = user.exchange or "binance"
    accounts = get_linked_accounts_for_master(db, exchange, master_uid)
    return {"master_uid": master_uid, "exchange": exchange, "accounts": accounts}


@router.get("/users/{user_id}/sub-account-filings")
def admin_user_sub_account_filings(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    from app.services.compliance_service import list_user_sub_account_filings

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return {"filings": list_user_sub_account_filings(db, user_id)}


@router.get("/compliance/sub-account-filings")
def admin_compliance_sub_filings(
    q: str | None = None,
    exchange: str | None = None,
    limit: int = 200,
    offset: int = 0,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.compliance_service import list_sub_account_filings

    return {"items": list_sub_account_filings(db, q=q, exchange=exchange, limit=limit, offset=offset)}


@router.get("/compliance/referral-blocks")
def admin_compliance_referral_blocks(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.compliance_service import list_referral_blocks

    return {"items": list_referral_blocks(db, q=q, limit=limit, offset=offset)}


@router.get("/compliance/audit-logs")
def admin_compliance_audit_logs(
    q: str | None = None,
    limit: int = 200,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.compliance_service import list_compliance_audit_logs

    return {"items": list_compliance_audit_logs(db, q=q, limit=limit)}


@router.get("/referrals/overview")
def admin_referrals_overview(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return build_admin_referral_overview(db)


@router.post("/users/{user_id}/sync-exchange-logs")
def admin_sync_user_exchange_logs(
    user_id: int,
    days: int = 90,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return sync_user_binance_fills(db, user, days=min(max(days, 1), 180))


@router.get("/settlements", response_model=list[AdminSettlementOut])
def all_settlements(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.query(Settlement).order_by(Settlement.created_at.desc()).limit(100).all()
    out: list[AdminSettlementOut] = []
    for s in rows:
        pending = get_pending_settlement(db, s.user_id)
        deferred = False
        if pending and pending.id == s.id:
            deferred = bool(get_user_control(db, s.user_id).get("settlement_fee_deferred"))
        out.append(AdminSettlementOut(
            id=s.id,
            user_id=s.user_id,
            period_start=s.period_start,
            period_end=s.period_end,
            gross_profit=s.gross_profit or 0.0,
            net_profit=s.net_profit,
            high_water_mark=s.high_water_mark or 0.0,
            platform_fee=s.platform_fee,
            user_payable=s.user_payable,
            cycle_days=s.cycle_days or 30,
            payment_status=s.payment_status,
            payment_chain=s.payment_chain,
            payment_tx_hash=s.payment_tx_hash,
            payment_amount=s.payment_amount,
            paid_at=s.paid_at,
            confirmed_at=s.confirmed_at,
            created_at=s.created_at,
            settlement_fee_deferred=deferred,
        ))
    return out


@router.post("/settlements/run")
def trigger_settlement(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    created = run_scheduled_settlements(db)
    return {"created": len(created), "ids": [s.id for s in created]}


@router.post("/settlements/run-scheduled")
@router.post("/settlements/run-monthly")
@router.post("/settlements/run-weekly")
def trigger_scheduled_settlement(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    created = run_scheduled_settlements(db)
    return {"created": len(created), "ids": [s.id for s in created]}


@router.post("/settlements/{settlement_id}/confirm")
def confirm_settlement(
    settlement_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if not s:
        raise HTTPException(404, "Settlement not found")
    if s.payment_status == PaymentStatus.CONFIRMED.value:
        raise HTTPException(400, "Settlement already confirmed")
    if s.payment_status == PaymentStatus.REJECTED.value:
        raise HTTPException(400, "Settlement was rejected")
    if s.payment_status != PaymentStatus.PAID.value:
        raise HTTPException(400, "Settlement must be paid before confirmation")
    confirm_settlement_payment(db, s)
    log_audit(
        db,
        "settlement.confirm",
        user_id=s.user_id,
        actor_id=admin.id,
        resource_type="settlement",
        resource_id=str(s.id),
        detail={"user_payable": s.user_payable, "net_profit": s.net_profit},
        request=request,
    )
    return {"status": "confirmed"}


@router.post("/settlements/{settlement_id}/reject")
def reject_settlement(
    settlement_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if not s:
        raise HTTPException(404, "Settlement not found")
    if s.payment_status == PaymentStatus.CONFIRMED.value:
        raise HTTPException(400, "Settlement already confirmed")
    try:
        reject_settlement_payment(db, s)
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "settlement.reject",
        user_id=s.user_id,
        actor_id=admin.id,
        resource_type="settlement",
        resource_id=str(s.id),
        request=request,
    )
    db.commit()
    return {"status": "rejected"}


# --- Platform deposit addresses ---

def _deposit_address_out(addr: PlatformDepositAddress) -> DepositAddressOut:
    return DepositAddressOut.from_model(addr)


@router.get("/deposit-addresses", response_model=list[DepositAddressOut])
def list_deposit_addresses(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.query(PlatformDepositAddress).order_by(
        PlatformDepositAddress.sort_order, PlatformDepositAddress.id
    ).all()
    return [_deposit_address_out(a) for a in rows]


@router.post("/deposit-addresses", response_model=DepositAddressOut)
def create_deposit_address(
    req: DepositAddressCreate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if req.chain.upper() not in SUPPORTED_CHAINS:
        raise HTTPException(400, f"Unsupported chain. Supported: {', '.join(SUPPORTED_CHAINS)}")
    addr = PlatformDepositAddress(
        chain=req.chain.upper(),
        address=req.address.strip(),
        label=req.label,
        sort_order=req.sort_order,
    )
    db.add(addr)
    db.flush()
    log_audit(
        db,
        "deposit_address.create",
        actor_id=admin.id,
        resource_type="deposit_address",
        resource_id=str(addr.id),
        detail={
            "chain": addr.chain,
            "address": addr.address,
            "label": addr.label,
            "is_active": addr.is_active,
        },
        request=request,
    )
    db.commit()
    db.refresh(addr)
    return _deposit_address_out(addr)


@router.patch("/deposit-addresses/{addr_id}", response_model=DepositAddressOut)
def update_deposit_address(
    addr_id: int,
    req: DepositAddressUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    before = {
        "chain": addr.chain,
        "address": addr.address,
        "label": addr.label,
        "sort_order": addr.sort_order,
        "is_active": addr.is_active,
    }
    if req.chain is not None:
        if req.chain.upper() not in SUPPORTED_CHAINS:
            raise HTTPException(400, f"Unsupported chain. Supported: {', '.join(SUPPORTED_CHAINS)}")
        addr.chain = req.chain.upper()
    if req.address is not None:
        addr.address = req.address.strip()
    if req.label is not None:
        addr.label = req.label
    if req.sort_order is not None:
        addr.sort_order = req.sort_order
    if req.is_active is not None:
        addr.is_active = req.is_active
    log_audit(
        db,
        "deposit_address.update",
        actor_id=admin.id,
        resource_type="deposit_address",
        resource_id=str(addr.id),
        detail={
            "before": before,
            "after": {
                "chain": addr.chain,
                "address": addr.address,
                "label": addr.label,
                "sort_order": addr.sort_order,
                "is_active": addr.is_active,
            },
        },
        request=request,
    )
    db.commit()
    db.refresh(addr)
    return _deposit_address_out(addr)


@router.post("/deposit-addresses/{addr_id}/qr-image", response_model=DepositAddressOut)
async def upload_deposit_qr_image(
    addr_id: int,
    request: Request,
    file: UploadFile = File(...),
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    if addr.qr_image_filename:
        delete_deposit_qr(addr.qr_image_filename)
    addr.qr_image_filename = await save_deposit_qr(addr_id, file)
    log_audit(
        db,
        "deposit_address.qr_upload",
        actor_id=admin.id,
        resource_type="deposit_address",
        resource_id=str(addr.id),
        detail={"chain": addr.chain, "address": addr.address, "qr_image_filename": addr.qr_image_filename},
        request=request,
    )
    db.commit()
    db.refresh(addr)
    return _deposit_address_out(addr)


@router.delete("/deposit-addresses/{addr_id}/qr-image", response_model=DepositAddressOut)
def remove_deposit_qr_image(
    addr_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    if addr.qr_image_filename:
        delete_deposit_qr(addr.qr_image_filename)
        old = addr.qr_image_filename
        addr.qr_image_filename = None
        log_audit(
            db,
            "deposit_address.qr_delete",
            actor_id=admin.id,
            resource_type="deposit_address",
            resource_id=str(addr.id),
            detail={"chain": addr.chain, "removed": old},
            request=request,
        )
        db.commit()
        db.refresh(addr)
    return _deposit_address_out(addr)


@router.post("/deposit-addresses/{addr_id}/toggle")
def toggle_deposit_address(
    addr_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    addr.is_active = not addr.is_active
    log_audit(
        db,
        "deposit_address.toggle",
        actor_id=admin.id,
        resource_type="deposit_address",
        resource_id=str(addr.id),
        detail={"chain": addr.chain, "address": addr.address, "is_active": addr.is_active},
        request=request,
    )
    db.commit()
    return {"id": addr.id, "is_active": addr.is_active}


@router.delete("/deposit-addresses/{addr_id}")
def delete_deposit_address(
    addr_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    snapshot = {
        "chain": addr.chain,
        "address": addr.address,
        "label": addr.label,
        "is_active": addr.is_active,
    }
    delete_deposit_qr(addr.qr_image_filename)
    db.delete(addr)
    log_audit(
        db,
        "deposit_address.delete",
        actor_id=admin.id,
        resource_type="deposit_address",
        resource_id=str(addr_id),
        detail=snapshot,
        request=request,
    )
    db.commit()
    return {"status": "ok"}


@router.get("/withdraw/settings")
def admin_withdraw_settings(admin=Depends(get_admin_user)):
    thresholds = get_withdraw_thresholds()
    payout = get_payout_status()
    return {
        **thresholds,
        "payout_auto_enabled": payout.enabled,
        "payout_configured_chains": payout.configured_chains,
    }


@router.patch("/withdraw/settings")
def admin_update_withdraw_settings(
    req: WithdrawThresholdsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    before = get_withdraw_thresholds()
    try:
        updated = set_withdraw_thresholds(
            auto_max_usd=req.auto_max_usd,
            review_min_usd=req.review_min_usd,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "withdraw_threshold.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="withdraw_thresholds",
        detail={
            "before": {
                "auto_max_usd": before["auto_max_usd"],
                "review_min_usd": before["review_min_usd"],
            },
            "after": {
                "auto_max_usd": updated["auto_max_usd"],
                "review_min_usd": updated["review_min_usd"],
            },
        },
        request=request,
    )
    payout = get_payout_status()
    return {
        **updated,
        "payout_auto_enabled": payout.enabled,
        "payout_configured_chains": payout.configured_chains,
    }


@router.get("/payout/settings", response_model=PayoutSettingsOut)
def admin_payout_settings(admin=Depends(get_admin_user)):
    return get_payout_settings()


@router.patch("/payout/settings", response_model=PayoutSettingsOut)
def admin_update_payout_settings(
    req: PayoutSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        updated = update_payout_keys(
            auto_enabled=req.auto_enabled,
            keys=req.private_keys,
            clear_chains=req.clear_chains,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "payout_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="payout_keys",
        detail={
            "auto_enabled": updated.get("auto_enabled"),
            "configured_chains": [c for c, ok in (updated.get("chains") or {}).items() if ok],
        },
        request=request,
    )
    return updated


@router.get("/deposit/wallet-settings", response_model=DepositWalletSettingsOut)
def admin_deposit_wallet_settings(admin=Depends(get_admin_user)):
    return get_deposit_wallet_settings()


@router.patch("/deposit/wallet-settings", response_model=DepositWalletSettingsUpdateResult)
def admin_update_deposit_wallet_settings(
    req: DepositWalletSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        if req.clear:
            updated = update_deposit_mnemonic(clear=True)
        elif req.mnemonic and req.mnemonic.strip():
            updated = update_deposit_mnemonic(mnemonic=req.mnemonic)
        else:
            raise HTTPException(400, "请提供助记词 mnemonic，或设置 clear=true 清除后台配置")
    except ValueError as e:
        raise HTTPException(400, str(e))

    backfilled = 0
    if req.backfill and is_deposit_mnemonic_configured():
        backfilled = backfill_all_user_deposit_addresses(db)

    log_audit(
        db,
        "deposit_wallet_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="deposit_hd_mnemonic",
        detail={
            "configured": updated.get("configured"),
            "source": updated.get("source"),
            "cleared": req.clear,
            "users_backfilled": backfilled,
        },
        request=request,
    )
    return {**updated, "users_backfilled": backfilled}


def _sweep_log_out(db: Session, row: DepositSweepLog) -> dict:
    user = db.query(User).filter(User.id == row.user_id).first()
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_uid": user.uid if user else "",
        "chain": row.chain,
        "from_address": row.from_address,
        "to_address": row.to_address,
        "amount": row.amount,
        "status": row.status,
        "gas_tx_hash": row.gas_tx_hash,
        "sweep_tx_hash": row.sweep_tx_hash,
        "error_message": row.error_message,
        "created_at": row.created_at,
    }


@router.get("/wallet/overview", response_model=WalletOverviewOut)
def admin_wallet_overview(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    """On-chain balances + wallet config summary for admin hub."""
    return get_wallet_overview(db)


@router.get("/sweep/settings", response_model=DepositSweepSettingsOut)
def admin_sweep_settings(admin=Depends(get_admin_user)):
    return get_sweep_settings()


@router.patch("/sweep/settings", response_model=DepositSweepSettingsOut)
def admin_update_sweep_settings(
    req: DepositSweepSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        updated = update_sweep_settings(
            auto_enabled=req.auto_enabled,
            min_usdt=req.min_usdt,
            require_matched_deposit=req.require_matched_deposit,
            cold_wallets=req.cold_wallets,
            gas_funder_keys=req.gas_funder_keys,
            clear_gas_funder=req.clear_gas_funder,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "sweep_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="deposit_sweep",
        detail={
            "auto_enabled": updated.get("auto_enabled"),
            "ready_chains": updated.get("ready_chains"),
        },
        request=request,
    )
    return updated


@router.get("/sweep/logs", response_model=list[DepositSweepLogOut])
def admin_sweep_logs(
    limit: int = 100,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DepositSweepLog)
        .order_by(DepositSweepLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [_sweep_log_out(db, r) for r in rows]


@router.post("/sweep/run")
def admin_run_sweep(
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    stats = run_deposit_sweep(db, force=True)
    log_audit(
        db,
        "sweep.manual_run",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="deposit_sweep",
        detail=stats,
        request=request,
    )
    return stats


@router.get("/webhook/logs", response_model=list[WebhookReceiveLogOut])
def admin_webhook_logs(
    limit: int = 100,
    action: str | None = None,
    event_status: str | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    q = db.query(WebhookReceiveLog).order_by(WebhookReceiveLog.created_at.desc())
    if action:
        q = q.filter(WebhookReceiveLog.action == action.upper())
    if event_status:
        q = q.filter(WebhookReceiveLog.event_status == event_status.lower())
    rows = q.limit(min(limit, 500)).all()
    return [webhook_log_to_dict(row, include_payload=False) for row in rows]


@router.get("/webhook/logs/{log_id}", response_model=WebhookReceiveLogDetailOut)
def admin_webhook_log_detail(
    log_id: int,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    detail = get_webhook_log_detail(db, log_id)
    if not detail:
        raise HTTPException(404, "Webhook log not found")
    return detail


@router.get("/platform/public-settings", response_model=PlatformPublicSettingsOut)
def admin_platform_public_settings(admin=Depends(get_admin_user)):
    from app.services.platform_public_settings import get_platform_public_settings

    return get_platform_public_settings()


@router.patch("/platform/public-settings", response_model=PlatformPublicSettingsOut)
def admin_update_platform_public_settings(
    req: PlatformPublicSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    from app.services.platform_public_settings import update_platform_public_settings

    try:
        updated = update_platform_public_settings(
            enabled_exchanges=req.enabled_exchanges,
            support_telegram=req.support_telegram,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "platform_public_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="platform_public",
        detail={
            "enabled_exchanges": updated.get("enabled_exchanges"),
            "has_support_telegram": bool(updated.get("support_telegram")),
        },
        request=request,
    )
    return updated


@router.get("/dingtalk/settings", response_model=DingTalkSettingsOut)
def admin_dingtalk_settings(admin=Depends(get_admin_user)):
    return get_dingtalk_settings()


@router.patch("/dingtalk/settings", response_model=DingTalkSettingsOut)
def admin_update_dingtalk_settings(
    req: DingTalkSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        updated = update_dingtalk_settings(
            webhook=req.webhook,
            secret=req.secret,
            clear=req.clear,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "dingtalk_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="dingtalk",
        detail={"configured": updated.get("configured"), "cleared": req.clear},
        request=request,
    )
    return updated


@router.get("/chain-rpc/settings", response_model=ChainRpcSettingsOut)
def admin_chain_rpc_settings(admin=Depends(get_admin_user)):
    return get_chain_rpc_settings()


@router.patch("/chain-rpc/settings", response_model=ChainRpcSettingsOut)
def admin_update_chain_rpc_settings(
    req: ChainRpcSettingsUpdate,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    try:
        updated = update_chain_rpc_settings(
            rpc_urls=req.rpc_urls,
            tron_api_url=req.tron_api_url,
            tron_api_key=req.tron_api_key,
            clear=req.clear,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "chain_rpc_settings.update",
        actor_id=admin.id,
        resource_type="platform_settings",
        resource_id="chain_rpc",
        detail={"has_runtime": updated.get("has_runtime"), "cleared": req.clear},
        request=request,
    )
    return updated


@router.post("/settings/change-password")
def admin_change_password(
    req: AdminPasswordChange,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if not verify_password(req.current_password, admin.password_hash):
        raise HTTPException(400, "当前密码不正确")
    if verify_password(req.new_password, admin.password_hash):
        raise HTTPException(400, "新密码不能与当前密码相同")
    admin.password_hash = hash_password(req.new_password)
    log_audit(
        db,
        "admin.password_change",
        actor_id=admin.id,
        resource_type="user",
        resource_id=str(admin.id),
        request=request,
    )
    db.commit()
    return {"status": "ok"}


@router.get("/settlement-deposits", response_model=list[AdminSettlementDepositOut])
def admin_list_settlement_deposits(
    status: str | None = None,
    user_id: int | None = None,
    limit: int = 100,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    q = db.query(SettlementDeposit).order_by(SettlementDeposit.detected_at.desc())
    if status:
        q = q.filter(SettlementDeposit.status == status)
    if user_id:
        q = q.filter(SettlementDeposit.user_id == user_id)
    rows = q.limit(min(limit, 500)).all()
    return [build_admin_deposit_row(db, r) for r in rows]


@router.get("/settlement-appeals", response_model=list[AdminSettlementAppealOut])
def admin_list_settlement_appeals(
    status: str | None = None,
    limit: int = 100,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    q = db.query(SettlementPaymentAppeal).order_by(SettlementPaymentAppeal.created_at.desc())
    if status:
        q = q.filter(SettlementPaymentAppeal.status == status)
    rows = q.limit(min(limit, 500)).all()
    return [build_admin_appeal_row(db, r) for r in rows]


@router.post("/settlement-appeals/{appeal_id}/approve", response_model=AdminSettlementAppealOut)
def admin_approve_settlement_appeal(
    appeal_id: int,
    body: SettlementAppealReview,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    appeal = db.query(SettlementPaymentAppeal).filter(SettlementPaymentAppeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "Appeal not found")
    try:
        updated = approve_payment_appeal(db, appeal, admin.id, body.admin_note or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "settlement.appeal_approve",
        user_id=appeal.user_id,
        actor_id=admin.id,
        resource_type="settlement_appeal",
        resource_id=str(appeal.id),
        detail={"settlement_id": appeal.settlement_id, "tx_hash": appeal.tx_hash},
        request=request,
    )
    return build_admin_appeal_row(db, updated)


@router.post("/settlement-appeals/{appeal_id}/reject", response_model=AdminSettlementAppealOut)
def admin_reject_settlement_appeal(
    appeal_id: int,
    body: SettlementAppealReview,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    appeal = db.query(SettlementPaymentAppeal).filter(SettlementPaymentAppeal.id == appeal_id).first()
    if not appeal:
        raise HTTPException(404, "Appeal not found")
    try:
        updated = reject_payment_appeal(db, appeal, admin.id, body.admin_note or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    log_audit(
        db,
        "settlement.appeal_reject",
        user_id=appeal.user_id,
        actor_id=admin.id,
        resource_type="settlement_appeal",
        resource_id=str(appeal.id),
        detail={"settlement_id": appeal.settlement_id, "admin_note": body.admin_note},
        request=request,
    )
    return build_admin_appeal_row(db, updated)


# --- Withdrawals ---

@router.get("/withdrawals", response_model=list[WithdrawalOut])
def list_withdrawals(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return db.query(WithdrawalRequest).order_by(
        WithdrawalRequest.created_at.desc()
    ).limit(100).all()


@router.post("/withdrawals/{withdrawal_id}/approve")
def approve_withdrawal(withdrawal_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status not in (WithdrawalStatus.PENDING.value, WithdrawalStatus.AUTO_APPROVED.value):
        raise HTTPException(400, "Withdrawal cannot be approved")
    req.status = WithdrawalStatus.APPROVED.value
    db.commit()
    return {"status": "approved"}


@router.post("/withdrawals/{withdrawal_id}/complete", response_model=WithdrawalOut)
def complete_withdrawal_route(
    withdrawal_id: int,
    body: WithdrawalComplete,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status in (WithdrawalStatus.COMPLETED.value, WithdrawalStatus.REJECTED.value):
        raise HTTPException(400, "Withdrawal already processed")
    result = complete_withdrawal(db, req, body.tx_hash.strip(), body.admin_note)
    log_audit(
        db,
        "withdrawal.complete",
        user_id=req.user_id,
        actor_id=admin.id,
        resource_type="withdrawal",
        resource_id=str(req.id),
        detail={"tx_hash": body.tx_hash.strip(), "manual": True},
        request=request,
    )
    return result


@router.post("/withdrawals/{withdrawal_id}/reject", response_model=WithdrawalOut)
def reject_withdrawal_route(
    withdrawal_id: int,
    body: WithdrawalReject,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status in (WithdrawalStatus.COMPLETED.value, WithdrawalStatus.REJECTED.value):
        raise HTTPException(400, "Withdrawal already processed")
    return reject_withdrawal(db, req, body.admin_note)


@router.get("/startup-audit")
def startup_audit(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    """VPS 自启账户接管审计 + 生产配置检查（管理员查看）。"""
    from app.services.startup_audit import validate_production_secrets, validate_production_infra

    sec = validate_production_secrets()
    return {
        "active_supervisors": len(supervisor_pool.get_all()),
        "audits": supervisor_pool.last_startup_audits,
        "failures": supervisor_pool.last_startup_failures,
        "security_warnings": sec,
        "production_ready": len(sec) == 0,
        "infra_notes": validate_production_infra(db),
    }


@router.get("/alerts", response_model=list[AdminAlertOut])
def get_alerts(
    unread_only: bool = False,
    limit: int = 100,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    alerts = list_alerts(db, unread_only=unread_only, limit=limit, system_only=True)
    return [
        AdminAlertOut(
            id=a.id,
            user_id=a.user_id,
            uid=None,
            severity=a.severity,
            alert_type=a.alert_type,
            title=a.title,
            message=a.message,
            detail_json=a.detail_json,
            is_read=a.is_read,
            created_at=a.created_at,
        )
        for a in alerts
    ]


@router.post("/alerts/{alert_id}/read")
def read_alert(alert_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    if not mark_alert_read(db, alert_id):
        raise HTTPException(404, "Alert not found")
    return {"status": "ok"}


@router.post("/alerts/read-all")
def read_all_alerts(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    count = mark_all_read(db, system_only=True)
    return {"status": "ok", "marked": count}


# --- Strategy review ---

def _strategy_admin_out(s: Strategy, user: User) -> dict:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user_uid": user.uid,
        "user_email": user.email or "",
        "user_nickname": user.nickname or "",
        "name": s.name,
        "description": s.description or "",
        "strategy_type": s.strategy_type,
        "status": s.status,
        "sharpe": s.sharpe,
        "profit_factor": s.profit_factor,
        "max_drawdown": s.max_drawdown,
        "win_rate": s.win_rate,
        "total_pnl": s.total_pnl,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("/strategies")
def list_strategies(
    status: str | None = None,
    limit: int = 200,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    q = db.query(Strategy, User).join(User, Strategy.user_id == User.id)
    if status:
        q = q.filter(Strategy.status == status)
    rows = q.order_by(Strategy.created_at.desc()).limit(min(limit, 500)).all()
    return [_strategy_admin_out(s, u) for s, u in rows]


@router.post("/strategies/{strategy_id}/review")
def review_strategy(
    strategy_id: int,
    body: dict,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    s = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not s:
        raise HTTPException(404, "Strategy not found")
    action = (body.get("action") or "").strip().lower()
    if action not in ("approve", "reject", "pause"):
        raise HTTPException(400, "action must be approve, reject, or pause")
    note = (body.get("note") or "").strip()
    if action == "approve":
        s.status = "active"
    else:
        s.status = "paused"
    log_audit(
        db,
        f"strategy.{action}",
        user_id=s.user_id,
        actor_id=admin.id,
        resource_type="strategy",
        resource_id=str(s.id),
        detail={"note": note} if note else None,
    )
    db.commit()
    db.refresh(s)
    user = db.query(User).filter(User.id == s.user_id).first()
    return _strategy_admin_out(s, user)


# --- User intervention ---

@router.get("/users/{user_id}/trading-control")
def admin_get_user_trading_control(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return build_trading_control_response(db, user)


@router.patch("/users/{user_id}/trading-control")
def admin_user_trading_control(
    user_id: int,
    body: dict,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if "settlement_fee_deferred" in body:
        want_defer = bool(body["settlement_fee_deferred"])
        if want_defer and not user_has_unsettled_payment(db, user_id):
            raise HTTPException(400, "No pending settlement to defer")
        if want_defer and user.role == UserRole.ADMIN.value:
            raise HTTPException(400, "Cannot defer settlement for admin account")
    if body.get("referral_invite_override") and not (body.get("referral_override_note") or "").strip():
        raise HTTPException(400, "referral_override_note required when enabling invite override")
    try:
        ctrl = set_user_control(
            db,
            user_id,
            trading_paused=body.get("trading_paused") if "trading_paused" in body else None,
            risk_level=body.get("risk_level") if "risk_level" in body else None,
            settlement_fee_deferred=body.get("settlement_fee_deferred") if "settlement_fee_deferred" in body else None,
            settlement_defer_note=body.get("settlement_defer_note") if "settlement_defer_note" in body else None,
            referral_invite_override=body.get("referral_invite_override") if "referral_invite_override" in body else None,
            referral_override_note=body.get("referral_override_note") if "referral_override_note" in body else None,
        )
    except ValueError:
        raise HTTPException(400, "Invalid risk_level")
    audit_detail = {
        "trading_paused": ctrl.get("trading_paused"),
        "risk_level": ctrl.get("risk_level"),
    }
    if "settlement_fee_deferred" in body:
        audit_detail["settlement_fee_deferred"] = ctrl.get("settlement_fee_deferred")
    if "referral_invite_override" in body:
        audit_detail["referral_invite_override"] = ctrl.get("referral_invite_override")
    log_audit(
        db,
        "admin.trading_control",
        user_id=user_id,
        actor_id=admin.id,
        resource_type="trading_control",
        resource_id=str(user_id),
        detail=audit_detail,
        request=request,
    )
    return build_trading_control_response(db, user)


@router.post("/users/{user_id}/force-close")
def admin_force_close(
    user_id: int,
    request: Request,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.api_status != ApiStatus.ACTIVE.value or not user.api_key_enc:
        raise HTTPException(400, "User API not active")

    result = _initiate_force_close(db, user, reason="Admin emergency force close")
    if result.get("status") == "error":
        raise HTTPException(500, result.get("message") or "Force close failed")
    if result.get("status") == "skipped":
        raise HTTPException(400, result.get("message") or "User API not active")

    log_audit(
        db,
        "admin.force_close",
        user_id=user_id,
        actor_id=admin.id,
        resource_type="user",
        resource_id=str(user_id),
        request=request,
    )
    return {"status": "closing", "message": "Force close initiated"}


# --- TV signal templates ---

@router.get("/signal-templates")
def list_signal_templates(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.query(TvSignalTemplate).order_by(TvSignalTemplate.created_at.desc()).all()
    return [template_to_dict(r) for r in rows]


@router.post("/signal-templates")
def create_signal_template(body: dict, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    payload = body.get("payload") or {}
    row = TvSignalTemplate(
        name=name,
        description=(body.get("description") or "").strip(),
        payload_json=json.dumps(payload),
        enabled=bool(body.get("enabled", True)),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit(db, "signal_template.create", actor_id=admin.id, resource_type="signal_template", resource_id=str(row.id))
    return template_to_dict(row)


@router.patch("/signal-templates/{template_id}")
def update_signal_template(template_id: int, body: dict, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    row = db.query(TvSignalTemplate).filter(TvSignalTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    if "name" in body:
        row.name = (body["name"] or "").strip() or row.name
    if "description" in body:
        row.description = body["description"] or ""
    if "payload" in body:
        row.payload_json = json.dumps(body["payload"] or {})
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    db.commit()
    db.refresh(row)
    log_audit(db, "signal_template.update", actor_id=admin.id, resource_type="signal_template", resource_id=str(row.id))
    return template_to_dict(row)


@router.delete("/signal-templates/{template_id}")
def delete_signal_template(template_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    row = db.query(TvSignalTemplate).filter(TvSignalTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    db.delete(row)
    db.commit()
    log_audit(db, "signal_template.delete", actor_id=admin.id, resource_type="signal_template", resource_id=str(template_id))
    return {"status": "deleted"}


@router.post("/signal-templates/{template_id}/test")
def test_signal_template(template_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    row = db.query(TvSignalTemplate).filter(TvSignalTemplate.id == template_id).first()
    if not row:
        raise HTTPException(404, "Template not found")
    try:
        template_payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        template_payload = {}
    payload = build_test_payload(template_payload)
    dispatch_row, result = run_signal_dispatch(db, payload, source="admin_test", template_id=row.id)
    log_audit(db, "signal_template.test", actor_id=admin.id, resource_type="signal_template", resource_id=str(template_id))
    return {
        "status": dispatch_row.status,
        "dispatch_id": dispatch_row.id,
        "dispatched": dispatch_row.dispatched_count,
        "errors": dispatch_row.error_count,
        "skipped": dispatch_row.skipped_count,
        "result": result,
    }
