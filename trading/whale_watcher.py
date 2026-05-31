#!/usr/bin/env python3
"""🐋 链上聪明钱追踪器 v2 — 并行RPC + 通知推送"""

import json, urllib.request, os, sys, concurrent.futures
from datetime import datetime
from threading import Lock

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(DIR, "whale_config.json")
STATE  = os.path.join(DIR, ".whale_state.json")

lock = Lock()

# ─── 加载配置 ────────────────────────────────
def load_config():
    with open(CONFIG) as f: return json.load(f)

def load_state():
    try:
        with open(STATE) as f: s = json.load(f)
        if "wallets" not in s: raise ValueError
        return s
    except:
        return {"wallets": {}, "last_run": "", "first_run": True}

def save_state(s):
    with open(STATE, "w") as f: json.dump(s, f, indent=2)

# ─── RPC ─────────────────────────────────────
def rpc_call(url, method, params=[], timeout=8):
    data = json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type":"application/json","User-Agent":"Mozilla/5.0"
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def get_balance(url, addr):
    try:
        result = rpc_call(url, "eth_getBalance", [addr, "latest"])["result"]
        return addr, int(result, 16) / 1e18, None
    except Exception as e:
        return addr, 0, str(e)

def get_nonce(url, addr):
    try:
        result = rpc_call(url, "eth_getTransactionCount", [addr, "latest"])["result"]
        return addr, int(result, 16), None
    except Exception as e:
        return addr, 0, str(e)

# ─── 主逻辑 ──────────────────────────────────
def main():
    cfg = load_config()
    state = load_state()
    now = datetime.now()
    alerts = []
    url = cfg["rpc_url"]
    wallets = cfg["watch_addresses"]
    addrs = [w["address"] for w in wallets]
    names = {w["address"].lower(): w["name"] for w in wallets}

    print(f"🐋 链上监控 — {now.strftime('%Y-%m-%d %H:%M')}")
    print("━" * 48)

    # 并行获取余额和nonce
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        bal_futures = {ex.submit(get_balance, url, a): a for a in addrs}
        nonce_futures = {ex.submit(get_nonce, url, a): a for a in addrs}
        
        balances = {}
        nonces = {}
        errors = {}
        
        for f in concurrent.futures.as_completed(bal_futures):
            addr, bal, err = f.result()
            if err:
                errors[addr] = err
            else:
                balances[addr] = bal
        
        for f in concurrent.futures.as_completed(nonce_futures):
            addr, nonce, err = f.result()
            if err:
                errors[addr] = err
            else:
                nonces[addr] = nonce

    first_run = state.get("first_run", True)

    # 逐个输出
    for w in wallets:
        addr = w["address"]
        name = w["name"]
        key = addr.lower()
        
        bal = balances.get(addr, 0)
        nonce = nonces.get(addr, 0)
        error = errors.get(addr)
        
        if error:
            print(f"  ❌ {name:18s} {fmt_addr(addr)} {error[:40]}")
            continue
        
        prev = state["wallets"].get(key, {})
        prev_bal = prev.get("bal", bal)
        prev_nonce = prev.get("nonce", nonce)
        
        bal_delta = bal - prev_bal
        has_new_tx = nonce > prev_nonce
        
        # 输出
        icon = "🟢" if bal > 100 else "⚪" if bal > 1 else "⚫"
        delta_s = ""
        if abs(bal_delta) >= 1 and not first_run:
            arrow = "📈" if bal_delta > 0 else "📉"
            delta_s = f" {arrow}{bal_delta:+.1f}"
        tx_s = " 📨新交易" if (has_new_tx and not first_run) else ""
        
        print(f"  {icon} {name:18s} {bal:>12.4f} ETH{delta_s}{tx_s}")
        
        # 第一次运行不报警
        if not first_run:
            if abs(bal_delta) >= cfg.get("eth_threshold", 50):
                alerts.append({
                    "name": name, "address": addr,
                    "type": "BALANCE_CHANGE",
                    "delta": round(bal_delta, 2),
                    "balance": round(bal, 2),
                    "direction": "OUT" if bal_delta < 0 else "IN",
                    "time": now.isoformat(),
                })
            if has_new_tx:
                alerts.append({
                    "name": name, "address": addr,
                    "type": "NEW_TX",
                    "nonce": nonce,
                    "time": now.isoformat(),
                })
        
        # 更新状态
        with lock:
            state["wallets"][key] = {"bal": round(bal, 4), "nonce": nonce}

    state["last_run"] = now.isoformat()
    state["first_run"] = False
    save_state(state)

    # 摘要
    print("━" * 48)
    print(f"  ✓ {len(wallets)} 个地址")
    
    if alerts:
        print(f"\n  🚨 {len(alerts)} 条警报:")
        for a in alerts[:8]:
            if a["type"] == "BALANCE_CHANGE":
                print(f"    {'📈' if a['direction']=='IN' else '📉'} {a['name']}: {a['delta']:+.0f} ETH")
            else:
                print(f"    📨 {a['name']}: 新交易")
    else:
        print("  ✅ 无异常" if not first_run else "  ℹ️ 首次运行，已记录基线")

    result = {
        "time": now.isoformat(),
        "alerts": alerts,
        "alert_count": len(alerts),
        "first_run": first_run
    }
    print(f"\nJSON_OUTPUT:{json.dumps(result, ensure_ascii=False)}")
    return result

def fmt_addr(addr):
    return f"{addr[:6]}...{addr[-4:]}"

if __name__ == "__main__":
    main()
