"""Startup recover + breakeven helpers for PositionSupervisor."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor, MIN_SL_MOVE


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_current_price.return_value = 3600.0
    client.cancel_all_open_orders.return_value = None
    sup = PositionSupervisor(user_id=42, client=client)
    return sup


def test_breakeven_sl_active_long(supervisor):
    supervisor.current_side = "LONG"
    supervisor.watched_entry = 3500.0
    supervisor.current_sl = 3500.0
    assert not supervisor._breakeven_sl_active()
    supervisor.current_sl = 3505.0
    assert supervisor._breakeven_sl_active()


def test_breakeven_sl_active_short(supervisor):
    supervisor.current_side = "SHORT"
    supervisor.watched_entry = 3500.0
    supervisor.current_sl = 3500.0
    assert not supervisor._breakeven_sl_active()
    supervisor.current_sl = 3495.0
    assert supervisor._breakeven_sl_active()


def test_recover_restores_radar_and_rebuilds_defenses(supervisor, monkeypatch):
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor._save_state()
    supervisor.best_price = 3650.0
    supervisor.current_sl = 3620.0
    supervisor.watched_entry = 3500.0
    supervisor.current_side = "LONG"
    supervisor.last_tv_side = "LONG"
    supervisor.tv_tps = [3600.0, 3700.0, 3800.0]
    supervisor.regime = 2
    supervisor._save_state()

    supervisor.client.get_current_price.return_value = 3660.0
    supervisor.leverage = 10
    supervisor.initial_principal = 7000.0
    supervisor.client.get_available_balance.return_value = 10000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "1.5", "entryPrice": "3500.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure:
        ensure.return_value = {
            "tp_defense": {"skipped": True, "aligned": True, "matched": 3, "expected": 3, "audit": {}},
            "defenses_skipped": True,
            "defenses_rebuilt": False,
            "defenses_aligned": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {},
            "startup_summary": "浮亏/防护轨 | TP3/3",
            "breakeven_active": True,
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            open_trade_id=99,
            recovery_context={
                "trade": {"id": 99, "side": "LONG", "regime": 2, "tv_tps": [3600, 3700, 3800]},
                "open_log": {"side": "LONG", "entry": 3500, "qty": 1.5, "tv_tps": [3600, 3700, 3800]},
                "latest_tv": {"action": "LONG", "tv_tps": [3600, 3700, 3800]},
                "checks": [],
            },
        )

    assert audit["has_position"] is True
    assert audit["defenses_skipped"] is True
    assert audit["breakeven_active"] is True
    assert audit["best_price"] == 3660.0
    assert audit["current_sl"] > supervisor.watched_entry
    ensure.assert_called_once()
    call_kw = ensure.call_args[1]
    assert call_kw.get("reason") == "VPS/部署重启"
    assert "cap_result" in call_kw
    supervisor.client.cancel_all_open_orders.assert_not_called()


def test_recover_falls_back_to_db_trade_context(supervisor):
    supervisor.client.get_current_price.return_value = 3580.0
    supervisor.leverage = 10
    supervisor.initial_principal = 7000.0
    supervisor.client.get_available_balance.return_value = 10000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "-0.8", "entryPrice": "3600.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure:
        ensure.return_value = {
            "tp_defense": {"skipped": True, "aligned": True, "matched": 3, "expected": 3, "audit": {}},
            "defenses_skipped": True,
            "defenses_rebuilt": False,
            "defenses_aligned": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {},
            "startup_summary": "浮亏/防护轨 | TP3/3",
            "breakeven_active": True,
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            open_trade_id=7,
            recovery_context={
                "trade": {"id": 7, "side": "SHORT", "regime": 4, "tv_tps": [3500, 3400, 3300]},
                "latest_tv": {"action": "SHORT", "tv_tps": [3500, 3400, 3300], "regime": 4},
                "checks": [],
            },
        )

    assert audit["tv_tps"] == [3500.0, 3400.0, 3300.0]
    assert supervisor.regime == 4
    assert supervisor.last_tv_side == "SHORT"
    assert audit["defenses_skipped"] is True


def test_min_sl_move_matches_tick():
    assert MIN_SL_MOVE == 0.01


def test_recover_manual_position_when_trade_is_null(supervisor, monkeypatch):
    """Manual exchange open LONG + user TV LONG — adopt with TP123, never force flat."""
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor.last_tv_side = "LONG"
    supervisor.client.get_current_price.return_value = 3650.0
    supervisor.leverage = 15
    supervisor.initial_principal = 700.0
    supervisor.client.get_available_balance.return_value = 1000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "0.42", "entryPrice": "3620.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure:
        ensure.return_value = {
            "tp_defense": {"skipped": False, "aligned": True, "matched": 3, "expected": 3},
            "defenses_skipped": False,
            "defenses_rebuilt": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {"aligned": True},
            "startup_summary": "浮亏/防护轨 | TP3/3 | TV硬止损✓",
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            open_trade_id=None,
            recovery_context={
                "trade": None,
                "open_log": None,
                "latest_tv": {
                    "action": "LONG",
                    "regime": 3,
                    "atr": 30.0,
                    "price": 3620.0,
                    "tv_sl": 3550.0,
                    "tv_tps": [3680.0, 3720.0, 3780.0],
                },
                "checks": [],
            },
        )

    assert audit.get("error") is None
    assert audit["has_position"] is True
    assert audit.get("adopted_manual") is True
    assert supervisor.last_tv_side == "LONG"
    assert audit.get("force_aligned") is not True
    ensure.assert_called_once()


def test_recover_manual_long_not_flat_when_platform_tv_short(supervisor, monkeypatch):
    """User manual LONG while platform-wide latest TV is SHORT — must adopt not flat."""
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor.last_tv_side = "LONG"
    supervisor.tv_tps = [3680.0, 3720.0, 3780.0]
    supervisor.client.get_current_price.return_value = 3650.0
    supervisor.leverage = 15
    supervisor.initial_principal = 700.0
    supervisor.client.get_available_balance.return_value = 1000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "0.42", "entryPrice": "3620.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure, patch.object(
        supervisor, "_close_all",
    ) as close_all:
        ensure.return_value = {
            "tp_defense": {"matched": 3, "expected": 3},
            "defenses_rebuilt": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {"aligned": True},
            "startup_summary": "浮亏/防护轨 | TP3/3",
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            recovery_context={
                "trade": None,
                "open_log": None,
                "state_last_tv_side": "LONG",
                "tv_signal_scope": "platform_fallback",
                "latest_tv": {
                    "action": "SHORT",
                    "tv_sl": 3700.0,
                    "tv_tps": [3500.0, 3400.0, 3300.0],
                },
                "checks": ["tv_signal_platform_fallback"],
            },
        )

    close_all.assert_not_called()
    ensure.assert_called_once()
    assert audit.get("force_aligned") is not True
    assert audit["has_position"] is True
    assert supervisor.last_tv_side == "LONG"
    assert audit.get("adopted_manual") is True
    assert supervisor.tv_tps == [3680.0, 3720.0, 3780.0]
    assert audit.get("direction_aligned") is True


def test_recover_realigns_stale_tv_side_not_flat(supervisor, monkeypatch):
    """Stale last_tv_side=SHORT + live LONG must adopt, never force flat."""
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor.last_tv_side = "SHORT"
    supervisor.client.get_current_price.return_value = 3650.0
    supervisor.leverage = 15
    supervisor.initial_principal = 700.0
    supervisor.client.get_available_balance.return_value = 1000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "0.42", "entryPrice": "3620.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure, patch.object(
        supervisor, "_close_all",
    ) as close_all:
        ensure.return_value = {
            "tp_defense": {"matched": 3, "expected": 3},
            "defenses_rebuilt": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {"aligned": True},
            "startup_summary": "浮亏/防护轨 | TP3/3",
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            recovery_context={
                "trade": None,
                "open_log": None,
                "latest_tv": {
                    "action": "LONG",
                    "tv_sl": 3550.0,
                    "tv_tps": [3680.0, 3720.0, 3780.0],
                },
                "checks": [],
            },
        )

    close_all.assert_not_called()
    assert supervisor.last_tv_side == "LONG"
    assert audit["direction_aligned"] is True


def test_recover_factory_short_not_flat_when_state_matches_live(supervisor, monkeypatch):
    """Factory SHORT + persisted state SHORT must not flatten on stale opposite latest TV."""
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor.last_tv_side = "SHORT"
    supervisor.client.get_current_price.return_value = 3650.0
    supervisor.leverage = 15
    supervisor.initial_principal = 700.0
    supervisor.client.get_available_balance.return_value = 1000.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "-0.42", "entryPrice": "3620.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure, patch.object(
        supervisor, "_close_all",
    ) as close_all:
        ensure.return_value = {
            "tp_defense": {"matched": 3, "expected": 3},
            "defenses_rebuilt": True,
            "tp_matched": 3,
            "tp_expected": 3,
            "shield": {"aligned": True},
            "startup_summary": "浮亏/防护轨 | TP3/3",
            "pnl_track": "loss_shield",
        }
        audit = supervisor.recover_on_startup(
            open_trade_id=88,
            recovery_context={
                "trade": {"id": 88, "side": "SHORT", "quantity": 0.42},
                "open_log": {"side": "SHORT", "entry": 3620, "qty": 0.42},
                "state_last_tv_side": "SHORT",
                "latest_tv": {
                    "action": "LONG",
                    "tv_sl": 3550.0,
                    "tv_tps": [3680.0, 3720.0, 3780.0],
                },
                "checks": [],
            },
        )

    close_all.assert_not_called()
    ensure.assert_called_once()
    assert audit.get("force_aligned") is not True
    assert audit["has_position"] is True
    assert supervisor.last_tv_side == "SHORT"


def test_recover_opposite_manual_position_force_flats(supervisor, monkeypatch):
    """Live SHORT vs TV LONG → FORCE_ALIGN 强平，不对齐实盘."""
    monkeypatch.setattr("app.core.position_supervisor.threading.Thread.start", lambda self: None)
    supervisor.client.get_current_price.return_value = 3650.0
    supervisor.leverage = 15
    supervisor.initial_principal = 700.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "-0.42", "entryPrice": "3620.0"},
    ), patch.object(supervisor, "_unified_startup_defense_reconcile") as ensure, patch.object(
        supervisor, "_close_all",
    ) as close_all:
        audit = supervisor.recover_on_startup(
            recovery_context={
                "trade": None,
                "open_log": None,
                "latest_tv": {
                    "action": "LONG",
                    "tv_sl": 3550.0,
                    "tv_tps": [3680.0, 3720.0, 3780.0],
                },
                "checks": [],
            },
        )

    close_all.assert_called_once()
    ensure.assert_not_called()
    assert audit.get("force_aligned") is True
    assert audit["has_position"] is False
    assert supervisor.last_tv_side == "LONG"
