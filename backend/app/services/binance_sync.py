"""Sync Binance ETHUSDT perpetual fill history into trade logs."""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, TradeLog, ApiStatus
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.dispatcher import supervisor_pool

logger = logging.getLogger(__name__)
settings = get_settings()
SYMBOL = settings.SYMBOL


def _client_for_user(user: User) -> BinanceClient | None:
    supervisor = supervisor_pool.get(user.id)
    if supervisor:
        return supervisor.client
    if user.api_key_enc and user.api_secret_enc and user.api_status == ApiStatus.ACTIVE.value:
        return BinanceClient(decrypt_text(user.api_key_enc), decrypt_text(user.api_secret_enc), user.id)
    return None


def _existing_binance_ids(db: Session, user_id: int) -> set[str]:
    rows = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user_id, TradeLog.event_type == "BINANCE_FILL")
        .all()
    )
    ids: set[str] = set()
    for row in rows:
        if not row.detail_json:
            continue
        try:
            detail = json.loads(row.detail_json)
        except json.JSONDecodeError:
            continue
        bid = detail.get("binance_trade_id")
        if bid is not None:
            ids.add(str(bid))
    return ids


def sync_user_binance_fills(
    db: Session,
    user: User,
    *,
    days: int = 90,
) -> dict:
    """Import ETHUSDT perpetual account trades from Binance into TradeLog."""
    client = _client_for_user(user)
    if not client:
        return {"synced": 0, "skipped": 0, "error": "api_not_active"}

    start_ms = int((datetime.utcnow() - timedelta(days=min(max(days, 1), 180))).timestamp() * 1000)
    try:
        fills = client.get_account_trades(symbol=SYMBOL, start_time_ms=start_ms, limit=500)
    except Exception as e:
        logger.warning("Binance fill sync failed user=%s: %s", user.id, e)
        return {"synced": 0, "skipped": 0, "error": str(e)}

    existing = _existing_binance_ids(db, user.id)
    synced = 0
    skipped = 0

    for fill in fills or []:
        bid = str(fill.get("id", ""))
        if not bid or bid in existing:
            skipped += 1
            continue

        side = fill.get("side", "?")
        qty = float(fill.get("qty", 0))
        price = float(fill.get("price", 0))
        pnl = float(fill.get("realizedPnl", 0))
        commission = float(fill.get("commission", 0))
        ts = fill.get("time")
        msg = (
            f"币安成交 {side} {qty} ETH @ ${price:.2f}"
            f" · 已实现 PnL ${pnl:.4f} · 手续费 {commission:.4f}"
        )
        detail = {
            "binance_trade_id": bid,
            "symbol": fill.get("symbol", SYMBOL),
            "side": side,
            "qty": qty,
            "price": price,
            "realized_pnl": pnl,
            "commission": commission,
            "commission_asset": fill.get("commissionAsset"),
            "order_id": fill.get("orderId"),
            "position_side": fill.get("positionSide"),
            "buyer": fill.get("buyer"),
            "maker": fill.get("maker"),
            "time_ms": ts,
        }
        created_at = datetime.utcfromtimestamp(ts / 1000) if ts else datetime.utcnow()
        db.add(TradeLog(
            user_id=user.id,
            event_type="BINANCE_FILL",
            message=msg,
            detail_json=json.dumps(detail, ensure_ascii=False),
            created_at=created_at,
        ))
        existing.add(bid)
        synced += 1

    db.commit()
    return {"synced": synced, "skipped": skipped, "symbol": SYMBOL}
