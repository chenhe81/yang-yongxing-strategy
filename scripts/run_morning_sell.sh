#!/bin/bash
# 青鸾早盘卖出 — 09:30-10:00 执行（10.26.0.7）
# 铁律：10:00 前必须清仓
cd "$(dirname "$0")/.."
DATE=$(date "+%Y-%m-%d")
mkdir -p logs
python3 run_morning_sell.py "$DATE" >> "logs/morning_sell_${DATE}.log" 2>&1
