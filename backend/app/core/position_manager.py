import logging
from typing import Optional, Dict, Any, List
from app.core.binance_client import BinanceClient

logger = logging.getLogger(__name__)


class PositionManager:
    def __init__(self, client: BinanceClient):
        self.client = client
        self.user_id = client.user_id

    def get_position(self, symbol: str = "ETHUSDT") -> Optional[Dict[str, Any]]:
        return self.client.get_position(symbol)

    def has_position(self, symbol: str = "ETHUSDT") -> bool:
        pos = self.get_position(symbol)
        return bool(pos and float(pos.get("positionAmt", 0)) != 0)

    def get_position_side(self, symbol: str = "ETHUSDT") -> Optional[str]:
        pos = self.get_position(symbol)
        if not pos:
            return None
        amt = float(pos.get("positionAmt", 0))
        if amt > 0:
            return "LONG"
        if amt < 0:
            return "SHORT"
        return None

    def get_position_qty(self, symbol: str = "ETHUSDT") -> float:
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        return abs(float(pos.get("positionAmt", 0)))

    def get_unrealized_pnl(self, symbol: str = "ETHUSDT") -> float:
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        return float(pos.get("unRealizedProfit", 0))

    def get_open_orders(self, symbol: str = "ETHUSDT") -> List[Dict]:
        return self.client.get_open_orders(symbol)

    def get_position_status(self, symbol: str = "ETHUSDT") -> Dict[str, Any]:
        pos = self.get_position(symbol)
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return {"has_position": False}
        return {
            "has_position": True,
            "side": self.get_position_side(symbol),
            "qty": self.get_position_qty(symbol),
            "entry_price": float(pos.get("entryPrice", 0)),
            "mark_price": float(pos.get("markPrice", 0) or 0),
            "unrealized_pnl": self.get_unrealized_pnl(symbol),
            "leverage": pos.get("leverage", "N/A"),
        }
