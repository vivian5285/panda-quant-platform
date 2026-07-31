import re
with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py") as f:
    lines = f.readlines()
# Find line with "snap = ensure_fresh" and remove following "if force" / "else ensure_fresh" lines
i = 0
new_lines = []
removed = 0
while i < len(lines):
    line = lines[i]
    if "snap = ensure_fresh(client=client, exchange=ex, symbol=sym)" in line and "if force" not in line and "else" not in line:
        new_lines.append(line)
        i += 1
        # Skip next line if it's "if force"
        if i < len(lines) and "if force" in lines[i]:
            i += 1
            removed += 1
        # Skip next line if it's "else ensure_fresh"
        if i < len(lines) and "else ensure_fresh" in lines[i]:
            i += 1
            removed += 1
        print("Removed %d lines at ternary block" % removed)
    else:
        new_lines.append(line)
        i += 1
with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py", "w") as f:
    f.writelines(new_lines)
print("Done, total lines removed: %d" % removed)
# Verify
with open("/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py") as f:
    content = f.read()
count = content.count("else ensure_fresh")
print("Remaining 'else ensure_fresh' occurrences: %d" % count)
