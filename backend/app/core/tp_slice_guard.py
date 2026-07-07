"""TP slice planning — exclude consumed tiers and redistribute remaining qty."""

from __future__ import annotations

from app.core.symbol_precision import round_quantity
from app.core.tp_defense_reconcile import tp_price_matches


def compute_tp_slices(
    qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    *,
    exclude_levels: set[int] | None = None,
    round_qty_fn=round_quantity,
) -> list[tuple[int, float, float]]:
    """Regime-ratio slices for live qty; skip consumed levels and re-normalize."""
    exclude_levels = exclude_levels or set()
    ratios = regime_settings[regime]["ratios"]
    active: list[tuple[int, float, float]] = []
    for i, ratio in enumerate(ratios):
        level = i + 1
        price = float(tv_tps[i]) if i < len(tv_tps) else 0.0
        if level in exclude_levels or price <= 0:
            continue
        active.append((level, ratio, price))
    if not active or qty <= 0:
        return []

    total_ratio = sum(r for _, r, _ in active)
    slices: list[tuple[int, float, float]] = []
    allocated = 0.0
    for idx, (level, ratio, price) in enumerate(active):
        if idx == len(active) - 1:
            part_qty = round_qty_fn(qty - allocated)
        else:
            part_qty = round_qty_fn(qty * (ratio / total_ratio))
            allocated += part_qty
        if part_qty > 0:
            slices.append((level, part_qty, price))
    return slices


def infer_filled_tp_levels(
    live_qty: float,
    curr_px: float,
    side: str | None,
    *,
    initial_qty: float,
    consumed_tp_levels: list[int] | None,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    open_tp_prices: list[float],
    qty_tol: float,
    price_tol: float = 0.02,
) -> set[int]:
    """
    Infer consumed TP tiers from:
    - persisted consumed_tp_levels
    - initial_qty vs live_qty prefix match
    - price crossed TP without live order at that price
    """
    filled = set(consumed_tp_levels or [])
    anchor = float(initial_qty or live_qty)
    if anchor <= 0:
        return filled

    all_slices = compute_tp_slices(
        anchor, regime, tv_tps, regime_settings, exclude_levels=set(),
    )
    for prefix_len in range(1, len(all_slices) + 1):
        prefix = all_slices[:prefix_len]
        consumed_qty = sum(q for _, q, _ in prefix)
        expected_live = round_quantity(anchor - consumed_qty)
        if abs(live_qty - expected_live) <= qty_tol:
            filled.update(level for level, _, _ in prefix)

    if curr_px <= 0 or side not in ("LONG", "SHORT"):
        return filled

    for level, _slice_qty, price in all_slices:
        if level in filled or price <= 0:
            continue
        has_order = any(tp_price_matches(px, price, price_tol) for px in open_tp_prices)
        if has_order:
            continue
        crossed = (
            (side == "LONG" and curr_px >= price)
            or (side == "SHORT" and curr_px <= price)
        )
        if crossed:
            filled.add(level)
    return filled


def slices_to_level_dicts(slices: list[tuple[int, float, float]]) -> list[dict]:
    return [{"level": lvl, "qty": q, "price": px} for lvl, q, px in slices]
