import json
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_client = None


def get_redis():
    global _client
    if _client is not None:
        return _client
    try:
        import redis
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        _client.ping()
        return _client
    except Exception as e:
        logger.debug("Redis unavailable: %s", e)
        _client = False
        return None


def cache_set(key: str, value: Any, ttl: int = 60):
    r = get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value))
    except Exception:
        pass


def cache_get(key: str) -> Any | None:
    r = get_redis()
    if not r:
        return None
    try:
        val = r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


def publish(channel: str, message: dict):
    r = get_redis()
    if not r:
        return
    try:
        r.publish(channel, json.dumps(message))
    except Exception:
        pass
