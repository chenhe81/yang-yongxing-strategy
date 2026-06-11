#!/bin/bash
# 运行历史回测（最近10个交易日）
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
python3 run_backtest.py --days 10
