"""Comprehensive fix: replace all force_refresh imports with ensure_fresh"""
import re
import os
import sys

root = "/home/panda/panda-quant-platform/backend/app"

changes = 0
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git', 'node_modules', '.pytest_cache')]
    for fn in filenames:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(dirpath, fn)
        rel = os.path.relpath(fp, root)
        with open(fp) as f:
            content = f.read()
        orig = content

        # Replace "from app.core.market_engine import ... force_refresh ..." with ensure_fresh
        content = re.sub(
            r'\bfrom\s+app\.core\.market_engine\s+import\s+([^)]*?)force_refresh([^)]*?)\b',
            lambda m: 'from app.core.market_engine import ' + m.group(1).rstrip(',') + 'ensure_fresh' + m.group(2),
            content
        )
        # Also handle single import
        content = re.sub(
            r'\bfrom\s+app\.core\.market_engine\s+import\s+force_refresh\b',
            'from app.core.market_engine import ensure_fresh',
            content
        )

        if content != orig:
            with open(fp, 'w') as f:
                f.write(content)
            changes += 1
            print(f"PATCHED: {rel}")

print(f"Total files changed: {changes}")
