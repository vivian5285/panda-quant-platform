import json
import logging
import threading

from flask import Flask, request, jsonify

from app.config import get_settings
from app.services.webhook_guard import check_webhook_access, validate_signal_payload

logger = logging.getLogger(__name__)
settings = get_settings()

webhook_app = Flask(__name__)


def _get_dispatcher():
    from app.services.dispatcher import signal_dispatcher
    return signal_dispatcher


def _run_dispatch_async(data: dict, fingerprint: str) -> None:
    from app.database import SessionLocal
    from app.services.signal_admin import record_webhook_hit, run_signal_dispatch
    from app.services.webhook_idempotency import finalize

    action = str(data.get("action", "UNKNOWN")).upper()
    record_webhook_hit(action)
    db = SessionLocal()
    try:
        row, _result = run_signal_dispatch(db, data, source="webhook")
        finalize(db, fingerprint, row.id)
    except Exception as e:
        logger.exception("Webhook dispatch persistence failed: %s", e)
    finally:
        db.close()


@webhook_app.route("/webhook", methods=["POST"])
def webhook():
    ok, msg, status = check_webhook_access()
    if not ok:
        return jsonify({"status": "error", "message": msg}), status

    try:
        data = request.get_json(silent=True) or json.loads(request.get_data(as_text=True) or "{}")
    except Exception:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    if not data:
        return jsonify({"status": "error", "message": "Empty payload"}), 400

    secret = str(data.get("secret", "")).strip()
    if secret != settings.WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    valid, err = validate_signal_payload(data)
    if not valid:
        return jsonify({"status": "error", "message": err}), 400

    from app.services.trading_control import is_globally_paused
    if is_globally_paused():
        return jsonify({"status": "error", "message": "Platform trading globally paused"}), 503

    from app.database import SessionLocal
    from app.services.webhook_idempotency import compute_fingerprint, try_acquire

    fingerprint = compute_fingerprint(data)
    db = SessionLocal()
    try:
        acquired, existing_dispatch_id = try_acquire(db, fingerprint)
    finally:
        db.close()

    if not acquired:
        logger.info("[Webhook] Duplicate signal fingerprint=%s dispatch_id=%s", fingerprint[:16], existing_dispatch_id)
        return jsonify({
            "status": "duplicate",
            "message": "Signal already processed (idempotent)",
            "dispatch_id": existing_dispatch_id,
            "action": str(data.get("action", "")).upper(),
        }), 200

    action = str(data.get("action", "UNKNOWN")).upper()
    reason = data.get("reason", "")
    if "CLOSE_PROTECT" in action:
        logger.info("[Webhook] CLOSE_PROTECT | reason=%s regime=%s", reason, data.get("regime"))
    else:
        logger.info("[Webhook] action=%s regime=%s atr=%s", action, data.get("regime"), data.get("atr"))

    threading.Thread(
        target=_run_dispatch_async,
        args=(data, fingerprint),
        daemon=True,
        name=f"webhook-dispatch-{action}",
    ).start()

    return jsonify({
        "status": "success",
        "message": "Signal received, dispatching to all users",
        "action": action,
    }), 200


@webhook_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
