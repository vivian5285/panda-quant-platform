import base64, subprocess
# Encode the Python webhook test script
code = b'''import urllib.request, json
d = json.dumps({"secret":"g3m1n1_tw1n5t4r_2025","action":"LONG","symbol":"XAUUSDT","price":2410.50,"atr":15.2,"stop_loss":2385.00,"tp1":2430.00,"tp2":2450.00,"tp3":2480.00,"regime":"strong","reason":"cursor_test","tv_tp1":2430.00,"tv_tp2":2450.00,"tv_tp3":2480.00,"tv_sl":2385.00}).encode("utf-8")
r = urllib.request.Request("https://twinstar.pro/gemini/webhook", data=d, headers={"Content-Type":"application/json"})
print(urllib.request.urlopen(r, timeout=20).read().decode())
'''
b64 = base64.b64encode(code).decode()
print(f"Encoded length: {len(b64)}")
# Write to a temp file
with open(r"C:\Users\Administrator\Desktop\panda-quant-platform\script_b64.txt", "w") as f:
    f.write(b64)
print("Written to script_b64.txt")
print("Base64 content:")
print(b64)
