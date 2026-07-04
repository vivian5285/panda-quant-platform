"""Tests for exchange enablement gating in dispatcher."""

from unittest.mock import MagicMock, patch

from app.core.exchange_factory import ExchangeNotEnabledError
from app.services.platform_public_settings import is_exchange_enabled, user_exchange_trading_allowed


@patch("app.services.platform_public_settings.get_platform_public_settings")
def test_is_exchange_enabled_respects_admin(mock_cfg):
    mock_cfg.return_value = {"enabled_exchanges": ["binance"]}
    assert is_exchange_enabled("binance") is True
    assert is_exchange_enabled("okx") is False


@patch("app.services.platform_public_settings.is_exchange_enabled", return_value=False)
def test_user_exchange_trading_allowed(_mock):
    user = MagicMock()
    user.exchange = "okx"
    assert user_exchange_trading_allowed(user) is False


def test_exchange_not_enabled_error():
    err = ExchangeNotEnabledError("okx")
    assert err.exchange == "okx"
