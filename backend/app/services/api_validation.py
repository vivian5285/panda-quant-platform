import logging

from app.config import get_settings
from app.core.binance_client import BinanceClient

logger = logging.getLogger(__name__)
settings = get_settings()

# 绑定必须全部通过的检测项（顺序即前端展示顺序）
REQUIRED_CHECK_IDS = (
    "connect",
    "withdraw_off",
    "futures_on",
    "can_trade",
    "balance",
    "one_way",
    "leverage",
)


def _check_item(check_id: str, ok: bool, *, hint_key: str | None = None) -> dict:
    item = {"id": check_id, "ok": bool(ok)}
    if hint_key and not ok:
        item["hint_key"] = hint_key
    return item


def _build_failure(
    checks: list[dict],
    message_key: str,
    *,
    detail: str | None = None,
    **fields,
) -> dict:
    passed = sum(1 for c in checks if c.get("ok"))
    return {
        "valid": False,
        "message_key": message_key,
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        "detail": detail,
        **fields,
    }


def validate_binance_api(api_key: str, api_secret: str, user_id: int = 0) -> dict:
    """Full API pre-bind check with per-requirement checklist."""
    client = BinanceClient(api_key, api_secret, user_id or 0)
    checks: list[dict] = []

    try:
        summary = client.get_futures_account_summary()
        connected = True
    except Exception as e:
        logger.warning("API validation failed user=%s: %s", user_id, e)
        checks.append(_check_item("connect", False, hint_key="api.hint.connect"))
        return _build_failure(checks, "api.connect_failed", detail=str(e))

    checks.append(_check_item("connect", True))

    can_trade = bool(summary.get("can_trade", True))
    equity = float(summary.get("total_margin_balance") or 0)
    restrictions = client.get_api_key_restrictions()
    withdraw_disabled = (
        not bool(restrictions.get("enableWithdrawals"))
        if restrictions
        else None
    )
    enable_futures = restrictions.get("enableFutures") if restrictions else None
    futures_on = enable_futures is not False and can_trade

    checks.append(
        _check_item(
            "withdraw_off",
            withdraw_disabled is True,
            hint_key="api.hint.withdraw_off",
        )
    )
    checks.append(
        _check_item(
            "futures_on",
            futures_on,
            hint_key="api.hint.futures_on",
        )
    )
    checks.append(
        _check_item(
            "can_trade",
            can_trade,
            hint_key="api.hint.can_trade",
        )
    )
    checks.append(
        _check_item(
            "balance",
            equity > 0,
            hint_key="api.hint.balance",
        )
    )

    activity = client.futures_activity_summary()
    hedge = client.is_hedge_mode()
    one_way = client.ensure_one_way_mode()
    one_way_hint = None
    if not one_way:
        if activity["open_orders"] > 0 or activity["open_positions"] > 0:
            one_way_hint = "api.hint.one_way_need_flat"
        elif hedge is True:
            one_way_hint = "api.hint.one_way_manual"
        else:
            one_way_hint = "api.hint.one_way_failed"
    checks.append(_check_item("one_way", one_way, hint_key=one_way_hint))

    price = client.get_current_price(settings.SYMBOL)
    leverage_ok = client.set_leverage(settings.SYMBOL, settings.LEVERAGE) is not None
    checks.append(
        _check_item(
            "leverage",
            leverage_ok,
            hint_key="api.hint.leverage",
        )
    )

    base_fields = {
        "total_balance": equity,
        "available_balance": float(summary.get("available_balance") or 0),
        "wallet_balance": float(summary.get("total_wallet_balance") or 0),
        "unrealized_pnl": float(summary.get("unrealized_pnl") or 0),
        "can_trade": can_trade,
        "one_way_mode": one_way,
        "leverage_ok": leverage_ok,
        "withdraw_disabled": withdraw_disabled,
        "enable_futures": enable_futures,
        "symbol": settings.SYMBOL,
        "symbol_price": price,
        "leverage": settings.LEVERAGE,
        "open_orders_count": activity["open_orders"],
        "open_positions_count": activity["open_positions"],
        "hedge_mode": hedge,
    }

    required_ok = all(c["ok"] for c in checks if c["id"] in REQUIRED_CHECK_IDS)
    passed = sum(1 for c in checks if c.get("ok"))

    if not required_ok:
        failed = [c["id"] for c in checks if c["id"] in REQUIRED_CHECK_IDS and not c.get("ok")]
        message_key = "api.verify_incomplete"
        if "connect" in failed:
            message_key = "api.connect_failed"
        elif not can_trade or enable_futures is False:
            message_key = "api.no_futures_api_flag" if enable_futures is False else "api.no_futures_permission"
        elif withdraw_disabled is not True:
            message_key = "api.withdraw_enabled"
        elif equity <= 0:
            message_key = "api.zero_balance"
        elif not one_way:
            message_key = "api.one_way_failed"
        elif not leverage_ok:
            message_key = "api.leverage_failed"
        return _build_failure(
            checks,
            message_key,
            checks_passed=passed,
            checks_total=len(checks),
            **base_fields,
        )

    return {
        "valid": True,
        "message_key": "api.verify_ok",
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        **base_fields,
    }


DEEPCOIN_REQUIRED_CHECK_IDS = ("connect", "balance", "leverage", "can_trade")


def validate_deepcoin_api(
    api_key: str,
    api_secret: str,
    passphrase: str,
    user_id: int = 0,
) -> dict:
    from app.core.deepcoin_client import DeepcoinClient

    client = DeepcoinClient(api_key, api_secret, passphrase, user_id or 0)
    checks: list[dict] = []

    if not passphrase.strip():
        checks.append(_check_item("connect", False, hint_key="api.hint.passphrase"))
        return _build_failure(checks, "api.passphrase_required")

    try:
        if not client.test_connection():
            raise RuntimeError("connection failed")
        summary = client.get_futures_account_summary()
        connected = True
    except Exception as e:
        logger.warning("Deepcoin API validation failed user=%s: %s", user_id, e)
        checks.append(_check_item("connect", False, hint_key="api.hint.connect"))
        return _build_failure(checks, "api.connect_failed", detail=str(e))

    checks.append(_check_item("connect", True))
    equity = float(summary.get("total_margin_balance") or 0)
    checks.append(_check_item("balance", equity > 0, hint_key="api.hint.balance"))
    checks.append(_check_item("can_trade", True))

    lev_res = client.set_leverage(settings.DEEPCOIN_SYMBOL, settings.DEEPCOIN_LEVERAGE)
    leverage_ok = bool(lev_res and client._is_success(lev_res))
    checks.append(_check_item("leverage", leverage_ok, hint_key="api.hint.leverage"))

    price = client.get_current_price(settings.DEEPCOIN_SYMBOL)
    base_fields = {
        "total_balance": equity,
        "available_balance": equity,
        "wallet_balance": equity,
        "unrealized_pnl": 0.0,
        "can_trade": True,
        "one_way_mode": True,
        "leverage_ok": leverage_ok,
        "withdraw_disabled": None,
        "enable_futures": True,
        "symbol": settings.DEEPCOIN_SYMBOL,
        "symbol_price": price,
        "leverage": settings.DEEPCOIN_LEVERAGE,
        "exchange": "deepcoin",
        "open_orders_count": 0,
        "open_positions_count": 0,
        "hedge_mode": False,
    }

    required_ok = all(c["ok"] for c in checks if c["id"] in DEEPCOIN_REQUIRED_CHECK_IDS)
    passed = sum(1 for c in checks if c.get("ok"))
    if not required_ok:
        message_key = "api.verify_incomplete"
        if equity <= 0:
            message_key = "api.zero_balance"
        elif not leverage_ok:
            message_key = "api.leverage_failed"
        return _build_failure(
            checks,
            message_key,
            checks_passed=passed,
            checks_total=len(checks),
            **base_fields,
        )

    return {
        "valid": True,
        "message_key": "api.verify_ok",
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        **base_fields,
    }


ALT_EXCHANGE_REQUIRED_CHECK_IDS = ("connect", "balance", "leverage", "can_trade")


def _validate_alt_exchange_api(
    *,
    exchange: str,
    client,
    symbol: str,
    leverage: int,
    require_passphrase: bool,
    passphrase: str = "",
) -> dict:
    checks: list[dict] = []
    if require_passphrase and not passphrase.strip():
        checks.append(_check_item("connect", False, hint_key="api.hint.passphrase"))
        return _build_failure(checks, "api.passphrase_required")

    try:
        if not client.test_connection():
            raise RuntimeError("connection failed")
        summary = client.get_futures_account_summary()
    except Exception as e:
        logger.warning("%s API validation failed: %s", exchange, e)
        checks.append(_check_item("connect", False, hint_key="api.hint.connect"))
        return _build_failure(checks, "api.connect_failed", detail=str(e))

    checks.append(_check_item("connect", True))
    equity = float(summary.get("total_margin_balance") or 0)
    checks.append(_check_item("balance", equity > 0, hint_key="api.hint.balance"))
    checks.append(_check_item("can_trade", bool(summary.get("can_trade", True)), hint_key="api.hint.can_trade"))

    one_way = client.ensure_one_way_mode()
    hedge = client.is_hedge_mode()
    checks.append(_check_item("one_way", one_way, hint_key="api.hint.one_way_failed"))

    lev_res = client.set_leverage(symbol, leverage)
    leverage_ok = lev_res is not None
    checks.append(_check_item("leverage", leverage_ok, hint_key="api.hint.leverage"))

    price = client.get_current_price(symbol)
    activity = client.futures_activity_summary()
    base_fields = {
        "total_balance": equity,
        "available_balance": float(summary.get("available_balance") or 0),
        "wallet_balance": float(summary.get("total_wallet_balance") or equity),
        "unrealized_pnl": float(summary.get("unrealized_pnl") or 0),
        "can_trade": bool(summary.get("can_trade", True)),
        "one_way_mode": one_way,
        "leverage_ok": leverage_ok,
        "withdraw_disabled": None,
        "enable_futures": True,
        "symbol": symbol,
        "symbol_price": price,
        "leverage": leverage,
        "exchange": exchange,
        "open_orders_count": activity.get("open_orders", 0),
        "open_positions_count": activity.get("open_positions", 0),
        "hedge_mode": hedge,
    }

    required_ok = all(c["ok"] for c in checks if c["id"] in ALT_EXCHANGE_REQUIRED_CHECK_IDS)
    passed = sum(1 for c in checks if c.get("ok"))
    if not required_ok:
        message_key = "api.verify_incomplete"
        if equity <= 0:
            message_key = "api.zero_balance"
        elif not leverage_ok:
            message_key = "api.leverage_failed"
        return _build_failure(
            checks,
            message_key,
            checks_passed=passed,
            checks_total=len(checks),
            **base_fields,
        )

    return {
        "valid": True,
        "message_key": "api.verify_ok",
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        **base_fields,
    }


def validate_okx_api(
    api_key: str,
    api_secret: str,
    passphrase: str,
    user_id: int = 0,
) -> dict:
    from app.core.okx_client import OkxClient

    client = OkxClient(api_key, api_secret, passphrase, user_id or 0)
    return _validate_alt_exchange_api(
        exchange="okx",
        client=client,
        symbol=settings.OKX_SYMBOL,
        leverage=settings.OKX_LEVERAGE,
        require_passphrase=True,
        passphrase=passphrase,
    )


def validate_gate_api(api_key: str, api_secret: str, user_id: int = 0) -> dict:
    from app.core.gate_client import GateClient

    client = GateClient(api_key, api_secret, user_id or 0)
    return _validate_alt_exchange_api(
        exchange="gate",
        client=client,
        symbol=settings.GATE_SYMBOL,
        leverage=settings.GATE_LEVERAGE,
        require_passphrase=False,
    )


def validate_exchange_api(
    exchange: str,
    api_key: str,
    api_secret: str,
    user_id: int = 0,
    passphrase: str = "",
) -> dict:
    ex = (exchange or "binance").strip().lower()
    if ex == "gateio":
        ex = "gate"
    if ex == "deepcoin":
        return validate_deepcoin_api(api_key, api_secret, passphrase, user_id)
    if ex == "okx":
        return validate_okx_api(api_key, api_secret, passphrase, user_id)
    if ex == "gate":
        return validate_gate_api(api_key, api_secret, user_id)
    return validate_binance_api(api_key, api_secret, user_id)
