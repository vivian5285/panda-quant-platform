import sys
sys.path.insert(0, '/app')

from app.core.redis_cache import global_redis
import json

r = global_redis()
keys = r.scan_iter('supervisor:*')
print(f"Found {len(list(keys))} supervisor keys")
keys = r.scan_iter('supervisor:*')
for k in list(keys)[:20]:
    v = r.get(k)
    if v:
        d = json.loads(v)
        print(f"  {k}: symbol={d.get('symbol')} side={d.get('current_side')} qty={d.get('watched_qty')}")

# Also check position book
pkeys = r.scan_iter('position:*')
print(f"\nFound {len(list(pkeys))} position keys")
pkeys = r.scan_iter('position:*')
for k in list(pkeys)[:10]:
    v = r.get(k)
    if v:
        d = json.loads(v)
        print(f"  {k}: {d}")
