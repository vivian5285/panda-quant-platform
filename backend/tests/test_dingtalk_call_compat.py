"""DeepCoin _call_dingtalk must tolerate legacy / mismatched signatures."""

from unittest.mock import MagicMock

from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor


def test_call_dingtalk_strips_unexpected_kwargs():
    seen = {}

    def legacy_report(*, reason, verify_note=None):
        seen["reason"] = reason
        seen["verify_note"] = verify_note

    DeepcoinPositionSupervisor._call_dingtalk(
        legacy_report,
        reason="仓位归零",
        verify_note="ok",
        verified=True,
        swept_dust=False,
    )
    assert seen["reason"] == "仓位归零"
    assert seen["verify_note"] == "ok"


def test_call_dingtalk_positional_fallback():
    seen = {}

    def very_old(msg):
        seen["msg"] = msg

    DeepcoinPositionSupervisor._call_dingtalk(
        very_old,
        reason="仓位归零 (CLOSE_QUICK_EXIT)",
        verify_note="note",
        verified=True,
    )
    assert "CLOSE_QUICK_EXIT" in seen["msg"] or "仓位归零" in seen["msg"]


def test_dingtalk_bridge_maps_supervisor_close_to_close_type():
    sup = MagicMock()
    from app.core.position_supervisor_deepcoin import _DingtalkBridge

    bridge = _DingtalkBridge(sup)
    bridge.report_supervisor_close(
        reason="仓位归零",
        verify_note="盘口无持仓",
        verified=True,
        swept_dust=False,
    )
    assert sup._alert.called
    severity, alert_type, title, message, detail = sup._alert.call_args[0]
    assert alert_type == "CLOSE"
    assert severity == "info"
