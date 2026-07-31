import sys
with open('/app/app/core/adverse_radar_guard.py', 'r', encoding='utf-8') as f:
    content = f.read()
changed = False
if 'from app.core.market_engine import (' in content and 'force_refresh' in content:
    if 'ensure_fresh' in content:
        pass
    else:
        content = content.replace(
            'from app.core.market_engine import (\n    atr_mismatch_ratio,\n    ensure_fresh,',
            'from app.core.market_engine import (\n    atr_mismatch_ratio,'
        )
        changed = True
        print('Removed duplicate ensure_fresh import line')
old_block = 'force_refresh(client=client, exchange=ex, symbol=sym)\n            if force\n            else ensure_fresh(client=client, exchange=ex, symbol=sym)'
new_block = 'ensure_fresh(client=client, exchange=ex, symbol=sym)'
if old_block in content:
    content = content.replace(old_block, new_block)
    changed = True
    print('Replaced force_refresh conditional with ensure_fresh')
else:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'force_refresh' in line:
            print('Found line %d: %s' % (i, repr(line)))
if changed:
    with open('/app/app/core/adverse_radar_guard.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patched successfully')
else:
    print('No changes needed or pattern not found')
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'force_refresh' in line or ('market_engine' in line and 'import' in line):
            print('Line %d: %s' % (i, repr(line[:100])))
