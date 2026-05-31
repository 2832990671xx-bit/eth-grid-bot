#!/home/nh/.openclaw/workspace/venv/bin/python
"""
ETH/USDT 网格交易回测
- 拉取 OKX 历史 1h K线
- 模拟网格交易
- 输出收益统计
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

# ---- 配置 ----
SYMBOL = 'ETH/USDT'
TIMEFRAME = '1h'         # 1小时线
LIMIT = 720              # 720小时 = 30天
INITIAL_USDT = 200       # 初始资金 USDT
INITIAL_ETH = 0.1        # 初始持仓 ETH
GRID_LEVELS = 10         # 网格层数
GRID_SPREAD = 0.015      # 网格间距 1.5%
FEE_RATE = 0.001         # 手续费 0.1%

# ---- 获取历史数据 ----
print("📡 正在拉取 OKX 历史数据...")
exchange = ccxt.okx()
since = exchange.parse8601((datetime.utcnow() - timedelta(hours=LIMIT)).isoformat())
ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, since=since, limit=LIMIT)

df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
print(f"✅ 获取到 {len(df)} 条数据")
print(f"   时间范围: {df['time'].iloc[0]} ~ {df['time'].iloc[-1]}")
print(f"   价格范围: ${df['low'].min():.2f} ~ ${df['high'].max():.2f}")

# ---- 网格交易模拟 ----
class GridSimulator:
    def __init__(self, usdt, eth, grid_levels, spread, fee_rate):
        self.usdt = usdt
        self.eth = eth
        self.grid_levels = grid_levels
        self.spread = spread
        self.fee_rate = fee_rate
        
        self.trades = []
        self.equity_curve = []
        self.grid_orders = {}  # price -> type ('buy' | 'sell')
        
    def setup_grid(self, current_price):
        """在初始价格周围布网"""
        center = current_price
        self.grid_prices = []
        for i in range(self.grid_levels):
            buy_price = center * (1 - self.spread * (i + 1))
            sell_price = center * (1 + self.spread * (i + 1))
            self.grid_prices.append(round(buy_price, 2))
            self.grid_prices.append(round(sell_price, 2))
        
        self.grid_prices = sorted(set(self.grid_prices))
        
        # 低于当前价的挂买单，高于当前价的挂卖单
        for p in self.grid_prices:
            if p < current_price:
                self.grid_orders[p] = 'buy'
            elif p > current_price:
                self.grid_orders[p] = 'sell'
        
        print(f"\n📐 网格设置:")
        print(f"   最低: ${min(self.grid_prices):.2f}")
        print(f"   最高: ${max(self.grid_prices):.2f}")
        print(f"   网格数: {len(self.grid_prices)}")
        print(f"   初始价格: ${current_price:.2f}")
                
    def on_price(self, price, time_str):
        """处理每个价格点"""
        # 记录权益
        equity = self.usdt + self.eth * price
        self.equity_curve.append({'time': time_str, 'price': price, 'equity': equity, 'usdt': self.usdt, 'eth': self.eth})
        
        # 检查每个网格是否触发
        for grid_price in list(self.grid_orders.keys()):
            order_type = self.grid_orders[grid_price]
            
            if order_type == 'buy' and price <= grid_price:
                # 买单触发：买入 ETH
                buy_amount = (self.usdt * 0.3) / grid_price  # 每次用30%资金
                if buy_amount > 0 and self.usdt > 5:
                    buy_amount = min(buy_amount, self.usdt / grid_price * 0.99)
                    cost = buy_amount * grid_price
                    fee = cost * self.fee_rate
                    self.eth += buy_amount - buy_amount * self.fee_rate
                    self.usdt -= cost
                    
                    self.trades.append({
                        'time': time_str,
                        'type': 'BUY',
                        'price': grid_price,
                        'amount': round(buy_amount, 6),
                        'cost': round(cost, 2),
                        'usdt_left': round(self.usdt, 2),
                        'eth_left': round(self.eth, 6),
                    })
                    
                    # 移除买单，在更高一格挂卖单
                    del self.grid_orders[grid_price]
                    sell_price = round(grid_price * (1 + self.spread), 2)
                    self.grid_orders[sell_price] = 'sell'
                    
            elif order_type == 'sell' and price >= grid_price:
                # 卖单触发：卖出 ETH
                eth_to_sell = self.eth * 0.3
                if eth_to_sell > 0 and self.eth > 0.001:
                    revenue = eth_to_sell * grid_price
                    fee = revenue * self.fee_rate
                    self.usdt += revenue - fee
                    self.eth -= eth_to_sell
                    
                    self.trades.append({
                        'time': time_str,
                        'type': 'SELL',
                        'price': grid_price,
                        'amount': round(eth_to_sell, 6),
                        'revenue': round(revenue, 2),
                        'usdt_left': round(self.usdt, 2),
                        'eth_left': round(self.eth, 6),
                    })
                    
                    # 移除卖单，在更低一格挂买单
                    del self.grid_orders[grid_price]
                    buy_price = round(grid_price * (1 - self.spread), 2)
                    self.grid_orders[buy_price] = 'buy'

# ---- 运行回测 ----
print("\n🚀 开始网格回测...")
sim = GridSimulator(INITIAL_USDT, INITIAL_ETH, GRID_LEVELS, GRID_SPREAD, FEE_RATE)
sim.setup_grid(df['close'].iloc[0])

for i in range(len(df)):
    row = df.iloc[i]
    sim.on_price(row['close'], row['time'].strftime('%m-%d %H:%M'))

# ---- 输出结果 ----
final_price = df['close'].iloc[-1]
final_equity = sim.usdt + sim.eth * final_price
initial_equity = INITIAL_USDT + INITIAL_ETH * df['close'].iloc[0]
profit = final_equity - initial_equity
profit_pct = (profit / initial_equity) * 100

# HODL 对比
hodl_value = INITIAL_USDT + INITIAL_ETH * final_price
hodl_profit = hodl_value - initial_equity
hodl_pct = (hodl_profit / initial_equity) * 100

print(f"\n{'='*50}")
print(f"📊 回测结果")
print(f"{'='*50}")
print(f"期间价格: ${df['close'].iloc[0]:.2f} → ${final_price:.2f}")
print(f"价格变动: {((final_price - df['close'].iloc[0]) / df['close'].iloc[0]) * 100:.2f}%")
print(f"\n💰 初始权益: ${initial_equity:.2f}")
print(f"💰 最终权益: ${final_equity:.2f}")
print(f"📈 网格收益: ${profit:.2f} ({profit_pct:+.2f}%)")
print(f"📈 HODL收益: ${hodl_profit:.2f} ({hodl_pct:+.2f}%)")
print(f"\n🔄 总交易次数: {len(sim.trades)}")
print(f"  买入: {sum(1 for t in sim.trades if t['type']=='BUY')} 次")
print(f"  卖出: {sum(1 for t in sim.trades if t['type']=='SELL')} 次")

if len(sim.trades) > 0:
    print(f"\n📋 最近5笔交易:")
    for t in sim.trades[-5:]:
        emoji = '🟢' if t['type'] == 'BUY' else '🔴'
        print(f"  {emoji} {t['time']} {t['type']} @ ${t['price']:.2f} | 金额: {t.get('amount',0)} | USDT: ${t['usdt_left']:.2f} | ETH: {t['eth_left']:.6f}")

# 保存详细结果
result = {
    'initial_equity': round(initial_equity, 2),
    'final_equity': round(final_equity, 2),
    'grid_profit': round(profit, 2),
    'grid_profit_pct': round(profit_pct, 2),
    'hodl_profit': round(hodl_profit, 2),
    'hodl_pct': round(hodl_pct, 2),
    'start_price': round(df['close'].iloc[0], 2),
    'end_price': round(final_price, 2),
    'total_trades': len(sim.trades),
    'equity_curve': sim.equity_curve,
    'trades': sim.trades,
}
with open('/home/nh/.openclaw/workspace/trading/grid_result.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)
print(f"\n💾 详细结果已保存到 trading/grid_result.json")
