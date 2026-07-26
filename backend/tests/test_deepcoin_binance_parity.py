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
    # Pine placeable: TP1=10% → remaining 90% (legacy 30% slice used 0.7).
    assert float(h.remaining_qty_pct) == pytest.approx(0.9)


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


def test_deepcoin_tp_slices_refuse_full_book_when_tp3_excluded():
    """Parity with Binance §7: placeable must not eat ~70% radar residual."""
    from app.core.tp_regime_targets import pine_tp_ratios_frac

    host = MagicMock()
    host.regime = 3
    host.tv_tps = [1895.66, 1904.63, 1913.2]
    host.initial_qty = 100
    host.regime_settings = {3: {"margin": 0.0, "ratios": list(pine_tp_ratios_frac())}}
    host._safe_qty = lambda x, d=0: int(float(x or d))

    with patch(
        "app.core.open_atr_scenario.supervisor_placeable_levels",
        return_value=frozenset({1, 2}),
    ):
        slices = DeepcoinPositionSupervisor._compute_tp_slices(host, 100, exclude_levels={3})
    used = sum(q for _, q, _ in slices)
    assert used > 0
    assert used <= 35  # ~30% + rounding
    assert all(lv in (1, 2) for lv, _, _ in slices)


def test_deepcoin_sentinel_skips_rest_on_pause_or_cool():
    src = inspect.getsource(DeepcoinPositionSupervisor._sentinel_loop)
    assert "_position_query_ban_remaining_sec" in src
    assert "trading_paused" in src
    assert "no REST" in src or "Cool-down" in src


def test_deepcoin_ensure_radar_qty_aware():
    src = inspect.getsource(DeepcoinPositionSupervisor._ensure_radar_sl)
    assert "_radar_stop_live_qty" in src
    assert "qty_mismatch" in src


def test_okx_gate_rate_limit_triggers_cool():
    from app.core.exchange_errors import is_rate_limit_error, parse_binance_error

    assert is_rate_limit_error("code=50011 msg=Too Many Requests")
    assert is_rate_limit_error("gate Too many requests")
    assert is_rate_limit_error("deepcoin frequent request")
    meta = parse_binance_error("code=50013 Rate limit")
    assert meta.get("code") in (-1003, 50013, "50013") or is_rate_limit_error(
        "code=50013", code=meta.get("code"),
    )