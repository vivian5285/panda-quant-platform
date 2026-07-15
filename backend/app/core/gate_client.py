"""Gate.io USDT-margined futures client — Binance-compatible surface for PositionSupervisor."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any

import requests

from app.config import get_settings
from app.core.symbol_precision import format_price, format_quantity

logger = logging.getLogger(__name__)
settings = get_settings()
CLIENT_VERSION = "v1.0.0-gate-usdt"
BASE_URL = "https://fx-api.gateio.ws/api/v4"


class GateClient:
    exchange_id = "gate"

    def __init__(self, api_key: str, api_secret: str, user_id: int = 0):
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.user_id = user_id
        self.trading_symbol = settings.GATE_SYMBOL
        self.trading_leverage = settings.GATE_LEVERAGE
        self._quanto = float(settings.GATE_QUANTO_MULTIPLIER)
        self._one_way_checked = False
        self._price_cache: dict[str, float] = {}
        self._price_cache_ts: dict[str, float] = {}
        self._price_lock = threading.Lock()
        self._pub_ws_running = False
        self._pub_ws_symbol: str | None = None
        self._last_rest_price_fetch = 0.0
        self._load_contract_meta()
        logger.info(f"[User {user_id}] Gate Client {CLIENT_VERSION} loaded ({self.trading_symbol})")

    def _sign(self, method: str, url_path: str, query: str, body: str, timestamp: str) -> str:
        payload_hash = hashlib.sha512(body.encode("utf-8") if body else b"").hexdigest()
        sign_str = f"{method.upper()}\n{url_path}\n{query}\n{payload_hash}\n{timestamp}"
        return hmac.new(self.api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha512).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | list | None = None,
    ) -> Any:
        if not self.api_key or not self.api_secret:
            logger.error("[User %s] Gate credentials missing", self.user_id)
            return None
        query = ""
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
        url_path = path if path.startswith("/") else f"/{path}"
        body_str = json.dumps(body) if body is not None else ""
        ts = str(int(time.time()))
        sign = self._sign(method, url_path, query, body_str, ts)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "KEY": self.api_key,
            "Timestamp": ts,
            "SIGN": sign,
        }
        url = f"{BASE_URL}{url_path}"
        if query:
            url = f"{url}?{query}"
        try:
            resp = requests.request(
                method.upper(),
                url,
                headers=headers,
                data=body_str if body_str else None,
                timeout=15,
            )
            if resp.status_code >= 400:
                logger.error(
                    "[User %s] Gate API %s %s status=%s body=%s",
                    self.user_id,
                    method,
                    path,
                    resp.status_code,
                    resp.text[:300],
                )
                return None
            if not resp.text:
                return {}
            return resp.json()
        except Exception as exc:
            logger.error("[User %s] Gate request failed %s: %s", self.user_id, path, exc)
            return None

    def _load_contract_meta(self) -> None:
        row = self._request("GET", f"/futures/usdt/contracts/{self.trading_symbol}")
        if isinstance(row, dict):
            try:
                self._quanto = float(row.get("quanto_multiplier") or self._quanto)
            except (TypeError, ValueError):
                pass

    def _eth_to_contracts(self, qty_eth: float) -> int:
        if self._quanto <= 0:
            return max(1, int(round(qty_eth * 100)))
        size = int(round(qty_eth / self._quanto))
        return max(1, size) if qty_eth > 0 else min(-1, size)

    def _contracts_to_eth(self, contracts: float) -> float:
        return round(abs(float(contracts)) * self._quanto, 3)

    def ensure_one_way_mode(self) -> bool:
        if self._one_way_checked:
            return True
        row = self._request("GET", "/futures/usdt/accounts")
        if isinstance(row, dict):
            dual = row.get("in_dual_mode")
            if dual is False:
                self._one_way_checked = True
                return True
        res = self._request("POST", "/futures/usdt/dual_mode", body={"dual_mode": False})
        ok = res is not None
        if ok:
            self._one_way_checked = True
        return ok

    def is_hedge_mode(self) -> bool | None:
        row = self._request("GET", "/futures/usdt/accounts")
        if not isinstance(row, dict):
            return None
        val = row.get("in_dual_mode")
        return bool(val) if val is not None else None

    def set_leverage(self, symbol: str | None = None, leverage: int | None = None):
        contract = symbol or self.trading_symbol
        lev = leverage or self.trading_leverage
        return self._request(
            "POST",
            f"/futures/usdt/positions/{contract}/leverage",
            body={"leverage": str(lev)},
        )

    def get_futures_account_summary(self) -> dict:
        row = self._request("GET", "/futures/usdt/accounts")
        if not isinstance(row, dict):
            return {
                "total_wallet_balance": 0.0,
                "total_margin_balance": 0.0,
                "available_balance": 0.0,
                "unrealized_pnl": 0.0,
                "can_trade": False,
            }
        total = float(row.get("total") or row.get("equity") or 0)
        avail = float(row.get("available") or total)
        upl = float(row.get("unrealised_pnl") or 0)
        return {
            "total_wallet_balance": round(total, 2),
            "total_margin_balance": round(total, 2),
            "available_balance": round(avail, 2),
            "unrealized_pnl": round(upl, 2),
            "can_trade": True,
        }

    def get_available_balance(self, asset: str = "USDT") -> float:
        return float(self.get_futures_account_summary().get("available_balance") or 0)

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

    def get_current_price(self, symbol: str | None = None, prefer_ws: bool = True) -> float:
        contract = symbol or self.trading_symbol
        if prefer_ws:
            px = self._get_ws_price(contract)
            if px:
                return px
        now = time.time()
        if now - self._last_rest_price_fetch < 2.0:
            return self._get_ws_price(contract, max_age=120.0) or 0.0
        self._last_rest_price_fetch = now
        rows = self._request("GET", "/futures/usdt/tickers", {"contract": contract})
        if isinstance(rows, list) and rows:
            try:
                px = float(rows[0].get("last") or rows[0].get("mark_price") or 0)
                if px > 0:
                    self._set_ws_price(contract, px)
                    return px
            except (TypeError, ValueError):
                pass
        return self._get_ws_price(contract, max_age=120.0) or 0.0

    def start_public_price_ws(self, symbol: str | None = None) -> None:
        contract = symbol or self.trading_symbol
        if self._pub_ws_running and self._pub_ws_symbol == contract:
            return
        self._pub_ws_symbol = contract
        if not self._pub_ws_running:
            self._pub_ws_running = True
            threading.Thread(
                target=self._public_price_ws_loop,
                args=(contract,),
                daemon=True,
                name=f"gate-ws-u{self.user_id}",
            ).start()

    def _public_price_ws_loop(self, contract: str) -> None:
        try:
            import websocket
        except ImportError:
            self._pub_ws_running = False
            return
        url = "wss://fx-ws.gateio.ws/v4/ws/usdt"

        def on_open(ws):
            ws.send(
                json.dumps(
                    {
                        "time": int(time.time()),
                        "channel": "futures.tickers",
                        "event": "subscribe",
                        "payload": [contract],
                    }
                )
            )

        def on_message(ws, message):
            try:
                data = json.loads(message)
                for row in data.get("result") or []:
                    px = float(row.get("last") or row.get("mark_price") or 0)
                    if px > 0:
                        self._set_ws_price(contract, px)
            except Exception:
                pass

        while self._pub_ws_running:
            try:
                ws_app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
                ws_app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                logger.warning("[User %s] Gate WS: %s", self.user_id, exc)
            if self._pub_ws_running:
                time.sleep(3)

    def get_position(self, symbol: str | None = None) -> dict | None:
        contract = symbol or self.trading_symbol
        row = self._request("GET", f"/futures/usdt/positions/{contract}")
        if not isinstance(row, dict):
            return None
        try:
            size = int(row.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size == 0:
            return {"positionAmt": "0", "entryPrice": "0", "markPrice": "0", "unRealizedProfit": "0"}
        eth_qty = self._contracts_to_eth(size)
        signed = eth_qty if size > 0 else -eth_qty
        return {
            "positionAmt": str(signed),
            "entryPrice": str(row.get("entry_price") or 0),
            "markPrice": str(row.get("mark_price") or 0),
            "unRealizedProfit": str(row.get("unrealised_pnl") or 0),
            "leverage": row.get("leverage", self.trading_leverage),
        }

    def _normalize_order(self, row: dict) -> dict:
        finish_as = str(row.get("finish_as") or "")
        tif = str(row.get("tif") or "")
        is_stop = bool(row.get("is_stop") or row.get("trigger_price"))
        out_type = "STOP_MARKET" if is_stop else "LIMIT"
        if tif == "ioc" and not row.get("price"):
            out_type = "MARKET"
        side = "BUY" if int(row.get("size") or 0) > 0 else "SELL"
        px = float(row.get("price") or row.get("trigger_price") or 0)
        qty_eth = self._contracts_to_eth(abs(int(row.get("size") or 0)))
        return {
            "orderId": row.get("id"),
            "type": out_type,
            "side": side,
            "price": format_price(px) if px else "0",
            "stopPrice": format_price(float(row.get("trigger_price") or 0)) if is_stop else "0",
            "origQty": format_quantity(qty_eth),
            "reduceOnly": bool(row.get("is_reduce_only") or row.get("reduce_only")),
        }

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        contract = symbol or self.trading_symbol
        rows = self._request("GET", "/futures/usdt/orders", {"contract": contract, "status": "open"})
        if not isinstance(rows, list):
            rows = []
        orders = [self._normalize_order(row) for row in rows]
        price_rows = self._request(
            "GET", "/futures/usdt/price_orders",
            {"contract": contract, "status": "open"},
        )
        if isinstance(price_rows, list):
            for row in price_rows:
                if not isinstance(row, dict):
                    continue
                initial = row.get("initial") if isinstance(row.get("initial"), dict) else {}
                trigger = float(initial.get("price") or row.get("trigger_price") or 0)
                orders.append({
                    "orderId": row.get("id") or row.get("order_id"),
                    "type": "STOP",
                    "stopPrice": trigger,
                    "price": float(initial.get("price") or 0),
                    "side": "SELL" if float(initial.get("size") or 0) < 0 else "BUY",
                    "isPriceOrder": True,
                })
        return orders

    def cancel_all_price_orders(self, symbol: str | None = None) -> None:
        contract = symbol or self.trading_symbol
        rows = self._request(
            "GET", "/futures/usdt/price_orders",
            {"contract": contract, "status": "open"},
        )
        if not isinstance(rows, list):
            return
        for row in rows:
            oid = row.get("id") or row.get("order_id")
            if oid is None:
                continue
            self._request("DELETE", f"/futures/usdt/price_orders/{oid}")

    def cancel_all_open_orders(self, symbol: str | None = None) -> None:
        contract = symbol or self.trading_symbol
        self._request("DELETE", "/futures/usdt/orders", {"contract": contract})
        self.cancel_all_price_orders(contract)

    def place_market_order(self, side, quantity, symbol: str | None = None, reduce_only: bool = False):
        contract = symbol or self.trading_symbol
        size = self._eth_to_contracts(float(quantity))
        if str(side).upper() in ("SELL", "SHORT"):
            size = -abs(size)
        else:
            size = abs(size)
        body: dict[str, Any] = {
            "contract": contract,
            "size": size,
            "price": "0",
            "tif": "ioc",
        }
        if reduce_only:
            body["reduce_only"] = True
        return self._request("POST", "/futures/usdt/orders", body=body)

    def place_limit_order(self, side, quantity, price, symbol: str | None = None, reduce_only: bool = True):
        contract = symbol or self.trading_symbol
        size = self._eth_to_contracts(float(quantity))
        if str(side).upper() in ("SELL", "SHORT"):
            size = -abs(size)
        else:
            size = abs(size)
        body: dict[str, Any] = {
            "contract": contract,
            "size": size,
            "price": format_price(price),
            "tif": "gtc",
        }
        if reduce_only:
            body["reduce_only"] = True
        return self._request("POST", "/futures/usdt/orders", body=body)

    def place_stop_market_order(
        self, side, stop_price, symbol: str | None = None, quantity=None, reduce_only=False,
    ):
        contract = symbol or self.trading_symbol
        close_side = str(side).upper()
        if quantity is not None and float(quantity) > 0:
            size = self._eth_to_contracts(float(quantity))
            if close_side in ("SELL", "SHORT"):
                size = -abs(size)
            else:
                size = abs(size)
        else:
            size = 0
            pos = self.get_position(contract)
            if pos:
                amt = float(pos.get("positionAmt") or 0)
                if amt != 0:
                    size = self._eth_to_contracts(abs(amt))
                    size = -abs(size) if amt > 0 and close_side in ("SELL", "SHORT") else abs(size)
            if size == 0:
                size = -1 if close_side in ("SELL", "SHORT") else 1
        body = {
            "contract": contract,
            "size": size,
            "price": "0",
            "tif": "ioc",
            "reduce_only": True,
            "stop_price": format_price(stop_price),
            "price_type": 1,
        }
        return self._request("POST", "/futures/usdt/price_orders", body=body)

    def place_stop_limit_order(
        self, side, stop_price, limit_price, symbol: str | None = None, quantity=None, reduce_only=True,
    ):
        """Price-triggered stop-limit from entry-based adverse tier."""
        contract = symbol or self.trading_symbol
        close_side = str(side).upper()
        if quantity is None or float(quantity) <= 0:
            return None
        size = self._eth_to_contracts(float(quantity))
        if close_side in ("SELL", "SHORT"):
            size = -abs(size)
        else:
            size = abs(size)
        body = {
            "contract": contract,
            "size": size,
            "price": format_price(limit_price),
            "tif": "gtc",
            "reduce_only": True,
            "stop_price": format_price(stop_price),
            "price_type": 1,
        }
        return self._request("POST", "/futures/usdt/price_orders", body=body)

    def cancel_order(self, symbol: str, order_id: int | str) -> bool:
        contract = symbol or self.trading_symbol
        res = self._request("DELETE", f"/futures/usdt/orders/{order_id}", {"contract": contract})
        return res is not None

    def futures_activity_summary(self) -> dict:
        orders = self.get_open_orders(self.trading_symbol)
        pos = self.get_position(self.trading_symbol)
        open_positions = 1 if pos and float(pos.get("positionAmt", 0)) != 0 else 0
        return {"open_orders": len(orders), "open_positions": open_positions}

    def test_connection(self) -> bool:
        try:
            row = self._request("GET", "/futures/usdt/accounts")
            if not isinstance(row, dict):
                return False
            self.ensure_one_way_mode()
            return True
        except Exception:
            return False

    def get_api_key_restrictions(self) -> dict | None:
        return None

    def get_funding_fees(self, symbol: str | None = None, start_time_ms: int | None = None) -> float:
        return 0.0

    def get_futures_cashflows(
        self,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Gate USDT futures account book — type=dnw is deposit/withdraw."""
        params: dict[str, Any] = {"limit": min(int(limit or 100), 1000)}
        if start_time_ms:
            params["from"] = int(start_time_ms // 1000)
        if end_time_ms:
            params["to"] = int(end_time_ms // 1000)
        # Prefer deposit/withdraw book; fall back to full book filtered client-side.
        rows = self._request("GET", "/futures/usdt/account_book", {**params, "type": "dnw"})
        if not isinstance(rows, list):
            rows = self._request("GET", "/futures/usdt/account_book", params)
        if not isinstance(rows, list):
            logger.warning("[User %s] Gate cashflow fetch returned non-list", self.user_id)
            return []

        out: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            book_type = str(r.get("type") or "").lower()
            try:
                amount = float(r.get("change") or 0)
            except (TypeError, ValueError):
                continue
            if abs(amount) < 1e-12:
                continue
            if book_type in ("dnw", "deposit", "withdraw", "transfer"):
                kind = "transfer"
            elif book_type in ("fund", "funding"):
                kind = "funding"
            elif book_type in ("fee", "point_dnw"):
                kind = "commission"
            elif book_type in ("pnl", "realized_pnl"):
                kind = "realized_pnl"
            else:
                kind = "other"
            time_raw = r.get("time")
            try:
                time_ms = int(float(time_raw) * 1000) if time_raw is not None else 0
            except (TypeError, ValueError):
                time_ms = 0
            out.append({
                "exchange": "gate",
                "kind": kind,
                "income_type": book_type,
                "amount": amount,
                "asset": "USDT",
                "symbol": r.get("contract") or "",
                "time_ms": time_ms,
                "tran_id": str(r.get("id") or ""),
                "info": str(r.get("text") or ""),
            })
        return out

    def get_account_trades(
        self,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict]:
        contract = symbol or self.trading_symbol
        params: dict[str, Any] = {"contract": contract, "limit": min(limit, 100)}
        rows = self._request("GET", "/futures/usdt/my_trades", params)
        return rows if isinstance(rows, list) else []
