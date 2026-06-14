#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 三设备定时任务部署 — 混合架构
#
# 数据层: 系统 cron（裸 Python，毫秒级执行）
# 汇报层: OpenClaw cron（AI 理解分析，推送到飞书）
#
# 用法:
#   bash setup_cron.sh                 → 显示全部
#   bash setup_cron.sh fengchu         → 凤雏(10.26.0.7)
#   bash setup_cron.sh zhongda          → 仲达(10.26.0.5)
#   bash setup_cron.sh kongming        → 孔明(本机)
#   bash setup_cron.sh openclaw        → OpenClaw 汇报层
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SEP="────────────────────────────────────────────────────────"

show_fengchu() {
    echo ""
    echo "$SEP"
    echo "  凤雏（10.26.0.7）— 杨永兴隔夜套利"
    echo "  部署：系统 cron"
    echo "$SEP"
    echo ""
    echo "步骤1：将项目复制到凤雏"
    echo "  scp -r $PROJECT_DIR chenhe@10.26.0.7:~/"
    echo ""
    echo "步骤2：SSH 登录凤雏安装依赖"
    echo "  ssh chenhe@10.26.0.7"
    echo "  pip install akshare pandas requests pyyaml"
    echo "  mkdir -p ~/股票市场扫描规则/logs"
    echo ""
    echo "步骤3：在凤雏上设置系统 cron（crontab -e）"
    echo ""
    echo "  # ── 凤雏（杨永兴隔夜套利）──"
    echo "  # 09:35 卖出昨日持仓（开盘价 +3%止盈 / -2%止损 / 10:00时间止损）"
    echo "  35 09 * * 1-5 cd ~/股票市场扫描规则 && python3 run_morning_sell.py >> logs/morning_sell.log 2>&1"
    echo ""
    echo "  # 14:00 全市场技术面日筛 + 模拟买入"
    echo "  00 14 * * 1-5 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy fengchu >> logs/fengchu.log 2>&1"
    echo ""
}

show_zhongda() {
    echo ""
    echo "$SEP"
    echo "  仲达（10.26.0.5）— SEPA 基本面周筛"
    echo "  部署：系统 cron"
    echo "$SEP"
    echo ""
    echo "步骤1：将项目复制到仲达"
    echo "  scp -r $PROJECT_DIR chenhe@10.26.0.5:~/"
    echo ""
    echo "步骤2：SSH 登录仲达安装依赖"
    echo "  ssh chenhe@10.26.0.5"
    echo "  pip install akshare pandas requests pyyaml"
    echo "  mkdir -p ~/股票市场扫描规则/logs"
    echo ""
    echo "步骤3：在仲达上设置系统 cron（crontab -e）"
    echo ""
    echo "  # ── 仲达（SEPA 基本面周筛）──"
    echo "  # 每日 08:30 增量检查（新闻/公告/财报）"
    echo "  30 08 * * 1-5 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy zhongda --incremental >> logs/zhongda_daily.log 2>&1"
    echo ""
    echo "  # 周日 21:00 全量重筛"
    echo "  00 21 * * 0 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy zhongda >> logs/zhongda_weekly.log 2>&1"
    echo ""
}

show_kongming() {
    echo ""
    echo "$SEP"
    echo "  孔明（本机）— 数据聚合 + 对比复盘"
    echo "  部署：系统 cron"
    echo "$SEP"
    echo ""
    echo "先决条件：配置 SSH 免密登录"
    echo "  ssh-copy-id chenhe@10.26.0.7"
    echo "  ssh-copy-id chenhe@10.26.0.5"
    echo ""
    echo "设置系统 cron（crontab -e）"
    echo ""
    echo "  # ── 孔明（数据聚合）──"
    echo "  # 15:30 从凤雏拉取今日扫描结果"
    echo "  30 15 * * 1-5 cd $PROJECT_DIR && scp chenhe@10.26.0.7:~/股票市场扫描规则/output/fengchu/candidates/*.json output/fengchu/candidates/ >> logs/fetch.log 2>&1"
    echo ""
    echo "  # 15:35 从凤雏拉取交易记录"
    echo "  35 15 * * 1-5 cd $PROJECT_DIR && scp chenhe@10.26.0.7:~/股票市场扫描规则/data/trades/fengchu_*.json data/trades/ >> logs/fetch.log 2>&1"
    echo ""
    echo "  # 16:00 生成双策略对比报告"
    echo "  00 16 * * 1-5 cd $PROJECT_DIR && python3 run_scan.py --compare >> logs/compare.log 2>&1"
    echo ""
    echo "  # 周日 22:00 合并核心池"
    echo "  00 22 * * 0 cd $PROJECT_DIR && python3 run_scan.py --merge-pools >> logs/merge.log 2>&1"
    echo ""
    echo "  # 配置 Dify API Key 后自动上传每日报告"
    echo "  export DIFY_API_KEY=\"your-key\""
    echo ""
}

show_openclaw() {
    echo ""
    echo "$SEP"
    echo "  OpenClaw — AI 汇报层"
    echo "  部署：openclaw cron add"
    echo "$SEP"
    echo ""
    echo "前提：OpenClaw Gateway 正在运行，已连接飞书频道"
    echo ""
    echo "凤雏复盘（交易日 10:00 发送结果到飞书）："
    echo ""
    echo "openclaw cron add \\"
    echo "  --name \"凤雏早盘复盘\" \\"
    echo "  --cron \"0 10 * * 1-5\" \\"
    echo "  --session isolated \\"
    echo "  --message \"读取 ~/股票市场扫描规则/output/fengchu/trades/ 下的最新交易记录，"
    echo "             生成今日凤雏早盘卖出复盘报告。"
    echo "             报告格式："
    echo "             1. 今日卖出股票列表（盈亏%）"
    echo "             2. 累计收益"
    echo "             3. 当前持仓（如有）\" \\"
    echo "  --announce --channel feishu --to \"user:me\""
    echo ""
    echo ""
    echo "凤雏收盘复盘（交易日 15:30）："
    echo ""
    echo "openclaw cron add \\"
    echo "  --name \"凤雏收盘复盘\" \\"
    echo "  --cron \"30 15 * * 1-5\" \\"
    echo "  --session isolated \\"
    echo "  --message \"读取 ~/股票市场扫描规则/output/fengchu/candidates/ 和 trades/ 下的最新文件，"
    echo "             生成今日凤雏策略收盘复盘报告。"
    echo "             包含今日筛选结果、买入记录、累计盈亏\" \\"
    echo "  --announce --channel feishu --to \"user:me\""
    echo ""
    echo ""
    echo "周报（周日 22:30）："
    echo ""
    echo "openclaw cron add \\"
    echo "  --name \"双策略周报\" \\"
    echo "  --cron \"30 22 * * 0\" \\"
    echo "  --session isolated \\"
    echo "  --message \"读取 ~/股票市场扫描规则/reports/comparison/ 下的对比报告，"
    echo "             生成本周双策略战绩周报。"
    echo "             对比凤雏日筛 vs 仲达周筛的总收益率、胜率\" \\"
    echo "  --announce --channel feishu --to \"user:me\""
    echo ""
}

show_all() {
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  股票市场扫描系统 — 完整部署手册                      ║"
    echo "║  数据层：系统 cron（三台设备）                       ║"
    echo "║  汇报层：OpenClaw cron（AI推送到飞书）                 ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    show_fengchu
    echo ""
    echo "════════════════════════════════════════════════════"
    echo ""
    show_zhongda
    echo ""
    echo "════════════════════════════════════════════════════"
    echo ""
    show_kongming
    echo ""
    echo "════════════════════════════════════════════════════"
    echo ""
    show_openclaw
    echo ""
    echo "════════════════════════════════════════════════════"
    echo ""
    echo "部署顺序："
    echo "  第1步：凤雏（10.26.0.7）— 系统 cron"
    echo "  第2步：仲达（10.26.0.5）— 系统 cron"
    echo "  第3步：孔明（本机）— 系统 cron（需 ssh-copy-id）"
    echo "  第4步：OpenClaw（本机）— openclaw cron add"
    echo ""
}

case "${1:-all}" in
    fengchu|0.7) show_fengchu ;;
    zhongda|0.5)  show_zhongda ;;
    kongming|local|本机) show_kongming ;;
    openclaw|ai) show_openclaw ;;
    all) show_all ;;
    help|--help|-h)
        echo "用法: bash $0 [fengchu|zhongda|kongming|openclaw|all]"
        exit 0
        ;;
    *) echo "未知参数: $1（使用 bash $0 help 查看帮助）"; exit 1 ;;
esac
