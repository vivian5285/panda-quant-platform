#!/bin/bash
cd /home/panda/panda-quant-platform
echo "=== git fetch ==="
git fetch origin
echo "=== git reset --hard origin/main ==="
git reset --hard origin/main
echo "=== git log -3 ==="
git log --oneline -3
echo "=== ALL DONE ==="
