"""Tests for encrypted webhook secret settings."""
from __future__ import annotations

import pytest

from app.services import webhook_secrets as ws


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
    monkeypatch.setattr(ws.settings, "WEBHOOK_SECRET", "528586")
    assert ws.get_webhook_secret() == "528586"


def test_update_webhook_settings_persists_short_secret(monkeypatch):
    monkeypatch.setattr(ws.settings, "WEBHOOK_SECRET", "")
    out = ws.update_webhook_settings(secret="1")
    assert out["configured"] is True
    assert out["production_ready"] is True
    assert out["source"] == "runtime"
    assert ws.get_webhook_secret() == "1"


def test_update_rejects_empty_secret():
    with pytest.raises(ValueError, match="不能为空"):
        ws.update_webhook_settings(secret="   ")


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
