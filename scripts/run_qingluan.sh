#!/bin/bash
# 青鸾每日扫描 — 部署到 10.26.0.7
# 每日 14:00 执行
cd "$(dirname "$0")/.."
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --strategy qingluan --date "$DATE" >> "logs/qingluan_${DATE}.log" 2>&1
echo "[$(date)] 青鸾扫描完成" >> "logs/qingluan_${DATE}.log"
