"""TP slice guard — evidence-based fill (qty + book + price)."""

from app.core.tp_slice_guard import (
    compute_tp_slices,
    confirm_tp_tier_fill,
    infer_filled_tp_levels,
    match_qty_reduction_to_tp_level,
    price_reached_tp,
    tp_limit_still_on_book,
)
from app.core.position_qty_tolerance import tp_slice_qty_tolerance
from app.core.tp_regime_ratios import build_regime_settings

REGIME_SETTINGS = {
    3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
}
TV_TPS = [1810.27, 1829.88, 1847.32]
INITIAL = 1.234


def test_exclude_tp1_redistributes_remaining_qty():
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
    assert abs(sum(q for _, q, _ in slices) - 0.987) < 0.002


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


def test_price_not_at_tp1_blocks_fill():
    slices = compute_tp_slices(INITIAL, 3, TV_TPS, REGIME_SETTINGS)
    tp1_qty = slices[0][1]
    live = round(INITIAL - tp1_qty, 3)
    filled = infer_filled_tp_levels(
        live,
        1805.0,  # below TP1
        "LONG",
        initial_qty=INITIAL,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],
    )
    assert filled == set()


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
    """Restart with curr_px=0: qty + book cleared is enough."""
    slices = compute_tp_slices(
        1.0, 3, TV_TPS, REGIME_SETTINGS, round_qty_fn=lambda x: round(x, 3),
    )
    tp1_qty = slices[0][1]
    live = round(1.0 - tp1_qty, 3)
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


def test_keep_three_tps_when_qty_covers_min():
    rs = build_regime_settings()
    slices = compute_tp_slices(
        0.03, 2, [100.0, 101.0, 102.0], rs,
        round_qty_fn=lambda x: round(x, 3),
        min_qty=0.01,
    )
    assert len(slices) == 3
    assert all(q >= 0.01 - 1e-9 for _, q, _ in slices)
    assert abs(sum(q for _, q, _ in slices) - 0.03) < 1e-9
