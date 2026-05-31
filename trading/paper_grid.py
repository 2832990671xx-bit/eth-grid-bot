#!/home/nh/.openclaw/workspace/venv/bin/python
"""
ETH/USDT 网格模拟盘 (Paper Trading) - 优化版 v2
- 区间: $1,800 ~ $2,200 (贴近当前价格)
- 30格等间距
- 价格穿线即触发，自动切换买卖方向
"""

import json
import os
import subprocess
from datetime import datetime

SYMBOL = 'ETH/USDT'
INITIAL_USDT = 200
INITIAL_ETH = 0.1
GRID_MIN = 1800
GRID_MAX = 2200
GRID_COUNT = 25
FEE_RATE = 0.001
STATE_FILE = os.path.join(os.path.dirname(__file__), 'paper_state.json')


class PaperGridBot:
    def __init__(self):
        self.state = self.load_state()
        self.grid_prices = self._calc_prices()

    def _calc_prices(self):
        step = (GRID_MAX - GRID_MIN) / (GRID_COUNT - 1)
        return [round(GRID_MIN + i * step, 2) for i in range(GRID_COUNT)]

    def load_state(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                return json.load(f)
        return {
            'usdt': INITIAL_USDT, 'eth': INITIAL_ETH,
            'trades': [], 'grid_orders': {},
            'last_price': None, 'start_time': datetime.now().isoformat(),
            'total_fees': 0,
        }

    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def get_price(self):
        """用 okx CLI 获取价格，避免 ccxt 直连被墙"""
        result = subprocess.run(
            ['okx', '--profile', 'okx-prod', 'market', 'ticker', 'ETH-USDT', '--json'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(f'okx CLI failed: {result.stderr}')
        data = json.loads(result.stdout)
        # okx CLI --json returns the raw API response
        if isinstance(data, dict) and 'data' in data:
            return float(data['data'][0]['last'])
        # fallback: try parsing table output
        result2 = subprocess.run(
            ['okx', '--profile', 'okx-prod', 'market', 'ticker', 'ETH-USDT'],
            capture_output=True, text=True, timeout=30
        )
        for line in result2.stdout.strip().split('\n'):
            if 'last' in line.lower():
                parts = line.split()
                for p in parts:
                    try:
                        return float(p)
                    except ValueError:
                        continue
        raise RuntimeError('Cannot parse price from okx CLI')

    def setup_grid(self, price):
        orders = {}
        for gp in self.grid_prices:
            if gp < price: orders[str(gp)] = 'buy'
            elif gp > price: orders[str(gp)] = 'sell'
        self.state['grid_orders'] = orders
        self.state['last_price'] = price
        self.state['grid_min'] = GRID_MIN
        self.state['grid_max'] = GRID_MAX
        self.save_state()
        prices = sorted(float(k) for k in orders)
        return {
            'center': price,
            'buys': [p for p in prices if p < price],
            'sells': [p for p in prices if p > price],
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
                    t = {'time': datetime.now().isoformat(), 'type': 'BUY', 'price': gp,
                         'amount': round(amt, 6), 'usdt': round(self.state['usdt'], 2),
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
                    t = {'time': datetime.now().isoformat(), 'type': 'SELL', 'price': gp,
                         'amount': round(amt, 6), 'usdt': round(self.state['usdt'], 2),
                         'eth': round(self.state['eth'], 6)}
                    self.state['trades'].append(t); triggered.append(t)
                    orders[gp] = 'buy'

        self.state['grid_orders'] = {str(k): v for k, v in orders.items()}
        self.state['last_price'] = price
        self.save_state()
        return triggered

    def summary(self, price):
        eq = self.state['usdt'] + self.state['eth'] * price
        buys = sum(1 for t in self.state['trades'] if t['type'] == 'BUY')
        sells = sum(1 for t in self.state['trades'] if t['type'] == 'SELL')
        return {
            'price': price, 'usdt': round(self.state['usdt'], 2),
            'eth': round(self.state['eth'], 6), 'equity': round(eq, 2),
            'trades': len(self.state['trades']), 'buys': buys, 'sells': sells,
            'fees': round(self.state['total_fees'], 4),
            'grids': len(self.state['grid_orders']),
            'gmin': GRID_MIN, 'gmax': GRID_MAX,
            'gstep': round((GRID_MAX - GRID_MIN) / (GRID_COUNT - 1), 2),
        }


if __name__ == '__main__':
    bot = PaperGridBot()
    price = bot.get_price()

    if not bot.state['grid_orders'] or bot.state.get('grid_min') != GRID_MIN:
        bot.state['grid_orders'] = {}
        bot.state['grid_min'] = GRID_MIN
        grid = bot.setup_grid(price)
        print(f"🤖 网格启动! ETH=${price:.2f}")
        print(f"   区间 ${GRID_MIN}~${GRID_MAX} | {GRID_COUNT}层 | 格距${(GRID_MAX-GRID_MIN)/(GRID_COUNT-1):.2f}")
        print(f"   买单 {len(grid['buys'])} | 卖单 {len(grid['sells'])}")
        print(f"   USDT ${bot.state['usdt']:.2f} | ETH {bot.state['eth']:.6f}")
    else:
        trig = bot.check_grid(price)
        if trig:
            for t in trig:
                e = '🟢' if t['type'] == 'BUY' else '🔴'
                print(f"  {e} {t['type']} @ ${t['price']:.2f} | {t['amount']:.6f}")
        s = bot.summary(price)
        print(f"\n📊 ETH=${price:.2f} | USDT=${s['usdt']} | ETH={s['eth']}")
        print(f"   权益=${s['equity']} | 交易 {s['trades']}({s['buys']}买/{s['sells']}卖)")
        print(f"   网格 {s['grids']}层 | 区间 ${s['gmin']}~${s['gmax']} (格距${s['gstep']})")
        if trig:
            print(f"\n📋 最近交易:")
            for t in bot.state['trades'][-5:]:
                e = '🟢' if t['type'] == 'BUY' else '🔴'
                print(f"  {e} ${t['price']:.2f}")
