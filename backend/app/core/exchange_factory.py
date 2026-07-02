"""Exchange client + supervisor factory (Gemini multi-exchange P0)."""
from __future__ import annotations

import logging
from typing import Callable, Optional, Union

from app.config import get_settings
from app.core.binance_client import BinanceClient
from app.core.deepcoin_client import DeepcoinClient
from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.models import ExchangeType, User

logger = logging.getLogger(__name__)
settings = get_settings()

SupervisorType = Union[PositionSupervisor, DeepcoinPositionSupervisor]


def normalize_exchange(exchange: str | None) -> str:
    val = (exchange or ExchangeType.BINANCE.value).strip().lower()
    if val not in (ExchangeType.BINANCE.value, ExchangeType.DEEPCOIN.value):
        return ExchangeType.BINANCE.value
    return val


def user_exchange(user: User) -> str:
    return normalize_exchange(getattr(user, "exchange", None))


def create_exchange_client(
    user: User,
    api_key: str,
    api_secret: str,
    passphrase: str = "",
) -> BinanceClient | DeepcoinClient:
    ex = user_exchange(user)
    if ex == ExchangeType.DEEPCOIN.value:
        return DeepcoinClient(api_key, api_secret, passphrase, user.id)
    return BinanceClient(api_key, api_secret, user.id)


def create_supervisor(
    user: User,
    client: BinanceClient | DeepcoinClient,
    *,
    on_log: Optional[Callable] = None,
    on_trade_open: Optional[Callable] = None,
    on_trade_close: Optional[Callable] = None,
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
            on_alert=on_alert,
        )
    return PositionSupervisor(
        user_id=user.id,
        client=client,  # type: ignore[arg-type]
        on_log=on_log,
        on_trade_open=on_trade_open,
        on_trade_close=on_trade_close,
        on_alert=on_alert,
    )


def user_has_api_credentials(user: User) -> bool:
    if not user.api_key_enc or not user.api_secret_enc:
        return False
    if user_exchange(user) == ExchangeType.DEEPCOIN.value:
        return bool(getattr(user, "passphrase_enc", None))
    return True
