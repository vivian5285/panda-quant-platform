#!/bin/bash
set -eu
cd /home/panda/panda-quant-platform
echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)==="
echo "===HEAD before==="
git log -1 --oneline
docker rm -f panda-quant-platform-backend-1 2>/dev/null || true
docker compose up -d --force-recreate backend
for i in $(seq 1 36); do
  if curl -sf -m 3 http://127.0.0.1:6010/health >/dev/null; then
    echo "healthy_try_$i"
    break
  fi
  sleep 5
done
curl -sS -m 5 http://127.0.0.1:6010/health; echo
echo "===HEAD after==="
git log -1 --oneline
git rev-parse HEAD
echo "===BREATH LOCK VERIFY==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.core.breathing_profile import (
    ETH_PROFILE,
    XAU_PROFILE,
    cold_start_multiplier,
    radar_arm_distance,
    stagnant_breath_samples,
    RATIO_FLOOR,
    RATIO_CEILING,
)
from app.core.breathing_stop import get_breathing_coefficient, compute_temp_tv_stop

eth_cold = cold_start_multiplier(ETH_PROFILE)
xau_cold = cold_start_multiplier(XAU_PROFILE)
print("ETH", ETH_PROFILE.coef_min, ETH_PROFILE.coef_max, eth_cold,
      ETH_PROFILE.step_advance_atr, ETH_PROFILE.chart_tf_min,
      ETH_PROFILE.stagnant_window_min, stagnant_breath_samples(ETH_PROFILE))
print("XAU", XAU_PROFILE.coef_min, XAU_PROFILE.coef_max, xau_cold,
      XAU_PROFILE.step_advance_atr, XAU_PROFILE.chart_tf_min,
      XAU_PROFILE.stagnant_window_min, stagnant_breath_samples(XAU_PROFILE))
print("RATIO", RATIO_FLOOR, RATIO_CEILING)
assert ETH_PROFILE.coef_min == 1.2 and ETH_PROFILE.coef_max == 2.5
assert XAU_PROFILE.coef_min == 0.5 and XAU_PROFILE.coef_max == 1.2
assert abs(eth_cold - 1.525) < 1e-9
assert abs(xau_cold - 0.675) < 1e-9
assert RATIO_FLOOR == 0.6 and RATIO_CEILING == 2.2
assert ETH_PROFILE.step_advance_atr == 0.4
assert ETH_PROFILE.early_breakeven_atr == 0.5
assert ETH_PROFILE.phase2_trigger_atr == 3.0
assert ETH_PROFILE.chart_tf_min == 90.0 and stagnant_breath_samples(ETH_PROFILE) == 18
assert XAU_PROFILE.step_advance_atr == 0.35
assert XAU_PROFILE.early_breakeven_atr == 0.3
assert XAU_PROFILE.phase2_trigger_atr == 3.0
assert XAU_PROFILE.chart_tf_min == 45.0 and stagnant_breath_samples(XAU_PROFILE) == 12
assert radar_arm_distance(10.0, 1.0, ETH_PROFILE) > 0
assert abs(compute_temp_tv_stop(1900, "LONG", 1880) - 1876.0) < 1e-9
assert abs(get_breathing_coefficient(1.0, "ETHUSDT") - 1.525) < 1e-9
assert abs(get_breathing_coefficient(1.0, "XAUUSDT") - 0.675) < 1e-9
print("LOCK_TABLE_OK")
PY
echo "===DONE==="
