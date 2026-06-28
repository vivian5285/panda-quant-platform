import logging
from binance.client import Client

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
            params = {
                "symbol": symbol,
                "side": binance_side,
                "type": "MARKET",
                "quantity": quantity,
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            order = self.client.futures_create_order(**params)
            logger.info(f"[User {self.user_id}] market {side} {quantity} reduce={reduce_only}")
            return order
        except Exception as e:
            logger.error(f"[User {self.user_id}] market order failed: {e}")
            return None

    def place_limit_order(self, side, quantity, price, symbol="ETHUSDT", reduce_only=True):
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            params = {
                "symbol": symbol, "side": binance_side, "type": "LIMIT",
                "timeInForce": "GTC", "quantity": quantity, "price": str(round(price, 2))
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            return self.client.futures_create_order(**params)
        except Exception as e:
            logger.error(f"[User {self.user_id}] limit order failed: {e}")
            return None

    def place_stop_market_order(self, side, stop_price, symbol="ETHUSDT"):
        try:
            binance_side = "BUY" if side.upper() in ["BUY", "LONG"] else "SELL"
            params = {
                "symbol": symbol, "side": binance_side, "type": "STOP_MARKET",
                "stopPrice": str(round(stop_price, 2)), "closePosition": "true"
            }
            return self.client.futures_create_order(**params)
        except Exception as e:
            logger.error(f"[User {self.user_id}] stop order failed: {e}")
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
