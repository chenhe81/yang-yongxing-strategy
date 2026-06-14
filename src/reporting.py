"""
报告生成器 — 每日/每周/最终复盘报告
"""
import json
import os
from datetime import datetime
from typing import List, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_trades(strategy: str) -> list:
    path = os.path.join(BASE_DIR, "data", "trades", f"{strategy}_trades.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def load_portfolio(strategy: str) -> dict:
    path = os.path.join(BASE_DIR, "data", "trades", f"{strategy}_portfolio.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def load_screening(strategy: str, date: str) -> list:
    path = os.path.join(BASE_DIR, "output", strategy, "candidates", f"screening_{date}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []


def generate_daily_report(strategy: str, date: str, scan_results: list) -> str:
    """生成每日复盘报告"""
    trades_today = [t for t in load_trades(strategy)
                    if t.get("date") == date or t.get("date", "").startswith(date)]
    portfolio = load_portfolio(strategy)

    lines = []
    lines.append(f"# {strategy} 战法日报 — {date}")
    lines.append("")

    # 今日扫描结果
    lines.append("## 今日扫描结果")
    if scan_results:
        candidates = [s for s in scan_results if s["decision"] in ("buy", "strong_buy")]
        if candidates:
            lines.append(f"共筛选出 {len(candidates)} 只候选股：")
            lines.append("")
            for c in candidates:
                dec = "🟢 坚决买入" if c["decision"] == "strong_buy" else "🟡 可买入"
                lines.append(f"- **{c['name']}({c['code']})** 评分={c['score']} {dec}")
                lines.append(f"  涨幅:{c.get('pct_change', 0):.1f}% "
                             f"量比:{c.get('volume_ratio', 0):.2f} "
                             f"换手:{c.get('turnover', 0):.1f}%")
                if c.get("sector"):
                    lines.append(f"  板块:{c['sector']}")
                lines.append("")
        else:
            lines.append("无符合条件的股票。")
            lines.append("")
    else:
        lines.append("今日未运行扫描或扫描异常。")
        lines.append("")

    # 今日交易
    buys = [t for t in trades_today if t["type"] == "buy"]
    sells = [t for t in trades_today if t["type"] == "sell"]

    lines.append("## 今日交易")
    if buys:
        lines.append("### 买入")
        for t in buys:
            lines.append(f"- **{t['name']}({t['code']})** "
                         f"价格:{t['price']:.2f} 数量:{t['shares']} "
                         f"金额:{t['amount']:.0f} 评分:{t.get('score', 'N/A')}")
    if sells:
        lines.append("### 卖出")
        for t in sells:
            pnl = t.get("pnl_pct", 0)
            if pnl >= 0:
                lines.append(f"- ✅ **{t['name']}({t['code']})** "
                             f"价格:{t['price']:.2f} 盈亏:+{pnl:.1f}% 原因:{t.get('reason', '')}")
            else:
                lines.append(f"- ❌ **{t['name']}({t['code']})** "
                             f"价格:{t['price']:.2f} 盈亏:{pnl:.1f}% 原因:{t.get('reason', '')}")
    if not buys and not sells:
        lines.append("今日无交易。")

    lines.append("")
    lines.append("## 持仓状态")
    if portfolio.get("positions"):
        for p in portfolio["positions"]:
            lines.append(f"- {p['name']}({p['code']})  买入价:{p['buy_price']} 数量:{p['shares']}")
        lines.append(f"现金余额: {portfolio.get('cash', 0):.0f}")
    else:
        lines.append("空仓")
        lines.append(f"现金余额: {portfolio.get('cash', 0):.0f}")

    return "\n".join(lines)


def generate_comparison_report() -> str:
    """生成双策略对比报告"""
    lines = []
    lines.append("# 仲达 vs 凤雏 — 双策略对比报告")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    for strategy in ["fengchu", "zhongda"]:
        p = load_portfolio(strategy)
        trades = load_trades(strategy)
        label = "凤雏" if strategy == "fengchu" else "仲达"

        lines.append(f"## {label} ({strategy})")
        lines.append("")
        lines.append(f"- 初始资金: {p.get('initial_capital', 0):.0f}")
        lines.append(f"- 当前现金: {p.get('cash', 0):.0f}")
        if p.get("positions"):
            pos_value = sum(pos["cost"] for pos in p["positions"])
            total = p.get("cash", 0) + pos_value
            lines.append(f"- 持仓市值: {pos_value:.0f}")
        else:
            total = p.get("cash", 0)
        lines.append(f"- 总资产: {total:.0f}")
        pnl = total - p.get("initial_capital", 0)
        pnl_pct = (pnl / p.get("initial_capital", 1)) * 100
        lines.append(f"- 总盈亏: {pnl:+.0f} ({pnl_pct:+.2f}%)")
        lines.append(f"- 已实现盈亏: {p.get('realized_pnl', 0):+.0f}")
        lines.append(f"- 交易次数: {len([t for t in trades if t['type'] == 'sell'])}笔已完成")
        lines.append("")

    lines.append("---")
    lines.append("")
    # Determine winner
    f_p = load_portfolio("fengchu")
    l_p = load_portfolio("zhongda")
    f_total = f_p.get("cash", 0) + sum(p["cost"] for p in f_p.get("positions", []))
    l_total = l_p.get("cash", 0) + sum(p["cost"] for p in l_p.get("positions", []))
    f_pnl = f_total - f_p.get("initial_capital", 0)
    l_pnl = l_total - l_p.get("initial_capital", 0)
    f_pnl_pct = (f_pnl / f_p.get("initial_capital", 1)) * 100
    l_pnl_pct = (l_pnl / l_p.get("initial_capital", 1)) * 100

    if f_pnl_pct > l_pnl_pct:
        lines.append(f"**🏆 当前领先: 凤雏**  ({f_pnl_pct:+.2f}% vs {l_pnl_pct:+.2f}%)")
    elif l_pnl_pct > f_pnl_pct:
        lines.append(f"**🏆 当前领先: 仲达**  ({l_pnl_pct:+.2f}% vs {f_pnl_pct:+.2f}%)")
    else:
        lines.append("**🤝 双方持平**")

    return "\n".join(lines)


def save_report(content: str, strategy: str, date: str, report_type: str = "daily"):
    """保存报告到文件"""
    if report_type == "daily":
        subdir = "daily"
        filename = f"{date}.md"
    elif report_type == "comparison":
        subdir = "comparison"
        filename = f"comparison_{date}.md"
    else:
        subdir = "other"
        filename = f"{report_type}_{date}.md"

    out_dir = os.path.join(BASE_DIR, "reports", subdir)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
