"""Check last 24h VPS events for Gemini."""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=120):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# VPS time
o,e = run('date')
print('VPS TIME:', o.strip())

# All trading events last 24h
o,e = run(f'cd {PROJ} && docker compose logs --since "24 hours ago" backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
lines = safe.split('\n')
events = [l for l in lines if any(kw in l for kw in [
    'UserEvent', 'OPEN', 'CLOSE', 'TP', 'FILLED', 'DingTalk',
    'signal', 'XAU', 'ETH', 'position', 'Telegram', 'SHORT', 'LONG',
    'webhook', 'RADAR', 'ERROR', 'startup', 'dispatch',
    'SIGNAL_RECV', 'DISPATCH', 'reentry', 'market', 'limit',
    'DepositMonitor', 'GEMINI', 'v6', 'DingTalk'
])]
print(f'\n--- EVENTS LAST 24H (found {len(events)}) ---')
for e in events:
    print(e[:200])

client.close()
