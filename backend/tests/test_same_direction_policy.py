"""Tests for same-direction entry intelligence (ATR-first)."""

from unittest.mock import MagicMock

import pytest

from app.core.same_direction_policy import (
    SameDirAction,
    atr_values_differ,
    evaluate_same_direction,
    format_reopen_reason,
    price_diff_pct,
)


def test_price_diff_pct_basic():
    assert round(price_diff_pct(3505, 3500, 3500), 3) == round(5 / 3500 * 100, 3)


def test_atr_values_differ():
    assert atr_values_differ(12.5, 12.5) is False
    assert atr_values_differ(12.5, 12.5004) is False
    assert atr_values_differ(12.5, 13.0) is True


def test_evaluate_reopen_when_atr_changed_even_if_small_price_diff():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=15.0,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.reason == "atr_changed"
    assert "ATR变化" in format_reopen_reason(ev, 0.20)


def test_evaluate_always_reopen_when_atr_same_and_small_price_diff():
    """Whitepaper §三: no REFRESH_TPS skip — same dir always close-reopen."""
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=12.5,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.reason == "same_dir_always_reopen"


def test_evaluate_reopen_when_regime_changed_atr_same():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=2,
        new_regime=4,
        held_atr=12.5,
        new_atr=12.5,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.reason == "regime_changed"


def test_evaluate_reopen_when_atr_same_and_price_diff_large():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="SHORT",
        signal_side="SHORT",
        entry_price=3500.0,
        tv_price=3420.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=12.5,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.reason == "same_dir_always_reopen"


def test_evaluate_open_new_when_flat():
    ev = evaluate_same_direction(
        has_position=False,
        current_side=None,
        signal_side="LONG",
        entry_price=0,
        tv_price=3500,
        mark_price=3500,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=12.5,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.OPEN_NEW


@pytest.fixture
def supervisor():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_current_price.return_value = 3500.0
    client.get_open_orders.return_value = []
    client.cancel_all_open_orders.return_value = None
    sup = PositionSupervisor(user_id=1, client=client)
    sup.position_manager.get_position = MagicMock(
        return_value={"positionAmt": "1.0", "entryPrice": "3500.0"}
    )
    sup._get_active_position = MagicMock(
        return_value={"size": 1.0, "entry_price": 3500.0, "side": "LONG"}
    )
    sup._rebuild_defenses = MagicMock(return_value={"aligned": True})
    sup._radar_sl_to_pass = MagicMock(return_value=None)
    sup._save_state = MagicMock()
    sup._log = MagicMock()
    sup._alert = MagicMock()
    sup.on_trade_update_targets = MagicMock()
    sup.current_trade_id = 42
    sup.regime = 3
    sup.tv_price = 3505.0
    sup.tv_tps = [3600.0, 3700.0, 3800.0]
    sup.current_atr = 12.5
    sup.watched_entry = 3500.0
    sup.monitoring = True
    return sup


def test_supervisor_same_dir_always_reopens(supervisor):
    """Whitepaper: same-dir with unchanged ATR still force-flats then opens."""
    supervisor._close_all = MagicMock()
    supervisor._open_position = MagicMock(return_value={"status": "ok"})
    supervisor._wait_until_flat = MagicMock(return_value=True)
    supervisor._force_flat_before_open = MagicMock(return_value=True)
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=12.5,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    supervisor._close_then_open_entry("LONG", 3500.0, ev)
    supervisor._force_flat_before_open.assert_called()


def test_supervisor_reopen_when_atr_changed(supervisor):
    supervisor._close_all = MagicMock()
    supervisor._open_position = MagicMock(return_value={"status": "ok"})
    supervisor._wait_until_flat = MagicMock(return_value=True)
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        held_atr=12.5,
        new_atr=18.0,
        threshold_pct=0.20,
    )
    supervisor._close_then_open_entry("LONG", 3500.0, ev)
    supervisor._close_all.assert_called_once()
    assert "ATR变化" in supervisor._alert.call_args[0][3]


def test_supervisor_opposite_still_closes(supervisor):
    supervisor.position_manager.get_position.return_value = {
        "positionAmt": "-1.0",
        "entryPrice": "3500.0",
    }
    supervisor._close_all = MagicMock()
    supervisor._open_position = MagicMock(return_value={"status": "ok"})
    supervisor._wait_until_flat = MagicMock(return_value=True)

    supervisor._handle_smart_entry("LONG", held_regime=3, held_atr=12.5, prev_tv_tps=[])

    supervisor._close_all.assert_called_once()
    supervisor._open_position.assert_called_once()
