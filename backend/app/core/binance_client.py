import json
import logging
import threading
import time

from binance.client import Client

from app.core.symbol_precision import format_price, format_quantity

logger = logging.getLogger(__name__)
WS_MARKET_BASE = "wss://fstream.binance.com/market/ws"
CLIENT_VERSION = "v13.4.6-flat-reconcile"


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, user_id: int):
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(api_key, api_secret)
        self._one_way_checked = False
        self._price_cache: dict[str, float] = {}
        self._price_cache_ts: dict[str, float] = {}
        self._price_lock = threading.Lock()
        self._pub_ws_running = False
        self._pub_ws_symbol: str | None = None
        self._rest_price_min_interval = 30.0
        self._last_rest_price_fetch = 0.0
        logger.info(f"[User {user_id}] Binance Client {CLIENT_VERSION} loaded")
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

    def set_leverage(self, symbol="ETHUSDT", leverage=20):
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

    def start_public_price_ws(self, symbol: str = "ETHUSDT") -> None:
        """Subscribe markPrice@1s — radar uses WS push, REST only as fallback."""
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

    def get_current_price(self, symbol="ETHUSDT", prefer_ws=True):
        """Prefer WS cache; rate-limit REST when WS is active."""
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

    def get_position(self, symbol="ETHUSDT"):
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            return positions[0] if positions else None
        except Exception as e:
            logger.error(f"[User {self.user_id}] get position failed: {e}")
            return None

    def get_open_orders(self, symbol="ETHUSDT"):
        try:
            return self.client.futures_get_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"[User {self.user_id}] get orders failed: {e}")
            return []

    def place_market_order(self, side, quantity, symbol="ETHUSDT", reduce_only=False):
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            qty_str = format_quantity(quantity)
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
            logger.info(f"[User {self.user_id}] market {side} {qty_str} reduce={reduce_only}")
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] market order failed: {e}")
            return None

    def place_limit_order(self, side, quantity, price, symbol="ETHUSDT", reduce_only=True):
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            qty_str = format_quantity(quantity)
            price_str = format_price(price)
            if float(qty_str) <= 0 or float(price_str) <= 0:
                logger.error(
                    f"[User {self.user_id}] limit order invalid qty={quantity} price={price}"
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
            logger.info(f"[User {self.user_id}] limit {side} {qty_str} @ {price_str} reduce={reduce_only}")
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] limit order failed: {e} qty={quantity} price={price}")
            return None

    def place_stop_market_order(self, side, stop_price, symbol="ETHUSDT"):
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            stop_str = format_price(stop_price)
            if float(stop_str) <= 0:
                logger.error(f"[User {self.user_id}] stop order invalid price: {stop_price}")
                return None
            params = {
                "symbol": symbol,
                "side": binance_side,
                "type": "STOP_MARKET",
                "stopPrice": stop_str,
                "closePosition": "true",
            }
            order = self.client.futures_create_order(**params)
            logger.info(f"[User {self.user_id}] stop {side} @ {stop_str}")
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] stop order failed: {e} stop={stop_price}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        try:
            self.client.futures_cancel_order(symbol=symbol, orderId=int(order_id))
            logger.info(f"[User {self.user_id}] cancel order {order_id}")
            return True
        except Exception as e:
            logger.warning(f"[User {self.user_id}] cancel order {order_id} failed: {e}")
            return False

    def cancel_all_open_orders(self, symbol="ETHUSDT"):
        try:
            self.client.futures_cancel_all_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"[User {self.user_id}] cancel orders failed: {e}")

    def test_connection(self) -> bool:
        try:
            self.client.futures_account()
            self.ensure_one_way_mode()
            return True
        except Exception:
            return False

    def get_api_key_restrictions(self) -> dict:
        """Binance API key permission flags (withdraw, futures, etc.)."""
        try:
            return self.client.get_account_api_restrictions() or {}
        except Exception as e:
            logger.warning(f"[User {self.user_id}] api restrictions fetch failed: {e}")
            return {}

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
        Master keys can query sub-account/list; sub keys typically cannot.
        """
        resolved_uid = self.get_exchange_uid()
        try:
            if not hasattr(self.client, "_request_margin_api"):
                return {"role": "unknown", "resolved_uid": resolved_uid}
            ts = self.client._get_timestamp() if hasattr(self.client, "_get_timestamp") else int(time.time() * 1000)
            self.client._request_margin_api(
                "get", "sub-account/list", True, data={"timestamp": ts, "limit": 1}
            )
            return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": True}
        except Exception as e:
            err = str(e).lower()
            sub_markers = (
                "sub-account", "sub account", "subaccount",
                "not allowed", "permission", "-2015", "invalid api-key",
            )
            if any(m in err for m in sub_markers):
                return {"role": "sub", "resolved_uid": resolved_uid, "can_list_subs": False}
            if resolved_uid:
                return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": False}
            return {"role": "unknown", "resolved_uid": resolved_uid, "error": str(e)}

    def verify_master_readonly(self) -> dict:
        """Verify master API can connect (no trading permission required)."""
        try:
            uid = self.get_exchange_uid()
            subs = self.list_sub_accounts()
            return {"ok": True, "uid": uid, "sub_accounts": subs}
        except Exception as e:
            return {"ok": False, "error": str(e), "uid": None, "sub_accounts": []}

    def get_funding_fees(self, symbol="ETHUSDT", start_time_ms: int | None = None) -> float:
        """Sum FUNDING_FEE income since position open (negative = paid by user)."""
        try:
            params: dict = {"symbol": symbol, "incomeType": "FUNDING_FEE", "limit": 100}
            if start_time_ms:
                params["startTime"] = start_time_ms
            rows = self.client.futures_income_history(**params)
            return round(sum(float(r.get("income", 0)) for r in rows), 4)
        except Exception as e:
            logger.warning(f"[User {self.user_id}] funding fee fetch failed: {e}")
            return 0.0

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
