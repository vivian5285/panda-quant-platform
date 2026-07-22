"""Per-symbol daily loss circuit — pause opens after −5.5% of equity (UTC day)."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DAILY_LOSS_LIMIT_PCT = 0.055  # 5.5% of equity
_lock = threading.RLock()


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _store_path(user_id: int | str, symbol: str) -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "daily_loss"
    root.mkdir(parents=True, exist_ok=True)
    can = str(symbol or "ETHUSDT").upper().replace(".P", "").replace("-", "").replace("_", "")
    if "XAU" in can:
        can = "XAUUSDT"
    elif can.startswith("ETH"):
        can = "ETHUSDT"
    return root / f"u{int(user_id)}_{can}.json"


def _load(user_id: int | str, symbol: str) -> dict[str, Any]:
    path = _store_path(user_id, symbol)
    if not path.exists():
        return {"day": _utc_day(), "realized_pnl_usd": 0.0, "equity_ref": 0.0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"day": _utc_day(), "realized_pnl_usd": 0.0, "equity_ref": 0.0}
    if str(data.get("day") or "") != _utc_day():
        return {"day": _utc_day(), "realized_pnl_usd": 0.0, "equity_ref": 0.0}
    return data


def _save(user_id: int | str, symbol: str, data: dict[str, Any]) -> None:
    path = _store_path(user_id, symbol)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def record_close_pnl(
    *,
    user_id: int | str,
    symbol: str,
    pnl_usd: float,
    equity: float | None = None,
) -> dict[str, Any]:
    """Accumulate realized PnL for this UTC day (losses are negative)."""
    with _lock:
        data = _load(user_id, symbol)
        data["realized_pnl_usd"] = float(data.get("realized_pnl_usd") or 0) + float(pnl_usd or 0)
        if equity and float(equity) > 0:
            data["equity_ref"] = float(equity)
        data["updated_at"] = time.time()
        _save(user_id, symbol, data)
        return dict(data)


def check_allows_open(
    *,
    user_id: int | str,
    symbol: str,
    equity: float,
) -> tuple[bool, dict[str, Any]]:
    """Return (ok, meta). ok=False when today's realized loss ≥ 5.5% of equity."""
    eq = float(equity or 0)
    with _lock:
        data = _load(user_id, symbol)
    pnl = float(data.get("realized_pnl_usd") or 0)
    ref = float(data.get("equity_ref") or 0) or eq
    loss_pct = (-pnl / ref) if ref > 0 and pnl < 0 else 0.0
    meta = {
        "day": data.get("day"),
        "realized_pnl_usd": round(pnl, 4),
        "equity_ref": round(ref, 4),
        "loss_pct": round(loss_pct, 6),
        "limit_pct": DAILY_LOSS_LIMIT_PCT,
        "symbol": symbol,
    }
    if ref > 0 and pnl < 0 and (-pnl / ref) + 1e-12 >= DAILY_LOSS_LIMIT_PCT:
        meta["error"] = "daily_loss_circuit"
        logger.warning(
            "[User %s] daily loss circuit trip symbol=%s loss_pct=%.2f%% pnl=%.4f",
            user_id, symbol, loss_pct * 100, pnl,
        )
        return False, meta
    return True, meta


def reset_for_tests() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "daily_loss"
    if root.exists():
        for p in root.glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
