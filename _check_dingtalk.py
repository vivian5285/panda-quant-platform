import sys
sys.path.insert(0, "/app")
from app.services.dingtalk_notify import _dingtalk_url
url = _dingtalk_url()
print(f"DingTalk URL: '{url}'")
print(f"Length: {len(url)}")
if not url:
    print("OK: DingTalk is DISABLED")
else:
    print("WARNING: DingTalk is still enabled!")
