"""TP slice guard — consumed tier exclude + infer from initial qty."""

import pytest

from app.core.tp_slice_guard import (
    compute_tp_slices,
    infer_filled_tp_levels,
    match_qty_reduction_to_tp_level,
)
from app.core.position_qty_tolerance import tp_slice_qty_tolerance

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
    tol = tp_slice_qty_tolerance(INITIAL)
    level = match_qty_reduction_to_tp_level(
        reduced,
        INITIAL,
        3,
        TV_TPS,
        REGIME_SETTINGS,
        qty_tol=tol,
    )
    assert level == 1
    assert abs(reduced - tp1_qty) <= tol


def test_infer_tp1_from_price_cross_without_order():
    tol = tp_slice_qty_tolerance(INITIAL)
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
        qty_tol=tol,
    )
    assert filled == {1}


def test_r4_full_position_does_not_false_infer_tp1():
    """R4 TP1≈5% ≤ 8% qty tol — full open must NOT mark TP1 (was false-arming radar)."""
    from app.core.tp_regime_ratios import build_regime_settings

    rs = build_regime_settings()
    anchor = 1.584
    tps = [1968.8, 1999.13, 2036.77]
    tol = tp_slice_qty_tolerance(anchor)
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
        qty_tol=tol,
    )
    assert filled == set()


def test_r4_true_tp1_reduction_still_infers():
    from app.core.tp_regime_ratios import build_regime_settings

    rs = build_regime_settings()
    anchor = 1.584
    tps = [1968.8, 1999.13, 2036.77]
    slices = compute_tp_slices(anchor, 4, tps, rs)
    tp1_qty = slices[0][1]
    live = round(anchor - tp1_qty, 3)
    tol = tp_slice_qty_tolerance(anchor)
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
        qty_tol=tol,
    )
    assert filled == {1}


def test_infer_does_not_mark_all_tps_when_price_crossed_but_qty_only_tp1():
    """Restart bug: price above all TPs must not consume TP2/3 if live qty only reflects TP1."""
    tol = tp_slice_qty_tolerance(INITIAL)
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
        qty_tol=tol,
    )
    assert filled == {1}
    assert 2 not in filled
    assert 3 not in filled


def test_infer_tp_prefix_from_initial_qty():
    slices = compute_tp_slices(
        1.0, 3, TV_TPS, REGIME_SETTINGS, round_qty_fn=lambda x: round(x, 3),
    )
    tp1_qty = slices[0][1]
    live = round(1.0 - tp1_qty, 3)
    tol = tp_slice_qty_tolerance(1.0)
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
        qty_tol=tol,
    )
    assert filled == {1}


def test_startup_scenario_tp1_done_remaining_gets_tp23_only():
    """Screenshot 2: initial 1.234, live 0.987 after TP1 — only TP2/TP3 slices."""
    tol = tp_slice_qty_tolerance(INITIAL)
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
        qty_tol=tol,
    )
    assert filled == {1}
    remaining = compute_tp_slices(
        0.987, 3, TV_TPS, REGIME_SETTINGS, exclude_levels=filled,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert len(remaining) == 2
    assert {lvl for lvl, _, _ in remaining} == {2, 3}
    assert abs(sum(q for _, q, _ in remaining) - 0.987) < 0.002
