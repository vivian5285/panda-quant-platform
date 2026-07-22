"""Unit tests: daily loss circuit + atr webhook hard reject helpers."""

from app.core.daily_loss_circuit import (
    DAILY_LOSS_LIMIT_PCT,
    check_allows_open,
    record_close_pnl,
    reset_for_tests,
)
from app.core.tv_entry_sizing import compute_tv_entry_qty


def setup_function():
    reset_for_tests()


def test_daily_loss_allows_when_flat_day():
    ok, meta = check_allows_open(user_id=6, symbol="ETHUSDT", equity=100.0)
    assert ok
    assert meta["loss_pct"] == 0.0


def test_daily_loss_trips_at_5_5_pct():
    record_close_pnl(user_id=6, symbol="ETHUSDT", pnl_usd=-5.5, equity=100.0)
    ok, meta = check_allows_open(user_id=6, symbol="ETHUSDT", equity=100.0)
    assert not ok
    assert meta["error"] == "daily_loss_circuit"
    assert meta["loss_pct"] + 1e-9 >= DAILY_LOSS_LIMIT_PCT


def test_daily_loss_isolated_per_symbol():
    record_close_pnl(user_id=6, symbol="ETHUSDT", pnl_usd=-6.0, equity=100.0)
    ok_eth, _ = check_allows_open(user_id=6, symbol="ETHUSDT", equity=100.0)
    ok_xau, _ = check_allows_open(user_id=6, symbol="XAUUSDT", equity=100.0)
    assert not ok_eth
    assert ok_xau


def test_min_notional_pre_reject_eth():
    # tiny equity → notional below Binance ETH min 20
    q, m = compute_tv_entry_qty(
        live_balance=1.0,
        initial_principal=1.0,
        price=2000.0,
        tv_sl=1970.0,
        tv_stop_loss=1980.0,
        tv_qty=0.001,
        symbol="ETHUSDT",
    )
    assert q == 0.0
    assert m.get("error") in ("below_min_notional", "below_min_qty", "zero_equity")
