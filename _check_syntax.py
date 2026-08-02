import ast
import sys

path = "c:/Users/Administrator/Desktop/panda-quant-platform/backend/app/core/position_supervisor.py"
try:
    with open(path) as f:
        source = f.read()
    ast.parse(source)
    print("OK - no syntax errors")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    lines = source.split('\n')
    start = max(0, e.lineno - 5)
    end = min(len(lines), e.lineno + 3)
    for i in range(start, end):
        marker = ">>> " if i == e.lineno - 1 else "    "
        print(f"{marker}{i+1}: {lines[i]}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(2)
