"""Get full trading timeline from VPS - today only."""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=120):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')

PROJ = '/home/panda/panda-quant-platform'

o,e = run('date')
print('VPS TIME:', o.strip())

# Get events since midnight UTC today
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-29T00:00:00" backend 2>&1 | grep -E "UserEvent|OPEN|CLOSE|TP|FILLED|DingTalk|signal|XAU|ETH|position|webhook|RADAR|ERROR|SIGNAL_RECV|DISPATCH|reentry|market|LIMIT|pending|limit|Telegram|SHORT|LONG|DepositMonitor|GEMINI|v6\\." | tail -n 100')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('\n=== TODAY TRADING EVENTS ===')
print(safe if safe.strip() else 'No trading events found')

# Also get health summary
o,e = run('curl -s http://localhost:8000/api/health')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('\n=== HEALTH ===')
print(safe.strip())

client.close()
