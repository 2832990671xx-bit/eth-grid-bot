#!/home/nh/.openclaw/workspace/venv/bin/python
"""
ETH/USDT 网格模拟盘 v3 — WSL版
新增: 等比/等差间距、CSV历史日志、绩效指标
"""
import json, os, subprocess, csv, math
from datetime import datetime

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


class PaperGridBot:
    def __init__(self):
        self.state = self.load_state()
        self.grid_prices = self._calc_prices()

    def _calc_prices(self):
        if SPACING == "GEOMETRIC":
            ratio = (GRID_MAX / GRID_MIN) ** (1.0 / (GRID_COUNT - 1))
            return [round(GRID_MIN * (ratio ** i), 2) for i in range(GRID_COUNT)]
        else:
            step = (GRID_MAX - GRID_MIN) / (GRID_COUNT - 1)
            return [round(GRID_MIN + i * step, 2) for i in range(GRID_COUNT)]

    def load_state(self):
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

    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def get_price(self):
        """用 OKX 公共 REST API 获取价格（不需要 API key）"""
        try:
            result = subprocess.run(
                ['curl', '-s', 'https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT'],
                capture_output=True, text=True, timeout=15
            )
            data = json.loads(result.stdout)
            return float(data['data'][0]['last'])
        except Exception:
            # fallback: 也用 okx CLI
            result = subprocess.run(
                ['okx', 'market', 'ticker', 'ETH-USDT', '--json'],
                capture_output=True, text=True, timeout=30
            )
            data = json.loads(result.stdout)
            return float(data['data'][0]['last'])

    def setup_grid(self, price):
        orders = {}
        for gp in self.grid_prices:
            if gp < price: orders[str(gp)] = 'buy'
            elif gp > price: orders[str(gp)] = 'sell'
        self.state['grid_orders'] = orders
        self.state['last_price']  = price
        self.state['grid_min']    = GRID_MIN
        self.state['grid_max']    = GRID_MAX
        self.state['grid_count']  = GRID_COUNT
        self.save_state()
        return {
            'center': price,
            'buys': [p for p in self.grid_prices if p < price],
            'sells': [p for p in self.grid_prices if p > price],
        }

    def check_grid(self, price):
        triggered = []
        orders = {float(k): v for k, v in self.state['grid_orders'].items()}
        last = self.state.get('last_price', price)
        up = price > last
        for gp in self.grid_prices:
            cur = orders.get(gp)
            if up and last < gp <= price and cur == 'buy':
                amt = max(self.state['usdt'] * 0.033 / gp, 0)
                if amt > 0.001 and self.state['usdt'] > 5:
                    cost = amt * gp; fee = cost * FEE_RATE
                    self.state['eth'] += amt - amt * FEE_RATE
                    self.state['usdt'] -= cost
                    self.state['total_fees'] += fee
                    t = {'time': datetime.now().isoformat(), 'type': 'BUY',
                         'price': gp, 'amount': round(amt, 6),
                         'usdt': round(self.state['usdt'], 2),
                         'eth': round(self.state['eth'], 6)}
                    self.state['trades'].append(t); triggered.append(t)
                    orders[gp] = 'sell'
            elif not up and price <= gp < last and cur == 'sell':
                amt = max(self.state['eth'] * 0.033, 0)
                if amt > 0.001 and self.state['eth'] > 0.002:
                    rev = amt * gp; fee = rev * FEE_RATE
                    self.state['usdt'] += rev - fee
                    self.state['eth'] -= amt
                    self.state['total_fees'] += fee
                    t = {'time': datetime.now().isoformat(), 'type': 'SELL',
                         'price': gp, 'amount': round(amt, 6),
                         'usdt': round(self.state['usdt'], 2),
                         'eth': round(self.state['eth'], 6)}
                    self.state['trades'].append(t); triggered.append(t)
                    orders[gp] = 'buy'
        self.state['grid_orders'] = {str(k): v for k, v in orders.items()}
        self.state['last_price']  = price
        self.save_state()
        return triggered

    def log_to_csv(self, price, equity):
        now = datetime.now()
        fexists = os.path.exists(HIST_PATH)
        with open(HIST_PATH, 'a', newline='') as f:
            w = csv.writer(f)
            if not fexists:
                w.writerow(['timestamp','price','usdt','eth','equity','trades','fees','peak_equity'])
            w.writerow([
                now.isoformat(), round(price,2),
                round(self.state['usdt'],2), round(self.state['eth'],6),
                round(equity,2), len(self.state['trades']),
                round(self.state['total_fees'],4),
                round(self.state.get('peak_equity', equity),2),
            ])

    def calc_metrics(self, price, equity):
        init_v = self.state.get('initial_value', INITIAL_USDT + INITIAL_ETH * 2000)
        peak   = max(self.state.get('peak_equity', equity), equity)
        self.state['peak_equity'] = peak
        self.save_state()
        roi  = (equity - init_v) / init_v * 100
        dd   = (peak - equity) / peak * 100 if peak > 0 else 0
        trades = self.state['trades']; n = len(trades)
        avg_profit = 0
        if n >= 2:
            bt = sum(t['price']*t['amount'] for t in trades if t['type']=='BUY')
            st = sum(t['price']*t['amount'] for t in trades if t['type']=='SELL')
            avg_profit = (st - bt) / max(n,1)
        try:
            start = datetime.fromisoformat(self.state.get('start_time', datetime.now().isoformat()))
            days = max((datetime.now() - start).total_seconds() / 86400, 0.01)
        except:
            days = 1
        return {
            'equity': equity, 'initial': init_v,
            'roi': f"{roi:+.2f}%",
            'daily_roi': f"{((equity/init_v)**(1/days)-1)*100:.4f}%",
            'drawdown': f"{dd:.2f}%",
            'trades': n,
            'buys': sum(1 for t in trades if t['type']=='BUY'),
            'sells': sum(1 for t in trades if t['type']=='SELL'),
            'avg_profit': f"${avg_profit:+.2f}",
            'fees': f"${self.state['total_fees']:.4f}",
            'freq': f"{n/max(days,0.01):.1f}单/天",
            'days': f"{days:.1f}天",
        }


if __name__ == '__main__':
    bot = PaperGridBot()
    price = bot.get_price()
    is_new = (not bot.state.get('grid_orders')
              or bot.state.get('grid_min') != GRID_MIN
              or bot.state.get('grid_max') != GRID_MAX
              or bot.state.get('grid_count') != GRID_COUNT)

    if is_new:
        bot.state['grid_orders'] = {}
        bot.state['grid_min'] = GRID_MIN
        bot.state['grid_max'] = GRID_MAX
        bot.state['grid_count'] = GRID_COUNT
        if not bot.state.get('start_time'):
            bot.state['start_time'] = datetime.now().isoformat()
        grid = bot.setup_grid(price)
        eq   = bot.state['usdt'] + bot.state['eth'] * price
        m    = bot.calc_metrics(price, eq)
        line = "─" * 48
        print(line)
        print(f"  🤖 ETH网格 v3 · {SPACING}间距")
        print(f"  📈 ETH=${price:.2f}  |  权益=${m['equity']:.2f}")
        print(f"  💰 ROI={m['roi']}  |  日化={m['daily_roi']}")
        print(f"  📉 回撤={m['drawdown']}  |  💸 交易{m['trades']}单")
        print(f"  📊 每单均利{m['avg_profit']}  |  手续费{m['fees']}")
        print(line)
        print(f"  🆕 网格初始化: {len(grid['buys'])}层买 / {len(grid['sells'])}层卖")
        print(f"     区间 ${GRID_MIN}~${GRID_MAX} | {GRID_COUNT}层 | {SPACING}")
        print(line)
    else:
        trig = bot.check_grid(price)
        eq   = bot.state['usdt'] + bot.state['eth'] * price
        m    = bot.calc_metrics(price, eq)
        line = "─" * 48
        print(line)
        print(f"  🤖 ETH网格 v3 · {SPACING}间距")
        print(f"  📈 ETH=${price:.2f}  |  权益=${m['equity']:.2f}")
        print(f"  💰 ROI={m['roi']}  |  日化={m['daily_roi']}")
        print(f"  📉 回撤={m['drawdown']}  |  💸 交易{m['trades']}单")
        print(f"  📊 每单均利{m['avg_profit']}  |  手续费{m['fees']}")
        print(line)
        if trig:
            for t in trig:
                e = '🟢BUY' if t['type']=='BUY' else '🔴SELL'
                print(f"  {e} @ ${t['price']:.2f} × {t['amount']:.6f}")
            print(line)
        else:
            print(f"  💤 无新成交 | 频率{m['freq']} | 运行{m['days']}")
            print(line)

    bot.log_to_csv(price, eq)
