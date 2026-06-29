"""Mutable platform runtime settings (Redis + JSON file fallback)."""
import json
import logging
from pathlib import Path

from app.config import get_settings
from app.services.redis_client import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()

WITHDRAW_AUTO_KEY = "platform:withdraw_auto_max_usd"
WITHDRAW_REVIEW_KEY = "platform:withdraw_review_min_usd"
GLOBAL_RISK_KEY = "platform:global_risk_multiplier"
GLOBAL_PAUSE_KEY = "platform:trading_paused"
RUNTIME_FILE = Path(__file__).resolve().parents[2] / "data" / "platform_runtime.json"


def _read_file() -> dict:
    try:
        if RUNTIME_FILE.exists():
            return json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to read platform_runtime.json: %s", e)
    return {}


def _write_file(data: dict) -> None:
    RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_runtime_file() -> dict:
    return _read_file()


def write_runtime_file(data: dict) -> None:
    _write_file(data)


def get_withdraw_thresholds() -> dict:
    out = {
        "auto_max_usd": float(settings.WITHDRAW_AUTO_MAX_USD),
        "review_min_usd": float(settings.WITHDRAW_REVIEW_MIN_USD),
        "min_usd": float(settings.WITHDRAW_MIN_USD),
    }
    file_withdraw = _read_file().get("withdraw", {})
    for key in ("auto_max_usd", "review_min_usd", "min_usd"):
        if key in file_withdraw:
            out[key] = float(file_withdraw[key])

    redis = get_redis()
    if redis:
        try:
            auto = redis.get(WITHDRAW_AUTO_KEY)
            review = redis.get(WITHDRAW_REVIEW_KEY)
            if auto is not None:
                out["auto_max_usd"] = float(auto)
            if review is not None:
                out["review_min_usd"] = float(review)
        except Exception as e:
            logger.debug("Redis withdraw thresholds read failed: %s", e)
    return out


def set_withdraw_thresholds(*, auto_max_usd: float, review_min_usd: float) -> dict:
    if auto_max_usd <= 0 or review_min_usd <= 0:
        raise ValueError("Thresholds must be positive")
    if review_min_usd <= auto_max_usd:
        raise ValueError("review_min_usd must be greater than auto_max_usd")

    data = _read_file()
    data["withdraw"] = {
        "auto_max_usd": round(auto_max_usd, 2),
        "review_min_usd": round(review_min_usd, 2),
    }
    _write_file(data)

    redis = get_redis()
    if redis:
        try:
            redis.set(WITHDRAW_AUTO_KEY, str(round(auto_max_usd, 2)))
            redis.set(WITHDRAW_REVIEW_KEY, str(round(review_min_usd, 2)))
        except Exception as e:
            logger.warning("Redis withdraw thresholds write failed: %s", e)

    return get_withdraw_thresholds()


def is_global_trading_paused() -> bool:
    redis = get_redis()
    if redis:
        try:
            raw = redis.get(GLOBAL_PAUSE_KEY)
            if raw is not None:
                return raw == "1"
        except Exception as e:
            logger.debug("Redis global pause read failed: %s", e)
    return bool(_read_file().get("global_trading_paused", False))


def set_global_trading_paused(paused: bool) -> None:
    data = _read_file()
    data["global_trading_paused"] = paused
    _write_file(data)
    redis = get_redis()
    if redis:
        try:
            if paused:
                redis.set(GLOBAL_PAUSE_KEY, "1")
            else:
                redis.delete(GLOBAL_PAUSE_KEY)
        except Exception as e:
            logger.warning("Redis global pause write failed: %s", e)


def get_global_risk_multiplier() -> float:
    out = 1.0
    file_val = _read_file().get("global_risk_multiplier")
    if file_val is not None:
        out = float(file_val)
    redis = get_redis()
    if redis:
        try:
            raw = redis.get(GLOBAL_RISK_KEY)
            if raw is not None:
                out = float(raw)
        except Exception as e:
            logger.debug("Redis global risk read failed: %s", e)
    return round(max(0.1, min(3.0, out)), 2)


def set_global_risk_multiplier(value: float) -> float:
    if value <= 0 or value > 3:
        raise ValueError("global_risk_multiplier must be between 0.1 and 3.0")
    value = round(value, 2)
    data = _read_file()
    data["global_risk_multiplier"] = value
    _write_file(data)
    redis = get_redis()
    if redis:
        try:
            redis.set(GLOBAL_RISK_KEY, str(value))
        except Exception as e:
            logger.warning("Redis global risk write failed: %s", e)
    return value
