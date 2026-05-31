#!/usr/bin/env python3
"""套利监控 — 对比多所ETH价格，发现价差机会"""
import json, urllib.request, os
from datetime import datetime

HISTORY_FILE = os.path.join(os.path.dirname(__file__), ".arb_history.json")
ARB_THRESHOLD = 0.3  # 价差超过0.3%才报

def fetch_json(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}

def main():
    now = datetime.now()
    prices = {}
    
    # 1. CoinGecko (一直好用)
    d = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd")
    if "ethereum" in d:
        prices["CoinGecko"] = d["ethereum"]["usd"]
    
    # 2. OKX (通了)
    d = fetch_json("https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT")
    if "data" in d and len(d["data"]) > 0:
        prices["OKX"] = float(d["data"][0]["last"])
    
    # 3. Kraken 
    d = fetch_json("https://api.kraken.com/0/public/Ticker?pair=ETHUSD")
    if "result" in d:
        key = list(d["result"].keys())[0]
        prices["Kraken"] = float(d["result"][key]["c"][0])
    
    # 4. CryptoCompare
    d = fetch_json("https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD")
    if "USD" in d:
        prices["CryptoCompare"] = d["USD"]
    
    print(f"🔄 套利监控 — {now.strftime('%Y-%m-%d %H:%M')}")
    
    if len(prices) >= 2:
        min_ex = min(prices, key=prices.get)
        max_ex = max(prices, key=prices.get)
        min_p = prices[min_ex]
        max_p = prices[max_ex]
        spread = (max_p - min_p) / min_p * 100
        
        print(f"   来源数: {len(prices)} | 价差: {spread:.2f}%")
        
        for ex, p in sorted(prices.items(), key=lambda x: x[1]):
            marker = " ⬅️最低" if ex == min_ex else (" ➡️最高" if ex == max_ex else "")
            print(f"     {ex:15s}: ${p:.2f}{marker}")
        
        if spread >= ARB_THRESHOLD:
            fee = 0.002  # 双边0.2%
            net_pct = (spread / 100) - fee * 2
            print(f"\n   🚨 套利机会! {min_ex}买 → {max_ex}卖")
            print(f"     毛利: {spread:.2f}% → 净利: {net_pct*100:.2f}%")
            if net_pct > 0:
                profit = max_p - min_p - min_p * fee * 2
                print(f"     1ETH可赚: ${profit:.2f}")
                print(f"     ALERT: true")
        else:
            print(f"\n   ✅ 价差{spread:.2f}%，未达套利阈值")
    else:
        print(f"   ❌ 仅有{len(prices)}个来源，无法比价")
        for ex, p in prices.items():
            print(f"     {ex}: ${p:.2f}")
    
    alert = spread >= ARB_THRESHOLD if len(prices) >= 2 else False
    history = {
        "time": now.isoformat(),
        "prices": prices,
        "spread_pct": round(spread, 2) if len(prices) >= 2 else 0,
        "alert": alert
    }
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)
    
    print(f"\nJSON_OUTPUT:{json.dumps(history)}")

if __name__ == "__main__":
    main()
