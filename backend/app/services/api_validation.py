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
            "message": "币安 API 连接失败 — 请检查 Key/Secret 是否正确，并确认已开启合约交易权限",
            "detail": str(e),
        }

    if not summary.get("can_trade", True):
        return {
            "valid": False,
            "message": "API 无合约交易权限（canTrade=false），请在币安开启 Futures 权限",
            **summary,
        }

    one_way = client.ensure_one_way_mode()
    price = client.get_current_price(settings.SYMBOL)

    leverage_ok = client.set_leverage(settings.SYMBOL, settings.LEVERAGE) is not None

    equity = summary["total_margin_balance"]
    if equity <= 0:
        return {
            "valid": False,
            "message": "合约账户余额为 0，请先向 U 本位合约账户转入 USDT",
            **summary,
            "symbol": settings.SYMBOL,
            "symbol_price": price,
            "one_way_mode": one_way,
            "leverage_ok": leverage_ok,
        }

    return {
        "valid": True,
        "message": "API 验证通过 · 合约账户可正常交易",
        "total_balance": equity,
        "available_balance": summary["available_balance"],
        "wallet_balance": summary["total_wallet_balance"],
        "unrealized_pnl": summary["unrealized_pnl"],
        "can_trade": summary.get("can_trade", True),
        "one_way_mode": one_way,
        "leverage_ok": leverage_ok,
        "symbol": settings.SYMBOL,
        "symbol_price": price,
        "leverage": settings.LEVERAGE,
    }
