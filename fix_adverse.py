import re
with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py", "r") as f:
    content = f.read()

# Fix 1: remove force_refresh from import list
content = re.sub(
    r'\n    force_refresh,\n',
    '\n',
    content,
    count=1
)

# Fix 2: replace the ternary block with single line
content = re.sub(
    r'\n        snap = \(\n            force_refresh\(client=client, exchange=ex, symbol=sym\)\n            if force\n            else ensure_fresh\(client=client, exchange=ex, symbol=sym\)\n        \)\n',
    '\n        snap = ensure_fresh(client=client, exchange=ex, symbol=sym)\n',
    content,
    count=1
)

with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py", "w") as f:
    f.write(content)

# Verify
with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py", "r") as f:
    c = f.read()
checks = {
    "force_refresh in import": "force_refresh," not in c.split("from app.core.market_engine import")[1].split(")")[0] if "from app.core.market_engine import" in c else False,
    "ternary replaced": "if force" not in c.split("snap = ")[1].split("\n")[0] if "snap = " in c else False,
}
for k, v in checks.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
