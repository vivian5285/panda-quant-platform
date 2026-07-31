import requests
r=requests.post("http://localhost:6010/webhook",json={"secret":"528586","action":"LONG","symbol":"ETHUSDT","price":3450,"atr":45.5,"stop_loss":3395,"tp1":3480,"tp2":3520,"tp3":3580,"bot_id":"test_fix","regime":"strong","bar_index":99994,"seq":1,"side":"long"},timeout=30)
print(f"Status: {r.status_code}")
