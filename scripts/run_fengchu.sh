#!/bin/bash
# 凤雏每日扫描 — 14:00 定时执行
# 部署到 设备A（Mac mini / NAS）
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --strategy fengchu --date "$DATE" >> "logs/fengchu_${DATE}.log" 2>&1
