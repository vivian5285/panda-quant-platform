"""Per-user admin margin% × leverage sizing overrides."""

from app.core.tv_entry_sizing import compute_tv_entry_qty
from app.services.trading_control import clamp_leverage, clamp_margin_pct_frac


def test_clamp_margin_accepts_percent_or_frac():
    assert clamp_margin_pct_frac(0.2) == 0.2
    assert clamp_margin_pct_frac(20) == 0.2
    assert clamp_leverage(10) == 10


def test_custom_margin_and_leverage_sizes_notional():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=2000.0,
        margin_pct=0.10,
        leverage=10,
        round_fn=lambda x: round(x, 3),
        min_qty=0.001,
        symbol="ETHUSDT",
    )
    # 1000 × 0.10 × 10 / 2000 = 0.5
    assert abs(qty - 0.5) < 1e-6
    assert meta["margin_pct_frac"] == 0.1
    assert meta["leverage"] == 10
    assert meta["binding"] == "margin10_lev10"
    assert abs(meta["notional_target"] - 1000.0) < 1e-6


def test_default_still_margin20_lev5():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=2000.0,
        round_fn=lambda x: round(x, 3),
        min_qty=0.001,
        symbol="ETHUSDT",
    )
    assert abs(qty - 0.5) < 1e-6
    assert meta["binding"] == "margin20_lev5"
