"""Check raw VPS docker logs - last 24h."""
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

# Docker container status
o,e = run(f'cd {PROJ} && docker compose ps -a 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('\n=== CONTAINERS ===')
print(safe)

# Recent raw logs - last 1h
o,e = run(f'cd {PROJ} && docker compose logs --tail=200 backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('\n=== RECENT RAW LOGS (tail 200) ===')
print(safe[:5000])

client.close()
