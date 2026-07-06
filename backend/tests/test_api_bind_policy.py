"""API bind policy: settlement gates, single exchange, rebind identity."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.models import ApiStatus, User
from app.services.api_bind_policy import (
    api_gate_blocked,
    bind_identity_changed,
    describe_bind_action,
    user_has_active_api,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _user(**kw) -> User:
    defaults = dict(
        uid="U100",
        email="u@test.local",
        password_hash="x",
        referral_code="GEMINI-U100",
        api_status=ApiStatus.NONE.value,
        exchange="binance",
    )
    defaults.update(kw)
    return User(**defaults)


@patch("app.services.api_bind_policy.referral_block_reason", return_value=None)
@patch("app.services.api_bind_policy.user_api_bind_blocked", return_value=(False, None))
def test_api_gate_open_when_clear(_bind, _ref, db):
    user = _user()
    db.add(user)
    db.commit()
    blocked, reason = api_gate_blocked(db, user.id)
    assert blocked is False
    assert reason is None


@patch("app.services.api_bind_policy.referral_block_reason", return_value="downline_credit_default")
@patch("app.services.api_bind_policy.user_api_bind_blocked", return_value=(False, None))
def test_api_gate_blocks_referrer_with_delinquent_downline(_bind, _ref, db):
    user = _user()
    db.add(user)
    db.commit()
    blocked, reason = api_gate_blocked(db, user.id)
    assert blocked is True
    assert reason == "downline_credit_default"


def test_bind_identity_unchanged_on_key_rotation_only():
    user = _user(
        api_status=ApiStatus.ACTIVE.value,
        api_key_enc="enc",
        exchange="binance",
        api_account_mode="master",
        exchange_uid="39210066",
    )
    assert user_has_active_api(user) is True
    assert bind_identity_changed(
        user,
        exchange="binance",
        account_mode="master",
        exchange_uid="39210066",
        master_exchange_uid="39210066",
    ) is False
    assert describe_bind_action(user, exchange="binance", account_mode="master") == "rebind"


def test_bind_identity_changed_on_exchange_switch():
    user = _user(
        api_status=ApiStatus.ACTIVE.value,
        api_key_enc="enc",
        exchange="binance",
        exchange_uid="111",
    )
    assert bind_identity_changed(
        user,
        exchange="okx",
        account_mode="master",
        exchange_uid="222",
        master_exchange_uid="222",
    ) is True
    assert describe_bind_action(user, exchange="okx", account_mode="master") == "exchange_switch"


def test_first_bind_always_new_identity():
    user = _user()
    assert bind_identity_changed(
        user,
        exchange="binance",
        account_mode="master",
        exchange_uid="111",
        master_exchange_uid="111",
    ) is True
    assert describe_bind_action(user, exchange="binance", account_mode="master") == "first_bind"
