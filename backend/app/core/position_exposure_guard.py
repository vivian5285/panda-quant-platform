"""Live position vs reduce-only TP book — detect over-commit / side flip."""

from __future__ import annotations

from typing import Any, Callable

from app.core.position_qty_tolerance import qty_drift_tolerance


def resolve_booked_side(
    *,
    current_side: str | None,
    last_tv_side: str | None,
) -> str | None:
    """Authoritative OPEN direction: TV last signal, then ledger current_side."""
    tv = str(last_tv_side or "").upper().strip()
    if tv in ("LONG", "SHORT"):
        return tv
    cur = str(current_side or "").upper().strip()
    if cur in ("LONG", "SHORT"):
        return cur
    return None


def live_side_from_amt(position_amt: float) -> str | None:
    amt = float(position_amt or 0)
    if amt > 0:
        return "LONG"
    if amt < 0:
        return "SHORT"
    return None


def sum_reduce_only_tp_qty(
    orders: list[dict],
    *,
    qty_keys: tuple[str, ...] = ("qty", "origQty", "quantity"),
) -> float:
    total = 0.0
    for o in orders or []:
        for key in qty_keys:
            raw = o.get(key)
            if raw is None or raw == "":
                continue
            try:
                total += abs(float(raw))
                break
            except (TypeError, ValueError):
                continue
    return round(total, 6)


def audit_position_tp_exposure(
    *,
    live_qty: float,
    live_side: str | None,
    tp_orders: list[dict],
    expected_levels: list[dict] | None = None,
    booked_side: str | None = None,
    is_contracts: bool = False,
) -> dict[str, Any]:
    """
    Compare exchange position with hanging reduce-only TP qty.
    Flags over-commit (TP sum > position) and TV/booked side flip.
    """
    qty = abs(float(live_qty or 0))
    tp_sum = sum_reduce_only_tp_qty(tp_orders)
    tol = qty_drift_tolerance(qty, qty, is_contracts=is_contracts) if qty > 0 else (
        1.0 if is_contracts else 0.001
    )
    expected_sum = 0.0
    if expected_levels:
        expected_sum = round(
            sum(abs(float(lv.get("qty", 0) or 0)) for lv in expected_levels),
            6,
        )

    over_committed = qty > 0 and tp_sum > qty + tol
    under_committed = qty > 0 and expected_sum > 0 and tp_sum + tol < expected_sum
    excess_qty = round(max(0.0, tp_sum - qty), 6) if over_committed else 0.0

    live = str(live_side or "").upper().strip() or None
    booked = str(booked_side or "").upper().strip() or None
    side_flip = (
        booked in ("LONG", "SHORT")
        and live in ("LONG", "SHORT")
        and booked != live
    )

    issues: list[str] = []
    if side_flip:
        issues.append(f"方向背离 账本/TV={booked} 实盘={live}")
    if over_committed:
        issues.append(f"止盈超挂 盘口{tp_sum} > 持仓{qty} (+{excess_qty})")
    if under_committed and not over_committed:
        issues.append(f"止盈欠挂 盘口{tp_sum} < 期望{expected_sum}")

    return {
        "live_qty": qty,
        "live_side": live,
        "booked_side": booked,
        "tp_booked_sum": tp_sum,
        "expected_tp_sum": expected_sum,
        "tolerance": tol,
        "over_committed": over_committed,
        "under_committed": under_committed,
        "excess_tp_qty": excess_qty,
        "side_flip": side_flip,
        "needs_remediate": bool(side_flip or over_committed),
        "issues": issues,
        "tp_order_count": len(tp_orders or []),
    }


def format_exposure_summary(audit: dict[str, Any]) -> str:
    parts = []
    if audit.get("live_side") and audit.get("live_qty"):
        parts.append(f"实盘 {audit['live_side']} {audit['live_qty']}")
    if audit.get("booked_side"):
        parts.append(f"TV/账本 {audit['booked_side']}")
    parts.append(f"止盈挂单合计 {audit.get('tp_booked_sum', 0)}")
    if audit.get("expected_tp_sum"):
        parts.append(f"期望合计 {audit['expected_tp_sum']}")
    if audit.get("issues"):
        parts.append("; ".join(audit["issues"]))
    return " | ".join(parts) if parts else "敞口正常"
