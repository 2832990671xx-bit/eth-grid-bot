#!/usr/bin/env python3
"""急跌警报脚本 — 5分钟跑一次，监控24小时跌幅"""
import json, urllib.request, os, sys

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "eth_prices.json")

def fetch():
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd&include_24hr_change=true",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["ethereum"]
    except:
        return None

# 报警记录，防止重复报警
ALERT_FILE = os.path.join(os.path.dirname(__file__), ".last_crash_alert")

data = fetch()
if not data:
    print("NO_DATA")
    sys.exit(0)

price = data["usd"]
change_24h = data.get("usd_24h_change", 0)
print(f"ETH=${price:.2f} 24h={change_24h:+.2f}%")

if change_24h < -5:
    # 检查是否已经报过警
    try:
        with open(ALERT_FILE) as f:
            last = float(f.read().strip())
    except:
        last = 0
    
    # 15分钟内不重复报警
    import time
    now = time.time()
    if now - last > 900:
        with open(ALERT_FILE, "w") as f:
            f.write(str(now))
        print(f"🚨 CRASH_ALERT: ETH=${price:.2f}, 24h跌{change_24h:.1f}%")
        sys.exit(42)  # 用exit code通知cron
    else:
        print("已报警过，跳过")
elif change_24h < -3:
    print(f"跌幅{change_24h:.1f}%，未达5%阈值")
else:
    print(f"正常波动 {change_24h:+.1f}%")
