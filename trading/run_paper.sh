#!/bin/bash
# 运行模拟盘，仅在有交易时输出
cd /home/nh/.openclaw/workspace/trading
TRADES_BEFORE=$(python3 -c "import json; d=json.load(open('paper_state.json')); print(len(d['trades']))" 2>/dev/null || echo "0")
./venv/bin/python paper_grid.py 2>/dev/null
TRADES_AFTER=$(python3 -c "import json; d=json.load(open('paper_state.json')); print(len(d['trades']))" 2>/dev/null || echo "0")
if [ "$TRADES_AFTER" != "$TRADES_BEFORE" ]; then
    echo "NEW_TRADE"
fi
cat paper_state.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
if len(d['trades']) > 0:
    t=d['trades'][-1]
    print(f\"{'BUY' if t['type']=='BUY' else 'SELL'} @ {t['price']}\")
"