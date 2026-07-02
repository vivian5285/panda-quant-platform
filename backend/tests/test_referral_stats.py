"""Referral stats helpers."""

from app.services.referral_stats import expected_referrer_reward


def test_expected_referrer_reward_l1():
    assert expected_referrer_reward(1000, 1) == 100.0


def test_expected_referrer_reward_l2():
    assert expected_referrer_reward(1000, 2) == 50.0


def test_expected_referrer_reward_no_profit():
    assert expected_referrer_reward(0, 1) == 0.0
    assert expected_referrer_reward(-100, 1) == 0.0
