#!/bin/bash
# 仲达周筛 — 部署到 10.26.0.5
# 周日 21:00 执行
cd "$(dirname "$0")/.."
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --strategy zhongda --date "$DATE" >> "logs/zhongda_${DATE}.log" 2>&1
echo "[$(date)] 仲达周筛完成" >> "logs/zhongda_${DATE}.log"
