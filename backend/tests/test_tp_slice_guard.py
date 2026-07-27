"""TP slice guard — evidence-based fill (qty + book + price)."""

from app.core.tp_slice_guard import (
    compute_tp_slices,
    confirm_tp_tier_fill,
    ensure_tp1_min_lot,
    infer_filled_tp_levels,
    match_qty_reduction_to_tp_level,
    price_reached_tp,
    resolve_tp_step_fill_level,
    top_up_tp12_to_target_ratio,
    tp_limit_still_on_book,
)
from app.core.position_qty_tolerance import tp_slice_qty_tolerance
from app.core.tp_regime_ratios import build_regime_settings

REGIME_SETTINGS = {
    3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
}
TV_TPS = [1810.27, 1829.88, 1847.32]
INITIAL = 1.234


def test_exclude_tp1_keeps_absolute_ratios_not_full_dump():
    """Excluding a filled tier must NOT renormalize remaining into 100% of live."""
    slices = compute_tp_slices(
        0.987,
        3,
        TV_TPS,
        REGIME_SETTINGS,
        exclude_levels={1},
        round_qty_fn=lambda x: round(x, 3),
    )
    assert len(slices) == 2
    assert slices[0][0] == 2
    assert slices[1][0] == 3
    # Absolute 0.32+0.50 of 0.987 — not full 0.987 dump into TP2+TP3
    used = sum(q for _, q, _ in slices)
    assert abs(used - 0.987 * (0.32 + 0.50)) < 0.02
    assert used + 1e-9 < 0.987


def test_exclude_tp3_never_eats_radar_residual():
    """Placeable-only: TP1+TP2 ≤ ~30%; must not assign full book to TP2 (1904 incident)."""
    rs = {3: {"margin": 0.0, "ratios": [0.10, 0.20, 0.70]}}
    tps = [1895.66, 1904.63, 1913.2]
    qty = 0.031
    slices = compute_tp_slices(
        qty,
        3,
        tps,
        rs,
        exclude_levels={3},
        round_qty_fn=lambda x: round(x, 3),
        min_notional=0.0,
    )
    used = sum(q for _, q, _ in slices)
    assert used > 0
    assert used <= qty * 0.35 + 1e-9
    assert abs(used - qty * 0.30) < 0.005
    assert all(lv in (1, 2) for lv, _, _ in slices)

def test_match_tp1_reduction_from_initial_open():
    slices = compute_tp_slices(
        INITIAL, 3, TV_TPS, REGIME_SETTINGS, round_qty_fn=lambda x: round(x, 3),
    )
    tp1_qty = slices[0][1]
    reduced = round(INITIAL - 0.987, 3)
    level = match_qty_reduction_to_tp_level(
        reduced,
        INITIAL,
        3,
        TV_TPS,
        REGIME_SETTINGS,
    )
    assert level == 1
    assert abs(reduced - tp1_qty) <= tp_slice_qty_tolerance(INITIAL)


def test_infer_tp1_from_price_cross_without_order():
    """Qty drop + TP1 gone from book + price ≥ TP1 → fill."""
    filled = infer_filled_tp_levels(
        0.987,
        1815.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],
    )
    assert filled == {1}


def test_tp1_still_on_book_blocks_fill_even_with_qty_and_price():
    """TP1 limit still hanging → never mark filled / arm radar."""
    slices = compute_tp_slices(INITIAL, 3, TV_TPS, REGIME_SETTINGS)
    tp1_qty = slices[0][1]
    live = round(INITIAL - tp1_qty, 3)
    filled = infer_filled_tp_levels(
        live,
        1815.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=list(TV_TPS),  # TP1 still on book
    )
    assert filled == set()


def test_price_pullback_after_tp1_still_infers_fill():
    """After TP1 fill mark may dip; peak or qty+book still consume."""
    from app.core.tp_slice_guard import should_skip_rehang_tp_level

    slices = compute_tp_slices(INITIAL, 3, TV_TPS, REGIME_SETTINGS)
    tp1_qty = slices[0][1]
    live = round(INITIAL - tp1_qty, 3)
    filled = infer_filled_tp_levels(
        live,
        1805.0,  # below TP1 after fill pullback
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],  # TP1 gone
        peak_px=1812.0,  # had touched TP1
    )
    assert filled == {1}
    skip, reason = should_skip_rehang_tp_level(
        1,
        TV_TPS[0],
        side="LONG",
        curr_px=1805.0,
        consumed=filled,
        live_qty=live,
        initial_qty=INITIAL,
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],
        peak_px=1812.0,
    )
    assert skip is True
    assert reason in ("consumed", "qty_book_implies_filled", "price_past_tp", "price_book_filled")


def test_price_reached_and_tp1_gone_even_if_qty_barely_moved():
    """User rule: TP1 price reached + limit gone → filled (ignore ETH mark qty noise)."""
    filled = infer_filled_tp_levels(
        INITIAL - 0.01,  # tiny qty noise, not a full TP1 slice
        1811.0,  # at/past TP1
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],  # TP1 gone
    )
    assert 1 in filled


def test_prefix_tp1_tp2_multi_fill():
    """TP1+TP2 fill in one poll must mark both — not fall through to empty consume."""
    from app.core.tp_slice_guard import infer_prefix_filled_levels

    slices = compute_tp_slices(INITIAL, 3, TV_TPS, REGIME_SETTINGS)
    prefix12 = slices[0][1] + slices[1][1]
    live = round(INITIAL - prefix12, 3)
    filled = infer_filled_tp_levels(
        live,
        1830.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1847.32],  # only TP3 left
    )
    assert 1 in filled and 2 in filled
    # Remaining plan must exclude TP1/TP2
    remain = compute_tp_slices(
        live, 3, TV_TPS, REGIME_SETTINGS, exclude_levels=filled,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert all(lvl == 3 for lvl, _, _ in remain)


def test_micro_noise_reduction_does_not_infer_tp1():
    """Tiny ETH size jitter must not look like TP1 fill."""
    filled = infer_filled_tp_levels(
        INITIAL - 0.01,
        1935.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=list(TV_TPS),
    )
    assert filled == set()


def test_r4_full_position_does_not_false_infer_tp1():
    rs = build_regime_settings()
    anchor = 1.584
    tps = [1968.8, 1999.13, 2036.77]
    filled = infer_filled_tp_levels(
        anchor,
        1935.0,
        "LONG",
        initial_qty=anchor,
        consumed_tp_levels=[],
        regime=4,
        tv_tps=tps,
        regime_settings=rs,
        open_tp_prices=tps,
    )
    assert filled == set()


def test_r4_true_tp1_reduction_still_infers():
    rs = build_regime_settings()
    anchor = 1.584
    tps = [1968.8, 1999.13, 2036.77]
    slices = compute_tp_slices(anchor, 4, tps, rs)
    tp1_qty = slices[0][1]
    live = round(anchor - tp1_qty, 3)
    filled = infer_filled_tp_levels(
        live,
        1970.0,
        "LONG",
        initial_qty=anchor,
        consumed_tp_levels=[],
        regime=4,
        tv_tps=tps,
        regime_settings=rs,
        open_tp_prices=[1999.13, 2036.77],
    )
    assert filled == {1}


def test_r4_tp1_on_book_blocks_even_after_price_stretch():
    """User scenario: price runs, TP1 limit still live → no radar."""
    rs = build_regime_settings()
    anchor = 1.584
    tps = [1968.8, 1999.13, 2036.77]
    filled = infer_filled_tp_levels(
        anchor - 0.02,  # noise-ish
        1975.0,  # price stretched past TP1
        "LONG",
        initial_qty=anchor,
        consumed_tp_levels=[1],  # stale false consume
        regime=4,
        tv_tps=tps,
        regime_settings=rs,
        open_tp_prices=tps,  # TP1 limit still there
    )
    assert filled == set()


def test_infer_does_not_mark_all_tps_when_price_crossed_but_qty_only_tp1():
    filled = infer_filled_tp_levels(
        0.987,
        1850.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],
    )
    assert filled == {1}
    assert 2 not in filled
    assert 3 not in filled


def test_infer_tp_prefix_from_initial_qty_restart():
    """Restart: no mark → do not invent TP fills; with peak evidence OK."""
    slices = compute_tp_slices(
        1.0, 3, TV_TPS, REGIME_SETTINGS, round_qty_fn=lambda x: round(x, 3),
    )
    tp1_qty = slices[0][1]
    live = round(1.0 - tp1_qty, 3)
    # No mark / peak → refuse (avoid CAP/穿价秒平误报 TP)
    assert infer_filled_tp_levels(
        live, 0.0, "LONG",
        initial_qty=1.0, consumed_tp_levels=[], regime=3,
        tv_tps=TV_TPS, regime_settings=REGIME_SETTINGS, open_tp_prices=[],
    ) == set()
    # Peak touched TP1 → OK
    filled = infer_filled_tp_levels(
        live,
        0.0,
        "LONG",
        initial_qty=1.0,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[],
        peak_px=TV_TPS[0],
    )
    assert filled == {1}


def test_startup_scenario_tp1_done_remaining_gets_tp23_only():
    filled = infer_filled_tp_levels(
        0.987,
        1815.0,
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[],
    )
    assert filled == {1}
    remaining = compute_tp_slices(
        0.987, 3, TV_TPS, REGIME_SETTINGS, exclude_levels=filled,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert len(remaining) == 2
    assert {lvl for lvl, _, _ in remaining} == {2, 3}


def test_confirm_tp_tier_fill_triple_gate():
    ok = confirm_tp_tier_fill(
        level=1,
        slice_qty=0.222,
        tp_price=1810.27,
        reduced=0.222,
        prefix_consumed_qty=0.222,
        curr_px=1815.0,
        side="LONG",
        open_tp_prices=[1829.88],
    )
    assert ok["confirmed"] is True
    blocked = confirm_tp_tier_fill(
        level=1,
        slice_qty=0.222,
        tp_price=1810.27,
        reduced=0.222,
        prefix_consumed_qty=0.222,
        curr_px=1815.0,
        side="LONG",
        open_tp_prices=[1810.27],
    )
    assert blocked["confirmed"] is False
    assert blocked["book_cleared"] is False


def test_helpers_price_and_book():
    assert price_reached_tp(1815.0, 1810.27, "LONG")
    assert not price_reached_tp(1800.0, 1810.27, "LONG")
    assert tp_limit_still_on_book(1810.27, [1810.28, 1829.0])
    assert not tp_limit_still_on_book(1810.27, [1829.0, 1847.0])
    # XAU short TP (price down) — relative slack, not ETH-sized absolute
    assert price_reached_tp(4004.0, 4004.75, "SHORT")
    assert not price_reached_tp(4020.0, 4004.75, "SHORT")


def test_keep_absolute_ratios_with_min_qty_floor():
    """Absolute 10/20/70: min_qty may fold early tiers, but must not dump 100% into one TP when TP3 present."""
    rs = build_regime_settings()
    slices = compute_tp_slices(
        1.0, 2, [100.0, 101.0, 102.0], rs,
        round_qty_fn=lambda x: round(x, 3),
        min_qty=0.01,
    )
    assert len(slices) == 3
    used = sum(q for _, q, _ in slices)
    assert abs(used - 1.0) < 1e-6  # full book when TP3 included
    assert abs(slices[0][1] - 0.10) < 0.02
    assert abs(slices[1][1] - 0.20) < 0.02
    assert abs(slices[2][1] - 0.70) < 0.02


def test_resolve_tp2_fill_after_heal_uses_remaining_plan():
    """After TP1, heal re-slices placeable TP2 on absolute 20% of anchor."""
    rs = build_regime_settings()
    tps = [1848.0, 1851.49, 1854.18]
    initial = 0.076
    old_qty = 0.031
    remaining = compute_tp_slices(
        initial, 1, tps, rs, exclude_levels={1, 3}, round_qty_fn=lambda x: round(x, 3),
        live_cap=old_qty,
    )
    assert len(remaining) == 1
    assert remaining[0][0] == 2
    tp2_qty = remaining[0][1]
    assert tp2_qty + 1e-9 < old_qty
    new_qty = round(old_qty - tp2_qty, 3)
    level = resolve_tp_step_fill_level(
        old_qty=old_qty,
        new_qty=new_qty,
        initial_qty=initial,
        regime=1,
        tv_tps=tps,
        regime_settings=rs,
        consumed_levels=[1],
        curr_px=1851.50,
        side="LONG",
        open_tp_prices=[1854.18],  # TP2 gone, TP3 still up
    )
    assert level == 2


def test_resolve_tp_fill_by_book_when_qty_slightly_off():
    rs = build_regime_settings()
    tps = [1848.0, 1851.49, 1854.18]
    level = resolve_tp_step_fill_level(
        old_qty=0.031,
        new_qty=0.009,
        initial_qty=0.076,
        regime=1,
        tv_tps=tps,
        regime_settings=rs,
        consumed_levels=[1],
        curr_px=1851.50,
        side="LONG",
        open_tp_prices=[1854.18],
    )
    assert level == 2


def test_ensure_tp1_min_lot_deepcoin_one_contract():
    """DeepCoin min lot = 1 contract (~0.1 ETH face): TP1 must not hang below 1."""
    tps = [2000.0, 2020.0, 2050.0]
    # Undersized TP1 stolen from fold / tiny ratio
    raw = [(1, 0.0, 2000.0), (2, 3.0, 2020.0)]
    out = ensure_tp1_min_lot(
        raw,
        total_qty=20.0,
        tv_tps=tps,
        min_lot=1.0,
        round_qty_fn=lambda x: float(int(max(x, 0))),
    )
    by = {lv: q for lv, q, _ in out}
    assert by.get(1) == 1.0
    assert by.get(2, 0) >= 0


def test_ensure_tp1_min_lot_empty_when_inventory_too_small():
    """Cannot hang legal TP1 + radar residual → all radar (empty placeable)."""
    out = ensure_tp1_min_lot(
        [(1, 0.0, 2000.0)],
        total_qty=2.0,
        tv_tps=[2000.0, 2020.0],
        min_lot=1.0,
        round_qty_fn=lambda x: float(int(max(x, 0))),
        max_placeable_frac=0.35,
    )
    assert out == []


def test_small_xau_top_up_recovers_tp12_near_30pct():
    """0.014 XAU: min_notional fold + min_lot left ~21%; top-up must restore ≈30%."""
    from app.core.symbol_precision import round_quantity
    from app.core.pipeline_officers import ExecutionOfficer

    qty = 0.014
    tps = [4062.36, 4049.15, 4036.52]
    rs = {3: {"ratios": [0.10, 0.20, 0.70]}}
    rq = lambda x: round_quantity(x, "XAUUSDT")
    raw = compute_tp_slices(
        qty,
        3,
        tps,
        rs,
        exclude_levels={3},
        round_qty_fn=rq,
        min_qty=0.001,
        min_notional=5.0,
        ref_price=4077.09,
        live_cap=qty,
    )
    mid = ensure_tp1_min_lot(
        raw, total_qty=qty, tv_tps=tps, min_lot=0.001, round_qty_fn=rq
    )
    out = top_up_tp12_to_target_ratio(
        mid,
        base_qty=qty,
        tv_tps=tps,
        round_qty_fn=rq,
        min_lot=0.001,
        min_notional=5.0,
    )
    used = sum(q for _, q, _ in out)
    assert used > 0
    assert used <= qty * 0.35 + 1e-9
    assert abs(used / qty - 0.30) <= 0.04 + 1e-9
    ok, detail = ExecutionOfficer.self_check_tp_slices(qty, out, relax_for_min_lot=True)
    assert ok, detail
    # Each hung leg must clear ~5U notional at XAU prices
    for _, q, px in out:
        assert float(q) * float(px) + 1e-9 >= 5.0
