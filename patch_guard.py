import sys
# Read the file
with open('/app/app/core/adverse_radar_guard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if force_refresh import exists
if 'from app.core.market_engine import' in content and 'force_refresh' in content:
    # The import exists - add ensure_fresh if not already there
    if 'ensure_fresh' in content:
        print('ensure_fresh already imported')
    else:
        # Replace the import line to include ensure_fresh
        content = content.replace(
            'from app.core.market_engine import (\n    atr_mismatch_ratio,\n    ensure_fresh,',
            'from app.core.market_engine import (\n    atr_mismatch_ratio,'
        )
        print('ensure_fresh import check done')

    # Replace force_refresh calls with ensure_fresh
    old = 'force_refresh(client=client, exchange=ex, symbol=sym)\n            if force\n            else ensure_fresh(client=client, exchange=ex, symbol=sym)'
    new = 'ensure_fresh(client=client, exchange=ex, symbol=sym)'
    if old in content:
        content = content.replace(old, new)
        print('Replaced force_refresh conditional with ensure_fresh')
    else:
        print('Pattern not found, checking raw content...')
        # Try to find the line
        for i, line in enumerate(content.split('\n')):
            if 'force_refresh' in line:
                print(f'Line {i}: {repr(line)}')

    with open('/app/app/core/adverse_radar_guard.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('File patched successfully')
else:
    print('force_refresh not found in imports or file - checking...')
    print('First 50 lines:')
    for i, line in enumerate(content.split('\n')[:50]):
        if 'force_refresh' in line or 'market_engine' in line or 'ensure_fresh' in line:
            print(f'  Line {i}: {line}')
