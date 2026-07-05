"""Exchange factory + multi-exchange wiring."""

from unittest.mock import MagicMock, patch

from app.core.exchange_factory import (
    create_supervisor,
    exchange_requires_passphrase,
    normalize_exchange,
    parse_exchange,
    user_exchange,
    user_has_api_credentials,
)
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.models import ExchangeType, User


def test_parse_exchange():
    assert parse_exchange("okx") == ExchangeType.OKX.value
    assert parse_exchange("gateio") == ExchangeType.GATE.value
    assert parse_exchange("unknown") is None


def test_normalize_exchange_defaults_binance():
    assert normalize_exchange(None) == ExchangeType.BINANCE.value
    assert normalize_exchange("unknown") == ExchangeType.BINANCE.value
    assert normalize_exchange("deepcoin") == ExchangeType.DEEPCOIN.value
    assert normalize_exchange("okx") == ExchangeType.OKX.value
    assert normalize_exchange("gate") == ExchangeType.GATE.value
    assert normalize_exchange("gateio") == ExchangeType.GATE.value


def test_exchange_requires_passphrase():
    assert exchange_requires_passphrase("deepcoin") is True
    assert exchange_requires_passphrase("okx") is True
    assert exchange_requires_passphrase("binance") is False
    assert exchange_requires_passphrase("gate") is False


def test_user_has_api_credentials_deepcoin_requires_passphrase():
    user = User(id=1, exchange=ExchangeType.DEEPCOIN.value)
    user.api_key_enc = "k"
    user.api_secret_enc = "s"
    user.passphrase_enc = None
    assert user_has_api_credentials(user) is False
    user.passphrase_enc = "p"
    assert user_has_api_credentials(user) is True


def test_user_has_api_credentials_okx_requires_passphrase():
    user = User(id=2, exchange=ExchangeType.OKX.value)
    user.api_key_enc = "k"
    user.api_secret_enc = "s"
    user.passphrase_enc = None
    assert user_has_api_credentials(user) is False
    user.passphrase_enc = "p"
    assert user_has_api_credentials(user) is True


def test_user_has_api_credentials_gate_key_secret_only():
    user = User(id=3, exchange=ExchangeType.GATE.value)
    user.api_key_enc = "k"
    user.api_secret_enc = "s"
    assert user_has_api_credentials(user) is True


def test_create_supervisor_routes_by_exchange():
    user = User(id=9, exchange=ExchangeType.BINANCE.value)
    binance_client = MagicMock()
    sup = create_supervisor(user, binance_client)
    assert isinstance(sup, PositionSupervisor)
    assert sup.user_id == 9

    user.exchange = ExchangeType.OKX.value
    okx_client = MagicMock()
    okx_client.trading_symbol = "ETH-USDT-SWAP"
    okx_client.trading_leverage = 8
    sup_okx = create_supervisor(user, okx_client)
    assert isinstance(sup_okx, PositionSupervisor)

    user.exchange = ExchangeType.GATE.value
    gate_client = MagicMock()
    gate_client.trading_symbol = "ETH_USDT"
    gate_client.trading_leverage = 8
    sup_gate = create_supervisor(user, gate_client)
    assert isinstance(sup_gate, PositionSupervisor)

    user.exchange = ExchangeType.DEEPCOIN.value
    dc_client = MagicMock()
    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        dc_sup = create_supervisor(user, dc_client)
    assert isinstance(dc_sup, DeepcoinPositionSupervisor)
    assert dc_sup.user_id == 9
    assert dc_sup.client is dc_client


def test_deepcoin_handle_signal_returns_ok():
    client = MagicMock()
    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=3, client=client)
    out = sup.handle_signal({"action": "LONG", "regime": 3})
    assert out["status"] == "ok"
    assert out["action"] == "LONG"


def test_user_exchange_from_model():
    user = User(id=1, exchange=ExchangeType.OKX.value)
    assert user_exchange(user) == "okx"
