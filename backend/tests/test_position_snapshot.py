"""Position snapshot helpers."""

from unittest.mock import MagicMock

from app.services.position_snapshot import (
    get_supervisor_account_summary,
    get_supervisor_position_status,
    position_fields_from_status,
)


class _PmSupervisor:
    user_id = 1

    def __init__(self, status):
        self.position_manager = MagicMock()
        self.position_manager.get_position_status.return_value = status
        self.client = MagicMock()
        self.client.get_futures_account_summary.return_value = {
            "total_margin_balance": 1200,
            "available_balance": 800,
        }


class _DeepcoinSupervisor:
    user_id = 2
    face_value = 0.1
    symbol = "ETHUSDT"
    leverage = 10

    def __init__(self, pos):
        self._pos = pos
        self.client = MagicMock()
        self.client.get_current_price.return_value = 3500.0

    def _get_active_position(self):
        return self._pos


def test_position_fields_empty():
    pf = position_fields_from_status({"has_position": False})
    assert pf["has_position"] is False
    assert pf["position_qty"] == 0.0


def test_position_fields_from_status():
    pf = position_fields_from_status({
        "has_position": True,
        "side": "LONG",
        "qty": 1.5,
        "entry_price": 3000,
        "mark_price": 3100,
        "unrealized_pnl": 15,
    })
    assert pf["position_side"] == "LONG"
    assert pf["position_qty"] == 1.5
    assert pf["position_entry"] == 3000
    assert pf["position_mark"] == 3100


def test_get_supervisor_position_via_position_manager():
    sup = _PmSupervisor({
        "has_position": True,
        "side": "SHORT",
        "qty": 0.5,
        "entry_price": 3200,
        "unrealized_pnl": -10,
    })
    status = get_supervisor_position_status(sup)
    assert status["has_position"] is True
    assert status["side"] == "SHORT"


def test_get_supervisor_position_deepcoin():
    sup = _DeepcoinSupervisor({
        "size": 2,
        "posSide": "long",
        "entry_price": 3400,
    })
    status = get_supervisor_position_status(sup)
    assert status["has_position"] is True
    assert status["side"] == "LONG"
    assert status["mark_price"] == 3500.0


def test_get_supervisor_position_manager_error():
    sup = _PmSupervisor({})
    sup.position_manager.get_position_status.side_effect = RuntimeError("api down")
    status = get_supervisor_position_status(sup)
    assert status["has_position"] is False
    assert "error" in status


def test_get_supervisor_account_summary():
    sup = _PmSupervisor({})
    summary = get_supervisor_account_summary(sup)
    assert summary["total_margin_balance"] == 1200
