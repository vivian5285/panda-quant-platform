"""One-off adapter: legacy deepcoin supervisor -> Gemini multi-user module."""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "app" / "core" / "position_supervisor_deepcoin.py"

HEADER = '''"""Deepcoin multi-user PositionSupervisor (Gemini P0)."""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from app.core.deepcoin_client import DeepcoinClient, CLIENT_VERSION
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

'''

BRIDGE = '''
class _DingtalkBridge:
    """Route legacy dingtalk.report_* calls to Gemini on_alert."""

    def __init__(self, supervisor: "DeepcoinPositionSupervisor"):
        self._sup = supervisor

    def __getattr__(self, name: str):
        def _call(*args, **kwargs):
            title = name.replace("report_", "").replace("_", " ").title()
            msg_parts = [str(a) for a in args if a is not None]
            message = " | ".join(msg_parts)[:500] if msg_parts else title
            severity = (
                "critical" if "fail" in name or "force" in name
                else "warning" if "alert" in name or "intervention" in name
                else "info"
            )
            detail = dict(kwargs) if kwargs else {}
            self._sup._alert(severity, name.upper(), title, message, detail)

        return _call

'''

LEGACY_LOG_SETUP = """if not os.path.exists('logs'):
    os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5 * 1024 * 1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Brain: %(message)s',
    handlers=[handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

"""

FOOTER = """
position_supervisor = DeepcoinPositionSupervisor()

# 仅在被 app / gunicorn 导入时执行一次闪电接管（避免 deploy 重复启动双进程）
if __name__ != "__main__":
    position_supervisor.recover_state_on_startup()
"""


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    idx = text.find("DEEPCOIN_SUPERVISOR_VERSION")
    if idx < 0:
        raise SystemExit("marker not found")
    text = HEADER + text[idx:]
    text = text.replace(LEGACY_LOG_SETUP, "")
    text = text.replace("import dingtalk\n", "")
    text = text.replace("from deepcoin_client import deepcoin_client, CLIENT_VERSION\n", "")
    text = text.replace("from logging.handlers import RotatingFileHandler\n", "")
    text = text.replace("class PositionSupervisor:", BRIDGE + "class DeepcoinPositionSupervisor:")
    text = text.replace("deepcoin_client", "self.client")
    text = text.replace(FOOTER, "")
    text = text.replace(
        "position_supervisor = PositionSupervisor()\n\n"
        "# 仅在被 app / gunicorn 导入时执行一次闪电接管（避免 deploy 重复启动双进程）\n"
        'if __name__ != "__main__":\n'
        "    position_supervisor.recover_state_on_startup()\n",
        "",
    )
    TARGET.write_text(text, encoding="utf-8")
    print(f"adapted {TARGET} ({len(text)} bytes)")


if __name__ == "__main__":
    main()
