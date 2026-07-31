#!/bin/bash
# Read position_supervisor.py
content=$(docker exec panda-quant-platform-backend-1 cat /app/app/core/position_supervisor.py)

# Check if import already exists
if echo "$content" | grep -q "from app.core.market_engine import force_refresh"; then
    echo "Import already exists"
    exit 0
fi

# Add the import
new_content=$(echo "$content" | sed 's/from app.core.breathing_stop import load_breathing_coef, resolve_breathing_coef/from app.core.breathing_stop import load_breathing_coef, resolve_breathing_coef\nfrom app.core.market_engine import force_refresh/')

# Write to temp file
echo "$new_content" > /tmp/position_supervisor_fixed.py

# Copy to container
docker cp /tmp/position_supervisor_fixed.py panda-quant-platform-backend-1:/tmp/position_supervisor_fixed.py

# Backup and replace
docker exec panda-quant-platform-backend-1 cp /app/app/core/position_supervisor.py /app/app/core/position_supervisor.py.bak
docker exec panda-quant-platform-backend-1 cp /tmp/position_supervisor_fixed.py /app/app/core/position_supervisor.py

echo "File updated. Restarting container..."
docker restart panda-quant-platform-backend-1
echo "Done. Container restarted."
