"""TP slice guard — consumed tier exclude + infer from initial qty."""

import pytest

from app.core.tp_slice_guard import compute_tp_slices, infer_filled_tp_levels

REGIME_SETTINGS = {
    3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
}
TV_TPS = [1810.27, 1829.88, 1847.32]


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


def test_infer_tp1_from_price_cross_without_order():
    filled = infer_filled_tp_levels(
        0.987,
        1815.0,
        "LONG",
        initial_qty=1.234,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[1829.88, 1847.32],
        qty_tol=0.05,
    )
    assert 1 in filled


def test_infer_tp_prefix_from_initial_qty():
    """When live qty matches initial minus first-tier slice, mark TP1 consumed."""
    initial = 1.0
    slices = compute_tp_slices(
        initial, 3, TV_TPS, REGIME_SETTINGS, round_qty_fn=lambda x: round(x, 3),
    )
    tp1_qty = slices[0][1]
    live = round(initial - tp1_qty, 3)
    filled = infer_filled_tp_levels(
        live,
        0.0,
        "LONG",
        initial_qty=initial,
        consumed_tp_levels=[],
        regime=3,
        tv_tps=TV_TPS,
        regime_settings=REGIME_SETTINGS,
        open_tp_prices=[],
        qty_tol=0.01,
    )
    assert 1 in filled
