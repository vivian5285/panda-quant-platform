"""Shared open-time ATR sanity check for all exchange supervisors."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.market_indicators import evaluate_atr_sanity


def check_open_atr_or_reject(
    supervisor: Any,
    *,
    atr: float,
    atr_series: list[float] | None,
    side: str | None = None,
    tv_sl_ref: float | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (ok, meta). On failure: log + DingTalk, reject this open only (no pause)."""
    settings = get_settings()
    lookback = int(getattr(settings, "ATR_MEDIAN_LOOKBACK", 50) or 50)
    floor_ratio = float(getattr(settings, "ATR_MEDIAN_FLOOR_RATIO", 0.30) or 0.30)
    sanity = evaluate_atr_sanity(
        atr,
        atr_series,
        lookback=lookback,
        floor_ratio=floor_ratio,
    )
    meta = {
        "sizing_mode": "risk20_cap5x_tv_qty_cap",
        "final_qty": 0.0,
        "sizing_atr": float(atr or 0),
        "sizing_side": side or None,
        "tv_sl_reference": tv_sl_ref if tv_sl_ref and tv_sl_ref > 0 else None,
        **sanity,
    }
    if sanity.get("ok"):
        return True, meta

    err = str(sanity.get("error") or "atr_invalid")
    meta["error"] = err
    atr_v = sanity.get("atr")
    med_v = sanity.get("atr_median")
    sym = getattr(supervisor, "canonical_symbol", None) or getattr(supervisor, "symbol", "")
    if err == "atr_anomaly":
        msg = (
            f"ATR异常（当前值{atr_v}，历史中位数{med_v}），已拒绝本次开仓信号"
            f" symbol={sym}"
        )
        alert_type = "ATR_ANOMALY"
        level = "warning"
    else:
        msg = (
            f"ATR无效/缺失（当前值{atr_v}），已拒绝本次开仓 — 请排查行情数据源"
            f" symbol={sym}"
        )
        alert_type = "ATR_INVALID"
        level = "critical"

    if hasattr(supervisor, "_log"):
        try:
            supervisor._log("ERROR", f"⛔ {msg}")
        except Exception:
            pass
    if hasattr(supervisor, "_alert"):
        try:
            supervisor._alert(
                level,
                alert_type,
                "ATR开仓校验失败",
                msg,
                {
                    "reason": err,
                    "atr": atr_v,
                    "atr_median": med_v,
                    "symbol": sym,
                },
            )
        except Exception:
            pass
    return False, meta
