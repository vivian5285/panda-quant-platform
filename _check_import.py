#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from app.core.market_engine import force_refresh
print(f"type: {type(force_refresh)}")
