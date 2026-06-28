import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from app.models import User, ApiStatus
from app.core.binance_client import BinanceClient
from app.core.position_supervisor import PositionSupervisor
from app.services.trade_logger import TradeLogger
from app.services.startup_audit import link_open_trade, log_takeover_audit, broadcast_startup_summary
from app.services.alert_service import notify_admin, notify_system
from app.utils.crypto import decrypt_text
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _user_event_handler(db: Session):
    """用户账户事件写入 TradeLog；不推送钉钉。"""
    trade_logger = TradeLogger(db)

    def handler(user_id: int, severity: str, alert_type: str, title: str, message: str, detail: dict | None = None):
        trade_logger.log_event(user_id, alert_type, f"{title}: {message}", detail)
        notify_admin(user_id, severity, alert_type, title, message, detail)

    return handler


class UserSupervisorPool:
    """Manages per-user PositionSupervisor instances."""

    def __init__(self):
        self._supervisors: dict[int, PositionSupervisor] = {}
        self._lock = threading.Lock()
        self.last_startup_audits: list[dict] = []
        self.last_startup_failures: list[dict] = []
        self.startup_in_progress = False
        self.startup_complete = False

    def load_active_users(self, db: Session):
        self.startup_in_progress = True
        try:
            users = db.query(User).filter(
                User.is_active == True,
                User.api_status == ApiStatus.ACTIVE.value,
                User.api_key_enc.isnot(None),
            ).all()
            audits = []
            failed = []
            for user in users:
                audit = self.add_user(user, db=db)
                if audit is None:
                    failed.append({
                        "user_id": user.id,
                        "uid": user.uid,
                        "reason": "supervisor_init_failed",
                    })
                else:
                    if audit.get("error"):
                        failed.append({
                            "user_id": user.id,
                            "uid": user.uid,
                            "reason": audit.get("error"),
                        })
                    audits.append(audit)
            self.last_startup_audits = audits
            self.last_startup_failures = failed
            logger.info("Loaded %d active supervisors", len(self._supervisors))
            if audits:
                with_pos = sum(1 for a in audits if a.get("has_position"))
                logger.info("[VPS STARTUP] 账户接管汇总: %d 用户 | %d 有持仓 | 失败 %d", len(audits), with_pos, len(failed))
            broadcast_startup_summary(audits, failed)
        finally:
            self.startup_complete = True
            self.startup_in_progress = False

    def add_user(self, user: User, db: Session | None = None) -> dict | None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            api_key = decrypt_text(user.api_key_enc)
            api_secret = decrypt_text(user.api_secret_enc)
            client = BinanceClient(api_key, api_secret, user.id)
            if not client.test_connection():
                logger.warning("User %s API connection failed", user.id)
                TradeLogger(db).log_event(
                    user.id, "ERROR", "API 连接失败，无法加载 Supervisor", {"uid": user.uid},
                )
                notify_admin(
                    user.id, "warning", "API_OFFLINE",
                    "用户 API 不可用",
                    "绑定 API 连接失败，无法加载 Supervisor",
                    {"uid": user.uid},
                )
                return None

            trade_logger = TradeLogger(db)
            user_events = _user_event_handler(db)
            supervisor = PositionSupervisor(
                user_id=user.id,
                client=client,
                on_log=trade_logger.log_event,
                on_trade_open=trade_logger.on_trade_open,
                on_trade_close=trade_logger.on_trade_close,
                on_alert=user_events,
            )
            open_trade_id = link_open_trade(db, user.id)
            audit = supervisor.recover_on_startup(open_trade_id=open_trade_id)
            audit["uid"] = user.uid
            log_takeover_audit(user, audit)

            with self._lock:
                self._supervisors[user.id] = supervisor
            logger.info("Supervisor added for user %s", user.id)
            return audit
        except Exception as e:
            logger.error("Failed to add supervisor user=%s: %s", user.id, e)
            TradeLogger(db).log_event(user.id, "ERROR", f"Supervisor 加载失败: {e}", {"uid": user.uid})
            notify_admin(
                user.id, "critical", "SUPERVISOR_FAIL",
                "Supervisor 加载失败",
                str(e),
                {"uid": user.uid},
            )
            return None
        finally:
            if own_db:
                db.close()

    def remove_user(self, user_id: int):
        with self._lock:
            self._supervisors.pop(user_id, None)

    def get_all(self) -> list[PositionSupervisor]:
        with self._lock:
            return list(self._supervisors.values())

    def get(self, user_id: int) -> PositionSupervisor | None:
        with self._lock:
            return self._supervisors.get(user_id)


supervisor_pool = UserSupervisorPool()


class SignalDispatcher:
    """Broadcast TV signals to all active user supervisors."""

    def __init__(self, pool: UserSupervisorPool, max_workers: int = 20):
        self.pool = pool
        self.max_workers = max_workers

    def dispatch(self, payload: dict) -> dict:
        supervisors = self.pool.get_all()
        if not supervisors:
            logger.warning("No active supervisors to dispatch")
            notify_system(
                "warning", "DISPATCH_EMPTY",
                "信号广播无接收者",
                f"收到 {payload.get('action', '?')} 信号，但无活跃 Supervisor",
                {"payload_action": payload.get("action")},
            )
            return {"dispatched": 0, "results": []}

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(s.handle_signal, payload): s.user_id
                for s in supervisors
            }
            for future in as_completed(futures):
                uid = futures[future]
                try:
                    future.result()
                    results.append({"user_id": uid, "status": "ok"})
                except Exception as e:
                    logger.error(f"Dispatch failed user={uid}: {e}")
                    errors.append({"user_id": uid, "message": str(e)})
                    err_db = SessionLocal()
                    try:
                        TradeLogger(err_db).log_event(
                            uid, "ERROR", f"信号执行失败: {e}",
                            {"action": payload.get("action")},
                        )
                    finally:
                        err_db.close()
                    notify_admin(
                        uid, "critical", "DISPATCH_ERROR",
                        "信号执行失败",
                        str(e),
                        {"action": payload.get("action")},
                    )
                    results.append({"user_id": uid, "status": "error", "message": str(e)})

        logger.info(f"Signal dispatched to {len(results)} users")
        if errors:
            notify_system(
                "warning", "DISPATCH_PARTIAL_FAIL",
                "信号广播部分失败",
                f"{len(errors)}/{len(results)} 用户执行失败",
                {"action": payload.get("action"), "errors": errors},
            )
        return {"dispatched": len(results), "results": results}


signal_dispatcher = SignalDispatcher(supervisor_pool)
