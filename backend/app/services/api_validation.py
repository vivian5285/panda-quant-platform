import logging

from app.config import get_settings
from app.core.binance_client import BinanceClient

logger = logging.getLogger(__name__)
settings = get_settings()


def validate_binance_api(api_key: str, api_secret: str, user_id: int = 0) -> dict:
    """Full API pre-bind check: connectivity, balance, trade permission, one-way mode."""
    client = BinanceClient(api_key, api_secret, user_id or 0)
    try:
        summary = client.get_futures_account_summary()
    except Exception as e:
        logger.warning("API validation failed user=%s: %s", user_id, e)
        return {
            "valid": False,
            "message_key": "api.connect_failed",
            "detail": str(e),
        }

    if not summary.get("can_trade", True):
        return {
            "valid": False,
            "message_key": "api.no_futures_permission",
            **summary,
        }

    restrictions = client.get_api_key_restrictions()
    if restrictions:
        if restrictions.get("enableWithdrawals"):
            return {
                "valid": False,
                "message_key": "api.withdraw_enabled",
                **summary,
                "withdraw_disabled": False,
                "enable_futures": restrictions.get("enableFutures"),
            }
        if restrictions.get("enableFutures") is False:
            return {
                "valid": False,
                "message_key": "api.no_futures_api_flag",
                **summary,
                "withdraw_disabled": True,
                "enable_futures": False,
            }
    withdraw_disabled = not bool(restrictions.get("enableWithdrawals")) if restrictions else None
    enable_futures = restrictions.get("enableFutures") if restrictions else None

    one_way = client.ensure_one_way_mode()
    price = client.get_current_price(settings.SYMBOL)

    leverage_ok = client.set_leverage(settings.SYMBOL, settings.LEVERAGE) is not None

    equity = summary["total_margin_balance"]
    if equity <= 0:
        return {
            "valid": False,
            "message_key": "api.zero_balance",
            **summary,
            "symbol": settings.SYMBOL,
            "symbol_price": price,
            "one_way_mode": one_way,
            "leverage_ok": leverage_ok,
        }

    return {
        "valid": True,
        "message_key": "api.verify_ok",
        "total_balance": equity,
        "available_balance": summary["available_balance"],
        "wallet_balance": summary["total_wallet_balance"],
        "unrealized_pnl": summary["unrealized_pnl"],
        "can_trade": summary.get("can_trade", True),
        "one_way_mode": one_way,
        "leverage_ok": leverage_ok,
        "withdraw_disabled": withdraw_disabled if withdraw_disabled is not None else True,
        "enable_futures": enable_futures if enable_futures is not None else True,
        "symbol": settings.SYMBOL,
        "symbol_price": price,
        "leverage": settings.LEVERAGE,
    }
