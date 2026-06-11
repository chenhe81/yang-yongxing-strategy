#!/bin/bash
# 三设备定时任务部署助手
# 孔明（本机）| 刘秀（10.26.0.5）| 凤雏（10.26.0.7）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

show_kongming() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  孔明（本机）— 数据聚合 + 对比复盘           ║"
    echo "║  部署到: $(hostname)                        ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    echo "请手动执行以下命令来安装 cron："
    echo ""
    echo "  crontab -e"
    echo ""
    echo "添加以下内容："
    echo ""
    echo "============================================"
    cat "$PROJECT_DIR/cron_config/kongming_cron.txt"
    echo "============================================"
    echo ""
    echo "先决条件："
    echo "1. 配置 SSH 免密登录到刘秀和凤雏:"
    echo "   ssh-copy-id chenhe@10.26.0.5"
    echo "   ssh-copy-id chenhe@10.26.0.7"
    echo "2. 确保本机 output/ 目录已创建"
    echo ""
}

show_liuxiu() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  刘秀（10.26.0.5）— SEPA + 基本面周筛       ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    echo "部署步骤："
    echo "1. 将项目复制到刘秀："
    echo "   scp -r $PROJECT_DIR chenhe@10.26.0.5:~/"
    echo ""
    echo "2. SSH 登录刘秀："
    echo "   ssh chenhe@10.26.0.5"
    echo ""
    echo "3. 在刘秀上安装依赖："
    echo "   pip install akshare pandas pyyaml requests"
    echo ""
    echo "4. 在刘秀上设置 cron："
    echo "   crontab -e"
    echo ""
    echo "添加以下内容："
    echo ""
    echo "============================================"
    cat "$PROJECT_DIR/cron_config/liuxiu_cron.txt"
    echo "============================================"
    echo ""
}

show_fengchu() {
    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  凤雏（10.26.0.7）— 杨永兴日筛 + 隔夜套利   ║"
    echo "╚══════════════════════════════════════════════╝"
    echo ""
    echo "部署步骤："
    echo "1. 将项目复制到凤雏："
    echo "   scp -r $PROJECT_DIR chenhe@10.26.0.7:~/"
    echo ""
    echo "2. SSH 登录凤雏："
    echo "   ssh chenhe@10.26.0.7"
    echo ""
    echo "3. 在凤雏上安装依赖："
    echo "   pip install akshare pandas pyyaml requests"
    echo ""
    echo "4. 在凤雏上设置 cron："
    echo "   crontab -e"
    echo ""
    echo "添加以下内容："
    echo ""
    echo "============================================"
    cat "$PROJECT_DIR/cron_config/fengchu_cron.txt"
    echo "============================================"
    echo ""
}

show_deploy_all() {
    echo "============================================"
    echo "  全量部署"
    echo "============================================"
    echo ""
    echo "第1步：部署到凤雏（10.26.0.7）"
    echo "  scp -r $PROJECT_DIR chenhe@10.26.0.7:~/"
    echo ""
    echo "第2步：部署到刘秀（10.26.0.5）"
    echo "  scp -r $PROJECT_DIR chenhe@10.26.0.5:~/"
    echo ""
    echo "第3步：登录各设备安装依赖 + 设置 cron"
    echo "  参考对应设备的配置说明"
    echo ""
    echo "第4步：在本机配置 SSH 免密 + 安装孔明 cron"
    echo "  ssh-copy-id chenhe@10.26.0.7"
    echo "  ssh-copy-id chenhe@10.26.0.5"
    echo ""
}

case "${1:-all}" in
    kongming|local|本机)
        show_kongming
        ;;
    liuxiu|0.5)
        show_liuxiu
        ;;
    fengchu|0.7)
        show_fengchu
        ;;
    all)
        show_kongming
        echo ""
        echo "────────────────────────────────────────────"
        echo ""
        show_liuxiu
        echo ""
        echo "────────────────────────────────────────────"
        echo ""
        show_fengchu
        echo ""
        echo "────────────────────────────────────────────"
        echo ""
        show_deploy_all
        ;;
    help|--help|-h)
        echo "用法: bash $0 [kongming|liuxiu|fengchu|all]"
        echo ""
        echo "  kongming  - 本机（孔明）cron 配置说明"
        echo "  liuxiu    - 10.26.0.5（刘秀）部署说明"
        echo "  fengchu   - 10.26.0.7（凤雏）部署说明"
        echo "  all       - 全部（默认）"
        ;;
    *)
        echo "未知参数: $1"
        echo "用法: bash $0 [kongming|liuxiu|fengchu|all]"
        exit 1
        ;;
esac
