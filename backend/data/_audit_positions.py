"""Audit all live positions on VPS for wrong-side stop losses."""

import subprocess
import os
import tempfile

PYTHON_CODE = r"""import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from app.database import SessionLocal
from app.models import User
from app.core.exchange_factory import create_exchange_client
from app.core.position_supervisor import PositionSupervisor
db = SessionLocal()
try:
    print('=== LIVE POSITIONS ===')
    for u in db.query(User).filter(User.is_active==True).all():
        c = create_exchange_client(u)
        try:
            pos = c.get_position(u.trading_symbol)
            if pos:
                amt = float(pos.get('positionAmt', 0) or 0)
                if amt != 0:
                    entry = float(pos.get('entryPrice', 0) or 0)
                    mark = float(pos.get('markPrice', 0) or 0)
                    side = 'LONG' if amt > 0 else 'SHORT'
                    print('uid=%s ex=%s sym=%s %s qty=%.4f entry=%.4f mark=%.4f' % (
                        u.uid, u.exchange, u.trading_symbol, side, abs(amt), entry, mark))
        except Exception as e:
            print('uid=%s pos_error: %s' % (u.uid, e))
    print('')
    print('=== SUPERVISOR STATE ===')
    for u in db.query(User).filter(User.is_active==True).all():
        try:
            sup = PositionSupervisor(u)
            side = getattr(sup, 'current_side', None)
            entry = float(getattr(sup, 'watched_entry', 0) or 0)
            frozen = float(getattr(sup, '_frozen_hard_stop_px', 0) or 0)
            tv_sl = float(getattr(sup, 'tv_sl', 0) or 0)
            tv_hard = float(getattr(sup, '_tv_hard_sl_price', 0) or 0)
            qty = float(getattr(sup, 'watched_qty', 0) or 0)
            warn = ''
            if side == 'LONG' and frozen > 0 and frozen > entry and entry > 0:
                warn = '!!! WRONG: LONG frozen_hard=%.2f > entry=%.2f !!!' % (frozen, entry)
            elif side == 'SHORT' and frozen > 0 and frozen < entry and entry > 0:
                warn = '!!! WRONG: SHORT frozen_hard=%.2f < entry=%.2f !!!' % (frozen, entry)
            print('uid=%s ex=%s %s entry=%.4f frozen=%.4f tv_sl=%.4f tv_hard=%.4f qty=%.4f %s' % (
                u.uid, u.exchange, side, entry, frozen, tv_sl, tv_hard, qty, warn))
        except Exception as e:
            print('uid=%s sup_error: %s' % (u.uid, e))
finally:
    db.close()
"""

temp_script = os.path.join(tempfile.gettempdir(), '_audit_inner.py')
with open(temp_script, 'w', encoding='utf-8') as f:
    f.write(PYTHON_CODE)

print('Using temp script:', temp_script)
print('Script contents:')
print(PYTHON_CODE[:200])

SCRIPT_CONTENT = r"""import paramiko
import os
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password=r"w'tFzgg2vPZ0D,Z;", timeout=30)
def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')
PROJ = '/home/panda/panda-quant-platform'
sftp = client.open_sftp()
sftp.put(r'SCRIPT_PATH', '/tmp/audit_pos.py')
sftp.close()
print('Uploaded to VPS')
o, e = run('cd ' + PROJ + ' && docker compose exec -T backend python3 /tmp/audit_pos.py 2>&1', timeout=120)
print(o)
if e:
    print('STDERR:', e[:500])
client.close()
print('DONE')
"""

outer = SCRIPT_CONTENT.replace('SCRIPT_PATH', temp_script)
with open(r"C:\Users\Administrator\AppData\Local\Temp\_audit_vps.py", "w", encoding="utf-8") as f:
    f.write(outer)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_audit_vps.py"],
    capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace'
)
print(result.stdout[:15000])
if result.stderr:
    print('ERR:', result.stderr[:300])
print('RC:', result.returncode)

try:
    os.unlink(temp_script)
except:
    pass
