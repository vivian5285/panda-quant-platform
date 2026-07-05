"""Signal dispatch chain: risk multiplier, pause gating, regime clamp, exchange parity."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.regime_utils import clamp_regime
from app.services.trading_control import _default_state, _parse, get_user_control
from app.services.webhook_guard import is_close_signal


def test_default_state_includes_risk_multiplier():
    state = _default_state()
    assert state["risk_multiplier"] == 1.0
    assert _parse(None)["risk_multiplier"] == 1.0


def test_clamp_regime_bounds():
    assert clamp_regime(1) == 1
    assert clamp_regime(4) == 4
    assert clamp_regime(99) == 3
    assert clamp_regime(None, default=2) == 2
    assert clamp_regime("bad", default=4) == 4


@pytest.mark.parametrize(
    "action,expected",
    [
        ("LONG", False),
        ("SHORT", False),
        ("CLOSE", True),
        ("CLOSE_TP3", True),
        ("CLOSE_PROTECT", True),
        ("CLOSE_PROTECT_LONG", True),
    ],
)
def test_is_close_signal(action, expected):
    assert is_close_signal(action) is expected


def test_deepcoin_open_position_applies_risk_multiplier():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    client = MagicMock()
    client.get_available_balance.return_value = 1000.0
    client.get_current_price.return_value = 3000.0
    client.place_market_order.return_value = {}

    sup = DeepcoinPositionSupervisor(user_id=1, client=client)
    sup.regime = 3
    sup.risk_multiplier = 0.6
    sup._get_active_position = MagicMock(return_value={"size": 1, "entry_price": 3000, "posSide": "long"})

    sup._open_position("LONG", 3000.0)

    base_margin = sup.regime_settings[3]["margin"]
    expected_margin = base_margin * 0.6
    expected_qty = max(int((1000 * expected_margin * sup.leverage) / (3000 * sup.face_value)), 1)
    client.place_market_order.assert_called_once()
    assert client.place_market_order.call_args[0][3] == expected_qty


@patch("app.services.dispatcher.notify_system")
@patch("app.services.dispatcher.SessionLocal")
def test_dispatch_allows_close_when_user_paused(mock_session_local, _notify):
    from app.models import User, ApiStatus
    from app.services.dispatcher import SignalDispatcher

    supervisor = MagicMock()
    supervisor.user_id = 6
    supervisor.handle_signal.return_value = {"status": "ok", "action": "CLOSE"}

    pool = MagicMock()
    pool.get_all.return_value = [supervisor]

    user = MagicMock()
    user.id = 6
    user.is_active = True
    user.api_status = ApiStatus.ACTIVE.value
    user.exchange = "binance"

    db = MagicMock()
    mock_session_local.return_value = db
    db.query.return_value.filter.return_value.first.return_value = user

    payload = {"action": "CLOSE", "reason": "test"}

    with patch("app.services.trading_control.is_globally_paused", return_value=False), \
         patch("app.services.dispatcher.is_exchange_enabled", return_value=True), \
         patch("app.services.dispatcher.user_exchange", return_value="binance"), \
         patch("app.services.trading_control.is_user_paused", return_value=True), \
         patch.object(SignalDispatcher, "_execute_for_user", return_value={"status": "ok"}) as mock_exec:
        result = SignalDispatcher(pool).dispatch(payload)

    assert mock_exec.called
    assert result["dispatched"] == 1
    blocked = [r for r in result["results"] if r.get("status") == "risk_blocked"]
    assert not blocked


@patch("app.services.dispatcher.notify_system")
@patch("app.services.dispatcher.SessionLocal")
def test_dispatch_blocks_entry_when_user_paused(mock_session_local, _notify):
    from app.models import User, ApiStatus
    from app.services.dispatcher import SignalDispatcher

    supervisor = MagicMock()
    supervisor.user_id = 6

    pool = MagicMock()
    pool.get_all.return_value = [supervisor]

    user = MagicMock()
    user.id = 6
    user.is_active = True
    user.api_status = ApiStatus.ACTIVE.value
    user.exchange = "binance"

    db = MagicMock()
    mock_session_local.return_value = db
    db.query.return_value.filter.return_value.first.return_value = user

    payload = {"action": "LONG", "regime": 1, "atr": 10, "price": 3000,
               "tv_tp1": 3100, "tv_tp2": 3200, "tv_tp3": 3300}

    with patch("app.services.trading_control.is_globally_paused", return_value=False), \
         patch("app.services.dispatcher.is_exchange_enabled", return_value=True), \
         patch("app.services.dispatcher.user_exchange", return_value="binance"), \
         patch("app.services.trading_control.is_user_paused", return_value=True), \
         patch("app.services.trading_control.get_user_control", return_value={"trading_paused": True}):
        result = SignalDispatcher(pool).dispatch(payload)

    assert result["dispatched"] == 0
    assert result["results"][0]["status"] == "risk_blocked"


@patch("app.services.dispatcher.SessionLocal")
def test_execute_for_user_without_trading_state(mock_session_local):
    from app.services.dispatcher import SignalDispatcher

    supervisor = MagicMock()
    supervisor.user_id = 6
    supervisor.handle_signal.return_value = {"status": "ok"}

    db = MagicMock()
    mock_session_local.return_value = db

    pool = MagicMock()
    dispatcher = SignalDispatcher(pool)

    with patch("app.services.trading_control.get_user_control", return_value=_default_state()), \
         patch("app.services.platform_runtime.get_global_risk_multiplier", return_value=1.0), \
         patch("app.services.trading_control.is_user_paused", return_value=False):
        outcome = dispatcher._execute_for_user(supervisor, {"action": "LONG"})

    assert outcome["status"] == "ok"
    sent = supervisor.handle_signal.call_args[0][0]
    assert sent["risk_multiplier"] == 1.0


def test_position_supervisor_load_state_clamps_regime(tmp_path, monkeypatch):
    from app.core.position_supervisor import PositionSupervisor

    state_dir = tmp_path / "supervisor" / "u1"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "state.json"
    state_file.write_text('{"regime": 99, "monitoring": false}', encoding="utf-8")

    client = MagicMock()
    sup = PositionSupervisor(user_id=1, client=client)
    monkeypatch.setattr(sup, "state_file", str(state_file))
    sup._load_state()
    assert sup.regime == 3
