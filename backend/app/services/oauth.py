"""OAuth2 helpers for Google, GitHub, X (Twitter) and Apple login."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests
from jose import jwt

from app.config import get_settings

settings = get_settings()

STATE_TTL_SECONDS = 600
OAUTH_PROVIDERS = ("google", "github", "twitter", "apple")


def _sign(raw: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


def make_oauth_state(provider: str, extra: dict | None = None) -> str:
    payload = {"p": provider, "t": int(time.time()), "n": secrets.token_urlsafe(8)}
    if extra:
        payload.update(extra)
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def parse_oauth_state(state: str, provider: str) -> dict | None:
    if not state or "." not in state:
        return None
    raw, sig = state.rsplit(".", 1)
    if not hmac.compare_digest(_sign(raw), sig):
        return None
    try:
        pad = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw + pad).decode())
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("p") != provider:
        return None
    if int(time.time()) - int(payload.get("t", 0)) > STATE_TTL_SECONDS:
        return None
    return payload


def verify_oauth_state(state: str, provider: str) -> bool:
    return parse_oauth_state(state, provider) is not None


def _apple_key_pem() -> str:
    raw = (settings.APPLE_PRIVATE_KEY or "").strip()
    if not raw:
        return ""
    if "BEGIN PRIVATE KEY" in raw:
        return raw.replace("\\n", "\n")
    return raw


def oauth_providers_enabled() -> dict[str, bool]:
    return {
        "google": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
        "github": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
        "twitter": bool(settings.TWITTER_CLIENT_ID and settings.TWITTER_CLIENT_SECRET),
        "apple": bool(
            settings.APPLE_CLIENT_ID
            and settings.APPLE_TEAM_ID
            and settings.APPLE_KEY_ID
            and _apple_key_pem()
        ),
    }


def _redirect_uri(provider: str) -> str:
    base = settings.API_PUBLIC_URL.rstrip("/")
    return f"{base}/api/auth/oauth/{provider}/callback"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def oauth_start_payload(provider: str) -> dict[str, Any]:
    if provider == "twitter":
        verifier, challenge = _pkce_pair()
        state = make_oauth_state(provider, {"v": verifier})
        return {"url": twitter_authorize_url(state, challenge), "state": state}
    state = make_oauth_state(provider)
    urls = {
        "google": google_authorize_url,
        "github": github_authorize_url,
        "apple": apple_authorize_url,
    }
    fn = urls.get(provider)
    if not fn:
        raise ValueError(f"Unknown provider {provider}")
    return {"url": fn(state), "state": state}


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


def twitter_authorize_url(state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.TWITTER_CLIENT_ID,
        "redirect_uri": _redirect_uri("twitter"),
        "scope": "users.read tweet.read offline.access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return "https://twitter.com/i/oauth2/authorize?" + urlencode(params)


def apple_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.APPLE_CLIENT_ID,
        "redirect_uri": _redirect_uri("apple"),
        "response_type": "code",
        "response_mode": "form_post",
        "scope": "name email",
        "state": state,
    }
    return "https://appleid.apple.com/auth/authorize?" + urlencode(params)


def _apple_client_secret() -> str:
    pem = _apple_key_pem()
    headers = {"kid": settings.APPLE_KEY_ID, "alg": "ES256"}
    now = int(time.time())
    payload = {
        "iss": settings.APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 86400 * 150,
        "aud": "https://appleid.apple.com",
        "sub": settings.APPLE_CLIENT_ID,
    }
    return jwt.encode(payload, pem, algorithm="ES256", headers=headers)


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


def exchange_twitter_code(code: str, code_verifier: str) -> dict[str, Any]:
    basic = base64.b64encode(
        f"{settings.TWITTER_CLIENT_ID}:{settings.TWITTER_CLIENT_SECRET}".encode()
    ).decode()
    token_res = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri("twitter"),
            "code_verifier": code_verifier,
        },
        timeout=15,
    )
    token_res.raise_for_status()
    access = token_res.json().get("access_token")
    if not access:
        raise ValueError("Twitter token exchange failed")
    user_res = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access}"},
        params={"user.fields": "profile_image_url"},
        timeout=15,
    )
    user_res.raise_for_status()
    user = user_res.json().get("data") or {}
    username = user.get("username") or "user"
    return {
        "provider_id": str(user.get("id", "")),
        "email": f"{username}@twitter.oauth.local",
        "name": user.get("name") or username,
        "avatar": user.get("profile_image_url"),
    }


def exchange_apple_code(code: str) -> dict[str, Any]:
    token_res = requests.post(
        "https://appleid.apple.com/auth/token",
        data={
            "client_id": settings.APPLE_CLIENT_ID,
            "client_secret": _apple_client_secret(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri("apple"),
        },
        timeout=15,
    )
    token_res.raise_for_status()
    id_token = token_res.json().get("id_token")
    if not id_token:
        raise ValueError("Apple token exchange failed")
    claims = jwt.get_unverified_claims(id_token)
    sub = str(claims.get("sub", ""))
    email = (claims.get("email") or "").lower()
    if not email:
        email = f"{sub[:12]}@apple.oauth.local"
    return {
        "provider_id": sub,
        "email": email,
        "name": email.split("@")[0],
        "avatar": None,
    }


def exchange_oauth_code(provider: str, code: str, state: str) -> dict[str, Any]:
    payload = parse_oauth_state(state, provider)
    if not payload:
        raise ValueError("Invalid OAuth state")
    if provider == "google":
        return exchange_google_code(code)
    if provider == "github":
        return exchange_github_code(code)
    if provider == "twitter":
        verifier = payload.get("v") or ""
        if not verifier:
            raise ValueError("Missing PKCE verifier")
        return exchange_twitter_code(code, verifier)
    if provider == "apple":
        return exchange_apple_code(code)
    raise ValueError(f"Unknown provider {provider}")
