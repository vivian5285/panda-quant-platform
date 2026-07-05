"""Same-direction TV entry policy — reduce churn when price/regime barely moved."""

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
    tv_price: float
    entry_price: float
    mark_price: float
    regime_changed: bool


def price_diff_pct(tv_price: float, entry_price: float, mark_price: float) -> float:
    if mark_price <= 0:
        return 100.0
    if tv_price <= 0 and entry_price <= 0:
        return 0.0
    ref_tv = tv_price if tv_price > 0 else entry_price
    return abs(ref_tv - entry_price) / mark_price * 100.0


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
    threshold_pct: float,
) -> SameDirectionEval:
    held = clamp_regime(held_regime)
    new = clamp_regime(new_regime)
    diff = price_diff_pct(tv_price, entry_price, mark_price)
    regime_changed = held != new

    base = dict(
        price_diff_pct=diff,
        held_regime=held,
        new_regime=new,
        tv_price=tv_price,
        entry_price=entry_price,
        mark_price=mark_price,
        regime_changed=regime_changed,
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

    if regime_changed:
        return SameDirectionEval(
            action=SameDirAction.CLOSE_REOPEN,
            reason="regime_changed",
            **base,
        )

    if diff < threshold_pct:
        return SameDirectionEval(
            action=SameDirAction.REFRESH_TPS,
            reason="price_diff_below_threshold",
            **base,
        )

    return SameDirectionEval(
        action=SameDirAction.CLOSE_REOPEN,
        reason="price_diff_sufficient",
        **base,
    )
