"""Same-direction TV entry policy — ATR-first, then price-diff filter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.core.regime_utils import clamp_regime


class SameDirAction(str, Enum):
    OPEN_NEW = "open_new"
    CLOSE_REOPEN = "close_reopen"
    REFRESH_TPS = "refresh_tps"


@dataclass(frozen=True)
class SameDirectionEval:
    action: SameDirAction
    reason: str
    price_diff_pct: float
    held_regime: int
    new_regime: int
    held_atr: float
    new_atr: float
    tv_price: float
    entry_price: float
    mark_price: float
    regime_changed: bool
    atr_changed: bool


def price_diff_pct(tv_price: float, entry_price: float, mark_price: float) -> float:
    if mark_price <= 0:
        return 100.0
    if tv_price <= 0 and entry_price <= 0:
        return 0.0
    ref_tv = tv_price if tv_price > 0 else entry_price
    return abs(ref_tv - entry_price) / mark_price * 100.0


def atr_values_differ(held_atr: float, new_atr: float) -> bool:
    """TV ATR vs position ATR — rounded to 2dp to avoid float noise."""
    return round(float(held_atr or 0), 2) != round(float(new_atr or 0), 2)


def format_reopen_reason(ev: "SameDirectionEval", threshold_pct: float) -> str:
    if ev.atr_changed:
        return f"同方向ATR变化 {ev.held_atr}→{ev.new_atr}，刷新仓位先平后开"
    if ev.regime_changed:
        return f"同方向档位变化 {ev.held_regime}→{ev.new_regime}，先平后开换仓"
    return (
        f"同方向ATR未变({ev.held_atr}) 价差 {ev.price_diff_pct:.3f}% "
        f"≥ 阈值 {threshold_pct}%，先平后开"
    )


def format_refresh_reason(ev: "SameDirectionEval", threshold_pct: float) -> str:
    return (
        f"ATR未变({ev.held_atr}) 价差 {ev.price_diff_pct:.3f}% "
        f"< 阈值 {threshold_pct}% → 忽略重复开仓，更新止盈"
    )


def evaluate_same_direction(
    *,
    has_position: bool,
    current_side: str | None,
    signal_side: str,
    entry_price: float,
    tv_price: float,
    mark_price: float,
    held_regime: int,
    new_regime: int,
    held_atr: float,
    new_atr: float,
    threshold_pct: float,
) -> SameDirectionEval:
    held = clamp_regime(held_regime)
    new = clamp_regime(new_regime)
    diff = price_diff_pct(tv_price, entry_price, mark_price)
    regime_changed = held != new
    atr_changed = atr_values_differ(held_atr, new_atr)

    base = dict(
        price_diff_pct=diff,
        held_regime=held,
        new_regime=new,
        held_atr=float(held_atr or 0),
        new_atr=float(new_atr or 0),
        tv_price=tv_price,
        entry_price=entry_price,
        mark_price=mark_price,
        regime_changed=regime_changed,
        atr_changed=atr_changed,
    )

    if not has_position or not current_side:
        return SameDirectionEval(
            action=SameDirAction.OPEN_NEW,
            reason="flat_or_no_side",
            **base,
        )

    if current_side != signal_side:
        return SameDirectionEval(
            action=SameDirAction.CLOSE_REOPEN,
            reason="opposite_side",
            **base,
        )

    # Priority 1: ATR change → refresh position (close then reopen)
    if atr_changed:
        return SameDirectionEval(
            action=SameDirAction.CLOSE_REOPEN,
            reason="atr_changed",
            **base,
        )

    # Priority 2: regime change → close then reopen
    if regime_changed:
        return SameDirectionEval(
            action=SameDirAction.CLOSE_REOPEN,
            reason="regime_changed",
            **base,
        )

    # Priority 3: same ATR + same regime → price diff gate
    if diff < threshold_pct:
        return SameDirectionEval(
            action=SameDirAction.REFRESH_TPS,
            reason="atr_same_price_diff_below_threshold",
            **base,
        )

    return SameDirectionEval(
        action=SameDirAction.CLOSE_REOPEN,
        reason="price_diff_sufficient",
        **base,
    )
