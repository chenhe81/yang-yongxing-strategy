#!/bin/bash
# 双策略同时运行
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --both --date "$DATE" >> "logs/both_${DATE}.log" 2>&1
