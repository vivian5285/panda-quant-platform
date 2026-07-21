"""OKX USDT-margined swap client — Binance-compatible surface for PositionSupervisor."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from app.config import get_settings
from app.core.symbol_precision import format_price, format_quantity
from app.core.binance_client import _error_indicates_sub_account_only

logger = logging.getLogger(__name__)
settings = get_settings()
CLIENT_VERSION = "v1.0.0-okx-swap"
BASE_URL = "https://www.okx.com"


class OkxClient:
    exchange_id = "okx"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        user_id: int = 0,
        trading_symbol: str | None = None,
    ):
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.passphrase = passphrase or ""
        self.user_id = user_id
        self.trading_symbol = trading_symbol or settings.OKX_SYMBOL
        self.trading_leverage = settings.OKX_LEVERAGE
        self.canonical_symbol = None
        self._ct_val = float(settings.OKX_CONTRACT_VALUE)
        self._lot_sz = float(settings.OKX_LOT_SIZE)
        self._one_way_checked = False
        self._price_cache: dict[str, float] = {}
        self._price_cache_ts: dict[str, float] = {}
        self._price_lock = threading.Lock()
        self._pub_ws_running = False
        self._pub_ws_symbol: str | None = None
        self._last_rest_price_fetch = 0.0
        self._rest_price_min_interval = 30.0
        self._load_instrument_meta()
        logger.info(f"[User {user_id}] OKX Client {CLIENT_VERSION} loaded ({self.trading_symbol})")

    def _timestamp(self) -> str:
        now = datetime.now(timezone.utc)
        ms = int(now.microsecond / 1000)
        return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        msg = f"{timestamp}{method.upper()}{path}{body}".encode("utf-8")
        digest = hmac.new(self.api_secret.encode("utf-8"), msg, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict | list | None:
        if not self.api_key or not self.api_secret or not self.passphrase:
            logger.error("[User %s] OKX credentials incomplete", self.user_id)
            return None
        query = ""
        if params:
            query = "?" + urlencode(params)
        request_path = f"/api/v5{path}{query}"
        body_str = json.dumps(body, separators=(",", ":")) if body else ""
        ts = self._timestamp()
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": self._sign(ts, method, request_path, body_str),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
        }
        url = f"{BASE_URL}{request_path}"
        try:
            resp = requests.request(
                method.upper(),
                url,
                headers=headers,
                data=body_str if body_str else None,
                timeout=15,
            )
            data = resp.json()
            if isinstance(data, dict) and str(data.get("code", "0")) != "0":
                logger.error(
                    "[User %s] OKX API %s %s code=%s msg=%s",
                    self.user_id,
                    method,
                    path,
                    data.get("code"),
                    data.get("msg"),
                )
            return data
        except Exception as exc:
            logger.error("[User %s] OKX request failed %s: %s", self.user_id, path, exc)
            return None

    @staticmethod
    def _data_list(res: Any) -> list:
        if isinstance(res, dict) and isinstance(res.get("data"), list):
            return res["data"]
        return []

    def _load_instrument_meta(self) -> None:
        res = self._request(
            "GET",
            "/public/instruments",
            {"instType": "SWAP", "instId": self.trading_symbol},
        )
        for row in self._data_list(res):
            try:
                self._ct_val = float(row.get("ctVal") or self._ct_val)
                self._lot_sz = float(row.get("lotSz") or self._lot_sz)
            except (TypeError, ValueError):
                pass

    def _eth_to_contracts(self, qty_eth: float) -> str:
        if self._ct_val <= 0:
            return format_quantity(qty_eth)
        contracts = max(self._lot_sz, round(qty_eth / self._ct_val / self._lot_sz) * self._lot_sz)
        if contracts < self._lot_sz:
            contracts = self._lot_sz
        text = f"{contracts:.8f}".rstrip("0").rstrip(".")
        return text or str(self._lot_sz)

    def _contracts_to_eth(self, contracts: float) -> float:
        return round(float(contracts) * self._ct_val, 3)

    def ensure_one_way_mode(self) -> bool:
        if self._one_way_checked:
            return True
        cfg = self._data_list(self._request("GET", "/account/config"))
        pos_mode = cfg[0].get("posMode") if cfg else None
        if pos_mode == "net_mode":
            self._one_way_checked = True
            return True
        res = self._request("POST", "/account/set-position-mode", body={"posMode": "net_mode"})
        ok = isinstance(res, dict) and str(res.get("code", "")) == "0"
        if ok:
            self._one_way_checked = True
        return ok

    def is_hedge_mode(self) -> bool | None:
        cfg = self._data_list(self._request("GET", "/account/config"))
        if not cfg:
            return None
        return cfg[0].get("posMode") == "long_short_mode"

    def set_leverage(self, symbol: str | None = None, leverage: int | None = None):
        inst = symbol or self.trading_symbol
        lev = int(leverage or self.trading_leverage)
        res = self._request(
            "POST",
            "/account/set-leverage",
            body={"instId": inst, "lever": str(lev), "mgnMode": "cross"},
        )
        if res is not None:
            self.trading_leverage = lev
        return res

    def get_futures_account_summary(self) -> dict:
        rows = self._data_list(self._request("GET", "/account/balance"))
        total_eq = 0.0
        avail = 0.0
        upl = 0.0
        for row in rows:
            for detail in row.get("details") or []:
                if detail.get("ccy") == "USDT":
                    total_eq = float(detail.get("eq") or detail.get("cashBal") or 0)
                    avail = float(detail.get("availEq") or detail.get("availBal") or total_eq)
                    upl = float(detail.get("upl") or 0)
        if total_eq <= 0 and rows:
            total_eq = float(rows[0].get("totalEq") or 0)
            avail = float(rows[0].get("availEq") or total_eq)
        return {
            "total_wallet_balance": round(total_eq, 2),
            "total_margin_balance": round(total_eq, 2),
            "available_balance": round(avail, 2),
            "unrealized_pnl": round(upl, 2),
            "can_trade": True,
        }

    def get_available_balance(self, asset: str = "USDT") -> float:
        return float(self.get_futures_account_summary().get("available_balance") or 0)

    def get_current_price(self, symbol: str | None = None, prefer_ws: bool = True) -> float:
        inst = symbol or self.trading_symbol
        if prefer_ws:
            px = self._get_ws_price(inst)
            if px:
                return px
        now = time.time()
        if now - self._last_rest_price_fetch < 2.0:
            stale = self._get_ws_price(inst, max_age=120.0)
            return stale or 0.0
        self._last_rest_price_fetch = now
        rows = self._data_list(self._request("GET", "/market/ticker", {"instId": inst}))
        if rows:
            try:
                px = float(rows[0].get("last") or rows[0].get("markPx") or 0)
                if px > 0:
                    self._set_ws_price(inst, px)
                    return px
            except (TypeError, ValueError):
                pass
        return self._get_ws_price(inst, max_age=120.0) or 0.0

    def fetch_klines(
        self,
        symbol: str | None = None,
        interval: str = "30m",
        limit: int = 300,
    ) -> list:
        """Public candles → Binance-shaped rows [open_time_ms, o, h, l, c, vol]."""
        inst = symbol or self.trading_symbol
        bar = interval if interval.endswith("m") or interval.endswith("H") else interval
        # OKX uses same 30m/1H tokens; map 1h → 1H
        if bar.lower() == "1h":
            bar = "1H"
        try:
            resp = requests.get(
                f"{BASE_URL}/api/v5/market/candles",
                params={"instId": inst, "bar": bar, "limit": str(int(limit))},
                timeout=15,
            )
            data = resp.json()
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return []
            out = []
            for row in reversed(rows):  # OKX returns newest first
                try:
                    out.append([
                        int(float(row[0])),
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                        float(row[5] if len(row) > 5 else 0),
                    ])
                except (TypeError, ValueError, IndexError):
                    continue
            return out
        except Exception as exc:
            logger.warning("[User %s] OKX fetch_klines failed: %s", self.user_id, exc)
            return []

    def _set_ws_price(self, symbol: str, price: float) -> None:
        with self._price_lock:
            self._price_cache[symbol] = price
            self._price_cache_ts[symbol] = time.time()
        from app.core.ws_price_listeners import notify_price_listeners
        notify_price_listeners(self, symbol, price)

    def register_price_listener(self, callback) -> None:
        from app.core.ws_price_listeners import register_price_listener
        register_price_listener(self, callback)

    def unregister_price_listener(self, callback) -> None:
        from app.core.ws_price_listeners import unregister_price_listener
        unregister_price_listener(self, callback)

    def _get_ws_price(self, symbol: str, max_age: float = 30.0) -> float | None:
        with self._price_lock:
            px = self._price_cache.get(symbol)
            ts = self._price_cache_ts.get(symbol, 0.0)
        if px and (time.time() - ts) <= max_age:
            return px
        return None

    def start_public_price_ws(self, symbol: str | None = None) -> None:
        inst = symbol or self.trading_symbol
        if self._pub_ws_running and self._pub_ws_symbol == inst:
            return
        self._pub_ws_symbol = inst
        if not self._pub_ws_running:
            self._pub_ws_running = True
            threading.Thread(
                target=self._public_price_ws_loop,
                args=(inst,),
                daemon=True,
                name=f"okx-ws-u{self.user_id}",
            ).start()

    def _public_price_ws_loop(self, inst: str) -> None:
        try:
            import websocket
        except ImportError:
            self._pub_ws_running = False
            return
        url = "wss://ws.okx.com:8443/ws/v5/public"

        def on_open(ws):
            ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "mark-price", "instId": inst}]}))

        def on_message(ws, message):
            try:
                data = json.loads(message)
                for row in data.get("data") or []:
                    px = float(row.get("markPx") or 0)
                    if px > 0:
                        self._set_ws_price(inst, px)
            except Exception:
                pass

        from app.core.ws_reconnect import sleep_ws_reconnect

        attempt = 0
        while self._pub_ws_running:
            try:
                ws_app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message)
                ws_app.run_forever(ping_interval=20, ping_timeout=10)
                attempt = 0
            except Exception as exc:
                logger.warning("[User %s] OKX WS: %s", self.user_id, exc)
            if self._pub_ws_running:
                sleep_ws_reconnect(attempt)
                attempt += 1

    def get_position(self, symbol: str | None = None) -> dict | None:
        inst = symbol or self.trading_symbol
        rows = self._data_list(
            self._request("GET", "/account/positions", {"instType": "SWAP", "instId": inst})
        )
        if not rows:
            return None
        row = rows[0]
        try:
            pos = float(row.get("pos") or 0)
        except (TypeError, ValueError):
            pos = 0.0
        if pos == 0:
            return {"positionAmt": "0", "entryPrice": "0", "markPrice": "0", "unRealizedProfit": "0"}
        eth_qty = self._contracts_to_eth(pos)
        return {
            "positionAmt": str(eth_qty if pos > 0 else -eth_qty),
            "entryPrice": str(row.get("avgPx") or 0),
            "markPrice": str(row.get("markPx") or 0),
            "unRealizedProfit": str(row.get("upl") or 0),
            "leverage": row.get("lever", self.trading_leverage),
        }

    def _normalize_order(self, row: dict) -> dict:
        side = str(row.get("side", "")).upper()
        ord_type = str(row.get("ordType", "")).lower()
        out_type = "LIMIT"
        if ord_type in ("conditional", "oco") or row.get("slTriggerPx") or row.get("tpTriggerPx"):
            out_type = "STOP_MARKET"
        reduce_only = str(row.get("reduceOnly", "")).lower() == "true"
        px = float(row.get("px") or row.get("slTriggerPx") or row.get("tpTriggerPx") or 0)
        qty_eth = self._contracts_to_eth(float(row.get("sz") or 0))
        return {
            "orderId": row.get("ordId") or row.get("algoId"),
            "type": out_type,
            "side": "BUY" if side == "BUY" else "SELL",
            "price": format_price(px) if px else "0",
            "stopPrice": format_price(px) if out_type == "STOP_MARKET" and px else "0",
            "origQty": format_quantity(qty_eth),
            "reduceOnly": reduce_only,
        }

    def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        inst = symbol or self.trading_symbol
        orders = []
        for row in self._data_list(
            self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": inst})
        ):
            orders.append(self._normalize_order(row))
        for row in self._data_list(
            self._request(
                "GET",
                "/trade/orders-algo-pending",
                {"instType": "SWAP", "instId": inst, "ordType": "conditional"},
            )
        ):
            orders.append(self._normalize_order(row))
        return orders

    def _place_order(self, body: dict) -> dict | None:
        res = self._request("POST", "/trade/order", body=body)
        if isinstance(res, dict) and str(res.get("code", "")) == "0":
            rows = self._data_list(res)
            return rows[0] if rows else res
        return None

    def place_market_order(self, side, quantity, symbol: str | None = None, reduce_only: bool = False):
        inst = symbol or self.trading_symbol
        okx_side = "buy" if str(side).upper() in ("BUY", "LONG") else "sell"
        body = {
            "instId": inst,
            "tdMode": "cross",
            "side": okx_side,
            "ordType": "market",
            "sz": self._eth_to_contracts(float(quantity)),
        }
        if reduce_only:
            body["reduceOnly"] = True
        return self._place_order(body)

    def place_limit_order(
        self,
        side,
        quantity,
        price,
        symbol: str | None = None,
        reduce_only: bool = True,
        time_in_force: str = "GTC",
    ):
        inst = symbol or self.trading_symbol
        okx_side = "buy" if str(side).upper() in ("BUY", "LONG") else "sell"
        tif = str(time_in_force or "GTC").upper()
        # OKX: ioc/fok are ordType; gtc uses limit
        if tif == "IOC":
            ord_type = "ioc"
        elif tif == "FOK":
            ord_type = "fok"
        else:
            ord_type = "limit"
        body = {
            "instId": inst,
            "tdMode": "cross",
            "side": okx_side,
            "ordType": ord_type,
            "px": format_price(price),
            "sz": self._eth_to_contracts(float(quantity)),
        }
        if reduce_only:
            body["reduceOnly"] = True
        return self._place_order(body)

    def place_stop_market_order(
        self, side, stop_price, symbol: str | None = None, quantity=None, reduce_only=False,
    ):
        inst = symbol or self.trading_symbol
        okx_side = "buy" if str(side).upper() in ("BUY", "LONG") else "sell"
        if quantity is not None and float(quantity) > 0:
            sz = self._eth_to_contracts(float(quantity))
        else:
            sz = self._eth_to_contracts(0.01)
            pos = self.get_position(inst)
            if pos:
                amt = abs(float(pos.get("positionAmt") or 0))
                if amt > 0:
                    sz = self._eth_to_contracts(amt)
        body = {
            "instId": inst,
            "tdMode": "cross",
            "side": okx_side,
            "ordType": "conditional",
            "sz": sz,
            "reduceOnly": True,
            "slTriggerPx": format_price(stop_price),
            "slOrdPx": "-1",
        }
        res = self._request("POST", "/trade/order-algo", body=body)
        if isinstance(res, dict) and str(res.get("code", "")) == "0":
            rows = self._data_list(res)
            return rows[0] if rows else res
        return None

    def place_stop_limit_order(
        self, side, stop_price, limit_price, symbol: str | None = None, quantity=None, reduce_only=True,
    ):
        """Conditional stop-limit — trigger at stop_price, fill as limit at limit_price."""
        inst = symbol or self.trading_symbol
        okx_side = "buy" if str(side).upper() in ("BUY", "LONG") else "sell"
        if quantity is None or float(quantity) <= 0:
            return None
        body = {
            "instId": inst,
            "tdMode": "cross",
            "side": okx_side,
            "ordType": "conditional",
            "sz": self._eth_to_contracts(float(quantity)),
            "reduceOnly": True,
            "slTriggerPx": format_price(stop_price),
            "slOrdPx": format_price(limit_price),
        }
        res = self._request("POST", "/trade/order-algo", body=body)
        if isinstance(res, dict) and str(res.get("code", "")) == "0":
            rows = self._data_list(res)
            return rows[0] if rows else res
        return None

    def cancel_order(self, symbol: str, order_id: int | str) -> bool:
        inst = symbol or self.trading_symbol
        oid = str(order_id)
        res = self._request(
            "POST",
            "/trade/cancel-order",
            body={"instId": inst, "ordId": oid},
        )
        if isinstance(res, dict) and str(res.get("code", "")) == "0":
            return True
        res = self._request(
            "POST",
            "/trade/cancel-algos",
            body=[{"instId": inst, "algoId": oid}],
        )
        return isinstance(res, dict) and str(res.get("code", "")) == "0"

    def cancel_all_open_orders(self, symbol: str | None = None) -> None:
        inst = symbol or self.trading_symbol
        for order in self.get_open_orders(inst):
            oid = order.get("orderId")
            if oid:
                self.cancel_order(inst, oid)

    def futures_activity_summary(self) -> dict:
        orders = self.get_open_orders(self.trading_symbol)
        pos = self.get_position(self.trading_symbol)
        open_positions = 1 if pos and float(pos.get("positionAmt", 0)) != 0 else 0
        return {"open_orders": len(orders), "open_positions": open_positions}

    def test_connection(self) -> bool:
        try:
            rows = self._data_list(self._request("GET", "/account/balance"))
            if not rows:
                return False
            self.ensure_one_way_mode()
            return True
        except Exception:
            return False

    def get_api_key_restrictions(self) -> dict | None:
        return None

    def get_exchange_uid(self) -> str | None:
        try:
            res = self._request("GET", "/account/config")
            if isinstance(res, dict) and str(res.get("code", "")) == "0":
                rows = res.get("data") or []
                if rows:
                    uid = rows[0].get("uid")
                    return str(uid) if uid is not None else None
        except Exception as e:
            logger.warning("[User %s] OKX uid fetch failed: %s", self.user_id, e)
        return None

    def list_sub_accounts(self) -> list[dict]:
        out: list[dict] = []
        try:
            res = self._request("GET", "/users/subaccount/list")
            if not isinstance(res, dict) or str(res.get("code", "")) != "0":
                return out
            for row in res.get("data") or []:
                uid = row.get("subAcct") or row.get("uid")
                if not uid:
                    continue
                out.append({"uid": str(uid), "label": str(uid)})
        except Exception as e:
            logger.warning("[User %s] OKX list sub-accounts failed: %s", self.user_id, e)
        return out

    def probe_trading_api_role(self) -> dict:
        """Sub-account API keys cannot list sub-accounts under the master."""
        resolved_uid = self.get_exchange_uid()
        try:
            res = self._request("GET", "/users/subaccount/list")
            if isinstance(res, dict) and str(res.get("code", "")) == "0":
                return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": True, "confirmed_sub": False}
            msg = str((res or {}).get("msg", ""))
            code = str((res or {}).get("code", ""))
            if _error_indicates_sub_account_only(msg):
                return {"role": "sub", "resolved_uid": resolved_uid, "can_list_subs": False, "confirmed_sub": True}
            if resolved_uid:
                return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": False, "confirmed_sub": False}
            return {"role": "unknown", "resolved_uid": resolved_uid, "confirmed_sub": False}
        except Exception as e:
            err = str(e)
            if _error_indicates_sub_account_only(err):
                return {"role": "sub", "resolved_uid": resolved_uid, "can_list_subs": False, "confirmed_sub": True}
            if resolved_uid:
                return {"role": "master", "resolved_uid": resolved_uid, "can_list_subs": False, "confirmed_sub": False}
            return {"role": "unknown", "resolved_uid": resolved_uid, "error": err, "confirmed_sub": False}

    def verify_master_readonly(self) -> dict:
        try:
            bal = self._data_list(self._request("GET", "/account/balance"))
            if not bal:
                return {"ok": False, "error": "connect failed", "uid": None, "sub_accounts": []}
            return {
                "ok": True,
                "uid": self.get_exchange_uid(),
                "sub_accounts": self.list_sub_accounts(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "uid": None, "sub_accounts": []}

    def get_funding_fees(self, symbol: str | None = None, start_time_ms: int | None = None) -> float:
        return 0.0

    def get_futures_cashflows(
        self,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """OKX SWAP account bills → normalized cashflow rows (transfer / funding / …)."""
        from app.services.equity_reconcile import OKX_TRANSFER_BILL_TYPES

        params: dict[str, Any] = {
            "instType": "SWAP",
            "ccy": "USDT",
            "limit": str(min(int(limit or 100), 100)),
        }
        if start_time_ms:
            params["begin"] = str(int(start_time_ms))
        if end_time_ms:
            params["end"] = str(int(end_time_ms))
        rows = self._data_list(self._request("GET", "/account/bills", params))
        if not rows:
            # Archive for older cycle windows
            rows = self._data_list(self._request("GET", "/account/bills-archive", params)) or []

        out: list[dict] = []
        for r in rows:
            bill_type = str(r.get("type") or "")
            try:
                amount = float(r.get("balChg") or r.get("pnl") or 0)
            except (TypeError, ValueError):
                continue
            if abs(amount) < 1e-12:
                continue
            if bill_type in OKX_TRANSFER_BILL_TYPES:
                kind = "transfer"
            elif bill_type == "8":
                kind = "funding"
            elif bill_type in ("2", "5", "9"):
                # trade / liquidation / ADL — leave for trade ledger; skip as transfer
                kind = "realized_pnl" if bill_type == "2" else "other"
            else:
                kind = "other"
            out.append({
                "exchange": "okx",
                "kind": kind,
                "income_type": bill_type,
                "amount": amount,
                "asset": r.get("ccy") or "USDT",
                "symbol": r.get("instId") or "",
                "time_ms": int(r.get("ts") or 0),
                "tran_id": str(r.get("billId") or ""),
                "info": str(r.get("subType") or ""),
            })
        return out

    def get_account_trades(
        self,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict]:
        inst = symbol or self.trading_symbol
        params: dict[str, Any] = {"instType": "SWAP", "instId": inst, "limit": str(min(limit, 100))}
        if start_time_ms:
            params["begin"] = str(start_time_ms)
        if end_time_ms:
            params["end"] = str(end_time_ms)
        return self._data_list(self._request("GET", "/trade/fills", params))
