"""Flat OPEN must not instantly partial-close via through-market TP or CAP trim."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from app.core.tp_slice_guard import (
    OPEN_CAP_ALIGN_GRACE_SEC,
    infer_filled_tp_levels,
    sanitize_tp_limit_price,
    tp_would_instant_fill,
)
from app.core.position_cap_guard import PositionCapGuardMixin


def test_sanitize_pushes_long_tp_above_mark():
    px, reason = sanitize_tp_limit_price("LONG", 1800.0, 1850.0)
    assert reason == "pushed_above_mark"
    assert px > 1850.0
    assert not tp_would_instant_fill("LONG", px, 1850.0)


def test_sanitize_blocks_without_mark():
    px, reason = sanitize_tp_limit_price("LONG", 1900.0, 0)
    assert px == 0.0
    assert reason == "no_mark"


def test_cap_align_skipped_in_open_grace():
    class _P(PositionCapGuardMixin):
        user_id = 1
        exchange_id = "binance"
        regime = 2
        trade_opened_at = time.time()
        regime_settings = {2: {"margin": 0.25, "ratios": [0.2, 0.3, 0.5]}}
        initial_principal = 1000.0
        risk_multiplier = 1.0
        current_side = "LONG"

        def _log(self, *a, **k):
            pass

        def _alert(self, *a, **k):
            pass

        def _cap_oversize_detail(self, *a, **k):
            raise AssertionError("should not compute cap during grace")

    p = _P()
    out = p._enforce_regime_cap_alignment(1.0, 1800.0, 1800.0, reason="哨兵")
    assert out.get("skipped") == "open_grace"
    assert OPEN_CAP_ALIGN_GRACE_SEC >= 30


def test_cap_align_skipped_post_open_reason():
    class _P(PositionCapGuardMixin):
        user_id = 1
        exchange_id = "binance"
        trade_opened_at = 0

        def _log(self, *a, **k):
            pass

        def _alert(self, *a, **k):
            pass

        def _cap_oversize_detail(self, *a, **k):
            raise AssertionError("post-open reason must skip")

    p = _P()
    out = p._enforce_regime_cap_alignment(1.0, 1800.0, 1800.0, reason="开仓后叠仓核验")
    assert out.get("skipped") == "open_grace"


def test_qty_drop_without_price_not_tp12():
    """Through-market / CAP trim must NOT be labeled TP1/TP2 when mark never reached TP."""
    rs = {
        2: {"margin": 0.25, "ratios": [0.2, 0.3, 0.5], "activation": 0.6, "trail_offset": 0.9},
    }
    tps = [1900.0, 1950.0, 2000.0]  # far above mark
    filled = infer_filled_tp_levels(
        0.05,  # tiny leftover after "instant" close
        1850.0,  # mark never reached 1900
        "LONG",
        initial_qty=0.25,
        consumed_tp_levels=[],
        regime=2,
        tv_tps=tps,
        regime_settings=rs,
        open_tp_prices=[],  # books empty after instant fills
        peak_px=1850.0,
    )
    assert filled == set()
