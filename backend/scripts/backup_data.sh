#!/usr/bin/env bash
# GEMINI · 备份 SQLite/MySQL 数据目录与交易状态
# 用法: bash scripts/backup_data.sh [目标目录，默认 ./backups]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$DEST/gemini_backup_$STAMP"
mkdir -p "$OUT"

echo ">>> Backup to $OUT"

if [ -f "$ROOT/backend/data/panda.db" ]; then
  cp "$ROOT/backend/data/panda.db" "$OUT/panda.db"
  echo "  + panda.db"
fi

if [ -d "$ROOT/backend/data" ]; then
  tar -czf "$OUT/data_dir.tar.gz" -C "$ROOT/backend" data 2>/dev/null || true
  echo "  + data/"
fi

if [ -d "$ROOT/backend/state" ]; then
  tar -czf "$OUT/state_dir.tar.gz" -C "$ROOT/backend" state
  echo "  + state/"
fi

if [ -f "$ROOT/backend/data/platform_runtime.json" ]; then
  cp "$ROOT/backend/data/platform_runtime.json" "$OUT/platform_runtime.json"
fi

# 保留最近 14 份
find "$DEST" -maxdepth 1 -type d -name 'gemini_backup_*' | sort | head -n -14 | xargs -r rm -rf

echo ">>> Done: $OUT"
