"""Regression tests for P0/P1 production fixes."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_global_pause_string_comparison():
    """Redis decode_responses=True returns str '1', not bytes."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = "1"
    with patch("app.services.platform_runtime.get_redis", return_value=mock_redis):
        from app.services.platform_runtime import is_global_trading_paused

        assert is_global_trading_paused() is True
    mock_redis.get.return_value = "0"
    with patch("app.services.platform_runtime.get_redis", return_value=mock_redis):
        from app.services.platform_runtime import is_global_trading_paused

        assert is_global_trading_paused() is False


def test_global_pause_file_fallback_when_redis_down(tmp_path, monkeypatch):
    runtime_file = tmp_path / "platform_runtime.json"
    runtime_file.write_text(json.dumps({"global_trading_paused": True}), encoding="utf-8")

    import app.services.platform_runtime as pr

    monkeypatch.setattr(pr, "RUNTIME_FILE", runtime_file)
    monkeypatch.setattr(pr, "get_redis", lambda: None)

    assert pr.is_global_trading_paused() is True


def test_position_status_includes_qty_and_mark_price():
    from app.core.position_manager import PositionManager

    client = MagicMock()
    client.user_id = 1
    client.get_position.return_value = {
        "positionAmt": "1.5",
        "entryPrice": "3000",
        "markPrice": "3010",
        "unRealizedProfit": "15",
        "leverage": "15",
    }
    status = PositionManager(client).get_position_status()
    assert status["qty"] == 1.5
    assert status["mark_price"] == 3010.0
    assert status["has_position"] is True


def test_risk_multiplier_applied_to_margin():
    from app.core.position_supervisor import PositionSupervisor

    sup = PositionSupervisor(user_id=999, client=MagicMock(), initial_principal=700.0)
    sup.regime = 3
    sup.risk_multiplier = 0.6
    base_margin = sup.regime_settings[3]["margin"]
    effective = base_margin * sup.risk_multiplier
    assert round(effective, 4) == round(0.35 * 0.6, 4)


def test_binance_principal_cap_regime4_margin():
    from app.core.position_sizing import compute_eth_qty
    from app.core.symbol_precision import round_quantity

    _, meta = compute_eth_qty(
        live_balance=1000.0,
        initial_principal=700.0,
        margin_pct=0.50,
        leverage=10,
        price=1770.0,
        round_fn=round_quantity,
    )
    assert meta["margin_usd"] == 350.0
    assert meta["sizing_source"] == "principal_cap"
