import logging
from binance.client import Client

from app.core.symbol_precision import format_price, format_quantity

logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str, user_id: int):
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = Client(api_key, api_secret)
        self._one_way_checked = False
        logger.info(f"[User {user_id}] Binance Client loaded")

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

    def set_leverage(self, symbol="ETHUSDT", leverage=15):
        try:
            return self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except Exception as e:
            logger.error(f"[User {self.user_id}] set_leverage failed: {e}")
            return None

    def get_current_price(self, symbol="ETHUSDT"):
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except Exception as e:
            logger.error(f"[User {self.user_id}] get price failed: {e}")
            return 0.0

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
