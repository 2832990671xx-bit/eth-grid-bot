#!/usr/bin/env python3
"""
ETH/USDT 网格模拟盘 - GitHub Actions 版
区间: $1,800 ~ $2,200 | 25层等间距
价格穿线即触发，自动切换买卖方向
"""
import json, os, sys
from datetime import datetime

# ── 参数 ──────────────────────────────────────────
INITIAL_USDT = 200.0
INITIAL_ETH  = 0.1
GRID_MIN     = 1800.0
GRID_MAX     = 2200.0
GRID_COUNT   = 25
FEE_RATE     = 0.001

# 脚本所在目录（相对于仓库根目录）
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BOT_DIR, 'paper_state.json')


# ── 网格核心 ──────────────────────────────────────
def calc_prices():
    step = (GRID_MAX - GRID_MIN) / (GRID_COUNT - 1)
    return [round(GRID_MIN + i * step, 2) for i in range(GRID_COUNT)]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    now = datetime.now().isoformat()
    return {
        'usdt': INITIAL_USDT, 'eth': INITIAL_ETH,
        'trades': [], 'grid_orders': {},
        'last_price': None, 'start_time': now, 'total_fees': 0,
    }


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def get_price():
    """GitHub Actions 服务器在海外，可以直接用 ccxt"""
    import ccxt
    ex = ccxt.okx({'enableRateLimit': True})
    ticker = ex.fetch_ticker('ETH/USDT')
    return ticker['last']


def setup_grid(state, price, grid_prices):
    orders = {}
    for gp in grid_prices:
        if gp < price:
            orders[str(gp)] = 'buy'
        elif gp > price:
            orders[str(gp)] = 'sell'
    state['grid_orders'] = orders
    state['last_price'] = price
    state['grid_min'] = GRID_MIN
    state['grid_max'] = GRID_MAX
    save_state(state)
    buys = [p for p in grid_prices if p < price]
    sells = [p for p in grid_prices if p > price]
    return buys, sells


def check_grid(state, price, grid_prices):
    triggered = []
    orders = {float(k): v for k, v in state['grid_orders'].items()}
    last = state.get('last_price', price)
    up = price > last

    for gp in grid_prices:
        cur = orders.get(gp)

        # 价格上涨 → 穿越 buy 级别 → 买入
        if up and last < gp <= price and cur == 'buy':
            amt = max(state['usdt'] * 0.033 / gp, 0)
            if amt > 0.001 and state['usdt'] > 5:
                cost = amt * gp
                fee = cost * FEE_RATE
                state['eth'] += amt - amt * FEE_RATE
                state['usdt'] -= cost
                state['total_fees'] += fee
                t = {
                    'time': datetime.now().isoformat(), 'type': 'BUY',
                    'price': gp, 'amount': round(amt, 6),
                    'usdt': round(state['usdt'], 2),
                    'eth': round(state['eth'], 6),
                }
                state['trades'].append(t)
                triggered.append(t)
                orders[gp] = 'sell'

        # 价格下跌 → 穿越 sell 级别 → 卖出
        elif not up and price <= gp < last and cur == 'sell':
            amt = max(state['eth'] * 0.033, 0)
            if amt > 0.001 and state['eth'] > 0.002:
                rev = amt * gp
                fee = rev * FEE_RATE
                state['usdt'] += rev - fee
                state['eth'] -= amt
                state['total_fees'] += fee
                t = {
                    'time': datetime.now().isoformat(), 'type': 'SELL',
                    'price': gp, 'amount': round(amt, 6),
                    'usdt': round(state['usdt'], 2),
                    'eth': round(state['eth'], 6),
                }
                state['trades'].append(t)
                triggered.append(t)
                orders[gp] = 'buy'

    state['grid_orders'] = {str(k): v for k, v in orders.items()}
    state['last_price'] = price
    save_state(state)
    return triggered


# ── 入口 ──────────────────────────────────────────
def main():
    state = load_state()
    grid_prices = calc_prices()
    price = get_price()

    # 首次运行或参数变更 → 初始化网格
    is_new = (not state.get('grid_orders')
              or state.get('grid_min') != GRID_MIN
              or state.get('grid_max') != GRID_MAX)

    if is_new:
        state['grid_orders'] = {}
        state['grid_min'] = GRID_MIN
        buys, sells = setup_grid(state, price, grid_prices)
        eq = state['usdt'] + state['eth'] * price
        print(f"GRID_START|{price:.2f}|{len(buys)}|{len(sells)}"
              f"|{state['usdt']:.2f}|{state['eth']:.6f}|{eq:.2f}")
    else:
        trig = check_grid(state, price, grid_prices)
        eq = state['usdt'] + state['eth'] * price
        info = f"GRID_RUN|{price:.2f}|{state['usdt']:.2f}|{state['eth']:.6f}|{eq:.2f}"
        if trig:
            trades_fmt = ';'.join(
                f"{t['type']}@{t['price']:.2f}x{t['amount']:.6f}" for t in trig
            )
            info += f"|TRADES:{trades_fmt}"
        print(info)

    return 0


if __name__ == '__main__':
    sys.exit(main())
