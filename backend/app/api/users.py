from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User, Trade, TradeLog, ApiStatus, PrincipalSnapshot, ExchangeType
from app.core.exchange_factory import exchange_requires_passphrase, parse_exchange
from app.schemas import (
    ApiBindRequest, ApiVerifyResponse, ApiVerifyCheckItem, UserProfile, DashboardStats,
    TradeOut, TradeLogOut, PrincipalSnapshotOut, UserAnalyticsOut, SignalStatsOut,
)
from app.api.deps import get_current_user
from app.utils.crypto import encrypt_text, decrypt_text
from app.services.dispatcher import supervisor_pool
from app.services.api_validation import validate_exchange_api
from app.services.principal import start_new_profit_cycle
from app.services.analytics import build_user_analytics, build_signal_stats
from app.services.platform_analytics import enrich_trades
from app.services.verification import verify_security_dual
from app.services.trading_control import (
    get_user_control,
    set_user_control,
    is_globally_paused,
    build_trading_control_response,
)
from app.services.audit import log_audit
from app.services.query_filters import parse_date_param, apply_trade_date_filter, apply_log_date_filter
from app.services.binance_sync import sync_user_binance_fills
from app.i18n import get_locale, t, translate_api_message
from app.i18n.errors import raise_i18n

router = APIRouter(prefix="/users", tags=["users"])


def _verify_response(result: dict) -> ApiVerifyResponse:
    localized = translate_api_message(result, get_locale())
    equity = float(localized.get("total_balance") or localized.get("total_margin_balance") or 0)
    checks_raw = result.get("checks") or []
    checks = [
        ApiVerifyCheckItem(
            id=str(c.get("id", "")),
            ok=bool(c.get("ok")),
            hint_key=c.get("hint_key"),
        )
        for c in checks_raw
    ]
    return ApiVerifyResponse(
        valid=bool(localized.get("valid")),
        message=localized.get("message", ""),
        total_balance=equity,
        available_balance=float(result.get("available_balance", 0)),
        wallet_balance=float(result.get("wallet_balance") or result.get("total_wallet_balance") or 0),
        unrealized_pnl=float(result.get("unrealized_pnl", 0)),
        can_trade=bool(result.get("can_trade", True)),
        one_way_mode=bool(result.get("one_way_mode", False)),
        leverage_ok=bool(result.get("leverage_ok", False)),
        withdraw_disabled=result.get("withdraw_disabled"),
        enable_futures=result.get("enable_futures"),
        symbol=result.get("symbol", "ETHUSDT"),
        symbol_price=float(result.get("symbol_price", 0)),
        leverage=int(result.get("leverage", 20)),
        initial_principal=equity if result.get("valid") else 0,
        detail=localized.get("detail"),
        checks=checks,
        checks_passed=int(result.get("checks_passed") or sum(1 for c in checks if c.ok)),
        checks_total=int(result.get("checks_total") or len(checks)),
        open_orders_count=int(result.get("open_orders_count") or 0),
        open_positions_count=int(result.get("open_positions_count") or 0),
        hedge_mode=result.get("hedge_mode"),
        exchange=result.get("exchange", "binance"),
    )


@router.get("/profile", response_model=UserProfile)
def profile(user: User = Depends(get_current_user)):
    from app.services.user_account import build_user_profile
    return build_user_profile(user)


@router.post("/bind-api/verify", response_model=ApiVerifyResponse)
def verify_bind_api(req: ApiBindRequest, user: User = Depends(get_current_user)):
    """绑定前校验：连接、余额、交易权限、单向持仓、杠杆。"""
    ex = parse_exchange(req.exchange)
    if ex is None:
        raise_i18n(400, "api.unsupported_exchange")
    result = validate_exchange_api(
        ex,
        req.api_key,
        req.api_secret,
        user.id,
        req.passphrase or "",
    )
    return _verify_response(result)


@router.get("/api-status", response_model=ApiVerifyResponse)
def api_status(user: User = Depends(get_current_user)):
    """已绑定用户复查 API 是否仍可用。"""
    if not user.api_key_enc or not user.api_secret_enc:
        raise_i18n(400, "api.not_bound")
    ex = user.exchange or ExchangeType.BINANCE.value
    passphrase = decrypt_text(user.passphrase_enc) if user.passphrase_enc else ""
    result = validate_exchange_api(
        ex,
        decrypt_text(user.api_key_enc),
        decrypt_text(user.api_secret_enc),
        user.id,
        passphrase,
    )
    resp = _verify_response(result)
    if user.initial_principal:
        resp.initial_principal = float(user.initial_principal)
    return resp


@router.post("/bind-api")
def bind_api(req: ApiBindRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.email and user.phone:
        if not req.email_code or not req.phone_code:
            raise_i18n(400, "api.security_codes_required")
        verify_security_dual(db, user, req.email_code, req.phone_code)

    ex = parse_exchange(req.exchange)
    if ex is None:
        raise_i18n(400, "api.unsupported_exchange")
    if exchange_requires_passphrase(ex) and not (req.passphrase or "").strip():
        raise_i18n(400, "api.passphrase_required")

    result = validate_exchange_api(
        ex,
        req.api_key,
        req.api_secret,
        user.id,
        req.passphrase or "",
    )
    if not result.get("valid"):
        localized = translate_api_message(result, get_locale())
        raise HTTPException(400, localized.get("message") or t("api.verify_fail", get_locale()))

    equity = float(result.get("total_balance", 0))
    user.exchange = ex
    user.api_key_enc = encrypt_text(req.api_key)
    user.api_secret_enc = encrypt_text(req.api_secret)
    user.passphrase_enc = encrypt_text(req.passphrase) if exchange_requires_passphrase(ex) else None
    user.api_status = ApiStatus.ACTIVE.value

    start_new_profit_cycle(
        db, user,
        snapshot_type="api_bind",
        equity=equity,
        note="首次绑定 API，记载初始本金",
    )
    db.commit()

    supervisor_pool.remove_user(user.id)
    supervisor_pool.add_user(user)
    return {
        "status": "ok",
        "api_status": user.api_status,
        "initial_principal": user.initial_principal,
        "message": t("api.bind_success", get_locale(), amount=f"{user.initial_principal:.2f}"),
    }


@router.delete("/bind-api")
def unbind_api(
    email_code: str,
    phone_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.verification import verify_security_dual
    from app.models import ApiStatus

    if not user.api_key_enc:
        raise HTTPException(400, "No API bound")
    if user.email and user.phone:
        verify_security_dual(db, user, email_code, phone_code)

    supervisor_pool.remove_user(user.id)
    user.api_key_enc = None
    user.api_secret_enc = None
    user.passphrase_enc = None
    user.exchange = ExchangeType.BINANCE.value
    user.api_status = ApiStatus.NONE.value
    db.commit()
    return {"status": "ok", "api_status": user.api_status}


@router.get("/positions")
def positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.user_account import build_dashboard_stats
    dash = build_dashboard_stats(db, user)
    return {
        "open_position": dash.open_position,
        "balance": dash.balance,
        "unrealized_pnl": dash.unrealized_pnl,
        "symbol": dash.symbol if hasattr(dash, "symbol") else "ETHUSDT",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/principal-history", response_model=list[PrincipalSnapshotOut])
def principal_history(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(PrincipalSnapshot)
        .filter(PrincipalSnapshot.user_id == user.id)
        .order_by(PrincipalSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.user_account import build_dashboard_stats
    return build_dashboard_stats(db, user)


@router.get("/trades", response_model=list[TradeOut])
def trades(
    limit: int = 200,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Trade).filter(Trade.user_id == user.id)
    q = apply_trade_date_filter(q, parse_date_param(start), parse_date_param(end), Trade)
    rows = q.order_by(Trade.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    return [TradeOut(**row) for row in enrich_trades(db, rows)]


@router.get("/logs", response_model=list[TradeLogOut])
def logs(
    limit: int = 200,
    offset: int = 0,
    start: str | None = None,
    end: str | None = None,
    sync_exchange: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if sync_exchange:
        sync_user_binance_fills(db, user)
    q = db.query(TradeLog).filter(TradeLog.user_id == user.id)
    q = apply_log_date_filter(q, parse_date_param(start), parse_date_param(end), TradeLog)
    rows = q.order_by(TradeLog.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    return [TradeLogOut.model_validate(r) for r in rows]


@router.post("/sync-exchange-logs")
def sync_exchange_logs(
    days: int = 90,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull ETHUSDT perpetual fills from Binance into execution logs."""
    return sync_user_binance_fills(db, user, days=min(max(days, 1), 180))


@router.get("/analytics", response_model=UserAnalyticsOut)
def analytics(days: int = 90, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_user_analytics(db, user.id, days=min(max(days, 7), 365))


@router.get("/signals", response_model=SignalStatsOut)
def signals(limit: int = 100, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_signal_stats(db, user.id, limit=min(max(limit, 10), 200))


@router.get("/trading-control")
def trading_control(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_trading_control_response(db, user)


@router.patch("/trading-control")
def update_trading_control(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ctrl = set_user_control(
            db,
            user.id,
            trading_paused=body.get("trading_paused") if "trading_paused" in body else None,
            risk_level=body.get("risk_level") if "risk_level" in body else None,
        )
    except ValueError:
        raise HTTPException(400, "Invalid risk_level")
    log_audit(
        db,
        "trading_control.update",
        user_id=user.id,
        resource_type="trading_control",
        resource_id=str(user.id),
        detail={"trading_paused": ctrl.get("trading_paused"), "risk_level": ctrl.get("risk_level")},
        request=request,
    )
    return build_trading_control_response(db, user)
