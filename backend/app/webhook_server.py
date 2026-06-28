import os
import json
import logging
import threading
from flask import Flask, request, jsonify

from app.services.webhook_guard import check_webhook_access, validate_signal_payload

logger = logging.getLogger(__name__)

webhook_app = Flask(__name__)


def _get_dispatcher():
    from app.services.dispatcher import signal_dispatcher
    return signal_dispatcher


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
    expected = os.getenv("WEBHOOK_SECRET", "528586")
    if secret != expected:
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    valid, err = validate_signal_payload(data)
    if not valid:
        return jsonify({"status": "error", "message": err}), 400

    action = str(data.get("action", "UNKNOWN")).upper()
    reason = data.get("reason", "")
    if "CLOSE_PROTECT" in action:
        logger.info("[Webhook] CLOSE_PROTECT | reason=%s regime=%s", reason, data.get("regime"))
    else:
        logger.info("[Webhook] action=%s regime=%s atr=%s", action, data.get("regime"), data.get("atr"))

    dispatcher = _get_dispatcher()
    threading.Thread(target=dispatcher.dispatch, args=(data,), daemon=True).start()

    return jsonify({
        "status": "success",
        "message": "Signal received, dispatching to all users",
        "action": action,
    }), 200


@webhook_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200
