#!/usr/bin/env python3
"""ETH价格监控脚本 — 获取当前价格并判断市场状态"""

import json
import urllib.request
import os
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "eth_prices.json")

def fetch_price():
    """从OKX和CoinGecko获取ETH价格"""
    prices = {}
    
    # OKX (现货)
    try:
        req = urllib.request.Request(
            "https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            prices["okx"] = float(data["data"][0]["last"])
            prices["okx_24h_change"] = float(data["data"][0].get("change24h", 0))
    except Exception as e:
        print(f"OKX失败: {e}")
    
    # CoinGecko
    try:
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd&include_24hr_change=true&include_7d_change=true",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            prices["coingecko"] = data["ethereum"]["usd"]
            prices["cg_24h_change"] = data["ethereum"].get("usd_24h_change", 0)
            prices["cg_7d_change"] = data["ethereum"].get("usd_7d_change", 0)
    except Exception as e:
        print(f"CoinGecko失败: {e}")
    
    return prices

def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"prices": [], "alerts_sent": []}

def save_history(history):
    # 只保留最近7天的数据
    history["prices"] = history["prices"][-336:]  # 7天 * 48次/天
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def analyze_trend(prices_7d):
    """判断市场趋势"""
    if len(prices_7d) < 10:
        return "insufficient_data"
    
    # 看最近几天的价格变化
    recent = prices_7d[-10:]  # 最近10个数据点
    prices_only = [p["price"] for p in recent]
    
    first = prices_only[0]
    last = prices_only[-1]
    change_pct = (last - first) / first * 100
    
    high = max(prices_only)
    low = min(prices_only)
    range_pct = (high - low) / low * 100
    
    # 判断
    if change_pct < -5:
        return "downtrend"
    elif change_pct > 5:
        return "uptrend"
    elif range_pct < 3:
        return "sideways_narrow"
    elif range_pct < 6:
        return "sideways_moderate"
    else:
        return "sideways_volatile"

def should_alert(history, prices):
    """判断是否需要发送警报"""
    now = datetime.now().isoformat()
    alerts = []
    price = prices.get("coingecko") or prices.get("okx", 0)
    
    # 1. 检查是否出现新低
    recent_prices = [p["price"] for p in history["prices"][-50:]]
    if recent_prices:
        current_min = min(recent_prices[-10:]) if len(recent_prices) >= 10 else min(recent_prices)
        # 如果是最近20个点内的新低
        if recent_prices and price <= min(recent_prices[-20:]):
            alerts.append(f"NEW_LOW: {price}")
    
    # 2. 检查跌幅
    cg_change = prices.get("cg_24h_change", 0)
    if cg_change < -3:
        alerts.append(f"DROP_3PCT_24H: {cg_change:.1f}%")
    if cg_change < -5:
        alerts.append(f"DROP_5PCT_24H: {cg_change:.1f}%")
    
    # 3. 检测横盘（适合开网格的信号）
    if len(recent_prices) >= 20:
        recent_20 = [p["price"] for p in history["prices"][-20:]]
        range_20 = (max(recent_20) - min(recent_20)) / min(recent_20) * 100
        change_20 = (recent_20[-1] - recent_20[0]) / recent_20[0] * 100
        # 波动<5%且涨跌幅<2% → 横盘
        if range_20 < 5 and abs(change_20) < 2:
            alerts.append(f"SIDEWAYS: range={range_20:.1f}%, change={change_20:.1f}%")
    
    return alerts

def main():
    prices = fetch_price()
    now = datetime.now()
    
    print(f"📊 ETH 监控 — {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   OKX: ${prices.get('okx', 'N/A')}")
    print(f"   CoinGecko: ${prices.get('coingecko', 'N/A')}")
    print(f"   24h变化: {prices.get('cg_24h_change', 0):+.2f}%")
    print(f"   7d变化: {prices.get('cg_7d_change', 0):+.2f}%")
    
    # 保存到历史
    history = load_history()
    entry = {
        "time": now.isoformat(),
        "price": prices.get("coingecko") or prices.get("okx", 0),
        "source_prices": prices
    }
    history["prices"].append(entry)
    
    # 趋势判断
    trend = analyze_trend(history["prices"])
    print(f"   趋势判断: {trend}")
    
    # 警报
    alerts = should_alert(history, prices)
    if alerts:
        print(f"   🚨 警报: {', '.join(alerts)}")
        for a in alerts:
            history.setdefault("alerts_sent", []).append({
                "time": now.isoformat(),
                "alert": a
            })
    
    save_history(history)
    
    # 输出JSON格式给cron用
    result = {
        "time": now.isoformat(),
        "price": entry["price"],
        "trend": trend,
        "alerts": alerts,
        "cg_24h": prices.get("cg_24h_change", 0),
        "cg_7d": prices.get("cg_7d_change", 0)
    }
    print(f"\nJSON_OUTPUT:{json.dumps(result)}")

if __name__ == "__main__":
    main()
