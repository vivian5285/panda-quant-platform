"""Backward-compatible Binance fill sync — delegates to multi-exchange sync. """
from app.services.exchange_fill_sync import (  # noqa: F401
    sync_user_binance_fills,
    sync_user_exchange_fills,
)
