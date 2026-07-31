import sys, json
sys.path.insert(0, '/app')
from app.services.webhook_payload import parse_webhook_payload
from app.services.webhook_guard import validate_signal_payload
from app.services.signal_admin import run_signal_dispatch
from app.database import SessionLocal

xau={"symbol":"XAUUSDT.P","action":"LONG","price":2381.19,"stop_loss":2358.33,"tp1":2405.61,"tp2":2429.14,"tp3":2453.56,"atr":15.0,"secret":"528586","bot_id":"Trillion_God_v7.2_VPSFinal","regime":"moderate","bar_index":1,"seq":1}
eth={"symbol":"ETHUSDT.P","action":"LONG","price":3500.0,"stop_loss":3400.0,"tp1":3600.0,"tp2":3700.0,"tp3":3800.0,"atr":15.0,"secret":"528586","bot_id":"Trillion_God_v7.2_VPSFinal","regime":"moderate","bar_index":3,"seq":3}

db=SessionLocal()
for name,payload in [("XAUUSDT LONG",xau),("ETHUSDT LONG",eth)]:
    print("="*50)
    print("内测:",name)
    data,err=parse_webhook_payload(json.dumps(payload))
    if err:
        print("  解析失败:",err)
        continue
    ok,verr=validate_signal_payload(data)
    if not ok:
        print("  验证失败:",verr)
        continue
    print("  验证通过,执行分发...")
    row,result=run_signal_dispatch(db,data,source="webhook")
    print("  分发: ok=%d errors=%d"%(row.dispatched_count,row.error_count))
    for r in result.get("results",[]):
        print("    uid=%s status=%s reason=%s"%(r.get("user_id"),r.get("status"),r.get("reason","")))
db.close()
