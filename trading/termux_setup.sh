#!/data/data/com.termux/files/usr/bin/bash
# 网格交易 - Termux 一键部署脚本
# 在 Termux 里直接复制粘贴运行：bash termux_setup.sh

set -e

echo "========================================"
echo "  网格交易 Termux 部署脚本"
echo "========================================"

# 1. 更新源
echo "[1/5] 更新软件源..."
pkg update -y

# 2. 安装依赖
echo "[2/5] 安装 Python..."
pkg install -y python python-pip git termux-services

# 3. 安装 Python 包
echo "[3/5] 安装 ccxt..."
pip install ccxt

# 4. 创建网格交易目录
echo "[4/5] 创建交易目录..."
mkdir -p ~/grid_bot
cd ~/grid_bot

# 5. 下载网格脚本
echo "[5/5] 下载网格脚本..."

# 网格核心脚本
cat > paper_grid.py << 'PYEOF'
#!/data/data/com.termux/files/usr/bin/python
import ccxt
import json
import os
import time
import logging
from datetime import datetime

# 配置
EXCHANGE = 'okx'
SYMBOL = 'ETH/USDT'
GRID_MIN = 1800
GRID_MAX = 2200
GRID_COUNT = 25
FEE_RATE = 0.001
STATE_FILE = os.path.expanduser('~/grid_bot/paper_state.json')
LOG_FILE = os.path.expanduser('~/grid_bot/paper.log')
PROXY = None  # 如果需要代理，改成 'http://127.0.0.1:7890'

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class PaperGrid:
    def __init__(self):
        if PROXY:
            self.exchange = ccxt.okx({'proxies': {'https': PROXY, 'http': PROXY}})
        else:
            self.exchange = ccxt.okx()
        self.exchange.timeout = 15000
        
        step = (GRID_MAX - GRID_MIN) / (GRID_COUNT - 1)
        self.grid_prices = [round(GRID_MIN + i * step, 2) for i in range(GRID_COUNT)]
        
        self.state = self.load_state()
        
    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except:
                pass
        return None
        
    def init_state(self, price):
        orders = {}
        for p in self.grid_prices:
            orders[str(p)] = 'buy' if p < price else 'sell'
        
        self.state = {
            'usdt': 200.0,
            'eth': 0.1,
            'trades': [],
            'grid_orders': orders,
            'last_price': price,
            'start_time': datetime.now().isoformat(),
            'total_fees': 0,
            'grid_min': GRID_MIN,
            'grid_max': GRID_MAX,
        }
        self.save_state()
        logging.info(f"初始化: ETH=${price}, {GRID_COUNT}格, $200 USDT + 0.1 ETH")
        
    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)
            
    def fetch_price(self):
        ticker = self.exchange.fetch_ticker(SYMBOL)
        return ticker['last']
        
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
                    cost = amt * gp
                    fee = cost * FEE_RATE
                    self.state['eth'] += amt - amt * FEE_RATE
                    self.state['usdt'] -= cost
                    self.state['total_fees'] += fee
                    t = {'time': datetime.now().isoformat(), 'type': 'BUY', 'price': gp,
                         'amount': round(amt, 6), 'usdt': round(self.state['usdt'], 2),
                         'eth': round(self.state['eth'], 6)}
                    self.state['trades'].append(t)
                    triggered.append(t)
                    orders[gp] = 'sell'
                    
            elif not up and price <= gp < last and cur == 'sell':
                amt = max(self.state['eth'] * 0.033, 0)
                if amt > 0.001 and self.state['eth'] > 0.002:
                    rev = amt * gp
                    fee = rev * FEE_RATE
                    self.state['usdt'] += rev - fee
                    self.state['eth'] -= amt
                    self.state['total_fees'] += fee
                    t = {'time': datetime.now().isoformat(), 'type': 'SELL', 'price': gp,
                         'amount': round(amt, 6), 'usdt': round(self.state['usdt'], 2),
                         'eth': round(self.state['eth'], 6)}
                    self.state['trades'].append(t)
                    triggered.append(t)
                    orders[gp] = 'buy'
                    
        if triggered:
            self.state['grid_orders'] = {str(k): v for k, v in orders.items()}
        self.state['last_price'] = price
        
        return triggered
        
    def run(self):
        try:
            price = self.fetch_price()
            
            if self.state is None:
                self.init_state(price)
                return []
            
            triggered = self.check_grid(price)
            
            for t in triggered:
                msg = f"{'✅' if t['type']=='BUY' else '🔴'} {t['type']} @ ${t['price']} | {t['amount']} ETH | USDT ${t['usdt']}"
                logging.info(msg)
                
            total = len(self.state['trades'])
            eq = self.state['usdt'] + self.state['eth'] * price
            summary = f"ETH=${price:.2f} | USDT=${self.state['usdt']:.2f} ETH={self.state['eth']:.6f} | 权益=${eq:.2f} | 总交易{total}笔"
            logging.info(summary)
            
            self.save_state()
            return triggered
            
        except Exception as e:
            logging.error(f"错误: {e}")
            return []

if __name__ == '__main__':
    bot = PaperGrid()
    trades = bot.run()
    if trades:
        print("NEW_TRADES:")
        for t in trades:
            print(f"{t['type']} @ ${t['price']}")
PYEOF

# 自动运行脚本（使用 termux-job-scheduler）
cat > run_grid.sh << 'SHEOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/grid_bot && python paper_grid.py
SHEOF
chmod +x run_grid.sh

# 设置定时任务（每5分钟）
echo "*/5 * * * * bash ~/grid_bot/run_grid.sh" > /sdcard/cron_android.txt

# 尝试安装 crond
echo ""
echo "========================================"
echo "  ✅ 部署完成！"
echo "========================================"
echo ""
echo "接下来需要两步操作："
echo ""
echo "【第一步】安装定时任务工具："
echo "  pkg install termux-services cronie"
echo "  crond"
echo ""
echo "【第二步】或者用 Termux 的定时任务："
echo "  termux-wake-lock"
echo "  while true; do"
echo "    bash ~/grid_bot/run_grid.sh"
echo "    sleep 300"
echo "  done"
echo ""
echo "【查看日志】"
echo "  cat ~/grid_bot/paper.log"
echo ""
echo "【查看余额】"
echo "  cat ~/grid_bot/paper_state.json | python3 -c 'import json,sys;d=json.load(sys.stdin);eq=d[\"usdt\"]+d[\"eth\"]*d[\"last_price\"];print(f\"💰 {eq:.2f} | 交易{len(d.get(\"trades\",[]))}笔\")'"
