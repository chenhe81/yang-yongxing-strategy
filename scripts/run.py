"""
杨永兴短线战法 - 主入口脚本
"""

import sys
import os
import logging
import json

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_scan(args):
    """执行选股扫描"""
    from scanner import Scanner
    from report import generate_scan_report

    skip_intraday = "--skip-intraday" in args or "-s" in args

    logger.info("🚀 开始杨永兴短线战法选股扫描...")
    scanner = Scanner()
    result = scanner.scan(skip_intraday=skip_intraday)

    report_text, filepath = generate_scan_report(result)
    print(report_text)
    print(f"\n📁 报告已保存至: {filepath}")

    # 如果有候选股，提示添加到持仓
    candidates = result.get("candidates", [])
    if candidates:
        print(f"\n💡 如需跟踪某只股票，请运行：")
        print(f"   python run.py add <代码> <名称> <买入价>")
        print(f"\n   候选股代码：")
        for c in candidates[:10]:
            print(f"   {c['code']} {c['name']} 现价{c['price']}")


def cmd_sepa_scan(args):
    """执行SEPA策略选股扫描"""
    from sepa_filter import SEPAFilter
    from report import generate_sepa_report

    skip_ma = "--skip-ma" in args or "-s" in args

    logger.info("🚀 开始米勒维尼SEPA策略选股扫描...")
    sepa = SEPAFilter()
    result = sepa.scan(skip_ma_check=skip_ma)

    report_text, filepath = generate_sepa_report(result)
    print(report_text)
    print(f"\n📁 报告已保存至: {filepath}")

    candidates = result.get("candidates", [])
    if candidates:
        print(f"\n💡 这些股票满足SEPA基本面筛选，可重点关注：")
        for c in candidates[:15]:
            rev_g = f"{c['revenue_growth_yoy']:.1f}%" if c.get("revenue_growth_yoy") else "N/A"
            profit_g = f"{c['profit_growth_yoy']:.1f}%" if c.get("profit_growth_yoy") else "N/A"
            roe = f"{c['roe']:.1f}%" if c.get("roe") else "N/A"
            print(f"   {c['code']} {c['name']} 营收增长:{rev_g} 净利增长:{profit_g} ROE:{roe}")


def cmd_combined_scan(args):
    """执行杨永兴+SEPA联合选股扫描（先杨永兴技术面筛选，再SEPA基本面验证）"""
    from combined_scanner import CombinedScanner
    from openviking_adapter import init_openviking
    from report import generate_combined_report

    skip_ma = "--skip-ma" in args
    skip_intraday = "--skip-intraday" in args or "-s" in args
    relax = "--relax" in args or "-r" in args
    use_openviking = "--openviking" in args or "-o" in args

    # 初始化 OpenViking
    ov = init_openviking(enabled=use_openviking)

    logger.info("🚀 开始杨永兴+SEPA联合选股扫描...")
    if ov.available:
        logger.info("📋 OpenViking 上下文管理已启用")

    scanner = CombinedScanner(openviking=ov)
    result = scanner.scan(
        skip_intraday=skip_intraday,
        skip_ma_check=skip_ma,
        relax_yang=relax,
    )

    report_text, filepath = generate_combined_report(result)
    print(report_text)
    print(f"\n📁 报告已保存至: {filepath}")

    yang = result.get("yang_candidates", [])
    final = result.get("final_candidates", [])

    if final:
        print(f"\n🌟 双战法同时通过（最高确定性）：")
        for c in final[:10]:
            rev_g = f"{c['revenue_growth_yoy']:.1f}%" if c.get("revenue_growth_yoy") else "N/A"
            profit_g = f"{c['profit_growth_yoy']:.1f}%" if c.get("profit_growth_yoy") else "N/A"
            roe = f"{c['roe']:.1f}%" if c.get("roe") else "N/A"
            print(f"   {c['code']} {c['name']} 现价{c.get('price','N/A')} 涨幅{c.get('change_pct',0):.1f}%")
            print(f"     基本面: 营收+{rev_g} 净利+{profit_g} ROE:{roe}")
            print(f"     技术面: 量比{c.get('volume_ratio','N/A')} 换手{c.get('turnover_rate','N/A')}% 市值{c.get('circ_mv_billion','N/A')}亿")
    elif yang:
        print(f"\n💡 今日杨永兴候选{yang}只，但无股票同时通过SEPA基本面验证")
        print(f"   候选股代码：")
        for c in yang[:10]:
            print(f"   {c['code']} {c['name']} 现价{c.get('price','N/A')} 涨幅{c.get('change_pct',0):.1f}%")
    else:
        print(f"\n💡 今日无符合杨永兴战法条件的股票")


def cmd_sell_check(args):
    """执行卖出信号检查"""
    from sell_checker import check_sell_signals
    from report import generate_sell_report

    logger.info("🔔 开始检查卖出信号...")
    result = check_sell_signals()

    report_text, filepath = generate_sell_report(result)
    print(report_text)
    print(f"\n📁 报告已保存至: {filepath}")


def cmd_portfolio(args):
    """查看持仓"""
    from portfolio import show_portfolio
    show_portfolio()


def cmd_add(args):
    """添加持仓: python run.py add 000001 平安银行 15.50"""
    from portfolio import add_position

    if len(args) < 3:
        print("用法: python run.py add <代码> <名称> <买入价> [备注]")
        return

    code = args[0]
    name = args[1]
    try:
        buy_price = float(args[2])
    except ValueError:
        print("❌ 买入价格式错误")
        return

    notes = args[3] if len(args) > 3 else ""
    add_position(code, name, buy_price, notes=notes)


def cmd_remove(args):
    """移除持仓: python run.py remove 000001"""
    from portfolio import remove_position

    if not args:
        print("用法: python run.py remove <代码>")
        return

    remove_position(args[0])


def cmd_watchlist(args):
    """查看自选"""
    from portfolio import show_watchlist
    show_watchlist()


def cmd_add_watch(args):
    """添加自选: python run.py watch-add 000001 平安银行"""
    from portfolio import add_watchlist

    if len(args) < 1:
        print("用法: python run.py watch-add <代码> [名称] [原因]")
        return

    code = args[0]
    name = args[1] if len(args) > 1 else ""
    reason = args[2] if len(args) > 2 else ""
    add_watchlist(code, name, reason)


def cmd_remove_watch(args):
    """移除自选: python run.py watch-remove 000001"""
    from portfolio import remove_watchlist

    if not args:
        print("用法: python run.py watch-remove <代码>")
        return

    remove_watchlist(args[0])


def cmd_clear(args):
    """清空持仓"""
    from portfolio import clear_portfolio
    clear_portfolio()


def cmd_openviking_status(args):
    """查看OpenViking状态"""
    from openviking_adapter import OpenVikingAdapter

    ov = OpenVikingAdapter()
    status = ov.get_status()

    print("=" * 50)
    print("📊 OpenViking 上下文管理状态")
    print("=" * 50)
    print(f"  已启用: {'✅' if status['enabled'] else '❌'}")
    print(f"  可用:   {'✅' if status['available'] else '❌'}")
    print(f"  地址:   {status['url']}")

    if status.get("server_health"):
        health = status["server_health"]
        if isinstance(health, dict):
            print(f"  健康:   ✅ {health}")
        else:
            print(f"  健康:   ❌ {health}")
    else:
        print(f"  健康:   未检测")

    if not status["available"]:
        print("\n💡 启用 OpenViking 上下文管理：")
        print("   1. 安装: pip install openviking")
        print("   2. 安装Ollama: brew install ollama")
        print("   3. 拉取模型: ollama pull nomic-embed-text")
        print("   4. 初始化: openviking-server init")
        print("   5. 启动服务: openviking-server")
        print("   6. 扫描时使用: python run.py combined-scan --openviking")

    print("=" * 50)


def cmd_openviking_init(args):
    """初始化OpenViking配置"""
    import subprocess

    print("🚀 初始化 OpenViking 上下文管理系统...")

    # 检查 openviking 是否安装
    try:
        import openviking
        print("✅ openviking 已安装")
    except ImportError:
        print("❌ openviking 未安装，正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "openviking"], check=True)
        print("✅ openviking 安装完成")

    # 检查 Ollama
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ Ollama 已安装并运行")
            # 检查嵌入模型
            if "nomic-embed-text" not in result.stdout:
                print("📥 正在拉取嵌入模型 nomic-embed-text...")
                subprocess.run(["ollama", "pull", "nomic-embed-text"], check=True)
                print("✅ nomic-embed-text 已就绪")
            else:
                print("✅ nomic-embed-text 已就绪")
        else:
            print("❌ Ollama 未运行，请先启动: brew services start ollama")
            return
    except FileNotFoundError:
        print("❌ Ollama 未安装，请先安装: brew install ollama")
        return
    except Exception as e:
        print(f"❌ Ollama 检查失败: {e}")
        return

    # 创建配置文件
    ov_dir = os.path.expanduser("~/.openviking")
    os.makedirs(ov_dir, exist_ok=True)

    conf_path = os.path.join(ov_dir, "ov.conf")
    if os.path.exists(conf_path):
        print(f"⚠️ 配置文件已存在: {conf_path}")
    else:
        conf = {
            "storage": {
                "workspace": os.path.join(ov_dir, "workspace")
            },
            "embedding": {
                "dense": {
                    "api_base": "http://localhost:11434/v1",
                    "api_key": "ollama",
                    "provider": "openai",
                    "dimension": 768,
                    "model": "nomic-embed-text"
                }
            },
            "vlm": {
                "api_base": "http://localhost:11434/v1",
                "api_key": "ollama",
                "provider": "litellm",
                "model": "qwen2.5:7b"
            }
        }

        import json
        with open(conf_path, 'w', encoding='utf-8') as f:
            json.dump(conf, f, indent=2, ensure_ascii=False)
        print(f"✅ 配置文件已创建: {conf_path}")

    # 提示启动
    print("\n" + "=" * 50)
    print("🎉 初始化完成！下一步：")
    print("   1. 启动 OpenViking 服务: openviking-server")
    print("   2. 使用联合扫描: python run.py combined-scan --openviking")
    print("=" * 50)


COMMANDS = {
    "scan": ("杨永兴九步选股扫描", cmd_scan),
    "sepa-scan": ("SEPA策略选股扫描（米勒维尼）", cmd_sepa_scan),
    "combined-scan": ("杨永兴+SEPA联合扫描（先杨永兴技术面筛选，再SEPA基本面验证）", cmd_combined_scan),
    "sell-check": ("卖出信号检查", cmd_sell_check),
    "portfolio": ("查看持仓", cmd_portfolio),
    "add": ("添加持仓 (add 代码 名称 买入价)", cmd_add),
    "remove": ("移除持仓 (remove 代码)", cmd_remove),
    "watchlist": ("查看自选股", cmd_watchlist),
    "watch-add": ("添加自选 (watch-add 代码 名称)", cmd_add_watch),
    "watch-remove": ("移除自选 (watch-remove 代码)", cmd_remove_watch),
    "clear": ("清空持仓", cmd_clear),
    "openviking-status": ("查看OpenViking上下文管理状态", cmd_openviking_status),
    "openviking-init": ("初始化OpenViking环境（一键配置）", cmd_openviking_init),
}


def print_help():
    print("杨永兴短线战法 - 尾盘选股扫描器")
    print("\n用法: python run.py <命令> [参数]")
    print("\n命令列表：")
    for cmd, (desc, _) in COMMANDS.items():
        print(f"  {cmd:<16} {desc}")
    print("\n选项：")
    print("  -s, --skip-intraday  跳过分时数据检查（加快扫描速度）")
    print("  -r, --relax          放宽杨永兴条件（涨幅不限、市值/换手率放宽）")
    print("  -o, --openviking     启用OpenViking上下文管理（记忆+经验积累）")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print_help()
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    if command in COMMANDS:
        _, handler = COMMANDS[command]
        handler(args)
    else:
        print(f"❌ 未知命令: {command}")
        print_help()
