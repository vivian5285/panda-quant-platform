import requests
url = 'http://127.0.0.1:6010/webhook'
payload = {
    'symbol': 'ETHUSDT.P',
    'action': 'LONG',
    'secret': '528586',
    'price': 3500.0,
    'qty': 1,
    'stop_loss': 3400.0,
    'tp1': 3600.0,
    'tp2': 3700.0,
    'tp3': 3800.0,
    'atr': 15.0,
    'bar_index': 1,
    'seq': 1
}
r = requests.post(url, json=payload)
print(r.text)
