"""DeepCoin vs Binance — targeted sync checks for verified fixes."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.position_cap_guard import PositionCapGuardMixin
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor


def test_deepcoin_inherits_shared_mixins():
    assert issubclass(DeepcoinPositionSupervisor, AdverseRadarMixin)
    assert issubclass(DeepcoinPositionSupervisor, PositionCapGuardMixin)
    assert issubclass(PositionSupervisor, AdverseRadarMixin)


def test_deepcoin_bump_sl_after_tp_calls_boost_like_binance():
    """C gap closed: TV reconcile path must resize stop via _boost_radar_after_tp_fill."""
    src = inspect.getsource(DeepcoinPositionSupervisor._bump_sl_after_tp_reconcile)
    assert "_boost_radar_after_tp_fill" in src
    assert "stop_resized" in src
    # Soft-stub that only updated remaining_qty_pct is gone
    assert "Soft-stub" not in src

    client = MagicMock(exchange_id="deepcoin")
    # Minimal host: call method unbound with a light object
    class Host(AdverseRadarMixin):
        pass

    h = Host()
    h.user_id = 1
    h.client = client
    h.exchange_id = "deepcoin"
    h.watched_qty = 70.0
    h.consumed_tp_levels = []
    h.remaining_qty_pct = 1.0
    h.tv_price = 2000.0
    h._save_state = MagicMock()
    called = {}

    def _boost(change, px, qty):
        called["change"] = change
        called["qty"] = qty

    h._boost_radar_after_tp_fill = _boost
    # Bind DeepCoin implementation onto host
    result = DeepcoinPositionSupervisor._bump_sl_after_tp_reconcile(h, "1")
    assert called["change"] == "tp1_filled"
    assert called["qty"] == pytest.approx(70.0)
    assert result.get("stop_resized") is True
    assert float(h.remaining_qty_pct) == pytest.approx(0.7)


def test_deepcoin_close_all_and_manual_flat_use_clear_position_local_state():
    close_src = inspect.getsource(DeepcoinPositionSupervisor._close_all)
    manual_src = inspect.getsource(DeepcoinPositionSupervisor._handle_manual_flat_detected)
    assert "_clear_position_local_state" in close_src
    assert "_clear_position_local_state" in manual_src


def test_deepcoin_startup_clean_flat_uses_full_clear():
    src = inspect.getsource(DeepcoinPositionSupervisor.recover_state_on_startup)
    assert "_clear_position_local_state" in src


def test_cap_align_detect_only_shared():
    from app.core import position_cap_guard as pcg

    src = inspect.getsource(pcg.PositionCapGuardMixin._enforce_regime_cap_alignment)
    assert "detect_only_no_trim" in src
    assert "Detect-only" in src or "detect-only" in src
