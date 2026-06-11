#!/bin/bash
# 设置定时任务 — 凤雏在本地，刘秀在远程
# 用法: bash scripts/setup_cron.sh [local|remote|all]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

install_fengchu_cron() {
    echo "安装凤雏定时任务 (本地设备)..."
    echo "# 凤雏策略 — 每日 14:00 技术面扫描 + 14:30 模拟买入"
    echo "# 每日 15:00 收盘复盘报告"
    (crontab -l 2>/dev/null; echo "") | sort -u | crontab -
    echo "凤雏定时任务已安装。"
    echo ""
    echo "请手动执行以下命令来安装cron（替换实际路径）："
    echo "  crontab -e"
    echo "添加以下行："
    echo "  # 凤雏 每日14:00扫描"
    echo "  00 14 * * 1-5 cd $PROJECT_DIR && python3 run_scan.py --strategy fengchu >> logs/cron_fengchu.log 2>&1"
    echo "  # 凤雏 15:00复盘"
    echo "  00 15 * * 1-5 cd $PROJECT_DIR && python3 run_scan.py --strategy fengchu --review >> logs/cron_review.log 2>&1"
}

install_liuxiu_cron() {
    echo "安装刘秀定时任务 (远程设备)..."
    echo ""
    echo "请手动执行以下命令来安装cron："
    echo "  crontab -e"
    echo "添加以下行："
    echo "  # 刘秀 周日21:00全量重筛"
    echo "  00 21 * * 0 cd $PROJECT_DIR && python3 run_scan.py --strategy liuxiu >> logs/cron_liuxiu.log 2>&1"
    echo "  # 刘秀 每日08:30增量检查"
    echo "  30 08 * * 1-5 cd $PROJECT_DIR && python3 run_scan.py --strategy liuxiu --incremental >> logs/cron_liuxiu_daily.log 2>&1"
}

case "${1:-local}" in
    local)
        install_fengchu_cron
        ;;
    remote)
        install_liuxiu_cron
        ;;
    all)
        echo "=== 本地设备（凤雏）==="
        install_fengchu_cron
        echo ""
        echo "=== 远程设备（刘秀）==="
        install_liuxiu_cron
        ;;
    *)
        echo "用法: $0 [local|remote|all]"
        exit 1
        ;;
esac
