"""Regression: limit place must invalidate REST book cache (TP thrash root)."""

from unittest.mock import MagicMock, patch


def test_binance_place_limit_invalidates_book_cache():
    from app.core.binance_client import BinanceClient

    c = object.__new__(BinanceClient)
    c.user_id = 6
    c.trading_symbol = "ETHUSDT"
    c.canonical_symbol = "ETHUSDT"
    c.client = MagicMock()
    c.client.futures_create_order.return_value = {"orderId": 1, "status": "NEW"}
    c._pace_rest = MagicMock()
    c._invalidate_book_cache = MagicMock()
    out = BinanceClient.place_limit_order(
        c, "SELL", 0.01, 1895.66, symbol="ETHUSDT", reduce_only=True,
    )
    assert out and out.get("orderId") == 1
    c._invalidate_book_cache.assert_called_with("limit_place")


def test_arm_temp_does_not_overwrite_pine_tv_sl_with_hang():
    from app.core.adverse_radar_guard import AdverseRadarMixin
    from app.core.breathing_stop import compute_temp_tv_stop

    class H(AdverseRadarMixin):
        pass

    h = H()
    h.user_id = 6
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = "LONG"
    h.tv_price = 1885.13
    h._tv_stop_loss_ref = 1874.9918165171
    h._pending_open_tv_sl = 1874.9918165171
    h.tv_sl = 1874.9918165171
    h._init_adverse_radar_fields()
    fill = 1886.3
    out = h._arm_temp_tv_stop_on_open(fill)
    assert out.get("ok") is True
    hard = float(out["stop_price"])
    expect = compute_temp_tv_stop(
        fill, "LONG", 1874.9918165171, tv_entry=1885.13, symbol="ETHUSDT",
    )
    assert abs(hard - expect) < 1e-6
    assert abs(float(h._tv_stop_loss_ref) - 1874.9918165171) < 1e-6
    assert abs(float(h.tv_sl) - 1874.9918165171) < 1e-6
    assert abs(float(h._frozen_hard_stop_px) - hard) < 1e-6
    assert hard < 1874.9918165171


def test_arm_heals_polluted_tv_sl_hang_back_to_pine():
    """If tv_sl was previously set to hang price, arm must restore pine ref."""
    from app.core.adverse_radar_guard import AdverseRadarMixin

    class H(AdverseRadarMixin):
        pass

    h = H()
    h.user_id = 6
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = "LONG"
    h.tv_price = 1885.13
    pine = 1874.9918165171
    hang_pollution = 1874.34
    h._tv_stop_loss_ref = pine
    h._pending_open_tv_sl = pine
    h.tv_sl = hang_pollution  # polluted audit field
    h._init_adverse_radar_fields()
    out = h._arm_temp_tv_stop_on_open(1886.3)
    assert out.get("ok") is True
    assert abs(float(h.tv_sl) - pine) < 1e-6
    assert abs(float(h._tv_stop_loss_ref) - pine) < 1e-6
    assert float(h._frozen_hard_stop_px) < pine
