"""Shared position qty drift tolerance — ignore normal post-open ETH mark-price noise."""
from __future__ import annotations

# Allow ~2% drift from margin/notional recalculation after open; only align on larger gaps.
CAP_DRIFT_RATIO = 0.02
CAP_DRIFT_MIN_QTY_ETH = 0.005
CAP_DRIFT_MIN_CONTRACTS = 1.0


def qty_drift_tolerance(
    qty_a: float,
    qty_b: float,
    *,
    is_contracts: bool = False,
    ratio: float = CAP_DRIFT_RATIO,
) -> float:
    """Effective tolerance band for comparing two position quantities."""
    anchor = max(abs(float(qty_a)), abs(float(qty_b)), 1e-9)
    rel_tol = anchor * float(ratio)
    if is_contracts:
        return max(CAP_DRIFT_MIN_CONTRACTS, rel_tol)
    return max(CAP_DRIFT_MIN_QTY_ETH, rel_tol)


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
