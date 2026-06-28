"""OAuth2 helpers for Google and GitHub login."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.config import get_settings

settings = get_settings()

STATE_TTL_SECONDS = 600


def _sign(raw: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


def make_oauth_state(provider: str) -> str:
    payload = {"p": provider, "t": int(time.time()), "n": secrets.token_urlsafe(8)}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def verify_oauth_state(state: str, provider: str) -> bool:
    if not state or "." not in state:
        return False
    raw, sig = state.rsplit(".", 1)
    if not hmac.compare_digest(_sign(raw), sig):
        return False
    try:
        pad = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw + pad).decode())
    except (ValueError, json.JSONDecodeError):
        return False
    if payload.get("p") != provider:
        return False
    if int(time.time()) - int(payload.get("t", 0)) > STATE_TTL_SECONDS:
        return False
    return True


def oauth_providers_enabled() -> dict[str, bool]:
    return {
        "google": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "github": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
    }


def _redirect_uri(provider: str) -> str:
    base = settings.API_PUBLIC_URL.rstrip("/")
    return f"{base}/api/auth/oauth/{provider}/callback"


def google_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def github_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": _redirect_uri("github"),
        "scope": "read:user user:email",
        "state": state,
    }
    return "https://github.com/login/oauth/authorize?" + urlencode(params)


def exchange_google_code(code: str) -> dict[str, Any]:
    token_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _redirect_uri("google"),
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    token_res.raise_for_status()
    access = token_res.json().get("access_token")
    if not access:
        raise ValueError("Google token exchange failed")
    profile = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access}"},
        timeout=15,
    )
    profile.raise_for_status()
    data = profile.json()
    if data.get("verified_email") is False:
        raise ValueError("Google email not verified")
    return {
        "provider_id": str(data.get("id", "")),
        "email": (data.get("email") or "").lower(),
        "name": data.get("name") or data.get("given_name") or "",
        "avatar": data.get("picture"),
    }


def exchange_github_code(code: str) -> dict[str, Any]:
    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": _redirect_uri("github"),
        },
        timeout=15,
    )
    token_res.raise_for_status()
    access = token_res.json().get("access_token")
    if not access:
        raise ValueError("GitHub token exchange failed")
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"}
    user_res = requests.get("https://api.github.com/user", headers=headers, timeout=15)
    user_res.raise_for_status()
    user = user_res.json()
    email = (user.get("email") or "").lower()
    if not email:
        emails_res = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15)
        emails_res.raise_for_status()
        for item in emails_res.json():
            if item.get("primary") and item.get("verified"):
                email = item.get("email", "").lower()
                break
        if not email:
            for item in emails_res.json():
                if item.get("verified"):
                    email = item.get("email", "").lower()
                    break
    return {
        "provider_id": str(user.get("id", "")),
        "email": email,
        "name": user.get("name") or user.get("login") or "",
        "avatar": user.get("avatar_url"),
    }
