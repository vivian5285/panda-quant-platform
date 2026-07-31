import requests
import json

payload = {
    'secret': '528586',
    'action': 'LONG',
    'symbol': 'ETHUSDT',
    'price': 3450.0,
    'atr': 45.5,
    'stop_loss': 3395.0,
    'tp1': 3480.0,
    'tp2': 3520.0,
    'tp3': 3580.0,
    'bot_id': 'u6_test',
    'regime': 'strong',
    'bar_time': '2026-07-30T12:00:00Z',
    'bar_index': 99997,
    'seq': 1,
    'side': 'long',
    'entry_type': 'standard',
    'risk_pct': 3,
    'qty_ratio': 1
}

print('Testing TradingView webhook with payload:')
print(json.dumps(payload, indent=2))
print()

r = requests.post('http://localhost:6010/webhook', json=payload, timeout=30)
print(f'Status: {r.status_code}')
print(f'Response: {r.text}')
