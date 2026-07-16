import json
import logging
import threading
import time

from binance.client import Client

from app.config import get_settings
from app.core.symbol_precision import format_price, format_quantity

logger = logging.getLogger(__name__)
settings = get_settings()
WS_MARKET_BASE = "wss://fstream.binance.com/market/ws"
CLIENT_VERSION = "v13.4.6-flat-reconcile"


def _error_indicates_sub_account_only(err: str) -> bool:
    """True only when the exchange explicitly says this key is a sub-account key."""
    e = err.lower()
    explicit = (
        "only available to master accounts",
        "only master account",
        "master account only",
        "this endpoint only support master",
        "sub-account api key",
        "sub account api key",
    )
    return any(m in e for m in explicit)


class BinanceClient:
    exchange_id = "binance"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        user_id: int,
        trading_symbol: str | None = None,
    ):
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_symbol = trading_symbol or settings.SYMBOL
        self.trading_leverage = settings.LEVERAGE
        self.canonical_symbol = trading_symbol or settings.SYMBOL
        self.client = Client(api_key, api_secret)
        self._one_way_checked = False
        self._price_cache: dict[str, float] = {}
        self._price_cache_ts: dict[str, float] = {}
        self._price_lock = threading.Lock()
        self._pub_ws_running = False
        self._pub_ws_symbol: str | None = None
        self._rest_price_min_interval = 30.0
        self._last_rest_price_fetch = 0.0
        logger.info(
            f"[User {user_id}] Binance Client {CLIENT_VERSION} loaded ({self.trading_symbol})"
        )

    def _sym(self, symbol: str | None = None) -> str:
        """Resolve order/query symbol — never silently fall back to ETHUSDT."""
        return (symbol or self.trading_symbol or settings.SYMBOL).strip()

    def _can_sym(self) -> str | None:
        return getattr(self, "canonical_symbol", None) or self.trading_symbol
    def is_hedge_mode(self) -> bool | None:
        """True=双向持仓, False=单向, None=查询失败。"""
        try:
            result = self.client.futures_get_position_mode()
            return bool(result.get("dualSidePosition"))
        except Exception as e:
            logger.warning(f"[User {self.user_id}] get position mode failed: {e}")
            return None

    def futures_activity_summary(self) -> dict:
        """统计阻碍切换单向持仓的挂单/持仓（全合约账户）。"""
        out = {"open_orders": 0, "open_positions": 0}
        try:
            orders = self.client.futures_get_open_orders()
            out["open_orders"] = len(orders or [])
        except Exception as e:
            logger.warning(f"[User {self.user_id}] list open orders failed: {e}")
        try:
            for pos in self.client.futures_position_information() or []:
                if abs(float(pos.get("positionAmt", 0) or 0)) > 0:
                    out["open_positions"] += 1
        except Exception as e:
            logger.warning(f"[User {self.user_id}] list positions failed: {e}")
        return out

    def ensure_one_way_mode(self) -> bool:
        """强制单向持仓模式，禁止双向对冲（永远一手）。"""
        if self._one_way_checked:
            return True
        try:
            self.client.futures_change_position_mode(dualSidePosition=False)
            logger.info(f"[User {self.user_id}] position mode → ONE-WAY")
            self._one_way_checked = True
            return True
        except Exception as e:
            err = str(e)
            if "-4059" in err or "No need to change" in err:
                self._one_way_checked = True
                return True
            logger.warning(f"[User {self.user_id}] one-way mode check: {e}")
            return False

    def set_leverage(self, symbol=None, leverage=None):
        symbol = symbol or self.trading_symbol
        leverage = int(leverage or self.trading_leverage)
        try:
            return self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.error(f"[User {self.user_id}] set_leverage failed: {e}")
            return None

    def _set_ws_price(self, symbol: str, price: float) -> None:
        with self._price_lock:
            self._price_cache[symbol] = price
            self._price_cache_ts[symbol] = time.time()

    def _get_ws_price(self, symbol: str, max_age: float = 30.0) -> float | None:
        with self._price_lock:
            px = self._price_cache.get(symbol)
            ts = self._price_cache_ts.get(symbol, 0.0)
        if px and (time.time() - ts) <= max_age:
            return px
        return None

    def start_public_price_ws(self, symbol: str | None = None) -> None:
        """Subscribe markPrice@1s — radar uses WS push, REST only as fallback."""
        symbol = self._sym(symbol)
        if self._pub_ws_running and self._pub_ws_symbol == symbol:
            return
        self._pub_ws_symbol = symbol
        if not self._pub_ws_running:
            self._pub_ws_running = True
            threading.Thread(
                target=self._public_price_ws_loop,
                args=(symbol,),
                daemon=True,
                name=f"binance-ws-u{self.user_id}",
            ).start()
            logger.info(f"[User {self.user_id}] public WS started: {symbol}@markPrice@1s")

    def _public_price_ws_loop(self, symbol: str) -> None:
        try:
            import websocket
        except ImportError:
            logger.warning("[User %s] websocket-client missing; radar falls back to REST", self.user_id)
            self._pub_ws_running = False
            return

        stream = f"{symbol.lower()}@markPrice@1s"
        url = f"{WS_MARKET_BASE}/{stream}"

        def on_message(ws, message):
            try:
                data = json.loads(message)
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
                px = float(data.get("p") or data.get("markPrice") or 0)
                if px > 0:
                    self._set_ws_price(symbol, px)
            except Exception as exc:
                logger.debug("[User %s] WS parse: %s", self.user_id, exc)

        def on_error(ws, error):
            logger.warning("[User %s] public WS error: %s", self.user_id, error)

        def on_close(ws, code, msg):
            logger.warning("[User %s] public WS closed: %s %s", self.user_id, code, msg)

        while self._pub_ws_running:
            try:
                ws_app = websocket.WebSocketApp(
                    url, on_message=on_message, on_error=on_error, on_close=on_close,
                )
                ws_app.run_forever(ping_interval=180, ping_timeout=30)
            except Exception as exc:
                logger.error("[User %s] public WS loop: %s", self.user_id, exc)
            if self._pub_ws_running:
                time.sleep(3)

    def get_current_price(self, symbol=None, prefer_ws=True):
        """Prefer WS cache; rate-limit REST when WS is active."""
        symbol = self._sym(symbol)
        if prefer_ws:
            ws_px = self._get_ws_price(symbol)
            if ws_px:
                return ws_px
        now = time.time()
        min_gap = self._rest_price_min_interval if self._pub_ws_running else 2.0
        cached = self._get_ws_price(symbol, max_age=min_gap)
        if cached:
            return cached
        if now - self._last_rest_price_fetch < min_gap:
            stale = self._get_ws_price(symbol, max_age=120.0)
            return stale or 0.0
        try:
            self._last_rest_price_fetch = now
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            price = float(ticker["price"])
            if price > 0:
                self._set_ws_price(symbol, price)
            return price
        except Exception as e:
            logger.error(f"[User {self.user_id}] get price failed: {e}")
            stale = self._get_ws_price(symbol, max_age=120.0)
            return stale or 0.0

    def get_available_balance(self, asset="USDT"):
        try:
            account = self.client.futures_account()
            for a in account.get("assets", []):
                if a.get("asset") == asset:
                    margin_bal = float(a.get("marginBalance", 0.0))
                    if margin_bal > 0:
                        return margin_bal
                    return float(a.get("availableBalance", 0.0))
            return 0.0
        except Exception as e:
            logger.error(f"[User {self.user_id}] get balance failed: {e}")
            return 0.0

    def get_futures_account_summary(self) -> dict:
        """U 本位合约账户概览（用于绑定校验与初始本金）。"""
        account = self.client.futures_account()
        usdt_available = 0.0
        usdt_margin = 0.0
        for a in account.get("assets", []):
            if a.get("asset") == "USDT":
                usdt_margin = float(a.get("marginBalance", 0.0))
                usdt_available = float(a.get("availableBalance", 0.0))
                break
        total_wallet = float(account.get("totalWalletBalance", 0.0))
        total_margin = float(account.get("totalMarginBalance", total_wallet))
        return {
            "total_wallet_balance": round(total_wallet, 2),
            "total_margin_balance": round(total_margin, 2),
            "available_balance": round(usdt_available or usdt_margin, 2),
            "unrealized_pnl": round(float(account.get("totalUnrealizedProfit", 0.0)), 2),
            "can_trade": bool(account.get("canTrade", True)),
        }

    def get_position(self, symbol=None):
        symbol = self._sym(symbol)
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            return positions[0] if positions else None
        except Exception as e:
            logger.error(f"[User {self.user_id}] get position failed: {e}")
            return None

    def estimate_atr(self, symbol=None, period: int = 14) -> float:
        """Wilder ATR from recent 1h klines — fallback when TV webhook omits atr."""
        symbol = self._sym(symbol)
        try:
            klines = self.client.futures_klines(
                symbol=symbol, interval="1h", limit=period + 2,
            )
            if not klines or len(klines) < period + 1:
                return 0.0
            trs: list[float] = []
            for i in range(1, len(klines)):
                high = float(klines[i][2])
                low = float(klines[i][3])
                prev_close = float(klines[i - 1][4])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            if len(trs) < period:
                return 0.0
            atr = sum(trs[:period]) / period
            for tr in trs[period:]:
                atr = (atr * (period - 1) + tr) / period
            return round(float(atr), 4)
        except Exception as e:
            logger.warning(f"[User {self.user_id}] estimate_atr failed: {e}")
            return 0.0

    def _normalize_algo_order(self, row: dict) -> dict:
        """Map Binance algo conditional order into futures_get_open_orders shape."""
        trigger = row.get("triggerPrice") or row.get("stopPrice")
        qty = row.get("quantity") or row.get("origQty") or row.get("qty")
        otype = str(row.get("orderType") or row.get("type") or "").upper()
        if otype == "CONDITIONAL":
            otype = str(row.get("orderType") or "STOP_MARKET").upper()
        close_pos = row.get("closePosition")
        if isinstance(close_pos, bool):
            close_pos = "true" if close_pos else "false"
        elif close_pos is not None:
            close_pos = str(close_pos).strip().lower()
            if close_pos in ("true", "1"):
                close_pos = "true"
            elif close_pos in ("false", "0", ""):
                close_pos = "false"
        return {
            "orderId": row.get("algoId") or row.get("orderId"),
            "algoId": row.get("algoId"),
            "clientOrderId": row.get("clientAlgoId") or row.get("clientOrderId"),
            "type": otype,
            "orderType": row.get("orderType") or otype,
            "stopPrice": trigger,
            "triggerPrice": trigger,
            "price": row.get("price"),
            "side": row.get("side"),
            "origQty": qty,
            "quantity": qty,
            "closePosition": close_pos,
            "reduceOnly": row.get("reduceOnly"),
            "isAlgoOrder": True,
            "algoStatus": row.get("algoStatus") or row.get("status"),
        }

    def _parse_algo_order_rows(self, raw) -> list[dict]:
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        if isinstance(raw, dict):
            if raw.get("algoId"):
                return [raw]
            for key in ("orders", "data", "algoOrders", "rows"):
                rows = raw.get(key)
                if isinstance(rows, list):
                    return [r for r in rows if isinstance(r, dict)]
        return []

    def get_algo_order(self, symbol: str, algo_id: int) -> dict | None:
        """Direct lookup — openAlgoOrders can lag after place."""
        try:
            raw = self.client._request_futures_api(
                "get", "algoOrder", signed=True,
                data={"symbol": symbol, "algoId": int(algo_id)},
            )
            if not isinstance(raw, dict) or not raw.get("algoId"):
                return None
            status = str(raw.get("algoStatus") or raw.get("status") or "").upper()
            if status in ("CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "FILLED"):
                return None
            return self._normalize_algo_order(raw)
        except Exception as e:
            logger.debug(f"[User {self.user_id}] get algo order {algo_id} failed: {e}")
            return None

    def get_open_algo_orders(self, symbol=None) -> list[dict]:
        """Conditional STOP/TP orders live on the algo book after 2025-12 migration."""
        symbol = self._sym(symbol)
        try:
            raw = self.client._request_futures_api(
                "get", "openAlgoOrders", signed=True, data={"symbol": symbol},
            )
            rows = self._parse_algo_order_rows(raw)
            out = []
            for row in rows or []:
                status = str(row.get("algoStatus") or row.get("status") or "").upper()
                if status in ("CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "FILLED"):
                    continue
                out.append(self._normalize_algo_order(row))
            return out
        except Exception as e:
            logger.warning(f"[User {self.user_id}] get algo orders failed: {e}")
            return []

    def get_open_orders(self, symbol=None):
        symbol = self._sym(symbol)
        try:
            regular = self.client.futures_get_open_orders(symbol=symbol) or []
        except Exception as e:
            logger.error(f"[User {self.user_id}] get orders failed: {e}")
            regular = []
        try:
            algo = self.get_open_algo_orders(symbol=symbol)
        except Exception:
            algo = []
        return list(regular) + list(algo)

    def _place_algo_stop_market(self, params: dict) -> dict | None:
        try:
            res = self.client._request_futures_api(
                "post", "algoOrder", signed=True, data=params,
            )
            if isinstance(res, dict):
                logger.info(
                    f"[User {self.user_id}] algo stop {params.get('side')} "
                    f"trigger={params.get('triggerPrice')} "
                    f"close={params.get('closePosition', 'false')}"
                )
                return self._normalize_algo_order(res)
            return None
        except Exception as e:
            logger.error(f"[User {self.user_id}] algo stop order failed: {e} params={params}")
            return None

    def place_market_order(self, side, quantity, symbol=None, reduce_only=False):
        symbol = self._sym(symbol)
        can = self._can_sym()
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            qty_str = format_quantity(quantity, can)
            if float(qty_str) <= 0:
                logger.error(f"[User {self.user_id}] market order qty invalid: {quantity}")
                return None
            params = {
                "symbol": symbol,
                "side": binance_side,
                "type": "MARKET",
                "quantity": qty_str,
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            order = self.client.futures_create_order(**params)
            logger.info(
                f"[User {self.user_id}] market {side} {qty_str} {symbol} reduce={reduce_only}"
            )
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] market order failed: {e}")
            return None

    def place_limit_order(self, side, quantity, price, symbol=None, reduce_only=True):
        symbol = self._sym(symbol)
        can = self._can_sym()
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            qty_str = format_quantity(quantity, can)
            price_str = format_price(price, can)
            if float(qty_str) <= 0 or float(price_str) <= 0:
                logger.error(
                    f"[User {self.user_id}] limit order invalid qty={quantity} price={price} symbol={symbol}"
                )
                return None
            params = {
                "symbol": symbol,
                "side": binance_side,
                "type": "LIMIT",
                "timeInForce": "GTC",
                "quantity": qty_str,
                "price": price_str,
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            order = self.client.futures_create_order(**params)
            logger.info(
                f"[User {self.user_id}] limit {side} {qty_str} @ {price_str} {symbol} reduce={reduce_only}"
            )
            return order
        except Exception as e:
            logger.error(
                f"[User {self.user_id}] limit order failed: {e} symbol={symbol} qty={quantity} price={price}"
            )
            return None

    def place_stop_market_order(
        self,
        side,
        stop_price,
        symbol=None,
        quantity=None,
        reduce_only=False,
    ):
        symbol = self._sym(symbol)
        can = self._can_sym()
        binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
        stop_str = format_price(stop_price, can)
        if float(stop_str) <= 0:
            logger.error(f"[User {self.user_id}] stop order invalid price: {stop_price}")
            return None

        algo_params: dict = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": binance_side,
            "type": "STOP_MARKET",
            "triggerPrice": stop_str,
            "workingType": "CONTRACT_PRICE",
        }
        if quantity is not None and float(format_quantity(quantity, can)) > 0:
            algo_params["quantity"] = format_quantity(quantity, can)
            algo_params["reduceOnly"] = "true"
        else:
            algo_params["closePosition"] = "true"

        res = self._place_algo_stop_market(algo_params)
        if res:
            return res

        # Legacy book fallback (pre-migration exchanges / test mocks)
        try:
            params: dict = {
                "symbol": symbol,
                "side": binance_side,
                "type": "STOP_MARKET",
                "stopPrice": stop_str,
                "workingType": "CONTRACT_PRICE",
            }
            if quantity is not None and float(format_quantity(quantity, can)) > 0:
                params["quantity"] = format_quantity(quantity, can)
                params["reduceOnly"] = "true"
            else:
                params["closePosition"] = "true"
            order = self.client.futures_create_order(**params)
            logger.info(
                f"[User {self.user_id}] stop {side} @ {stop_str} {symbol} "
                f"qty={params.get('quantity', 'close-all')}"
            )
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] stop order failed: {e} stop={stop_price}")
            return None

    def place_stop_limit_order(
        self,
        side,
        stop_price,
        limit_price,
        symbol=None,
        quantity=None,
        reduce_only=True,
    ):
        """STOP limit — trigger at stop_price, execute as limit at limit_price."""
        symbol = self._sym(symbol)
        can = self._can_sym()
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            stop_str = format_price(stop_price, can)
            limit_str = format_price(limit_price, can)
            if float(stop_str) <= 0 or float(limit_str) <= 0:
                logger.error(
                    f"[User {self.user_id}] stop-limit invalid stop={stop_price} limit={limit_price}"
                )
                return None
            if quantity is None or float(format_quantity(quantity, can)) <= 0:
                logger.error(f"[User {self.user_id}] stop-limit requires quantity")
                return None
            params: dict = {
                "symbol": symbol,
                "side": binance_side,
                "type": "STOP",
                "stopPrice": stop_str,
                "price": limit_str,
                "timeInForce": "GTC",
                "quantity": format_quantity(quantity, can),
                "workingType": "CONTRACT_PRICE",
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            order = self.client.futures_create_order(**params)
            logger.info(
                f"[User {self.user_id}] stop-limit {side} qty={params['quantity']} {symbol} "
                f"trigger={stop_str} limit={limit_str}"
            )
            return order
        except Exception as e:
            logger.error(
                f"[User {self.user_id}] stop-limit failed: {e} stop={stop_price} limit={limit_price}"
            )
            return None

    def cancel_order(self, symbol: str | None, order_id: int) -> bool:
        symbol = self._sym(symbol)
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=int(order_id))
            logger.info(f"[User {self.user_id}] cancel order {order_id}")
            return True
        except Exception as e:
            logger.debug(f"[User {self.user_id}] regular cancel {order_id} failed: {e}")
        try:
            self.client._request_futures_api(
                "delete", "algoOrder", signed=True,
                data={"symbol": symbol, "algoId": int(order_id)},
            )
            logger.info(f"[User {self.user_id}] cancel algo order {order_id}")
            return True
        except Exception as e:
            logger.warning(f"[User {self.user_id}] cancel order {order_id} failed: {e}")
            return False

    def cancel_all_open_orders(self, symbol=None):
        symbol = self._sym(symbol)
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"[User {self.user_id}] cancel orders failed: {e}")
        try:
            self.client._request_futures_api(
                "delete", "algoOpenOrders", signed=True, data={"symbol": symbol},
            )
        except Exception as e:
            logger.debug(f"[User {self.user_id}] cancel algo orders: {e}")

    def test_connection(self) -> bool:
        try:
            self.client.futures_account()
            self.ensure_one_way_mode()
            return True
        except Exception:
            return False

    def get_api_key_restrictions(self) -> dict | None:
        """Binance SAPI GET /sapi/v1/account/apiRestrictions. None on failure."""
        try:
            if not hasattr(self.client, "_request_margin_api"):
                logger.warning(
                    "[User %s] python-binance missing _request_margin_api for restrictions",
                    self.user_id,
                )
                return None
            raw = self.client._request_margin_api("get", "account/apiRestrictions", True)
            if isinstance(raw, dict):
                return raw
            return None
        except Exception as e:
            logger.warning(f"[User {self.user_id}] api restrictions fetch failed: {e}")
            return None

    def get_exchange_uid(self) -> str | None:
        """Master account UID via SAPI (read-only)."""
        try:
            if hasattr(self.client, "_request_margin_api"):
                info = self.client._request_margin_api("get", "account/info", True)
                if isinstance(info, dict) and info.get("uid") is not None:
                    return str(info["uid"])
        except Exception as e:
            logger.warning(f"[User {self.user_id}] exchange uid fetch failed: {e}")
        return None

    def list_sub_accounts(self) -> list[dict]:
        """List sub-accounts under master (requires master API with sub-account read)."""
        out: list[dict] = []
        try:
            if not hasattr(self.client, "_request_margin_api"):
                return out
            ts = self.client._get_timestamp() if hasattr(self.client, "_get_timestamp") else int(time.time() * 1000)
            data = self.client._request_margin_api(
                "get", "sub-account/list", True, data={"timestamp": ts}
            )
            rows = data if isinstance(data, list) else (data or {}).get("subAccounts", [])
            for row in rows or []:
                uid = row.get("subUserId") or row.get("subAccountId") or row.get("email")
                if uid is None:
                    continue
                out.append({
                    "uid": str(uid),
                    "label": str(row.get("email") or row.get("remark") or uid),
                })
        except Exception as e:
            logger.warning(f"[User {self.user_id}] list sub-accounts failed: {e}")
        return out

    def probe_trading_api_role(self) -> dict:
        """
        Detect whether this API key belongs to a master or sub-account.
        Master keys can query sub-account/list when sub-management permission is enabled.
        Permission denied on sub-account/list does NOT imply a sub-account key.
        """
        resolved_uid = self.get_exchange_uid()
        try:
            if not hasattr(self.client, "_request_margin_api"):
                return {"role": "unknown", "resolved_uid": resolved_uid, "confirmed_sub": False}
            ts = self.client._get_timestamp() if hasattr(self.client, "_get_timestamp") else int(time.time() * 1000)
            self.client._request_margin_api(
                "get", "sub-account/list", True, data={"timestamp": ts, "limit": 1}
            )
            return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": True, "confirmed_sub": False}
        except Exception as e:
            err = str(e)
            if _error_indicates_sub_account_only(err):
                return {
                    "role": "sub",
                    "resolved_uid": resolved_uid,
                    "can_list_subs": False,
                    "confirmed_sub": True,
                }
            # Trading-only master APIs often lack sub-account/list permission (-2015 / -1002).
            if resolved_uid:
                return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": False, "confirmed_sub": False}
            return {"role": "unknown", "resolved_uid": resolved_uid, "error": err, "confirmed_sub": False}

    def verify_master_readonly(self) -> dict:
        """Verify master API can connect (no trading permission required)."""
        try:
            uid = self.get_exchange_uid()
            subs = self.list_sub_accounts()
            return {"ok": True, "uid": uid, "sub_accounts": subs}
        except Exception as e:
            return {"ok": False, "error": str(e), "uid": None, "sub_accounts": []}

    def get_funding_fees(self, symbol=None, start_time_ms: int | None = None) -> float:
        """Sum FUNDING_FEE income since position open (negative = paid by user)."""
        symbol = self._sym(symbol)
        try:
            params: dict = {"symbol": symbol, "incomeType": "FUNDING_FEE", "limit": 100}
            if start_time_ms:
                params["startTime"] = start_time_ms
            rows = self.client.futures_income_history(**params)
            return round(sum(float(r.get("income", 0)) for r in rows), 4)
        except Exception as e:
            logger.warning(f"[User {self.user_id}] funding fee fetch failed: {e}")
            return 0.0

    def get_futures_cashflows(
        self,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Normalize USDT-M income into transfer / funding / commission / realized rows."""
        from app.services.equity_reconcile import (
            BINANCE_FEE_INCOME_TYPES,
            BINANCE_TRANSFER_INCOME_TYPES,
        )

        try:
            params: dict = {"limit": min(int(limit or 1000), 1000)}
            if start_time_ms:
                params["startTime"] = int(start_time_ms)
            if end_time_ms:
                params["endTime"] = int(end_time_ms)
            raw = self.client.futures_income_history(**params) or []
        except Exception as e:
            logger.warning(f"[User {self.user_id}] futures cashflow fetch failed: {e}")
            return []

        out: list[dict] = []
        for r in raw:
            income_type = str(r.get("incomeType") or "").upper()
            try:
                amount = float(r.get("income") or 0)
            except (TypeError, ValueError):
                continue
            if abs(amount) < 1e-12:
                continue
            if income_type in BINANCE_TRANSFER_INCOME_TYPES:
                kind = "transfer"
            elif income_type == "FUNDING_FEE":
                kind = "funding"
            elif income_type in BINANCE_FEE_INCOME_TYPES:
                kind = "commission"
            elif income_type == "REALIZED_PNL":
                kind = "realized_pnl"
            else:
                kind = "other"
            out.append({
                "exchange": "binance",
                "kind": kind,
                "income_type": income_type,
                "amount": amount,
                "asset": r.get("asset") or "USDT",
                "symbol": r.get("symbol") or "",
                "time_ms": int(r.get("time") or 0),
                "tran_id": str(r.get("tranId") or r.get("tradeId") or ""),
                "info": str(r.get("info") or ""),
            })
        return out

    def get_account_trades(
        self,
        symbol: str = "ETHUSDT",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """USDT-M perpetual account trade history (fills)."""
        try:
            params: dict = {"symbol": symbol, "limit": min(limit, 1000)}
            if start_time_ms:
                params["startTime"] = start_time_ms
            if end_time_ms:
                params["endTime"] = end_time_ms
            return self.client.futures_account_trades(**params) or []
        except Exception as e:
            logger.warning(f"[User {self.user_id}] account trades fetch failed: {e}")
            return []
