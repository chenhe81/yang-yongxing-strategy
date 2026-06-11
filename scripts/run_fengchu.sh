#!/bin/bash
# 凤雏每日扫描 — 部署到 10.26.0.7
# 每日 14:00 执行
cd "$(dirname "$0")/.."
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --strategy fengchu --date "$DATE" >> "logs/fengchu_${DATE}.log" 2>&1
echo "[$(date)] 凤雏扫描完成" >> "logs/fengchu_${DATE}.log"
