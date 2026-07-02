import logging
from typing import Optional, Dict, Any, List


class PositionManager:
    def __init__(self, client):
        self.client = client
        self.user_id = client.user_id
        self.default_symbol = getattr(client, "trading_symbol", "ETHUSDT")

    def _symbol(self, symbol: str | None = None) -> str:
        return symbol or self.default_symbol

    def get_position(self, symbol: str | None = None) -> Optional[Dict[str, Any]]:
        return self.client.get_position(self._symbol(symbol))

    def has_position(self, symbol: str | None = None) -> bool:
        pos = self.get_position(symbol)
        return bool(pos and float(pos.get("positionAmt", 0)) != 0)

    def get_position_side(self, symbol: str | None = None) -> Optional[str]:
        pos = self.get_position(symbol)
        if not pos:
            return None
        amt = float(pos.get("positionAmt", 0))
        if amt > 0:
            return "LONG"
        if amt < 0:
            return "SHORT"
        return None

    def get_position_qty(self, symbol: str | None = None) -> float:
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        return abs(float(pos.get("positionAmt", 0)))

    def get_unrealized_pnl(self, symbol: str | None = None) -> float:
        pos = self.get_position(symbol)
        if not pos:
            return 0.0
        return float(pos.get("unRealizedProfit", 0))

    def get_open_orders(self, symbol: str | None = None) -> List[Dict]:
        return self.client.get_open_orders(self._symbol(symbol))

    def get_position_status(self, symbol: str | None = None) -> Dict[str, Any]:
        sym = self._symbol(symbol)
        pos = self.get_position(sym)
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return {"has_position": False}
        return {
            "has_position": True,
            "side": self.get_position_side(sym),
            "qty": self.get_position_qty(sym),
            "entry_price": float(pos.get("entryPrice", 0)),
            "mark_price": float(pos.get("markPrice", 0) or 0),
            "unrealized_pnl": self.get_unrealized_pnl(sym),
            "leverage": pos.get("leverage", "N/A"),
        }
