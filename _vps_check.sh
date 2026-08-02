#!/bin/bash
# Check VPS system status via API endpoints
echo "=== Checking local API status ==="
curl -s --connect-timeout 5 http://localhost:8000/api/health 2>/dev/null || echo "Local API not running"
echo ""
echo "=== VPS Connection Info ==="
echo "SSH: root@187.77.130.144"
echo "Project: /home/panda/panda-quant-platform"
echo "Docker logs location: Inside containers"
