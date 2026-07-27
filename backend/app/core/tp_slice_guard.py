"""TP slice planning + evidence-based fill detection for radar/TP reconciliation."""

from __future__ import annotations

from app.core.symbol_precision import round_quantity
from app.core.position_qty_tolerance import (
    qty_drift_tolerance,
    tp_slice_qty_tolerance,
)
from app.core.tp_defense_reconcile import tp_price_matches

# Mark-price proximity for "price reached TP"
TP_REACH_PRICE_TOL_PCT = 0.0008
# Slightly looser for "ever touched" via peak/best (pullback after fill)
TP_TOUCH_PEAK_TOL_PCT = 0.0015
# Fill qty match: must track the slice itself, never the whole-position drift band
TP_FILL_SLICE_FRAC = 0.35
# Reasons that must never place a TP limit (death-spiral / instant fill)
SKIP_REHANG_HARD = frozenset({
    "consumed",
    "price_book_filled",
    "qty_book_implies_filled",
    "price_past_tp",
    "invalid_price",
})
# Persist into consumed_tp_levels so restart / heal never re-plan this tier
SKIP_REHANG_PERSIST_CONSUMED = frozenset({
    "price_book_filled",
    "qty_book_implies_filled",
    "price_past_tp",
})


def levels_past_by_mark(
    curr_px: float,
    side: str | None,
    tv_tps: list[float] | None,
    *,
    peak_px: float = 0.0,
) -> set[int]:
    """
    Contiguous TP tiers already reached by mark or peak (entry→TP path).

    Restart / heal rule: if mark ≥ TP1 (LONG) do NOT hang TP1 — only TP2/TP3
    (+ radar). Same for TP2→ only TP3. Never sanitize-and-place through-market TP1.
    """
    out: set[int] = set()
    if side not in ("LONG", "SHORT"):
        return out
    mark = float(curr_px or 0)
    peak = float(peak_px or 0)
    if mark <= 0 and peak <= 0:
        return out
    for i, raw in enumerate(list(tv_tps or [])[:3]):
        level = i + 1
        tp = float(raw or 0)
        if tp <= 0:
            break
        reached = False
        if mark > 0 and (
            price_reached_tp(mark, tp, side) or tp_would_instant_fill(side, tp, mark)
        ):
            reached = True
        elif peak > 0 and price_reached_tp(peak, tp, side):
            reached = True
        if reached:
            out.add(level)
        else:
            break
    return out


# Never place reduce-only TP at/through mark (instant partial close → ant residue)
TP_SAFE_BUFFER_PCT = 0.002
# After factory OPEN: forbid regime_cap market trim
OPEN_CAP_ALIGN_GRACE_SEC = 60.0


def tp_would_instant_fill(side: str | None, tp_price: float, mark_px: float) -> bool:
    """True when a reduce-only TP limit would fill immediately at mark."""
    mark = float(mark_px or 0)
    tp = float(tp_price or 0)
    if mark <= 0 or tp <= 0 or side not in ("LONG", "SHORT"):
        return False
    if side == "LONG":
        return tp <= mark * (1.0 + TP_SAFE_BUFFER_PCT * 0.25)
    return tp >= mark * (1.0 - TP_SAFE_BUFFER_PCT * 0.25)


def sanitize_tp_limit_price(
    side: str | None,
    tp_price: float,
    mark_px: float,
    *,
    buffer_pct: float = TP_SAFE_BUFFER_PCT,
) -> tuple[float, str]:
    """
    Gate / push TP away from mark so place≠instant fill.

    Returns (price, reason). price<=0 → do not place (no mark / invalid).
    """
    mark = float(mark_px or 0)
    tp = float(tp_price or 0)
    if mark <= 0:
        return 0.0, "no_mark"
    if tp <= 0 or side not in ("LONG", "SHORT"):
        return 0.0, "invalid_tp"
    buf = max(float(buffer_pct), 0.0005)
    if side == "LONG":
        floor = mark * (1.0 + buf)
        if tp < floor:
            return floor, "pushed_above_mark"
        return tp, "ok"
    ceil = mark * (1.0 - buf)
    if tp > ceil:
        return ceil, "pushed_below_mark"
    return tp, "ok"


def _ceil_to_qty_step(need: float, round_qty_fn) -> float:
    """Smallest exchange qty >= need (round_qty usually floors)."""
    need_f = float(need or 0)
    if need_f <= 0:
        return 0.0
    q = float(round_qty_fn(need_f))
    if q + 1e-12 >= need_f:
        return q
    from decimal import Decimal, ROUND_UP

    # Infer step: difference between two consecutive floored probes
    a = Decimal(str(float(round_qty_fn(0.001))))
    b = Decimal(str(float(round_qty_fn(0.002))))
    step = b - a
    if step <= 0:
        # Contract / integer lot (DeepCoin): step 1
        c = Decimal(str(float(round_qty_fn(1.5))))
        d = Decimal(str(float(round_qty_fn(2.5))))
        step = d - c if d > c else Decimal("1")
    if step <= 0:
        step = Decimal("0.001")
    return float(
        (Decimal(str(need_f)) / step).to_integral_value(rounding=ROUND_UP) * step
    )


def compute_tp_slices(
    qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    *,
    exclude_levels: set[int] | None = None,
    round_qty_fn=round_quantity,
    min_qty: float = 0.0,
    min_notional: float = 0.0,
    ref_price: float = 0.0,
    live_cap: float | None = None,
) -> list[tuple[int, float, float]]:
    """Absolute-ratio TP slices; never dump excluded (radar) share into last limit.

    Spec 10/20/70: when TP3 is excluded from placeable limits, TP1+TP2 must stay
    ≈30% of base qty — **not** renormalize so TP2 absorbs the 70% radar residual.
    That bug closed full ETH books at TP2 (~1904) while peer systems rode to 1920+.

    ``live_cap``: optional max total to hang (current position); base ``qty`` should
    be open anchor / initial when available.
    """
    exclude_levels = exclude_levels or set()
    ratios = regime_settings[regime]["ratios"]
    active: list[tuple[int, float, float]] = []
    for i, ratio in enumerate(ratios):
        level = i + 1
        price = float(tv_tps[i]) if i < len(tv_tps) else 0.0
        if level in exclude_levels or price <= 0:
            continue
        active.append((level, float(ratio), price))
    if not active or qty <= 0:
        return []

    floor = max(float(min_qty or 0), 0.0)
    min_n = max(float(min_notional or 0), 0.0)
    ref = max(float(ref_price or 0), 0.0)
    base = float(qty)
    cap_live = float(live_cap) if live_cap is not None and float(live_cap) > 0 else base

    def _notional_floor_qty(px: float) -> float:
        if min_n <= 0 or (ref <= 0 and px <= 0):
            return 0.0
        use = float(px or ref or 0)
        if use <= 0:
            return 0.0
        return _ceil_to_qty_step(float(min_n) / use, round_qty_fn)

    total_ratio = sum(r for _, r, _ in active)
    # Hard placeable budget from absolute ratios (do NOT use base * 1.0).
    placeable_budget = min(cap_live, round_qty_fn(base * total_ratio) if total_ratio > 0 else 0.0)
    if placeable_budget <= 0 and total_ratio > 0:
        placeable_budget = min(cap_live, base * total_ratio)

    # Absolute split — last tier does NOT receive (base - allocated).
    raw: list[tuple[int, float, float]] = []
    for level, ratio, price in active:
        part_qty = round_qty_fn(base * ratio)
        if part_qty > 0:
            raw.append((level, part_qty, price))

    slices: list[tuple[int, float, float]] = []
    carry = 0.0
    for idx, (level, part_qty, price) in enumerate(raw):
        q = round_qty_fn(float(part_qty) + carry)
        carry = 0.0
        is_last = idx == len(raw) - 1
        need_q = max(floor, _notional_floor_qty(price))
        if not is_last and need_q > 0 and q + 1e-12 < need_q:
            # Fold undersized early tier into next placeable — still inside budget.
            carry = float(q)
            continue
        if q > 0:
            slices.append((level, q, price))
    if carry > 0 and slices:
        lvl, q, px = slices[-1]
        slices[-1] = (lvl, round_qty_fn(float(q) + carry), px)
    elif carry > 0 and not slices:
        # Cannot form a placeable tier — leave all to radar (better than full-TP dump).
        return []

    slices = _fold_notional_undersized(slices, min_n, round_qty_fn)
    # Enforce budget: shrink from the end; never let placeable ≈ 100% of book.
    used = sum(float(q) for _, q, _ in slices)
    budget = float(placeable_budget or 0)
    if budget > 0 and used > budget + 1e-12:
        overflow = used - budget
        trimmed: list[tuple[int, float, float]] = []
        for lvl, q, px in reversed(slices):
            qf = float(q)
            if overflow <= 1e-12:
                trimmed.append((lvl, round_qty_fn(qf), px))
                continue
            take = min(qf, overflow)
            overflow -= take
            left = round_qty_fn(qf - take)
            if left > 0:
                trimmed.append((lvl, left, px))
        slices = list(reversed(trimmed))
    used = sum(float(q) for _, q, _ in slices)
    # Catastrophic guard: if TP3 reserved and placeable still ≥95% of base, wipe.
    if 3 in exclude_levels and base > 0 and used + 1e-12 >= 0.95 * min(base, cap_live):
        return []
    # Clamp to live_cap
    if cap_live + 1e-12 < used:
        overflow = used - cap_live
        trimmed = []
        for lvl, q, px in reversed(slices):
            qf = float(q)
            if overflow <= 1e-12:
                trimmed.append((lvl, round_qty_fn(qf), px))
                continue
            take = min(qf, overflow)
            overflow -= take
            left = round_qty_fn(qf - take)
            if left > 0:
                trimmed.append((lvl, left, px))
        slices = list(reversed(trimmed))
    return slices


def top_up_tp12_to_target_ratio(
    slices: list[tuple[int, float, float]],
    *,
    base_qty: float,
    tv_tps: list[float] | None = None,
    target_ratio: float = 0.30,
    max_placeable_frac: float = 0.35,
    round_qty_fn=round_quantity,
    min_lot: float = 0.0,
    min_notional: float = 0.0,
) -> list[tuple[int, float, float]]:
    """After lot/notional folds, top up TP1+TP2 toward ≈30% without eating radar.

    Small XAU/ETH opens (e.g. 0.014) can fold TP1 under min_notional then
    ``ensure_tp1_min_lot`` leaves ~21% placeable; self-check then wiped the book
    (empty TP12 + chief_auditor_fail). Prefer topping up TP2 within the 35%
    radar-safe budget over returning an empty placeable set.
    """
    base = float(base_qty or 0)
    if base <= 0:
        return list(slices or [])
    tps = list(tv_tps or [])
    by_lv: dict[int, tuple[float, float]] = {
        int(lv): (float(q), float(px)) for lv, q, px in (slices or []) if float(q) > 0
    }
    # Ensure each hung tier clears exchange min notional when budget allows
    max_placeable = round_qty_fn(base * float(max_placeable_frac))
    min_n = max(float(min_notional or 0), 0.0)
    lot = max(float(min_lot or 0), 0.0)

    def _need_qty(px: float) -> float:
        need = lot
        if min_n > 0 and float(px or 0) > 0:
            need = max(need, min_n / float(px))
        if need <= 0:
            return 0.0
        return _ceil_to_qty_step(need, round_qty_fn)

    for lv in (1, 2):
        if lv not in by_lv:
            continue
        q, px = by_lv[lv]
        need = _need_qty(px)
        if need <= 0 or q + 1e-12 >= need:
            continue
        deficit = need - q
        used = sum(float(x[0]) for x in by_lv.values())
        room = max(0.0, float(max_placeable) - used)
        take = min(deficit, room)
        if take + 1e-12 < deficit:
            # Cannot clear min notional for this tier — drop it (fold qty into next)
            if lv == 1 and 2 in by_lv:
                q2, px2 = by_lv[2]
                by_lv[2] = (round_qty_fn(q2 + q), px2)
                del by_lv[1]
            continue
        by_lv[lv] = (round_qty_fn(q + take), px)

    used = sum(float(q) for q, _ in by_lv.values())
    target = round_qty_fn(base * float(target_ratio))
    if target <= 0:
        return [(lv, round_qty_fn(q), px) for lv, (q, px) in sorted(by_lv.items()) if q > 0]
    if used + 1e-12 >= target:
        return [(lv, round_qty_fn(q), px) for lv, (q, px) in sorted(by_lv.items()) if q > 0]

    need = float(target) - float(used)
    room = max(0.0, float(max_placeable) - float(used))
    add = round_qty_fn(min(need, room))
    if add <= 0:
        return [(lv, round_qty_fn(q), px) for lv, (q, px) in sorted(by_lv.items()) if q > 0]

    if 2 in by_lv:
        q2, px2 = by_lv[2]
        by_lv[2] = (round_qty_fn(q2 + add), px2)
    elif 1 in by_lv:
        q1, px1 = by_lv[1]
        by_lv[1] = (round_qty_fn(q1 + add), px1)
    elif tps:
        px2 = float(tps[1]) if len(tps) > 1 and float(tps[1] or 0) > 0 else float(tps[0] or 0)
        if px2 > 0:
            by_lv[2] = (add, px2)

    out = [(lv, round_qty_fn(q), px) for lv, (q, px) in sorted(by_lv.items()) if q > 0]
    used = sum(float(q) for _, q, _ in out)
    if used + 1e-12 >= 0.95 * base:
        return list(slices or [])
    return out


def ensure_tp1_min_lot(
    slices: list[tuple[int, float, float]],
    *,
    total_qty: float,
    tv_tps: list[float] | None,
    min_lot: float,
    round_qty_fn=round_quantity,
    max_placeable_frac: float = 0.35,
) -> list[tuple[int, float, float]]:
    """Guarantee TP1 hangs at least ``min_lot`` when inventory allows.

    DeepCoin/contract exchanges: min_lot=1 (1 contract). Coin-margined ETH:
    exchange ``min_order_qty``. Never let placeable TP1+TP2 exceed ~35% of book
    (radar must keep the residual). If total is too small for TP1+radar residual,
    return empty (all radar) rather than hanging an illegal/undersized TP1.
    """
    lot = float(min_lot or 0)
    total = float(total_qty or 0)
    if lot <= 0 or total <= 0:
        return list(slices or [])
    tps = list(tv_tps or [])
    tp1_px = float(tps[0]) if tps else 0.0
    if tp1_px <= 0:
        return list(slices or [])

    by_lv: dict[int, tuple[float, float]] = {
        int(lv): (float(q), float(px)) for lv, q, px in (slices or [])
    }
    # Already OK
    if 1 in by_lv and by_lv[1][0] + 1e-12 >= lot:
        return [(lv, q, px) for lv, (q, px) in sorted(by_lv.items())]

    # Need room: TP1 min + some residual for radar (≥ ~65%)
    max_placeable = round_qty_fn(total * float(max_placeable_frac))
    if max_placeable + 1e-12 < lot:
        # Cannot hang legal TP1 without eating radar residual — all to radar
        return []

    # Steal from TP2 first, then drop TP2 if needed
    need = lot - float(by_lv.get(1, (0.0, tp1_px))[0])
    tp2_q, tp2_px = by_lv.get(2, (0.0, float(tps[1]) if len(tps) > 1 else 0.0))
    take = min(float(tp2_q), need)
    tp2_q = round_qty_fn(float(tp2_q) - take)
    need -= take
    if need > 1e-12:
        # Still short — only proceed if leftover placeable budget allows fresh TP1
        used_other = sum(float(q) for lv, (q, _) in by_lv.items() if lv != 1)
        if used_other + lot > max_placeable + 1e-12:
            return []
    by_lv[1] = (lot, tp1_px)
    if tp2_q > 0 and tp2_px > 0:
        by_lv[2] = (tp2_q, tp2_px)
    elif 2 in by_lv:
        del by_lv[2]

    out = [(lv, round_qty_fn(q), px) for lv, (q, px) in sorted(by_lv.items()) if q > 0]
    used = sum(float(q) for _, q, _ in out)
    if used + 1e-12 >= 0.95 * total:
        return []
    return out


def _fold_notional_undersized(
    slices: list[tuple[int, float, float]],
    min_notional: float,
    round_qty_fn,
) -> list[tuple[int, float, float]]:
    """Merge early TP tiers whose notional < min_notional into later tiers."""
    if not slices or float(min_notional or 0) <= 0:
        return slices
    out: list[tuple[int, float, float]] = []
    carry = 0.0
    for idx, (level, part_qty, price) in enumerate(slices):
        q = round_qty_fn(float(part_qty) + carry)
        carry = 0.0
        is_last = idx == len(slices) - 1
        notion = float(q) * float(price or 0)
        if not is_last and notion + 1e-9 < float(min_notional):
            carry = float(q)
            continue
        if q > 0:
            out.append((level, q, price))
    if carry > 0:
        if out:
            lvl, q, px = out[-1]
            out[-1] = (lvl, round_qty_fn(float(q) + carry), px)
        else:
            level, _, price = slices[-1]
            q = round_qty_fn(sum(float(x[1]) for x in slices))
            if q > 0:
                out.append((level, q, price))
    return out


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
    peak_px: float = 0.0,
) -> int | None:
    """
    Classify one position reduction as TP1/2/3 fill.

    Requires price/peak at TP — qty drop alone (CAP trim / through-market) is not a fill.
    """
    old_q = float(old_qty or 0)
    new_q = float(new_qty or 0)
    reduced = old_q - new_q
    if reduced <= 0 or new_q < 0:
        return None
    consumed = {int(x) for x in (consumed_levels or []) if int(x) in (1, 2, 3)}
    anchor = float(initial_qty or old_q or 0)

    all_slices = compute_tp_slices(
        anchor if anchor > 0 else old_q,
        regime,
        tv_tps,
        regime_settings,
        exclude_levels=set(),
    )
    live_slices = compute_tp_slices(
        old_q, regime, tv_tps, regime_settings, exclude_levels=consumed,
    )
    next_level = (max(consumed) + 1) if consumed else 1
    for level, slice_qty, tp_px in all_slices:
        if level < next_level:
            continue
        if level > next_level:
            break
        if float(slice_qty) <= 0 or float(tp_px) <= 0:
            break
        min_drop = float(slice_qty) * 0.4
        if live_slices:
            min_drop = min(min_drop, float(live_slices[0][1]) * 0.4)
        if reduced + 1e-12 < max(min_drop, 1e-9):
            break
        px_ok = _price_or_peak_reached_tp(curr_px, tp_px, side, peak_px=peak_px)
        if not px_ok:
            break
        book_gone = not tp_limit_still_on_book(tp_px, open_tp_prices)
        tol = tp_fill_qty_tolerance(slice_qty, is_contracts=is_contracts)
        qty_match = abs(reduced - float(slice_qty)) <= tol
        if book_gone and (qty_match or px_ok):
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


def _price_or_peak_reached_tp(
    curr_px: float,
    tp_price: float,
    side: str | None,
    peak_px: float = 0.0,
) -> bool:
    """Mark now at TP, or peak/best already touched TP (fill then pullback)."""
    if price_reached_tp(curr_px, tp_price, side):
        return True
    peak = float(peak_px or 0)
    if peak > 0 and side in ("LONG", "SHORT"):
        return price_reached_tp(peak, tp_price, side, tol_pct=TP_TOUCH_PEAK_TOL_PCT)
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
    peak_px: float = 0.0,
) -> dict:
    """
    Evidence that a TP tier truly filled.

    Primary (user rule): TP limit gone from book + price reached/touched
    → filled. ETH/XAU mark noise may leave qty nearly unchanged briefly;
    do not require perfect slice qty for this path.

    Secondary: qty reduction match + book cleared (price may pull back).
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
    if not qty_ok and float(prefix_consumed_qty) > 0:
        qty_ok = float(reduced) + 1e-12 >= float(prefix_consumed_qty) * 0.55
    noise = qty_drift_tolerance(float(prefix_consumed_qty) or float(slice_qty), 0.0)
    if float(reduced) <= max(noise * 0.5, 1e-9) and float(reduced) < float(slice_qty) * 0.5:
        qty_ok = False
    detail["qty_ok"] = bool(qty_ok)
    detail["fill_tol"] = fill_tol

    book_cleared = not tp_limit_still_on_book(tp_price, open_tp_prices, price_tol=price_tol)
    detail["book_cleared"] = book_cleared

    has_mark = float(curr_px or 0) > 0 or float(peak_px or 0) > 0
    price_ok = (
        _price_or_peak_reached_tp(curr_px, tp_price, side, peak_px=peak_px)
        if has_mark
        else False
    )
    detail["price_ok"] = bool(price_ok)

    # Primary: 价到 + 限价消失 → 认定成交（必须有市价/峰值）
    if book_cleared and price_ok and has_mark:
        detail["confirmed"] = True
        detail["confirm_mode"] = "price_book"
        return detail

    # Secondary: qty + book only when price also touched (forbid CAP/穿价秒平成 TP)
    if qty_ok and book_cleared and price_ok:
        detail["confirmed"] = True
        detail["confirm_mode"] = "qty_book"
        return detail

    if require_price and not price_ok:
        return detail

    # require_price=False (rare recovery): allow qty+book without mark
    if not require_price and qty_ok and book_cleared:
        detail["confirmed"] = True
        detail["confirm_mode"] = "qty_book_no_mark"
        return detail

    detail["confirmed"] = bool(qty_ok and book_cleared and price_ok)
    detail["confirm_mode"] = "triple" if detail["confirmed"] else "none"
    return detail


def infer_prefix_filled_levels(
    *,
    reduced: float,
    all_slices: list[tuple[int, float, float]],
    open_tp_prices: list[float] | None,
    is_contracts: bool = False,
    price_tol: float = 0.02,
    curr_px: float = 0.0,
    side: str | None = None,
    peak_px: float = 0.0,
) -> set[int]:
    """
    If reduction matches sum(TP1..TPk) and those limits are gone, mark 1..k.

    Requires price/peak at each tier — CAP/穿价秒平不得冒充 TP12 成交.
    """
    filled: set[int] = set()
    if reduced <= 0 or not all_slices:
        return filled
    prefix = 0.0
    for level, slice_qty, tp_price in all_slices:
        prefix += float(slice_qty)
        tol = tp_fill_qty_tolerance(prefix, is_contracts=is_contracts)
        qty_ok = abs(float(reduced) - prefix) <= tol or float(reduced) + 1e-12 >= prefix * 0.55
        if not qty_ok:
            break
        if not _price_or_peak_reached_tp(curr_px, tp_price, side, peak_px=peak_px):
            break
        if tp_limit_still_on_book(tp_price, open_tp_prices, price_tol=price_tol):
            break
        filled.add(int(level))
        if float(reduced) <= prefix + tol:
            break
    return filled


def should_skip_rehang_tp_level(
    level: int,
    tp_price: float,
    *,
    side: str | None,
    curr_px: float,
    consumed: set[int] | list[int] | None,
    live_qty: float,
    initial_qty: float,
    regime: int,
    tv_tps: list[float],
    regime_settings: dict,
    open_tp_prices: list[float] | None = None,
    is_contracts: bool = False,
    peak_px: float = 0.0,
) -> tuple[bool, str]:
    """
    Hard gate before placing ANY TP limit.

    User rule: TP limit gone + price reached/touched → never rehang; wait for
    higher tiers. Also skip consumed / mark past / qty+book evidence.
    """
    lvl = int(level)
    consumed_set = {int(x) for x in (consumed or []) if int(x) in (1, 2, 3)}
    if lvl in consumed_set:
        return True, "consumed"
    tp = float(tp_price or 0)
    if tp <= 0:
        return True, "invalid_price"
    # No mark → never place (would risk through-market instant fill)
    if float(curr_px or 0) <= 0:
        return True, "no_mark_price"

    book_gone = not tp_limit_still_on_book(tp, open_tp_prices)
    touched = _price_or_peak_reached_tp(curr_px, tp, side, peak_px=peak_px)

    # Primary: 价到 + 该档限价没了 → 已成交，禁止补挂
    if book_gone and touched:
        return True, "price_book_filled"

    # Mark at/past TP → never place at raw TV price (caller may sanitize/push)
    if side in ("LONG", "SHORT") and tp_would_instant_fill(side, tp, curr_px):
        return True, "price_past_tp"

    anchor = float(initial_qty or 0)
    live = float(live_qty or 0)
    if anchor > 0 and live < anchor:
        all_slices = compute_tp_slices(
            anchor, regime, tv_tps, regime_settings, exclude_levels=set(),
        )
        by_level = {l: (q, px) for l, q, px in all_slices}
        if lvl in by_level:
            slice_qty, _ = by_level[lvl]
            prefix = sum(by_level[l][0] for l in by_level if l <= lvl)
            reduced = round_quantity(anchor - live)
            min_drop = max(float(slice_qty) * 0.5, float(prefix) * 0.4)
            if book_gone and reduced + 1e-12 >= min_drop:
                return True, "qty_book_implies_filled"

    return False, ""


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
    peak_px: float = 0.0,
) -> set[int]:
    """
    Infer consumed TP tiers.

    Prefer price_reached/touched + book cleared (ignore tiny ETH/XAU qty noise).
    Also: qty+book, prefix multi-fill. Never invent fills on a still-full open
    without book/price evidence.
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

    by_level = {lvl: (q, px) for lvl, q, px in all_slices}
    filled: set[int] = set()
    peak = float(peak_px or 0)

    # Price+book path works even when qty barely moved (API lag / mark noise)
    def _confirm(level: int, slice_qty: float, tp_price: float, *, require_price: bool) -> dict:
        prefix_qty = sum(by_level[l][0] for l in by_level if l <= level)
        return confirm_tp_tier_fill(
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
            require_price=require_price,
            peak_px=peak,
        )

    # Sanitize persisted — drop false consumes when TP limit still on book
    for level in sorted(persisted):
        if level not in by_level:
            continue
        slice_qty, tp_price = by_level[level]
        ev = _confirm(level, slice_qty, tp_price, require_price=True)
        if ev["confirmed"]:
            filled.add(level)
        elif ev.get("price_ok") and ev.get("book_cleared"):
            filled.add(level)
        # else: stale consumed while limit still live → drop

    # Discover contiguous tiers: must have price/peak at TP
    next_level = (max(filled) + 1) if filled else 1
    for level, slice_qty, tp_price in all_slices:
        if level < next_level:
            continue
        if level > next_level:
            break
        ev = _confirm(level, slice_qty, tp_price, require_price=True)
        if ev.get("confirm_mode") == "price_book" or (
            ev["confirmed"] and ev.get("confirm_mode") in ("price_book", "qty_book", "triple")
        ):
            filled.add(level)
            next_level = level + 1
            continue
        break

    # Prefix multi-fill when qty drop is material + price evidence
    tp1_slice = float(all_slices[0][1])
    min_reduce = max(
        tp1_slice * 0.5,
        tp_fill_qty_tolerance(tp1_slice, is_contracts=is_contracts) * 0.5,
    )
    if reduced >= min_reduce:
        filled |= infer_prefix_filled_levels(
            reduced=reduced,
            all_slices=all_slices,
            open_tp_prices=open_tp_prices,
            is_contracts=is_contracts,
            price_tol=price_tol,
            curr_px=curr_px,
            side=side,
            peak_px=peak,
        )

    return filled


def slices_to_level_dicts(slices: list[tuple[int, float, float]]) -> list[dict]:
    return [{"level": lvl, "qty": q, "price": px} for lvl, q, px in slices]
