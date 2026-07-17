"""Manual TV-aligned positions: adopt TP123 + SL, never flatten unless opposite."""

from unittest.mock import MagicMock

import pytest

from app.core.startup_reconcile import (
    StartupReconcileMixin,
    finalize_recovery_tv_params,
    live_matches_entry_direction,
    live_matches_tv_direction,
    prepare_manual_adopt,
    should_skip_startup_tv_close_flatten,
    should_skip_tv_close_for_manual,
)


def test_live_matches_tv_direction_uses_entry_tv():
    assert live_matches_tv_direction(
        {"latest_entry_tv_action": "LONG", "latest_tv_action": "CLOSE"},
        "LONG",
    )


def test_live_matches_entry_direction_ignores_stale_latest_tv():
    assert live_matches_entry_direction(
        {"state_last_tv_side": "SHORT", "latest_tv_action": "LONG"},
        "SHORT",
    )
    assert not live_matches_entry_direction(
        {"latest_tv_action": "LONG"},
        "SHORT",
    )


def test_should_skip_startup_tv_close_flatten_same_direction():
    class Sup:
        current_side = "SHORT"
        last_tv_side = "SHORT"
        adopted_manual = False
        current_trade_id = 99
        watched_qty = 0.4

    # Bare CLOSE + live matches entry → skip flatten on restart
    skip, reason = should_skip_startup_tv_close_flatten(
        Sup(),
        {"state_last_tv_side": "SHORT", "latest_tv_action": "CLOSE"},
    )
    assert skip is True
    assert reason == "live_matches_entry_direction"


def test_finalize_recovery_derives_missing_tp3():
    class Sup:
        tv_tps = [2050.0, 2100.0, 0.0]
        tv_sl = 0.0
        last_tv_side = "LONG"
        current_side = "LONG"
        watched_entry = 2000.0
        tv_price = 2000.0
        current_atr = 30.0
        regime = 3

        def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
            from app.core.vps_hard_sl import compute_vps_hard_sl
            meta = compute_vps_hard_sl(
                float(entry_px or self.watched_entry),
                side or self.current_side or self.last_tv_side,
                self.current_atr,
                self.regime,
                tv_sl_reference=float((payload or {}).get("tv_sl") or 0) or None,
            )
            self.tv_sl = float(meta.get("stop_price") or 0)
            return meta

    sup = Sup()
    report: dict = {"open_log_entry": 2000.0, "open_log_side": "LONG"}
    recovery = {
        "latest_tv": {"action": "CLOSE", "tv_tps": [2050.0, 2100.0, 0.0]},
        "latest_entry_tv": {
            "action": "LONG",
            "tv_tps": [2050.0, 2100.0, 0.0],
            "atr": 30.0,
            "regime": 3,
            "price": 2000.0,
            "tv_sl": 1900.0,
        },
    }
    finalize_recovery_tv_params(sup, report, recovery)
    assert sup.tv_tps[2] > 0
    assert sup.tv_sl == pytest.approx(2000.0 * (1 - 0.0556), rel=0.01)
    assert report.get("tv_sl_reference") == pytest.approx(1900.0)
    assert "tv_tps_derived_from_regime" in report.get("warnings", [])


def test_prepare_manual_adopt_resets_consumed():
    class Sup:
        watched_qty = 0.42
        watched_entry = 1806.01
        initial_qty = 1.0
        base_qty = 0.0
        consumed_tp_levels = [1]
        current_sl = 1808.0
        best_price = 1810.0

    sup = Sup()
    prepare_manual_adopt(sup)
    assert sup.initial_qty == 0.42
    assert sup.consumed_tp_levels == []
    assert sup.adopted_manual is True
    assert sup.current_sl == 0.0
    assert sup.best_price == 1806.01


def test_ensure_radar_sl_blocked_before_tp1_on_manual_adopt():
    from app.core.binance_smart_defense import BinanceSmartDefenseMixin

    class Probe(BinanceSmartDefenseMixin):
        user_id = 1
        symbol = "ETHUSDT"
        current_side = "LONG"
        watched_entry = 1806.01
        adopted_manual = True
        consumed_tp_levels = []
        regime = 3
        tv_tps = [1850.0, 1900.0, 1950.0]
        current_atr = 20.0
        regime_settings = {3: {"activation": 0.90, "trail_offset": 1.35, "ratios": [0.18, 0.32, 0.5]}}
        client = MagicMock()

        def _current_tp_price(self):
            return 1805.85

        def _def_log(self, msg, level=0):
            pass

        def _radar_activation_reached(self, curr_px):
            from app.core.radar_trail import radar_may_arm
            progress = self._radar_activation_progress(curr_px)

            return radar_may_arm(
                consumed_tp_levels=self.consumed_tp_levels,
                progress=progress,
                activation_ratio=0.90,
                radar_active=False,
            )

        def _radar_activation_progress(self, curr_px):
            entry = self.watched_entry
            tp1_dist = abs(self.tv_tps[0] - entry)
            required = entry + tp1_dist * 0.90
            span = required - entry
            return max(0.0, min(1.0, (curr_px - entry) / span))

    probe = Probe()
    assert probe._ensure_radar_sl(1808.5, 0.043) is False


class _WatchHost(StartupReconcileMixin):
    def __init__(self):
        self.user_id = 1
        self.monitoring = False
        self.watched_qty = 0.0
        self.current_side = None
        self.watched_entry = 0.0
        self.last_tv_side = "LONG"
        self._close_all = MagicMock()
        self._log = MagicMock()
        self._alert = MagicMock()


def test_should_skip_tv_close_for_manual_position():
    class Sup:
        adopted_manual = True
        current_trade_id = None
        current_side = "LONG"
        watched_qty = 0.5
        last_tv_side = "LONG"
        symbol = "ETHUSDT"
        position_manager = None

    skip, reason = should_skip_tv_close_for_manual(Sup(), "CLOSE")
    assert skip is True
    assert "manual" in reason


def test_hard_close_never_skipped_for_manual_adopt():
    """CLOSE_PROTECT / STOPLOSS / TP3 always flatten — even adopted_manual (ETH/XAU)."""
    from app.core.startup_reconcile import is_hard_tv_close_action

    class Sup:
        adopted_manual = True
        current_trade_id = None
        current_side = "SHORT"
        watched_qty = 0.42
        last_tv_side = "SHORT"
        symbol = "ETHUSDT"
        position_manager = None

    assert is_hard_tv_close_action("CLOSE_PROTECT")
    assert is_hard_tv_close_action("CLOSE_STOPLOSS")
    assert is_hard_tv_close_action("CLOSE_TP3")
    assert not is_hard_tv_close_action("CLOSE")

    for action in ("CLOSE_PROTECT", "CLOSE_STOPLOSS", "CLOSE_TP3"):
        skip, _ = should_skip_tv_close_for_manual(Sup(), action)
        assert skip is False, action


def test_tv_screenshot_close_protect_not_skipped():
    """Exact TV payload from 2026-07-16 23:00 ETHUSDT.P protect alert."""
    class Sup:
        adopted_manual = True
        current_trade_id = None
        current_side = "SHORT"
        watched_qty = 1.2
        last_tv_side = "SHORT"
        symbol = "ETHUSDT"
        position_manager = None

    payload_action = "CLOSE_PROTECT"
    skip, _ = should_skip_tv_close_for_manual(Sup(), payload_action)
    assert skip is False


def test_should_not_skip_tv_close_for_factory_trade():
    class Sup:
        adopted_manual = False
        current_trade_id = 42
        current_side = "LONG"
        watched_qty = 0.5
        last_tv_side = "LONG"

    skip, _ = should_skip_tv_close_for_manual(Sup(), "CLOSE")
    assert skip is False


def test_startup_hard_close_not_skipped():
    class Sup:
        current_side = "SHORT"
        last_tv_side = "SHORT"
        adopted_manual = True
        current_trade_id = None
        watched_qty = 0.4

    skip, _ = should_skip_startup_tv_close_flatten(
        Sup(),
        {
            "state_last_tv_side": "SHORT",
            "latest_tv_action": "CLOSE_PROTECT",
            "latest_entry_tv_action": "SHORT",
        },
    )
    assert skip is False


def test_execute_signal_skips_close_for_manual_adopt():
    from unittest.mock import MagicMock, patch

    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
    client.get_current_price.return_value = 1775.0
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    sup.adopted_manual = True
    sup.current_trade_id = None
    sup.current_side = "LONG"
    sup.watched_qty = 0.42
    sup.watched_entry = 1760.0
    sup.last_tv_side = "LONG"
    sup.monitoring = True
    sup.on_log = MagicMock()
    sup.on_alert = MagicMock()
    sup.position_manager = MagicMock()
    sup.position_manager.get_position.return_value = {
        "positionAmt": 0.42,
        "entryPrice": 1760.0,
    }

    with patch.object(sup, "_preserve_manual_on_tv_close") as preserve:
        preserve.return_value = {"status": "skipped", "reason": "manual_same_direction_skip_tv_close"}
        result = sup._execute_signal({
            "action": "CLOSE",
            "reason": "策略指标反转",
            "side": "LONG",
            "regime": 3,
            "atr": 21.2,
            "price": 1775.36,
        })
    preserve.assert_called_once()
    assert result["status"] == "skipped"
    sup.client.place_market_order.assert_not_called()


def test_execute_signal_close_protect_flattens_manual_adopt():
    """Regression: TV CLOSE_PROTECT must not be swallowed by adopted_manual."""
    from unittest.mock import MagicMock, patch

    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
    client.get_current_price.return_value = 1882.85
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 25

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    sup.adopted_manual = True
    sup.current_trade_id = None
    sup.current_side = "SHORT"
    sup.watched_qty = 1.2
    sup.watched_entry = 1900.0
    sup.last_tv_side = "SHORT"
    sup.monitoring = True
    sup.on_log = MagicMock()
    sup.on_alert = MagicMock()
    sup.position_manager = MagicMock()
    sup.position_manager.get_position.return_value = {
        "positionAmt": -1.2,
        "entryPrice": 1900.0,
    }

    with patch.object(sup, "_close_all") as close_all, patch.object(
        sup, "_preserve_manual_on_tv_close"
    ) as preserve:
        result = sup._execute_signal({
            "symbol": "ETHUSDT.P",
            "action": "CLOSE_PROTECT",
            "secret": "528586",
            "regime": 4,
            "price": 1882.85,
            "atr": 13.1372332303,
            "side": "SHORT",
            "reason": "常规防守：大级别转多或动能衰竭",
            "pnl_pct": 0.26,
        })
    preserve.assert_not_called()
    close_all.assert_called_once()
    assert result["status"] == "ok"
    assert result["action"] == "CLOSE_PROTECT"


def test_idle_watch_does_not_flatten_manual_on_tv_close():
    host = _WatchHost()
    host._get_active_position = MagicMock(
        return_value={"size": 0.42, "side": "LONG", "entry_price": 3600.0},
    )
    host._is_dust_qty = MagicMock(return_value=False)
    host._should_finalize_tp_victory = MagicMock(return_value=False)
    host._reconcile_radar_context = MagicMock(
        return_value={"latest_tv_action": "CLOSE", "latest_entry_tv_action": "LONG"},
    )
    host._load_idle_recovery_context = MagicMock(
        return_value={
            "latest_tv": {"action": "CLOSE"},
            "latest_entry_tv": {"action": "LONG", "tv_tps": [3700, 3800, 3900], "tv_sl": 3500},
            "trade": None,
            "open_log": None,
        },
    )
    host.recover_on_startup = MagicMock(
        return_value={"has_position": True, "monitoring": True, "startup_summary": "TP3/3"},
    )

    host._run_idle_live_watch()

    host._close_all.assert_not_called()
    host.recover_on_startup.assert_called_once()
