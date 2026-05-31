#!/usr/bin/env python3
"""
ETH/USDT 网格模拟盘 v3 — 学习自 jordantete/grid-trading-bot 等开源项目
=================================================================
新增功能:
  - 等比/等差间距可选 (GEOMETRIC / ARITHMETIC)
  - CSV历史日志 → 可导入Excel/Grafana看权益趋势
  - 绩效指标: ROI、日变化、最大回撤、平均每单利润、交易频次
  - 更详细的运行报告

区间: $1,800 ~ $2,200 | 25层 | FEE 0.1%
"""
import json, os, sys, csv, math
from datetime import datetime

# ── 参数 ──────────────────────────────────────────
INITIAL_USDT  = 200.0
INITIAL_ETH   = 0.1
GRID_MIN      = 1800.0
GRID_MAX      = 2200.0
GRID_COUNT    = 25
FEE_RATE      = 0.001
SPACING       = "ARITHMETIC"  # ARITHMETIC(等差) | GEOMETRIC(等比)
HISTORY_FILE  = "paper_history.csv"

BOT_DIR   = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BOT_DIR, 'paper_state.json')
HIST_PATH  = os.path.join(BOT_DIR, HISTORY_FILE)


# ── 1. 网格价格计算 (等差/等比) ─────────────────
def calc_prices():
    if SPACING == "GEOMETRIC":
        # 等比：低价区格距小，高价区格距大
        ratio = (GRID_MAX / GRID_MIN) ** (1.0 / (GRID_COUNT - 1))
        return [round(GRID_MIN * (ratio ** i), 2) for i in range(GRID_COUNT)]
    # 等差（默认）：等间距
    step = (GRID_MAX - GRID_MIN) / (GRID_COUNT - 1)
    return [round(GRID_MIN + i * step, 2) for i in range(GRID_COUNT)]


# ── 2. 状态持久化 ──────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    now = datetime.now().isoformat()
    return {
        'usdt': INITIAL_USDT, 'eth': INITIAL_ETH,
        'trades': [], 'grid_orders': {},
        'last_price': None, 'start_time': now,
        'total_fees': 0, 'peak_equity': INITIAL_USDT + INITIAL_ETH * 2000,
        'initial_value': INITIAL_USDT + INITIAL_ETH * 2000,
    }


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


# ── 3. 获取价格 ────────────────────────────────
def get_price():
    """获取 ETH/USDT 最新价 (无需API密钥)
    优先 ccxt (GitHub Actions海外服务器)，
    回退 HTTP GET OKX 公共API (WSL2国内环境)"""
    import subprocess
    try:
        import ccxt
        ex = ccxt.okx({'enableRateLimit': True})
        return ex.fetch_ticker('ETH/USDT')['last']
    except (ImportError, Exception):
        # 用 curl 直连 OKX 公共 REST API（不需要 API key）
        result = subprocess.run(
            ['curl', '-s', 'https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            raise RuntimeError(f'curl failed: {result.stderr}')
        import json
        data = json.loads(result.stdout)
        return float(data['data'][0]['last'])


# ── 4. 网格初始化和检查 ─────────────────────────
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
    state['grid_count'] = GRID_COUNT
    save_state(state)
    buys  = [p for p in grid_prices if p < price]
    sells = [p for p in grid_prices if p > price]
    return buys, sells


def check_grid(state, price, grid_prices):
    triggered = []
    orders = {float(k): v for k, v in state['grid_orders'].items()}
    last = state.get('last_price', price)
    up = price > last

    for gp in grid_prices:
        cur = orders.get(gp)
        if up and last < gp <= price and cur == 'buy':
            amt = max(state['usdt'] * 0.033 / gp, 0)
            if amt > 0.001 and state['usdt'] > 5:
                cost  = amt * gp
                fee   = cost * FEE_RATE
                state['eth']  += amt - amt * FEE_RATE
                state['usdt'] -= cost
                state['total_fees'] += fee
                t = {'time': datetime.now().isoformat(), 'type': 'BUY',
                     'price': gp, 'amount': round(amt, 6),
                     'usdt': round(state['usdt'], 2),
                     'eth': round(state['eth'], 6)}
                state['trades'].append(t); triggered.append(t)
                orders[gp] = 'sell'
        elif not up and price <= gp < last and cur == 'sell':
            amt = max(state['eth'] * 0.033, 0)
            if amt > 0.001 and state['eth'] > 0.002:
                rev  = amt * gp
                fee  = rev * FEE_RATE
                state['usdt'] += rev - fee
                state['eth']  -= amt
                state['total_fees'] += fee
                t = {'time': datetime.now().isoformat(), 'type': 'SELL',
                     'price': gp, 'amount': round(amt, 6),
                     'usdt': round(state['usdt'], 2),
                     'eth': round(state['eth'], 6)}
                state['trades'].append(t); triggered.append(t)
                orders[gp] = 'buy'
    state['grid_orders'] = {str(k): v for k, v in orders.items()}
    state['last_price']  = price
    save_state(state)
    return triggered


# ── 5. CSV历史日志 ──────────────────────────────
def log_to_csv(state, price, equity):
    now = datetime.now()
    file_exists = os.path.exists(HIST_PATH)
    with open(HIST_PATH, 'a', newline='') as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(['timestamp', 'price', 'usdt', 'eth', 'equity',
                        'trades', 'fees', 'peak_equity'])
        w.writerow([
            now.isoformat(),
            round(price, 2),
            round(state['usdt'], 2),
            round(state['eth'], 6),
            round(equity, 2),
            len(state['trades']),
            round(state['total_fees'], 4),
            round(state.get('peak_equity', equity), 2),
        ])


# ── 6. 绩效指标 ──────────────────────────────────
def calc_metrics(state, price, equity):
    """计算并打印绩效指标"""
    initial = state.get('initial_value', INITIAL_USDT + INITIAL_ETH * 2000)
    peak    = max(state.get('peak_equity', equity), equity)
    state['peak_equity'] = peak
    save_state(state)

    roi       = (equity - initial) / initial * 100
    dd        = (peak - equity) / peak * 100  if peak > 0 else 0
    trades    = state['trades']
    n_trades  = len(trades)

    # 平均每单利润
    avg_profit = 0
    if n_trades >= 2:
        buy_total = sum(t['price'] * t['amount'] for t in trades if t['type'] == 'BUY')
        sell_total = sum(t['price'] * t['amount'] for t in trades if t['type'] == 'SELL')
        avg_profit = (sell_total - buy_total) / max(n_trades, 1)

    # 启动至今天数
    try:
        start = datetime.fromisoformat(state.get('start_time', datetime.now().isoformat()))
        days = max((datetime.now() - start).total_seconds() / 86400, 0.01)
    except:
        days = 1

    daily_roi = ((equity / initial) ** (1 / days) - 1) * 100 if days > 0 else 0
    trade_freq = n_trades / days

    return {
        'equity': equity,
        'initial': initial,
        'roi': roi,
        'roi_pct': f"{roi:+.2f}%",
        'daily_roi': daily_roi,
        'peak': peak,
        'drawdown': dd,
        'drawdown_pct': f"{dd:.2f}%",
        'trades': n_trades,
        'buys': sum(1 for t in trades if t['type'] == 'BUY'),
        'sells': sum(1 for t in trades if t['type'] == 'SELL'),
        'avg_profit': f"${avg_profit:+.2f}",
        'fees': state['total_fees'],
        'freq': f"{trade_freq:.1f} 单/天",
        'days': f"{days:.1f} 天",
    }


def print_report(m, price, spacing_name, trig):
    """打印完整的绩效报告"""
    line = "─" * 48
    print(line)
    print(f"  🤖 ETH网格 v3 · {spacing_name}间距")
    print(line)
    print(f"  📈 ETH=${price:.2f}  |  权益=${m['equity']:.2f}")
    print(f"  💰 ROI={m['roi_pct']}  |  日化={m['daily_roi']:.4f}%")
    print(f"  📉 回撤={m['drawdown_pct']}  |  峰值=${m['peak']:.2f}")
    print(f"  💸 交易{m['trades']}单 ({m['buys']}买/{m['sells']}卖)")
    print(f"  📊 每单均利{m['avg_profit']}  |  手续费=${m['fees']:.4f}")
    print(f"  ⏱️ 运行{m['days']}  |  频率{m['freq']}")
    print(line)
    if trig:
        for t in trig:
            e = '🟢BUY' if t['type'] == 'BUY' else '🔴SELL'
            print(f"  {e} @ ${t['price']:.2f} × {t['amount']:.6f}")
        print(line)


# ── 入口 ──────────────────────────────────────────
def main():
    state          = load_state()
    grid_prices    = calc_prices()
    price          = get_price()

    # 判断是否是首次运行或参数变更
    is_new = (not state.get('grid_orders')
              or state.get('grid_min') != GRID_MIN
              or state.get('grid_max') != GRID_MAX
              or state.get('grid_count') != GRID_COUNT)

    if is_new:
        state['grid_orders'] = {}
        state['grid_min'] = GRID_MIN
        state['grid_max'] = GRID_MAX
        state['grid_count'] = GRID_COUNT
        if not state.get('start_time'):
            state['start_time'] = datetime.now().isoformat()
        buys, sells = setup_grid(state, price, grid_prices)
        eq = state['usdt'] + state['eth'] * price
        m = calc_metrics(state, price, eq)
        print_report(m, price, SPACING, [])
        print(f"  🆕 网格初始化: {len(buys)}层买 / {len(sells)}层卖")
        print(f"     区间 ${GRID_MIN}~${GRID_MAX} | {GRID_COUNT}层 | {SPACING}")
        print(line := "─" * 48)
    else:
        trig = check_grid(state, price, grid_prices)
        eq   = state['usdt'] + state['eth'] * price
        m    = calc_metrics(state, price, eq)
        print_report(m, price, SPACING, trig)

        # 简要行（给 GitHub Actions log 解析用）
        brief = f"GRID|{price:.2f}|USDT={state['usdt']:.2f}|ETH={state['eth']:.6f}|EQ={eq:.2f}|ROI={m['roi_pct']}"
        if trig:
            tr = '|'.join(f"{t['type']}${t['price']:.2f}" for t in trig)
            brief += f"|TRADES:{tr}"
        print(brief)

    # 记录 CSV 历史
    log_to_csv(state, price, state['usdt'] + state['eth'] * price)
    return 0


if __name__ == '__main__':
    sys.exit(main())
