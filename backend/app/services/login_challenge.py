"""Short-lived login challenges for TOTP second step."""
import secrets
from datetime import timedelta

from app.services.redis_client import get_redis
from app.utils.auth import create_access_token, decode_access_token

CHALLENGE_TTL = 300


def create_login_challenge(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    redis = get_redis()
    if redis:
        redis.setex(f"auth:challenge:{token}", CHALLENGE_TTL, str(user_id))
        return token
    return create_access_token(
        {"sub": user_id, "typ": "login_challenge"},
        expires_delta=timedelta(minutes=5),
    )


def consume_login_challenge(token: str) -> int | None:
    if not token:
        return None
    redis = get_redis()
    if redis:
        try:
            raw = redis.get(f"auth:challenge:{token}")
            if raw:
                redis.delete(f"auth:challenge:{token}")
                val = raw.decode() if isinstance(raw, bytes) else raw
                return int(val)
        except Exception:
            pass
    payload = decode_access_token(token)
    if payload and payload.get("typ") == "login_challenge" and payload.get("sub"):
        try:
            return int(payload["sub"])
        except (TypeError, ValueError):
            return None
    return None
