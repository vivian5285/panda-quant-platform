# Observation window log (Gemini Binance)

## Clock rule
Do **not** count minutes while Binance REST returns `-1003` / IP ban.
Official observe clock starts only after a clean stretch with **no new -1003**.
**No rebuild / hot-deploy during this window.**

## Deploy `77d171b` (production-grade final)
- GitHub: `77d171b` — Root-fix DingTalk leverage + unregistered-position adopt
- VPS pull + backend recreate: **2026-07-22T10:20Z** (approx; after health ok)
- Health: `{"status":"ok"}`
- Verify: `FIXED_LEVERAGE=5`, theme leverage=5, `exchange_leverage=5`
- Pre-clock check (`--since 10m`): **`-1003` count = 0**

## OBSERVE_START
- **2026-07-22T10:22:00Z** (approx; 18:22 CST)
- Target: 30–60 min clean (pause clock on any new `-1003`)
- Watch for: TP duplicate thrash, wrong DingTalk leverage, bare external position without breath SL, attribution false positives

## Deliverables linked
- Deleted-list: `docs/LEGACY_PURGE_LIST_20260722.md`
- Commit: `77d171b0991bf58808decd4ea25486e91981f002`

## Prior window (superseded for this batch)
- Earlier OBSERVE_START `2026-07-22T09:40:00Z` was for safety-batch `78ad0d8`; clock resets after this rebuild.
