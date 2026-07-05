"""Exchange client + supervisor factory (multi-exchange)."""
from __future__ import annotations

import logging
from typing import Callable, Optional, Union

from app.config import get_settings
from app.core.binance_client import BinanceClient
from app.core.deepcoin_client import DeepcoinClient
from app.core.gate_client import GateClient
from app.core.okx_client import OkxClient
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.models import ExchangeType, User

logger = logging.getLogger(__name__)
settings = get_settings()

SupervisorType = Union[PositionSupervisor, DeepcoinPositionSupervisor]

SUPPORTED_EXCHANGES = frozenset({
    ExchangeType.BINANCE.value,
    ExchangeType.DEEPCOIN.value,
    ExchangeType.OKX.value,
    ExchangeType.GATE.value,
})

PASSPHRASE_EXCHANGES = frozenset({
    ExchangeType.DEEPCOIN.value,
    ExchangeType.OKX.value,
})


class ExchangeNotEnabledError(Exception):
    """Raised when admin has not enabled API/trading for this exchange."""

    def __init__(self, exchange: str):
        self.exchange = exchange
        super().__init__(f"Exchange not enabled: {exchange}")


def normalize_exchange(exchange: str | None) -> str:
    val = (exchange or ExchangeType.BINANCE.value).strip().lower()
    if val == "gateio":
        val = ExchangeType.GATE.value
    if val not in SUPPORTED_EXCHANGES:
        return ExchangeType.BINANCE.value
    return val


def parse_exchange(exchange: str | None) -> str | None:
    """Normalize exchange id; return None when unsupported."""
    val = (exchange or ExchangeType.BINANCE.value).strip().lower()
    if val == "gateio":
        val = ExchangeType.GATE.value
    if val not in SUPPORTED_EXCHANGES:
        return None
    return val


def user_exchange(user: User) -> str:
    return normalize_exchange(getattr(user, "exchange", None))


def exchange_requires_passphrase(exchange: str | None) -> bool:
    return normalize_exchange(exchange) in PASSPHRASE_EXCHANGES


def create_exchange_client(
    user: User,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
) -> BinanceClient | DeepcoinClient | OkxClient | GateClient:
    from app.services.platform_public_settings import is_exchange_enabled

    ex = user_exchange(user)
    if not is_exchange_enabled(ex):
        raise ExchangeNotEnabledError(ex)
    if ex == ExchangeType.DEEPCOIN.value:
        return DeepcoinClient(api_key, api_secret, passphrase, user.id)
    if ex == ExchangeType.OKX.value:
        return OkxClient(api_key, api_secret, passphrase, user.id)
    if ex == ExchangeType.GATE.value:
        return GateClient(api_key, api_secret, user.id)
    return BinanceClient(api_key, api_secret, user.id)


def create_supervisor(
    user: User,
    client: BinanceClient | DeepcoinClient | OkxClient | GateClient,
    *,
    on_log: Optional[Callable] = None,
    on_trade_open: Optional[Callable] = None,
    on_trade_close: Optional[Callable] = None,
    on_trade_update_targets: Optional[Callable] = None,
    on_alert: Optional[Callable] = None,
) -> SupervisorType:
    ex = user_exchange(user)
    if ex == ExchangeType.DEEPCOIN.value:
        return DeepcoinPositionSupervisor(
            user_id=user.id,
            client=client,  # type: ignore[arg-type]
            on_log=on_log,
            on_trade_open=on_trade_open,
            on_trade_close=on_trade_close,
            on_trade_update_targets=on_trade_update_targets,
            on_alert=on_alert,
        )
    return PositionSupervisor(
        user_id=user.id,
        client=client,  # type: ignore[arg-type]
        on_log=on_log,
        on_trade_open=on_trade_open,
        on_trade_close=on_trade_close,
        on_trade_update_targets=on_trade_update_targets,
        on_alert=on_alert,
    )


def user_has_api_credentials(user: User) -> bool:
    if not user.api_key_enc or not user.api_secret_enc:
        return False
    if exchange_requires_passphrase(user_exchange(user)):
        return bool(getattr(user, "passphrase_enc", None))
    return True
