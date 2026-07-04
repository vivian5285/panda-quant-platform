"""Tests for encrypted webhook secret settings."""
from __future__ import annotations

import pytest

from app.services import webhook_secrets as ws
from app.services.platform_runtime import RUNTIME_FILE


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    path = tmp_path / "platform_runtime.json"
    monkeypatch.setattr(ws, "read_runtime_file", lambda: __import__("json").loads(path.read_text()) if path.exists() else {})
    def _write(data):
        path.write_text(__import__("json").dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ws, "write_runtime_file", _write)
    monkeypatch.setattr("app.services.platform_runtime.RUNTIME_FILE", path)
    yield path


def test_get_webhook_secret_env_fallback(monkeypatch):
    monkeypatch.setattr(ws.settings, "WEBHOOK_SECRET", "env-secret-12chars")
    assert ws.get_webhook_secret() == "env-secret-12chars"


def test_update_webhook_settings_persists(monkeypatch):
    monkeypatch.setattr(ws.settings, "WEBHOOK_SECRET", "")
    secret = "a" * 16
    out = ws.update_webhook_settings(secret=secret)
    assert out["configured"] is True
    assert out["production_ready"] is True
    assert out["source"] == "runtime"
    assert out["insecure"] is False
    assert ws.get_webhook_secret() == secret


def test_update_rejects_short_secret():
    with pytest.raises(ValueError, match="至少 12"):
        ws.update_webhook_settings(secret="short")


def test_update_rejects_insecure_default():
    with pytest.raises(ValueError, match="过于简单"):
        ws.update_webhook_settings(secret="528586528586")


def test_get_webhook_public_url_production(monkeypatch):
    monkeypatch.setattr(ws.settings, "API_PUBLIC_URL", "https://twinstar.pro")
    monkeypatch.setattr(ws.settings, "WEBHOOK_PUBLIC_PATH", "/gemini/webhook")
    monkeypatch.setattr(ws.settings, "PLATFORM_DOMAIN", "twinstar.pro")
    assert ws.get_webhook_public_url() == "https://twinstar.pro/gemini/webhook"


def test_get_webhook_public_url_domain_fallback(monkeypatch):
    monkeypatch.setattr(ws.settings, "API_PUBLIC_URL", "")
    monkeypatch.setattr(ws.settings, "PLATFORM_DOMAIN", "twinstar.pro")
    monkeypatch.setattr(ws.settings, "WEBHOOK_PUBLIC_PATH", "/gemini/webhook")
    assert ws.get_webhook_public_url() == "https://twinstar.pro/gemini/webhook"
