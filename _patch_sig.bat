@echo off
rem Write patch script to VPS using quoted heredoc
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "cat > /tmp/patch_sig.py << 'PATCHEOF'
import re
path = "/home/panda/panda-quant-platform/backend/app/core/position_supervisor.py"
with open(path) as f:
    c = f.read()
orig = c
# Find the _execute_signal method and patch its exception handling
# The pattern: "except Exception:" followed by "pass"
# Replace with: print full traceback
old = "except Exception:\n            pass"
new = "except Exception:\n            import traceback, sys\n            sys.stderr.write(traceback.format_exc())\n            sys.stderr.flush()"
if old not in c:
    print("Pattern not found!")
    print("Searching...")
    idx = c.find("except Exception:")
    if idx >= 0:
        print("Found at:", idx)
        print(c[idx:idx+50])
else:
    c = c.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(c)
    print("Patched OK")
PATCHEOF"
echo Patch script written

rem Run the patch
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "python3 /tmp/patch_sig.py"
echo Patch result: %ERRORLEVEL%

rem Copy patched file to container
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "docker cp /home/panda/panda-quant-platform/backend/app/core/position_supervisor.py panda-quant-platform-backend-1:/tmp/pos_sup.py"
echo Copy result: %ERRORLEVEL%

rem Verify the patch
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "grep -n 'sys.stderr.write' /home/panda/panda-quant-platform/backend/app/core/position_supervisor.py | head -3"
echo Verify result: %ERRORLEVEL%
