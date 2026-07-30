import requests
r = requests.post('http://localhost:6080/webhook', json={
    'symbol': 'ETHUSDT',
    'action': 'SHORT',
    'price': 1894.87,
    'stop_loss': 1912.63,
    'qty': 0.03
})
print(r.text)
