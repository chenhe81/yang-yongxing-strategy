#!/bin/bash
# 刘秀周筛 — 周日 21:00 定时执行
# 部署到 设备B（另一台电脑 / 服务器）
cd "$(dirname "$0")/.."
source venv/bin/activate 2>/dev/null || true
DATE=$(date "+%Y-%m-%d")
python3 run_scan.py --strategy liuxiu --date "$DATE" >> "logs/liuxiu_${DATE}.log" 2>&1
