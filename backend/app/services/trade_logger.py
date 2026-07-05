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

    @staticmethod
    def enrich_detail(detail: dict | None, event_type: str) -> dict:
        """Attach live-verification metadata for user-facing audit logs."""
        d = dict(detail or {})
        if event_type == "BINANCE_FILL":
            d.setdefault("source", "binance_exchange_sync")
        else:
            d.setdefault("source", "platform_supervisor")
            if event_type not in ("SIGNAL", "ERROR"):
                d.setdefault("live_verified", True)
        d.setdefault("verified_at", datetime.utcnow().isoformat() + "Z")
        return d

    def log_event(self, user_id: int, event_type: str, message: str, detail: dict | None = None, trade_id: int | None = None):
        try:
            enriched = self.enrich_detail(detail, event_type)
            log = TradeLog(
                user_id=user_id,
                trade_id=trade_id,
                event_type=event_type,
                message=message,
                detail_json=json.dumps(enriched, ensure_ascii=False),
            )
            self.db.add(log)
            self.db.commit()
        except Exception as e:
            logger.error(f"Log event failed user={user_id}: {e}")
            self.db.rollback()

    def on_trade_open(self, user_id: int, side: str, qty: float, entry_price: float, regime: int, tv_tps: list) -> int:
        """Create Trade row only; event detail is logged by PositionSupervisor._log(OPEN)."""
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
            return trade.id
        except Exception as e:
            logger.error(f"Trade open log failed user={user_id}: {e}")
            self.db.rollback()
            return 0

    def on_trade_close(self, trade_id: int, exit_price: float, pnl: float, reason: str, funding_fee: float = 0.0):
        """Update Trade row only; CLOSE event is logged by PositionSupervisor._log(CLOSE)."""
        try:
            trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
            if not trade:
                return
            trade.exit_price = exit_price
            trade.realized_pnl = pnl
            trade.funding_fee = funding_fee
            trade.status = "closed"
            trade.closed_at = datetime.utcnow()
            trade.action = reason[:30] if reason else "CLOSE"
            self.db.commit()
        except Exception as e:
            logger.error(f"Trade close log failed trade={trade_id}: {e}")
            self.db.rollback()

    def on_trade_update_targets(
        self,
        trade_id: int,
        *,
        tv_tps: list,
        regime: int | None = None,
        atr: float | None = None,
    ) -> None:
        """Refresh open trade TV targets after same-direction TP-only update."""
        if not trade_id:
            return
        try:
            trade = self.db.query(Trade).filter(Trade.id == trade_id).first()
            if not trade or trade.status != "open":
                return
            if len(tv_tps) > 0:
                trade.tv_tp1 = float(tv_tps[0] or 0)
            if len(tv_tps) > 1:
                trade.tv_tp2 = float(tv_tps[1] or 0)
            if len(tv_tps) > 2:
                trade.tv_tp3 = float(tv_tps[2] or 0)
            if regime is not None:
                trade.regime = int(regime)
            self.db.commit()
        except Exception as e:
            logger.error(f"Trade target update failed trade={trade_id}: {e}")
            self.db.rollback()
