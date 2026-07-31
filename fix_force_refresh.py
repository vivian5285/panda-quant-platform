#!/usr/bin/env python3
"""Patch fix for force_refresh NameError."""
import re

def patch_market_engine():
    """Fix market_engine.py - ensure force_refresh is properly defined."""
    path = "/app/app/core/market_engine.py"
    with open(path, "r") as f:
        content = f.read()

    # The issue: force_refresh = ensure_fresh overrides the function
    # Fix: ensure force_refresh points to the actual function
    old = """def force_refresh(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    return refresh_indicators(
        client=client, exchange=exchange, symbol=symbol, force=True,
    )


# Backward-compatible alias — any code that still calls force_refresh()
# directly (not via the function) will gracefully fall through to ensure_fresh.
# This prevents NameError from circular import scenarios.
force_refresh = ensure_fresh"""

    new = """def force_refresh(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    return refresh_indicators(
        client=client, exchange=exchange, symbol=symbol, force=True,
    )


# Ensure force_refresh is always the function (not overwritten)
# This prevents NameError when code accesses force_refresh as a module-level name
if "force_refresh" not in dir():
    force_refresh = ensure_fresh"""

    if old in content:
        content = content.replace(old, new)
        with open(path, "w") as f:
            f.write(content)
        print(f"Patched {path}")
        return True
    else:
        print(f"Pattern not found in {path}")
        return False

if __name__ == "__main__":
    patch_market_engine()
