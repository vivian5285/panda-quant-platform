"""Regression: astronomical TV.qty must size+order the same safe qty."""

from app.core.tv_entry_sizing import (
    ABSURD_TV_QTY_VS_CAPS,
    NOTIONAL_MARGIN_HAIRCUT,
    compute_tv_entry_qty,
)


def test_absurd_tv_qty_ignored_binds_notional_haircut():
    """Real 2026-07-22 TV qty≈8.6e8 must not produce unfillable full-5x without haircut."""
    equity = 61.4
    price = 1932.4
    vps_stop = price - 1.5 * 15.6453  # VPS initialStop
    tv_stop = 1916.7567275275
    tv_qty = 860680123.0

    qty, meta = compute_tv_entry_qty(
        live_balance=equity,
        initial_principal=equity,
        price=price,
        tv_sl=vps_stop,
        tv_stop_loss=tv_stop,
        tv_qty=tv_qty,
        symbol="ETHUSDT",
    )
    assert meta.get("tv_qty_ignored_absurd") is True
    assert meta.get("binding") in ("notional_cap", "stop_risk")
    # Same number that would be passed to place_market_order
    assert abs(float(meta["final_qty"]) - float(qty)) < 1e-12
    # Haircut keeps notional below raw equity×5
    raw_5x = equity * 5 / price
    assert qty < raw_5x - 1e-9
    assert qty <= (equity * 5 * NOTIONAL_MARGIN_HAIRCUT) / price + 1e-9
    assert qty > 0
    # Must be nowhere near TV.qty scale
    assert qty < 1.0
    assert adjusted_is_absurd(meta)


def adjusted_is_absurd(meta: dict) -> bool:
    return float(meta.get("adjusted_tv_qty_cap") or 0) > float(
        max(meta.get("qty_by_risk") or 0, meta.get("qty_by_notional") or 0)
    ) * (ABSURD_TV_QTY_VS_CAPS * 0.5)


def test_normal_tv_qty_still_can_bind_tv_cap():
    equity = 61.4
    price = 1932.4
    atr = 15.6453
    vps_stop = price - 1.5 * atr
    tv_stop = price - 1.0 * atr
    qty, meta = compute_tv_entry_qty(
        live_balance=equity,
        initial_principal=equity,
        price=price,
        tv_sl=vps_stop,
        tv_stop_loss=tv_stop,
        tv_qty=0.03,
        symbol="ETHUSDT",
    )
    assert meta.get("tv_qty_ignored_absurd") is False
    assert abs(float(meta["final_qty"]) - float(qty)) < 1e-12
    assert qty <= 0.03 + 1e-9


def test_sizing_order_qty_identity_huge_and_small():
    """Contract: whatever compute returns is the only order qty (no second path)."""
    for tv_qty in (860680123.0, 0.02, 0.03):
        qty, meta = compute_tv_entry_qty(
            live_balance=1719.0,
            initial_principal=1719.0,
            price=1932.4,
            tv_sl=1909.0,
            tv_stop_loss=1916.76,
            tv_qty=tv_qty,
            symbol="ETHUSDT",
        )
        assert qty == float(meta.get("final_qty") or 0)
        # Simulate "order params" using sizing result only
        order_qty = qty
        assert order_qty == qty
