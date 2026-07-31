import sys
with open('/app/app/core/adverse_radar_guard.py', 'r', encoding='utf-8') as f:
    content = f.read()

changed = False

# Fix the call on line 510: replace the conditional with ensure_fresh
# Pattern: "force_refresh(client=client, exchange=ex, symbol=sym)"  followed by conditional
old_pattern = 'force_refresh(client=client, exchange=ex, symbol=sym)\n            if force\n            else ensure_fresh(client=client, exchange=ex, symbol=sym)'
new_pattern = 'ensure_fresh(client=client, exchange=ex, symbol=sym)'

if old_pattern in content:
    content = content.replace(old_pattern, new_pattern)
    changed = True
    print('Replaced force_refresh conditional at line ~510')
else:
    # Try line-by-line
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'force_refresh(client=client' in line:
            print('Found call at line %d: %s' % (i, repr(line)))
            # Check if it's the conditional block
            if i+1 < len(lines) and 'if force' in lines[i+1]:
                if i+2 < len(lines) and 'else ensure_fresh' in lines[i+2]:
                    # Replace all 3 lines
                    lines[i] = new_pattern
                    lines[i+1] = ''
                    lines[i+2] = ''
                    content = '\n'.join(lines)
                    changed = True
                    print('Replaced 3-line conditional block at line %d' % i)
                    break

# Remove force_refresh from import (keep it in import for backward compat, just don't use it)
# Actually, let's keep the import - removing it might cause other issues

if changed:
    with open('/app/app/core/adverse_radar_guard.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('File patched successfully')
else:
    print('ERROR: Could not find pattern to replace')
    sys.exit(1)
