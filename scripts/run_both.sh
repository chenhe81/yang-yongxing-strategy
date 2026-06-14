#!/bin/bash
# 北辰本地双策略比较（从本地 output/ 目录读取已有的青鸾/仲达数据）
# 本机执行
cd "$(dirname "$0")/.."
DATE=$(date "+%Y-%m-%d")
echo "========================================" >> "logs/beichen_${DATE}.log"
echo "[$(date)] 北辰: 开始聚合分析" >> "logs/beichen_${DATE}.log"

# 检查青鸾数据
if [ -f "output/qingluan/candidates/screening_${DATE}.json" ]; then
    echo "青鸾数据: 存在" >> "logs/beichen_${DATE}.log"
else
    echo "青鸾数据: 未找到（尝试从10.26.0.7拉取）" >> "logs/beichen_${DATE}.log"
    # 如果配置了免密，自动拉取
    scp "chenhe@10.26.0.7:~/股票市场扫描规则/output/qingluan/candidates/screening_${DATE}.json" \
        "output/qingluan/candidates/" 2>/dev/null && \
        echo "青鸾数据已从10.26.0.7拉取" >> "logs/beichen_${DATE}.log"
fi

# 检查仲达数据
if [ -f "output/zhongda/reports/market_snapshot_${DATE}.md" ]; then
    echo "仲达数据: 存在" >> "logs/beichen_${DATE}.log"
else
    echo "仲达数据: 未找到（尝试从10.26.0.5拉取）" >> "logs/beichen_${DATE}.log"
    scp "chenhe@10.26.0.5:~/股票市场扫描规则/output/zhongda/reports/market_snapshot_${DATE}.md" \
        "output/zhongda/reports/" 2>/dev/null && \
        echo "仲达数据已从10.26.0.5拉取" >> "logs/beichen_${DATE}.log"
fi

echo "[$(date)] 北辰: 聚合分析完成" >> "logs/beichen_${DATE}.log"
