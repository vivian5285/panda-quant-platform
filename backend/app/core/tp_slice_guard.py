"""TP slice planning + evidence-based fill detection for radar/TP reconciliation."""

from __future__ import annotations

from app.core.symbol_precision import round_quantity
from app.core.position_qty_tolerance import (
    qty_drift_tolerance,
    tp_slice_qty_tolerance,
)
from app.core.tp_defense_reconcile import tp_price_matches

# Mark-price proximity for "price reached TP" (tight — not a substitute for fill)
TP_REACH_PRICE_TOL_PCT = 0.0008
# Fill qty match: must track the slice itself, never the whole-position drift band
TP_FILL_SLICE_FRAC = 0.35


def compute_tp_slices(
    qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    *,
    exclude_levels: set[int] | None = None,
    round_qty_fn=round_quantity,
    min_qty: float = 0.0,
) -> list[tuple[int, float, float]]:
    """Regime-ratio slices for live qty; skip consumed levels and re-normalize.

    ``min_qty``: exchange lot-size floor.
    - If qty ≥ N × min_qty: keep all N tiers (floor each, distribute remainder by ratio).
    - Else: fold undersized early tiers into later ones so at least one placeable TP remains.
    """
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

    floor = max(float(min_qty or 0), 0.0)
    total_ratio = sum(r for _, r, _ in active)
    n = len(active)
    qty = float(qty)

    # Prefer full TP123 when position is large enough for every tier ≥ min_qty
    if floor > 0 and qty + 1e-12 >= n * floor and total_ratio > 0:
        remainder = max(qty - n * floor, 0.0)
        slices: list[tuple[int, float, float]] = []
        allocated = 0.0
        for idx, (level, ratio, price) in enumerate(active):
            if idx == n - 1:
                part = round_qty_fn(qty - allocated)
            else:
                part = round_qty_fn(floor + remainder * (ratio / total_ratio))
                if part + 1e-12 < floor:
                    part = round_qty_fn(floor)
                allocated += part
            if part > 0:
                slices.append((level, part, price))
        # Fix float drift: last slice eats remainder
        if slices:
            used = sum(q for _, q, _ in slices[:-1])
            last_lvl, _, last_px = slices[-1]
            last_q = round_qty_fn(qty - used)
            if last_q > 0:
                slices[-1] = (last_lvl, last_q, last_px)
            else:
                slices.pop()
        return slices

    # Small position: ratio-split then fold under-min into next tier
    raw: list[tuple[int, float, float]] = []
    allocated = 0.0
    for idx, (level, ratio, price) in enumerate(active):
        if idx == n - 1:
            part_qty = round_qty_fn(qty - allocated)
        else:
            part_qty = round_qty_fn(qty * (ratio / total_ratio))
            allocated += part_qty
        raw.append((level, part_qty, price))

    slices = []
    carry = 0.0
    for idx, (level, part_qty, price) in enumerate(raw):
        q = round_qty_fn(part_qty + carry)
        carry = 0.0
        is_last = idx == len(raw) - 1
        if not is_last and floor > 0 and q + 1e-12 < floor:
            carry = q
            continue
        if q > 0:
            slices.append((level, q, price))
    if carry > 0 and slices:
        lvl, q, px = slices[-1]
        slices[-1] = (lvl, round_qty_fn(q + carry), px)
    elif carry > 0 and not slices and raw:
        level, _, price = raw[-1]
        q = round_qty_fn(qty)
        if q > 0:
            slices.append((level, q, price))
    return slices


def match_qty_reduction_to_tp_level(
    reduced_qty: float,
    initial_qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    *,
    consumed_levels: set[int] | None = None,
    qty_tol: float | None = None,
) -> int | None:
    """Match a single qty drop to the next unconsumed TP tier from initial open size."""
    anchor = float(initial_qty or 0)
    if anchor <= 0 or reduced_qty <= 0:
        return None
    slices = compute_tp_slices(
        anchor,
        regime,
        tv_tps,
        regime_settings,
        exclude_levels=consumed_levels or set(),
    )
    if not slices:
        return None
    level, slice_qty, _ = slices[0]
    tol = qty_tol if qty_tol is not None else tp_fill_qty_tolerance(slice_qty)
    if abs(float(reduced_qty) - float(slice_qty)) <= tol:
        return level
    return None


def resolve_tp_step_fill_level(
    *,
    old_qty: float,
    new_qty: float,
    initial_qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    consumed_levels: list[int] | set[int] | None = None,
    curr_px: float = 0.0,
    side: str | None = None,
    open_tp_prices: list[float] | None = None,
    is_contracts: bool = False,
) -> int | None:
    """
    Classify one position reduction as TP1/2/3 fill (exchange-grade).

    Tries in order:
    1. Step qty vs next slice of *current* remaining plan (post-heal TP23 sizes)
    2. Step qty vs next slice of *original* open plan
    3. Book cleared + price reached for next TP (qty already dropped)
    """
    old_q = float(old_qty or 0)
    new_q = float(new_qty or 0)
    reduced = old_q - new_q
    if reduced <= 0 or new_q < 0:
        return None
    consumed = {int(x) for x in (consumed_levels or []) if int(x) in (1, 2, 3)}
    anchor = float(initial_qty or old_q or 0)

    # 1) Current remaining book plan (after TP1 heal, TP2/TP3 are re-sliced on old_qty)
    live_slices = compute_tp_slices(
        old_q, regime, tv_tps, regime_settings, exclude_levels=consumed,
    )
    if live_slices:
        level, slice_qty, tp_px = live_slices[0]
        tol = tp_fill_qty_tolerance(slice_qty, is_contracts=is_contracts)
        if abs(reduced - float(slice_qty)) <= tol:
            return level

    # 2) Original open plan next unconsumed tier
    if anchor > 0:
        level = match_qty_reduction_to_tp_level(
            reduced,
            anchor,
            regime,
            tv_tps,
            regime_settings,
            consumed_levels=consumed,
            qty_tol=tp_fill_qty_tolerance(
                max(reduced, 1e-9), is_contracts=is_contracts,
            ),
        )
        if level is not None:
            return level

    # 3) Exchange book evidence: next TP limit gone + price touched
    all_slices = compute_tp_slices(
        anchor if anchor > 0 else old_q,
        regime,
        tv_tps,
        regime_settings,
        exclude_levels=set(),
    )
    next_level = (max(consumed) + 1) if consumed else 1
    for level, slice_qty, tp_px in all_slices:
        if level < next_level:
            continue
        if level > next_level:
            break
        if float(slice_qty) <= 0 or float(tp_px) <= 0:
            break
        # Need a meaningful drop (at least ~40% of expected slice or live next slice)
        min_drop = float(slice_qty) * 0.4
        if live_slices:
            min_drop = min(min_drop, float(live_slices[0][1]) * 0.4)
        if reduced + 1e-12 < max(min_drop, 1e-9):
            break
        book_gone = not tp_limit_still_on_book(tp_px, open_tp_prices)
        px_ok = (
            price_reached_tp(curr_px, tp_px, side)
            if float(curr_px or 0) > 0 and side in ("LONG", "SHORT")
            else True
        )
        if book_gone and px_ok:
            return level
        break
    return None


def tp_fill_qty_tolerance(slice_qty: float, *, is_contracts: bool = False) -> float:
    """
    Tight tolerance for claiming a fill equals a TP slice.
    Always ≤ ~35% of the slice — never the whole-position 8% band (that falsely
    matched R4 TP1≈5% on a full open).
    """
    sq = max(abs(float(slice_qty)), 1e-9)
    if is_contracts:
        return max(1.0, sq * TP_FILL_SLICE_FRAC)
    return max(0.002, sq * TP_FILL_SLICE_FRAC)


def price_reached_tp(
    curr_px: float,
    tp_price: float,
    side: str | None,
    *,
    tol_pct: float = TP_REACH_PRICE_TOL_PCT,
) -> bool:
    """True when mark has reached / crossed the TP limit price."""
    px = float(curr_px or 0)
    tp = float(tp_price or 0)
    if px <= 0 or tp <= 0 or side not in ("LONG", "SHORT"):
        return False
    slack = max(tp * float(tol_pct), 0.05)
    if side == "LONG":
        return px + slack >= tp
    return px - slack <= tp


def tp_limit_still_on_book(
    tp_price: float,
    open_tp_prices: list[float] | None,
    *,
    price_tol: float = 0.02,
) -> bool:
    """True when the exchange still has a limit order near this TP price."""
    tp = float(tp_price or 0)
    if tp <= 0:
        return False
    for px in open_tp_prices or []:
        try:
            if tp_price_matches(float(px), tp, price_tol):
                return True
        except (TypeError, ValueError):
            continue
    return False


def confirm_tp_tier_fill(
    *,
    level: int,
    slice_qty: float,
    tp_price: float,
    reduced: float,
    prefix_consumed_qty: float,
    curr_px: float,
    side: str | None,
    open_tp_prices: list[float] | None,
    is_contracts: bool = False,
    price_tol: float = 0.02,
    require_price: bool = True,
) -> dict:
    """
    Triple-gate evidence that a TP tier truly filled:

    1. Qty — realized reduction matches the expected prefix / slice (tight band)
    2. Book — that TP limit is gone from the exchange open orders
    3. Price — mark reached TP (required when curr_px>0; restart may omit)

    Any missing gate → not filled. Prevents mark-noise / R4 small-slice false radar.
    """
    detail = {
        "level": int(level),
        "slice_qty": float(slice_qty),
        "tp_price": float(tp_price),
        "reduced": float(reduced),
        "qty_ok": False,
        "book_cleared": False,
        "price_ok": False,
        "confirmed": False,
    }
    fill_tol = tp_fill_qty_tolerance(slice_qty, is_contracts=is_contracts)
    qty_ok = abs(float(reduced) - float(prefix_consumed_qty)) <= fill_tol
    if not qty_ok:
        qty_ok = abs(float(reduced) - float(slice_qty)) <= fill_tol and float(reduced) > fill_tol
    noise = qty_drift_tolerance(float(prefix_consumed_qty) or float(slice_qty), 0.0)
    if float(reduced) <= max(noise * 0.5, 1e-9) and float(reduced) < float(slice_qty) * 0.5:
        qty_ok = False
    detail["qty_ok"] = bool(qty_ok)
    detail["fill_tol"] = fill_tol

    book_cleared = not tp_limit_still_on_book(tp_price, open_tp_prices, price_tol=price_tol)
    detail["book_cleared"] = book_cleared

    if float(curr_px or 0) > 0:
        price_ok = price_reached_tp(curr_px, tp_price, side)
        detail["price_ok"] = price_ok
        if require_price and not price_ok:
            return detail
    else:
        detail["price_ok"] = True
        price_ok = True

    detail["confirmed"] = bool(qty_ok and book_cleared and price_ok)
    return detail


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
    qty_tol: float | None = None,
    price_tol: float = 0.02,
    is_contracts: bool = False,
) -> set[int]:
    """
    Infer consumed TP tiers with exchange-grade evidence.

    Persisted levels are kept only if they still pass book/qty sanity.
    Newly inferred levels require: qty reduction match + TP limit gone + price reached.
    Never mark fills on a still-full open (ignores mark-price noise on ETH size).
    """
    persisted = set(int(x) for x in (consumed_tp_levels or []) if int(x) in (1, 2, 3))
    anchor = float(initial_qty or live_qty)
    if anchor <= 0:
        return set()

    live_qty = float(live_qty or 0)
    all_slices = compute_tp_slices(
        anchor, regime, tv_tps, regime_settings, exclude_levels=set(),
    )
    reduced = round_quantity(anchor - live_qty)
    if not all_slices:
        return set()

    tp1_slice = float(all_slices[0][1])
    # Full / sub-TP1 noise: require at least half a TP1 slice reduced (not 8% position band)
    if reduced < max(tp1_slice * 0.5, tp_fill_qty_tolerance(tp1_slice, is_contracts=is_contracts) * 0.5):
        return set()

    by_level = {lvl: (q, px) for lvl, q, px in all_slices}
    filled: set[int] = set()

    # Sanitize persisted: drop levels whose limit is still hanging or qty denies
    for level in sorted(persisted):
        if level not in by_level:
            continue
        slice_qty, tp_price = by_level[level]
        prefix_qty = sum(by_level[l][0] for l in by_level if l <= level)
        ev = confirm_tp_tier_fill(
            level=level,
            slice_qty=slice_qty,
            tp_price=tp_price,
            reduced=reduced,
            prefix_consumed_qty=prefix_qty,
            curr_px=curr_px,
            side=side,
            open_tp_prices=open_tp_prices,
            is_contracts=is_contracts,
            price_tol=price_tol,
            require_price=False,
        )
        if ev["qty_ok"] and ev["book_cleared"]:
            filled.add(level)

    # Discover next unfilled tier with full triple gate
    next_level = (max(filled) + 1) if filled else 1
    for level, slice_qty, tp_price in all_slices:
        if level < next_level:
            continue
        if level > next_level:
            break
        prefix_qty = sum(q for lvl, q, _ in all_slices if lvl <= level)
        ev = confirm_tp_tier_fill(
            level=level,
            slice_qty=slice_qty,
            tp_price=tp_price,
            reduced=reduced,
            prefix_consumed_qty=prefix_qty,
            curr_px=curr_px,
            side=side,
            open_tp_prices=open_tp_prices,
            is_contracts=is_contracts,
            price_tol=price_tol,
            require_price=True,
        )
        if not ev["confirmed"]:
            break
        filled.add(level)
        next_level = level + 1

    return filled


def slices_to_level_dicts(slices: list[tuple[int, float, float]]) -> list[dict]:
    return [{"level": lvl, "qty": q, "price": px} for lvl, q, px in slices]
