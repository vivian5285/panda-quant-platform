import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Trade, TradeLog
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class TradeLogger:
    """Persist trades and logs to database."""

    def __init__(self, db: Session):
        self.db = db

    def log_event(self, user_id: int, event_type: str, message: str, detail: dict | None = None, trade_id: int | None = None):
        try:
            log = TradeLog(
                user_id=user_id,
                trade_id=trade_id,
                event_type=event_type,
                message=message,
                detail_json=json.dumps(detail or {}, ensure_ascii=False),
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.error(f"Log event failed user={user_id}: {e}")
            self.db.rollback()

    def on_trade_open(self, user_id: int, side: str, qty: float, entry_price: float, regime: int, tv_tps: list) -> int:
        try:
            trade = Trade(
                user_id=user_id,
                symbol=settings.SYMBOL,
                side=side,
                action=side,
                quantity=qty,
                entry_price=entry_price,
                regime=regime,
                tv_tp1=tv_tps[0] if len(tv_tps) > 0 else 0,
                tv_tp2=tv_tps[1] if len(tv_tps) > 1 else 0,
                tv_tp3=tv_tps[2] if len(tv_tps) > 2 else 0,
                status="open",
            )
            self.db.add(trade)
            self.db.commit()
            self.db.refresh(trade)
            self.log_event(user_id, "OPEN", f"开仓 {side} {qty} @ {entry_price}", {"regime": regime}, trade.id)
            return trade.id
        except Exception as e:
            logger.error(f"Trade open log failed user={user_id}: {e}")
            self.db.rollback()
            return 0

    def on_trade_close(self, trade_id: int, exit_price: float, pnl: float, reason: str):
        try:
            trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                return
            trade.exit_price = exit_price
            trade.realized_pnl = pnl
            trade.status = "closed"
            trade.closed_at = datetime.utcnow()
            trade.action = reason[:30] if reason else "CLOSE"
            self.db.commit()
            self.log_event(trade.user_id, "CLOSE", reason, {"exit_price": exit_price, "pnl": pnl}, trade_id)
        except Exception as e:
            logger.error(f"Trade close log failed trade={trade_id}: {e}")
            self.db.rollback()
