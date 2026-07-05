import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from app.models import User, ApiStatus
from app.core.exchange_factory import create_exchange_client, create_supervisor, user_has_api_credentials, user_exchange
from app.services.platform_public_settings import is_exchange_enabled
from app.services.trade_logger import TradeLogger
from app.services.radar_context import build_radar_recovery_context
from app.services.startup_audit import log_takeover_audit, broadcast_startup_summary
from app.services.alert_service import notify_admin, notify_system
from app.utils.crypto import decrypt_text
from app.database import SessionLocal

logger = logging.getLogger(__name__)


def _user_event_handler(db: Session):
    """用户实盘关键动作 → 管理员钉钉抄送（明细已由 PositionSupervisor._log 写入 TradeLog）。"""

    def handler(user_id: int, severity: str, alert_type: str, title: str, message: str, detail: dict | None = None):
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
            users = [u for u in users if user_has_api_credentials(u) and is_exchange_enabled(user_exchange(u))]
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
            if not is_exchange_enabled(user_exchange(user)):
                logger.warning("User %s exchange not enabled for托管", user.id)
                TradeLogger(db).log_event(
                    user.id,
                    "WARNING",
                    "交易所未开放，无法加载 Supervisor",
                    {"exchange": user_exchange(user)},
                )
                return None
            api_key = decrypt_text(user.api_key_enc)
            api_secret = decrypt_text(user.api_secret_enc)
            passphrase = decrypt_text(user.passphrase_enc) if user.passphrase_enc else ""
            client = create_exchange_client(user, api_key, api_secret, passphrase)
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
            supervisor = create_supervisor(
                user,
                client,
                on_log=trade_logger.log_event,
                on_trade_open=trade_logger.on_trade_open,
                on_trade_close=trade_logger.on_trade_close,
                on_trade_update_targets=trade_logger.on_trade_update_targets,
                on_alert=user_events,
            )
            recovery = build_radar_recovery_context(db, user.id)
            trade = recovery.get("trade") or {}
            open_trade_id = trade.get("id")
            audit = supervisor.recover_on_startup(
                open_trade_id=open_trade_id,
                recovery_context=recovery,
            )
            audit["uid"] = user.uid
            audit["exchange"] = user_exchange(user)
            log_takeover_audit(user, audit)

            try:
                from app.services.profit_audit import run_startup_dual_audit
                run_startup_dual_audit(db, user)
            except Exception as audit_err:
                logger.warning("Dual profit audit failed user=%s: %s", user.id, audit_err)

            with self._lock:
                self._supervisors[user.id] = supervisor
            logger.info("Supervisor added for user %s", user.id)
            return audit
        except Exception as e:
            from app.core.exchange_factory import ExchangeNotEnabledError
            if isinstance(e, ExchangeNotEnabledError):
                logger.warning("User %s exchange client blocked: %s", user.id, e.exchange)
                TradeLogger(db).log_event(
                    user.id,
                    "WARNING",
                    "交易所未开放，无法连接 API 网关",
                    {"exchange": e.exchange},
                )
                return None
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
            sup = self._supervisors.pop(user_id, None)
        if sup:
            sup.monitoring = False

    def shutdown_all(self, wait_seconds: float = 3.0) -> None:
        """Graceful shutdown: stop sentinel loops before process exit."""
        with self._lock:
            supervisors = list(self._supervisors.values())
        logger.info("Shutting down %d supervisors...", len(supervisors))
        for sup in supervisors:
            sup.monitoring = False
        if wait_seconds > 0 and supervisors:
            time.sleep(wait_seconds)
        with self._lock:
            self._supervisors.clear()
        logger.info("Supervisor pool cleared")

    def get_all(self) -> list:
        with self._lock:
            return list(self._supervisors.values())

    def get(self, user_id: int):
        with self._lock:
            return self._supervisors.get(user_id)


supervisor_pool = UserSupervisorPool()


class SignalDispatcher:
    """Broadcast TV signals to all active user supervisors."""

    def __init__(self, pool: UserSupervisorPool, max_workers: int = 20):
        self.pool = pool
        self.max_workers = max_workers

    def dispatch(self, payload: dict) -> dict:
        from app.services.trading_control import get_user_control, is_globally_paused, is_user_paused
        from app.services.webhook_guard import is_close_signal

        action = str(payload.get("action", "")).upper().strip()
        is_close = is_close_signal(action)

        if is_globally_paused() and not is_close:
            logger.warning("Signal rejected: platform globally paused")
            notify_system(
                "warning", "GLOBAL_PAUSE",
                "全局交易已暂停",
                f"收到 {payload.get('action', '?')} 信号但未执行（平台暂停）",
                {"payload_action": payload.get("action")},
            )
            return {"dispatched": 0, "results": [], "reason": "global_pause"}

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

        db = SessionLocal()
        try:
            eligible: list = []
            results: list[dict] = []
            for s in supervisors:
                user = db.query(User).filter(User.id == s.user_id).first()
                if not user or not user.is_active:
                    results.append({
                        "user_id": s.user_id,
                        "status": "risk_blocked",
                        "reason": "user_inactive",
                    })
                    continue
                if user.api_status != ApiStatus.ACTIVE.value:
                    results.append({
                        "user_id": s.user_id,
                        "status": "risk_blocked",
                        "reason": "api_inactive",
                    })
                    continue
                if not is_exchange_enabled(user_exchange(user)):
                    results.append({
                        "user_id": s.user_id,
                        "status": "risk_blocked",
                        "reason": "exchange_not_open",
                    })
                    continue
                if is_user_paused(db, s.user_id) and not is_close:
                    from app.services.credit_control import user_trading_blocked_by_credit
                    reason = "user_paused"
                    ctrl = get_user_control(db, s.user_id)
                    if not ctrl.get("trading_paused"):
                        _, credit_reason = user_trading_blocked_by_credit(db, s.user_id)
                        reason = credit_reason or "settlement_blocked"
                    results.append({
                        "user_id": s.user_id,
                        "status": "risk_blocked",
                        "reason": reason,
                    })
                else:
                    eligible.append(s)
        finally:
            db.close()

        if not eligible:
            logger.warning("No eligible supervisors (all paused, settlement-gated, or inactive)")
            return {"dispatched": 0, "results": results, "reason": "all_users_paused"}

        errors = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._execute_for_user, s, payload): s.user_id
                for s in eligible
            }
            for future in as_completed(futures):
                uid = futures[future]
                try:
                    outcome = future.result()
                    results.append({"user_id": uid, **outcome})
                    if outcome.get("status") == "error":
                        errors.append({"user_id": uid, "message": outcome.get("message", "")})
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

        ok_count = sum(1 for r in results if r.get("status") == "ok")
        logger.info(f"Signal dispatched: ok={ok_count} total={len(results)}")
        if errors:
            notify_system(
                "warning", "DISPATCH_PARTIAL_FAIL",
                "信号广播部分失败",
                f"{len(errors)}/{len(results)} 用户执行失败",
                {"action": payload.get("action"), "errors": errors},
            )
        return {"dispatched": ok_count, "results": results}

    def _execute_for_user(self, supervisor, payload: dict) -> dict:
        from app.services.platform_runtime import get_global_risk_multiplier
        from app.services.trading_control import get_user_control, is_user_paused
        from app.services.webhook_guard import ENTRY_ACTIONS

        t0 = time.time()
        action = str(payload.get("action", "")).upper().strip()
        db = SessionLocal()
        try:
            if action in ENTRY_ACTIONS and is_user_paused(db, supervisor.user_id):
                return {
                    "status": "risk_blocked",
                    "reason": "user_paused",
                    "latency_ms": max(1, int((time.time() - t0) * 1000)),
                }
            ctrl = get_user_control(db, supervisor.user_id)
            effective_risk = round(get_global_risk_multiplier() * ctrl.get("risk_multiplier", 1.0), 4)
            user_payload = {**payload, "risk_multiplier": effective_risk}
        finally:
            db.close()
        outcome = supervisor.handle_signal(user_payload)
        if not isinstance(outcome, dict):
            outcome = {"status": "ok"}
        outcome["latency_ms"] = max(1, int((time.time() - t0) * 1000))
        return outcome


signal_dispatcher = SignalDispatcher(supervisor_pool)
