import json
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, Trade, TradeLog, ApiStatus, PrincipalSnapshot
from app.schemas import (
    ApiBindRequest, ApiVerifyResponse, UserProfile, DashboardStats,
    TradeOut, TradeLogOut, PrincipalSnapshotOut,
)
from app.services.user_lookup import display_name
from app.api.deps import get_current_user
from app.utils.crypto import encrypt_text, decrypt_text
from app.services.dispatcher import supervisor_pool
from app.services.api_validation import validate_binance_api
from app.services.principal import fetch_live_equity, start_new_profit_cycle

router = APIRouter(prefix="/users", tags=["users"])


def _verify_response(result: dict) -> ApiVerifyResponse:
    equity = float(result.get("total_balance") or result.get("total_margin_balance") or 0)
    return ApiVerifyResponse(
        valid=bool(result.get("valid")),
        message=result.get("message", ""),
        total_balance=equity,
        available_balance=float(result.get("available_balance", 0)),
        wallet_balance=float(result.get("wallet_balance") or result.get("total_wallet_balance") or 0),
        unrealized_pnl=float(result.get("unrealized_pnl", 0)),
        can_trade=bool(result.get("can_trade", True)),
        one_way_mode=bool(result.get("one_way_mode", False)),
        leverage_ok=bool(result.get("leverage_ok", False)),
        symbol=result.get("symbol", "ETHUSDT"),
        symbol_price=float(result.get("symbol_price", 0)),
        leverage=int(result.get("leverage", 15)),
        initial_principal=equity if result.get("valid") else 0,
        detail=result.get("detail"),
    )


@router.get("/profile", response_model=UserProfile)
def profile(user: User = Depends(get_current_user)):
    return UserProfile(
        id=user.id,
        uid=user.uid,
        email=user.email,
        phone=user.phone,
        nickname=user.nickname,
        display_name=display_name(user),
        referral_code=user.referral_code,
        api_status=user.api_status,
        role=user.role,
        is_active=user.is_active,
        high_water_mark=user.high_water_mark,
        has_withdraw_password=bool(user.withdraw_password_hash),
        has_email=bool(user.email),
        has_phone=bool(user.phone),
        initial_principal=float(user.initial_principal or 0),
        initial_principal_at=user.initial_principal_at,
        created_at=user.created_at,
    )


@router.post("/bind-api/verify", response_model=ApiVerifyResponse)
def verify_bind_api(req: ApiBindRequest, user: User = Depends(get_current_user)):
    """绑定前校验：连接、余额、交易权限、单向持仓、杠杆。"""
    result = validate_binance_api(req.api_key, req.api_secret, user.id)
    return _verify_response(result)


@router.get("/api-status", response_model=ApiVerifyResponse)
def api_status(user: User = Depends(get_current_user)):
    """已绑定用户复查 API 是否仍可用。"""
    if not user.api_key_enc or not user.api_secret_enc:
        raise HTTPException(400, "尚未绑定 API")
    result = validate_binance_api(
        decrypt_text(user.api_key_enc),
        decrypt_text(user.api_secret_enc),
        user.id,
    )
    resp = _verify_response(result)
    if user.initial_principal:
        resp.initial_principal = float(user.initial_principal)
    return resp


@router.post("/bind-api")
def bind_api(req: ApiBindRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    result = validate_binance_api(req.api_key, req.api_secret, user.id)
    if not result.get("valid"):
        raise HTTPException(400, result.get("message", "API 验证失败"))

    equity = float(result.get("total_balance", 0))
    user.api_key_enc = encrypt_text(req.api_key)
    user.api_secret_enc = encrypt_text(req.api_secret)
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
        "message": f"绑定成功 · 初始本金 ${user.initial_principal:.2f}",
    }


@router.get("/principal-history", response_model=list[PrincipalSnapshotOut])
def principal_history(
    limit: int = 20,
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
    balance, unrealized, position = 0.0, 0.0, None
    equity = 0.0

    supervisor = supervisor_pool.get(user.id)
    if supervisor:
        summary = supervisor.client.get_futures_account_summary()
        equity = float(summary.get("total_margin_balance", 0))
        balance = float(summary.get("available_balance", equity))
        status = supervisor.position_manager.get_position_status()
        if status.get("has_position"):
            unrealized = status.get("unrealized_pnl", 0)
            position = status
    elif user.api_key_enc and user.api_status == ApiStatus.ACTIVE.value:
        try:
            equity = fetch_live_equity(user)
            balance = equity
        except Exception:
            pass

    initial = float(user.initial_principal or 0)
    cycle_pnl = round(equity - initial, 2) if initial > 0 else 0.0

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    today_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, func.date(Trade.closed_at) == today
    ).scalar() or 0

    week_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, func.date(Trade.closed_at) >= week_start
    ).scalar() or 0

    total_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, Trade.status == "closed"
    ).scalar() or 0

    return DashboardStats(
        balance=balance,
        unrealized_pnl=unrealized,
        today_pnl=float(today_pnl),
        week_pnl=float(week_pnl),
        total_pnl=float(total_pnl),
        initial_principal=initial,
        cycle_pnl=cycle_pnl,
        initial_principal_at=user.initial_principal_at,
        open_position=position,
    )


@router.get("/trades", response_model=list[TradeOut])
def trades(limit: int = 50, offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/logs", response_model=list[TradeLogOut])
def logs(limit: int = 100, offset: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(TradeLog).filter(TradeLog.user_id == user.id).order_by(TradeLog.created_at.desc()).offset(offset).limit(limit).all()
