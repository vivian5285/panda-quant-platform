"""Shared position qty drift tolerance — ignore normal post-open ETH mark-price noise."""
from __future__ import annotations

# 叠仓纠偏：仅当实盘超出档位上限超过此比例才强制减仓（默认 10%）
CAP_EXCESS_RATIO = 0.10
# 哨兵异动 / TP 匹配：仓位数量变化超过此比例才重挂止盈（默认 5%）
QTY_DRIFT_RATIO = 0.05
# 向后兼容别名
CAP_DRIFT_RATIO = QTY_DRIFT_RATIO


def qty_drift_tolerance(
    qty_a: float,
    qty_b: float,
    *,
    is_contracts: bool = False,
    ratio: float = QTY_DRIFT_RATIO,
    min_absolute: float | None = None,
) -> float:
    """Effective tolerance band for comparing two position quantities."""
    anchor = max(abs(float(qty_a)), abs(float(qty_b)), 1e-9)
    rel_tol = anchor * float(ratio)
    if is_contracts:
        floor = 1.0 if min_absolute is None else float(min_absolute)
        return max(floor, rel_tol)
    floor = 0.001 if min_absolute is None else float(min_absolute)
    return max(floor, rel_tol)


def cap_excess_tolerance(live_qty: float, target_qty: float, *, is_contracts: bool = False) -> float:
    """Lenient band for regime cap — only trim when excess is materially large."""
    return qty_drift_tolerance(
        live_qty,
        target_qty,
        is_contracts=is_contracts,
        ratio=CAP_EXCESS_RATIO,
        min_absolute=1.0 if is_contracts else 0.001,
    )


def qty_change_significant(
    old_qty: float,
    new_qty: float,
    *,
    is_contracts: bool = False,
    extra_absolute: float = 0.0,
) -> bool:
    """True when |old - new| exceeds allowed drift (price/margin noise ignored)."""
    diff = abs(float(old_qty) - float(new_qty))
    if diff <= 1e-9:
        return False
    tol = qty_drift_tolerance(old_qty, new_qty, is_contracts=is_contracts) + float(extra_absolute)
    return diff > tol + 1e-9
