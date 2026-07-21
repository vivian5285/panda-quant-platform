"""WS mark-price listeners + radar poll cadence (all exchanges)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
import threading

from app.core.ws_price_listeners import (
    notify_price_listeners,
    register_price_listener,
    unregister_price_listener,
)
from app.core.position_supervisor import (
    PositionSupervisor,
    RADAR_WS_TICK_MIN_SEC,
    SENTINEL_POLL_ARMING,
    SENTINEL_POLL_NORMAL,
    SENTINEL_POLL_RADAR,
)


def test_ws_price_listener_fanout():
    client = SimpleNamespace()
    seen = []

    def cb(symbol, price):
        seen.append((symbol, price))

    register_price_listener(client, cb)
    notify_price_listeners(client, "ETHUSDT", 2500.5)
    notify_price_listeners(client, "ETHUSDT", 0)  # ignored
    assert seen == [("ETHUSDT", 2500.5)]
    unregister_price_listener(client, cb)
    notify_price_listeners(client, "ETHUSDT", 2501.0)
    assert seen == [("ETHUSDT", 2500.5)]


def test_radar_ws_tick_min_sec_is_subsecond():
    assert RADAR_WS_TICK_MIN_SEC < 1.0
    # All exchanges aligned: arming/radar sentinel = 0.5s (拍板)
    assert SENTINEL_POLL_ARMING == 0.5
    assert SENTINEL_POLL_RADAR == 0.5
    assert SENTINEL_POLL_NORMAL <= 5.0


def test_deepcoin_sentinel_aligned_to_half_sec():
    from app.core import position_supervisor_deepcoin as dc

    assert dc.SENTINEL_POLL_ARMING == 0.5
    assert dc.SENTINEL_POLL_RADAR == 0.5
    assert dc.SENTINEL_POLL_NORMAL == 5.0


def _stub_supervisor():
    client = MagicMock()
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT")
    client.start_public_price_ws = MagicMock()
    client.register_price_listener = MagicMock()
    client.unregister_price_listener = MagicMock()
    sup = object.__new__(PositionSupervisor)
    sup.user_id = 1
    sup.client = client
    sup.symbol = "ETHUSDT"
    sup.exchange_id = "binance"
    sup.monitoring = True
    sup._radar_ws_bound = False
    sup._radar_ws_tick_ts = 0.0
    sup._lock = threading.Lock()
    sup.watched_entry = 1800.0
    sup.tv_tps = [1830.0, 1850.0, 1870.0]
    sup.current_side = "LONG"
    sup.regime = 3
    sup.regime_settings = {3: {"activation": 0.75}}
    sup.consumed_tp_levels = []
    sup.radar_latched = False
    sup.current_sl = 0.0
    # AdverseRadarMixin fields used by _is_radar_engaged / poll
    sup._adverse_radar_inited = True
    return sup


def test_ensure_price_ws_binds_listener_once():
    sup = _stub_supervisor()
    PositionSupervisor._ensure_price_ws(sup)
    PositionSupervisor._ensure_price_ws(sup)
    assert sup._radar_ws_bound is True
    assert sup.client.register_price_listener.call_count == 1
    PositionSupervisor._unbind_price_ws_listener(sup)
    assert sup._radar_ws_bound is False
    assert sup.client.unregister_price_listener.call_count == 1


def test_sentinel_poll_fast_near_activation():
    from app.core.adverse_radar_guard import AdverseRadarMixin

    # Bind mixin methods onto stub (PositionSupervisor already subclasses mixin in prod)
    sup = _stub_supervisor()
    # Far from TP1 (~10% of path) → normal
    far = 1800.0 + (1830.0 - 1800.0) * 0.10
    assert PositionSupervisor._sentinel_poll_sec(sup, far) == SENTINEL_POLL_NORMAL
    # Near activation threshold → arming
    near = 1800.0 + (1830.0 - 1800.0) * 0.50
    assert PositionSupervisor._sentinel_poll_sec(sup, near) == SENTINEL_POLL_ARMING
    # Latched → radar cadence
    sup.radar_latched = True
    assert AdverseRadarMixin._is_radar_engaged(sup) is True
    assert PositionSupervisor._sentinel_poll_sec(sup, near) == SENTINEL_POLL_RADAR
