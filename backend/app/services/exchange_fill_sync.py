"""Multi-exchange ETH perpetual fill sync + authoritative realized PnL.

Admin/settlement cycle PnL prefers Σ exchange fill realizedPnL for the ETH
contract (Binance/OKX fills, Gate position_close / account_book pnl, Deepcoin
orders-history pnl). Platform Trade mark×qty estimate is fallback only.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiStatus, TradeLog, User
from app.services.dispatcher import supervisor_pool
from app.utils.crypto import decrypt_text

logger = logging.getLogger(__name__)
settings = get_settings()

EXCHANGE_FILL_EVENT = "EXCHANGE_FILL"
LEGACY_BINANCE_FILL = "BINANCE_FILL"
FILL_EVENTS = (EXCHANGE_FILL_EVENT, LEGACY_BINANCE_FILL)


def trading_symbol_for_exchange(exchange: str | None, canonical: str | None = None) -> str:
    from app.core.symbol_registry import exchange_native_symbol, normalize_canonical_symbol, DEFAULT_CANONICAL

    can = normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL
    return exchange_native_symbol(exchange, can)


def resolve_trading_client(user: User, canonical: str | None = None):
    supervisor = supervisor_pool.get(user.id, canonical)
    if supervisor and getattr(supervisor, "client", None):
        return supervisor.client
    if not (user.api_key_enc and user.api_secret_enc and user.api_status == ApiStatus.ACTIVE.value):
        return None
    from app.core.exchange_factory import create_exchange_client

    passphrase = decrypt_text(user.passphrase_enc) if user.passphrase_enc else ""
    return create_exchange_client(
        user,
        decrypt_text(user.api_key_enc),
        decrypt_text(user.api_secret_enc),
        passphrase,
        canonical_symbol=canonical,
    )


def _safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def normalize_fill_row(exchange: str, raw: dict) -> dict | None:
    """Normalize one exchange-native fill/close into a common shape."""
    if not isinstance(raw, dict):
        return None
    ex = (exchange or "binance").lower()

    if ex == "binance":
        fill_id = str(raw.get("id") or raw.get("tradeId") or "")
        if not fill_id:
            return None
        return {
            "fill_id": fill_id,
            "exchange": "binance",
            "symbol": raw.get("symbol") or settings.SYMBOL,
            "side": str(raw.get("side") or "").upper(),
            "qty": _safe_float(raw.get("qty")),
            "price": _safe_float(raw.get("price")),
            "realized_pnl": _safe_float(raw.get("realizedPnl")),
            "commission": abs(_safe_float(raw.get("commission"))),
            "time_ms": int(raw.get("time") or 0),
            "order_id": str(raw.get("orderId") or ""),
            "raw_kind": "account_trade",
        }

    if ex == "okx":
        fill_id = str(raw.get("tradeId") or raw.get("billId") or "")
        if not fill_id:
            return None
        return {
            "fill_id": fill_id,
            "exchange": "okx",
            "symbol": raw.get("instId") or settings.OKX_SYMBOL,
            "side": str(raw.get("side") or "").upper(),
            "qty": _safe_float(raw.get("fillSz") or raw.get("sz")),
            "price": _safe_float(raw.get("fillPx") or raw.get("px")),
            "realized_pnl": _safe_float(raw.get("fillPnl") or raw.get("pnl")),
            "commission": abs(_safe_float(raw.get("fee"))),
            "time_ms": int(_safe_float(raw.get("ts") or raw.get("fillTime"))),
            "order_id": str(raw.get("ordId") or ""),
            "raw_kind": "trade_fill",
        }

    if ex == "gate":
        # position_close rows: {time, pnl, side, contract}
        if "pnl" in raw and ("contract" in raw or raw.get("raw_kind") == "position_close"):
            fill_id = f"pc-{raw.get('time')}-{raw.get('side')}-{raw.get('pnl')}"
            return {
                "fill_id": fill_id,
                "exchange": "gate",
                "symbol": raw.get("contract") or settings.GATE_SYMBOL,
                "side": str(raw.get("side") or "").upper(),
                "qty": _safe_float(raw.get("size") or raw.get("close_size")),
                "price": _safe_float(raw.get("price")),
                "realized_pnl": _safe_float(raw.get("pnl")),
                "commission": 0.0,
                "time_ms": int(_safe_float(raw.get("time")) * 1000) if raw.get("time") and float(raw.get("time") or 0) < 1e12 else int(_safe_float(raw.get("time"))),
                "order_id": str(raw.get("order_id") or ""),
                "raw_kind": "position_close",
            }
        # account_book pnl type
        if str(raw.get("type") or "").lower() == "pnl" or raw.get("raw_kind") == "account_book_pnl":
            fill_id = str(raw.get("id") or f"ab-{raw.get('time')}-{raw.get('change')}")
            return {
                "fill_id": fill_id,
                "exchange": "gate",
                "symbol": raw.get("contract") or settings.GATE_SYMBOL,
                "side": "",
                "qty": 0.0,
                "price": 0.0,
                "realized_pnl": _safe_float(raw.get("change") or raw.get("pnl")),
                "commission": 0.0,
                "time_ms": int(_safe_float(raw.get("time")) * 1000) if raw.get("time") and float(raw.get("time") or 0) < 1e12 else int(_safe_float(raw.get("time"))),
                "order_id": "",
                "raw_kind": "account_book_pnl",
            }
        # my_trades — no per-fill realized; skip for PnL sum unless close_size hints later
        return None

    if ex == "deepcoin":
        # Prefer orders-history rows with pnl (reduce/close filled orders)
        fill_id = str(raw.get("ordId") or raw.get("tradeId") or raw.get("billId") or "")
        if not fill_id:
            return None
        pnl = _safe_float(raw.get("pnl") or raw.get("fillPnl"))
        # opening fills often have pnl=0; still keep for audit if filled
        return {
            "fill_id": fill_id,
            "exchange": "deepcoin",
            "symbol": raw.get("instId") or settings.DEEPCOIN_SYMBOL,
            "side": str(raw.get("side") or "").upper(),
            "qty": _safe_float(raw.get("accFillSz") or raw.get("fillSz") or raw.get("sz")),
            "price": _safe_float(raw.get("avgPx") or raw.get("fillPx") or raw.get("px")),
            "realized_pnl": pnl,
            "commission": abs(_safe_float(raw.get("fee"))),
            "time_ms": int(_safe_float(raw.get("uTime") or raw.get("cTime") or raw.get("fillTime") or raw.get("ts"))),
            "order_id": str(raw.get("ordId") or ""),
            "raw_kind": "orders_history" if raw.get("ordId") else "fill",
        }

    return None


def fetch_live_eth_fills(client: Any, exchange: str, start_time_ms: int | None = None, canonical: str | None = None) -> list[dict]:
    """Pull native history and normalize to common fill rows (ETH/XAU perps)."""
    from app.core.symbol_registry import enabled_trading_symbols

    ex = (exchange or getattr(client, "exchange_id", "binance") or "binance").lower()
    symbols = [canonical] if canonical else enabled_trading_symbols()
    out: list[dict] = []

    for can in symbols:
        symbol = trading_symbol_for_exchange(ex, can)
        try:
            if ex == "binance":
                raw = client.get_account_trades(symbol=symbol, start_time_ms=start_time_ms, limit=1000) or []
                for r in raw:
                    n = normalize_fill_row("binance", r)
                    if n:
                        n["canonical_symbol"] = can
                        out.append(n)
                continue

            if ex == "okx":
                # Client may be bound to one trading_symbol — temporarily use requested
                prev = getattr(client, "trading_symbol", None)
                try:
                    client.trading_symbol = symbol
                    raw = client.get_account_trades(symbol=symbol, start_time_ms=start_time_ms, limit=100) or []
                finally:
                    if prev is not None:
                        client.trading_symbol = prev
                for r in raw:
                    n = normalize_fill_row("okx", r)
                    if n:
                        n["canonical_symbol"] = can
                        out.append(n)
                continue

            if ex == "gate":
                if hasattr(client, "get_position_close_history"):
                    raw = client.get_position_close_history(symbol=symbol, start_time_ms=start_time_ms) or []
                    for r in raw:
                        r = dict(r)
                        r["raw_kind"] = "position_close"
                        n = normalize_fill_row("gate", r)
                        if n:
                            n["canonical_symbol"] = can
                            out.append(n)
                if not any(f.get("canonical_symbol") == can for f in out) and hasattr(client, "get_futures_cashflows"):
                    cash = client.get_futures_cashflows(start_time_ms=start_time_ms) or []
                    for r in cash:
                        if str(r.get("kind") or "") == "realized_pnl" or str(r.get("income_type") or "").lower() == "pnl":
                            out.append({
                                "fill_id": str(r.get("tran_id") or f"cf-{r.get('time_ms')}-{r.get('amount')}"),
                                "exchange": "gate",
                                "symbol": r.get("symbol") or symbol,
                                "canonical_symbol": can,
                                "side": "",
                                "qty": 0.0,
                                "price": 0.0,
                                "realized_pnl": _safe_float(r.get("amount")),
                                "commission": 0.0,
                                "time_ms": int(r.get("time_ms") or 0),
                                "order_id": "",
                                "raw_kind": "cashflow_pnl",
                            })
                continue

            if ex == "deepcoin":
                prev = getattr(client, "trading_symbol", None)
                try:
                    client.trading_symbol = symbol
                    if hasattr(client, "get_orders_history_pnl"):
                        raw = client.get_orders_history_pnl(symbol=symbol, start_time_ms=start_time_ms) or []
                        for r in raw:
                            n = normalize_fill_row("deepcoin", r)
                            if n:
                                n["canonical_symbol"] = can
                                out.append(n)
                    elif hasattr(client, "get_account_trades"):
                        raw = client.get_account_trades(symbol=symbol, start_time_ms=start_time_ms) or []
                        for r in raw:
                            n = normalize_fill_row("deepcoin", r)
                            if n:
                                n["canonical_symbol"] = can
                                out.append(n)
                finally:
                    if prev is not None:
                        client.trading_symbol = prev
                continue
        except Exception as exc:
            logger.warning("[FillSync] live fetch failed exchange=%s symbol=%s: %s", ex, can, exc)
    return out


def sum_realized_from_fills(fills: list[dict], *, start_ms: int | None = None, end_ms: int | None = None) -> float:
    total = 0.0
    for f in fills or []:
        ts = int(f.get("time_ms") or 0)
        if start_ms and ts and ts < start_ms:
            continue
        if end_ms and ts and ts > end_ms:
            continue
        total += float(f.get("realized_pnl") or 0)
    return round(total, 4)


def _existing_fill_ids(db: Session, user_id: int) -> set[str]:
    rows = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user_id, TradeLog.event_type.in_(FILL_EVENTS))
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
        fid = detail.get("fill_id") or detail.get("binance_trade_id")
        if fid is not None:
            ids.add(str(fid))
    return ids


def sync_user_exchange_fills(db: Session, user: User, *, days: int = 90) -> dict:
    """Import ETH contract fills into TradeLog for all supported exchanges."""
    client = resolve_trading_client(user)
    if not client:
        return {"synced": 0, "skipped": 0, "error": "api_not_active", "exchange": user.exchange}

    exchange = (user.exchange or getattr(client, "exchange_id", "binance") or "binance").lower()
    symbol = trading_symbol_for_exchange(exchange)
    start_ms = int((datetime.utcnow() - timedelta(days=min(max(days, 1), 180))).timestamp() * 1000)
    fills = fetch_live_eth_fills(client, exchange, start_time_ms=start_ms)
    existing = _existing_fill_ids(db, user.id)
    synced = 0
    skipped = 0

    for fill in fills:
        fid = str(fill.get("fill_id") or "")
        if not fid or fid in existing:
            skipped += 1
            continue
        pnl = float(fill.get("realized_pnl") or 0)
        commission = float(fill.get("commission") or 0)
        msg = (
            f"{exchange}成交 {fill.get('side') or '?'} {fill.get('qty')} @ "
            f"${float(fill.get('price') or 0):.4f} · 已实现 PnL ${pnl:.4f}"
            + (f" · 手续费 {commission:.4f}" if commission else "")
        )
        detail = {
            "fill_id": fid,
            "binance_trade_id": fid if exchange == "binance" else None,
            "exchange": exchange,
            "symbol": fill.get("symbol") or symbol,
            "side": fill.get("side"),
            "qty": fill.get("qty"),
            "price": fill.get("price"),
            "realized_pnl": pnl,
            "commission": commission,
            "order_id": fill.get("order_id"),
            "time_ms": fill.get("time_ms"),
            "raw_kind": fill.get("raw_kind"),
        }
        ts = fill.get("time_ms")
        created_at = datetime.utcfromtimestamp(ts / 1000) if ts else datetime.utcnow()
        # Dual-write BINANCE_FILL for backward-compatible audit tools.
        events = [EXCHANGE_FILL_EVENT]
        if exchange == "binance":
            events.append(LEGACY_BINANCE_FILL)
        for ev in events:
            db.add(TradeLog(
                user_id=user.id,
                event_type=ev,
                message=msg if ev == EXCHANGE_FILL_EVENT else f"[legacy] {msg}",
                detail_json=json.dumps(detail, ensure_ascii=False),
                created_at=created_at,
            ))
        existing.add(fid)
        synced += 1

    db.commit()
    logger.info(
        "[FillSync] user=%s exchange=%s synced=%s skipped=%s symbol=%s fills=%s",
        user.id, exchange, synced, skipped, symbol, len(fills),
    )
    return {
        "synced": synced,
        "skipped": skipped,
        "symbol": symbol,
        "exchange": exchange,
        "fill_count": len(fills),
        "live_fill_pnl": sum_realized_from_fills(fills, start_ms=start_ms),
    }


# Backward-compatible alias used across the codebase.
def sync_user_binance_fills(db: Session, user: User, *, days: int = 90) -> dict:
    return sync_user_exchange_fills(db, user, days=days)


def sum_synced_fill_pnl(
    db: Session,
    user_id: int,
    period_start: date | None = None,
    period_end: date | None = None,
) -> float:
    """Sum realized PnL from EXCHANGE_FILL / BINANCE_FILL logs (dedupe by fill_id)."""
    rows = (
        db.query(TradeLog)
        .filter(TradeLog.user_id == user_id, TradeLog.event_type.in_(FILL_EVENTS))
        .all()
    )
    seen: set[str] = set()
    total = 0.0
    for row in rows:
        if not row.detail_json:
            continue
        try:
            detail = json.loads(row.detail_json)
        except json.JSONDecodeError:
            continue
        fid = str(detail.get("fill_id") or detail.get("binance_trade_id") or "")
        key = fid or f"{row.event_type}:{row.id}"
        if key in seen:
            continue
        seen.add(key)
        ts = detail.get("time_ms") or (row.created_at.timestamp() * 1000 if row.created_at else None)
        if ts:
            d = datetime.utcfromtimestamp(ts / 1000).date()
            if period_start and d < period_start:
                continue
            if period_end and d > period_end:
                continue
        total += float(detail.get("realized_pnl") or 0)
    return round(total, 4)


def date_bounds_ms(period_start: date | None, period_end: date | None) -> tuple[int | None, int | None]:
    start_ms = None
    end_ms = None
    if period_start:
        start_ms = int(datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc).timestamp() * 1000)
    if period_end:
        end_dt = datetime(period_end.year, period_end.month, period_end.day, 23, 59, 59, tzinfo=timezone.utc)
        end_ms = int(end_dt.timestamp() * 1000)
    return start_ms, end_ms


def authoritative_eth_cycle_pnl(
    db: Session,
    user: User,
    period_start: date | None = None,
    period_end: date | None = None,
    *,
    sync: bool = True,
) -> tuple[float, dict]:
    """Prefer live exchange ETH realized PnL; else TradeLog fills; else platform Trades."""
    from app.services.profit_audit import sum_closed_trade_pnl

    meta: dict[str, Any] = {
        "exchange": user.exchange or "binance",
        "symbol": trading_symbol_for_exchange(user.exchange),
        "period_start": str(period_start) if period_start else None,
        "period_end": str(period_end) if period_end else None,
    }
    sync_result = None
    if sync:
        try:
            sync_result = sync_user_exchange_fills(db, user, days=180)
            meta["sync"] = sync_result
        except Exception as exc:
            meta["sync_error"] = str(exc)
            logger.warning("[FillSync] authoritative sync failed user=%s: %s", user.id, exc)

    start_ms, end_ms = date_bounds_ms(period_start, period_end)
    client = resolve_trading_client(user)
    if client:
        try:
            fills = fetch_live_eth_fills(client, meta["exchange"], start_time_ms=start_ms)
            live = sum_realized_from_fills(fills, start_ms=start_ms, end_ms=end_ms)
            meta["source"] = "exchange_live_fills"
            meta["fill_count"] = len(fills)
            meta["live_fill_pnl"] = live
            # Prefer live when we successfully talked to the exchange (even if 0).
            if fills or (sync_result and sync_result.get("error") is None):
                platform = sum_closed_trade_pnl(db, user.id, period_start, period_end)
                meta["platform_trade_pnl"] = platform
                meta["platform_vs_exchange_delta"] = round(live - platform, 4)
                logger.info(
                    "[FillSync] user=%s source=live exchange_pnl=%.4f platform_pnl=%.4f delta=%.4f fills=%s",
                    user.id, live, platform, live - platform, len(fills),
                )
                return round(live, 2), meta
        except Exception as exc:
            meta["live_error"] = str(exc)

    logged = sum_synced_fill_pnl(db, user.id, period_start, period_end)
    platform = sum_closed_trade_pnl(db, user.id, period_start, period_end)
    meta["platform_trade_pnl"] = platform
    if abs(logged) > 1e-9 or (sync_result and sync_result.get("fill_count", 0) > 0):
        meta["source"] = "tradelog_fills"
        meta["logged_fill_pnl"] = logged
        meta["platform_vs_exchange_delta"] = round(logged - platform, 4)
        return round(logged, 2), meta

    meta["source"] = "platform_trades_fallback"
    meta["note"] = "exchange fills unavailable; using mark-estimate Trade.realized_pnl"
    return platform, meta
