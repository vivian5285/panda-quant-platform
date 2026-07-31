@echo off
cd /d C:\Users\Administrator\Desktop\panda-quant-platform
git add backend\app\core\adverse_radar_guard.py
git add backend\app\core\binance_smart_defense.py
git add backend\app\core\rest_throttle_valve.py
git add backend\app\core\rest_book_cache.py
git add backend\app\core\rest_symbol_pace.py
git add backend\app\core\position_supervisor.py
git add backend\scripts\check_system.py
git add _verify_fixes.py
git commit -m "fix: stop force_refresh death spiral under IP cool-down + pending-order merge"
git push origin HEAD
