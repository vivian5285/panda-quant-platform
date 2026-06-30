#!/usr/bin/env bash
# GEMINI · 备份 SQLite/MySQL 数据目录与交易状态
# 用法（在 backend/ 目录）: bash scripts/backup_data.sh [目标目录，默认 ./backups]
# 或从项目根: bash backend/scripts/backup_data.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$DEST/gemini_backup_$STAMP"
mkdir -p "$OUT"

echo ">>> Backup to $OUT"

if [ -f "$ROOT/data/panda.db" ]; then
  cp "$ROOT/data/panda.db" "$OUT/panda.db"
  echo "  + panda.db"
fi

if [ -d "$ROOT/data" ]; then
  tar -czf "$OUT/data_dir.tar.gz" -C "$ROOT" data 2>/dev/null || true
  echo "  + data/"
fi

if [ -d "$ROOT/state" ]; then
  tar -czf "$OUT/state_dir.tar.gz" -C "$ROOT" state
  echo "  + state/"
fi

if [ -f "$ROOT/data/platform_runtime.json" ]; then
  cp "$ROOT/data/platform_runtime.json" "$OUT/platform_runtime.json"
  echo "  + platform_runtime.json (encrypted runtime keys)"
fi

find "$DEST" -maxdepth 1 -type d -name 'gemini_backup_*' 2>/dev/null | sort | head -n -14 | xargs -r rm -rf 2>/dev/null || true

echo ">>> Done: $OUT"
