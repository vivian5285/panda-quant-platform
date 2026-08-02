import sys
path = "backend/app/core/position_supervisor.py"
try:
    with open(path) as f:
        src = f.read()
except Exception as e:
    print(f"FILE READ ERROR: {e}")
    sys.exit(1)

try:
    import ast
    ast.parse(src)
    print("SYNTAX OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR line {e.lineno}: {e.msg}")
    lines = src.split('\n')
    for i in range(max(0, e.lineno-4), min(len(lines), e.lineno+2)):
        prefix = ">>>" if i == e.lineno-1 else "   "
        print(f"{prefix} {i+1:4d}: {lines[i]}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(2)
