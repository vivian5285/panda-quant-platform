# Observation window log (Gemini Binance)

## Clock rule
Do **not** count minutes while Binance REST returns `-1003` / IP ban.
Official B1–B3 observe clock starts only after a clean stretch with **no new -1003**.

## Batch deploy (query-fail + attribution + related)
- VPS backend recreate: `2026-07-22T09:33:54Z`
- Health: `ok`
- Pre-clock check (`--since 20m`): **`-1003` count = 0**, no `banned until` lines

## OBSERVE_START
- **2026-07-22T09:40:00Z** (approx; 17:40 CST)
- Target B1 window: ≥30–60 min without nuclear TP rehang / duplicate TP thrash
- **No rebuild / hot-deploy during this window**

## Notes
- Safety-batch GitHub push is separate from later B1–B3 evidence push.
- If a new `-1003` appears, pause the clock until clean again; do not fold ban minutes into “normal observe”.
