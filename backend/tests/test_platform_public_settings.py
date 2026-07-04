"""Tests for platform public settings (open exchanges, support Telegram)."""

import json

import pytest

from app.services.platform_public_settings import (
    get_platform_public_settings,
    is_exchange_enabled,
    update_platform_public_settings,
)


@pytest.fixture
def runtime_file(tmp_path, monkeypatch):
    path = tmp_path / "platform_runtime.json"
    monkeypatch.setattr("app.services.platform_runtime.RUNTIME_FILE", path)
    return path


def test_default_only_binance_enabled(runtime_file):
    cfg = get_platform_public_settings()
    assert cfg["enabled_exchanges"] == ["binance"]
    assert is_exchange_enabled("binance") is True
    assert is_exchange_enabled("okx") is False


def test_update_enabled_exchanges(runtime_file):
    updated = update_platform_public_settings(
        enabled_exchanges=["binance", "okx"],
        support_telegram="@support",
    )
    assert updated["enabled_exchanges"] == ["binance", "okx"]
    assert updated["support_telegram"] == "@support"
    saved = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert saved["platform_public"]["enabled_exchanges"] == ["binance", "okx"]


def test_cannot_disable_all_exchanges(runtime_file):
    runtime_file.write_text(
        json.dumps({"platform_public": {"enabled_exchanges": ["binance"]}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        update_platform_public_settings(enabled_exchanges=[])
