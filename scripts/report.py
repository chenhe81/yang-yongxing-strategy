"""
杨永兴短线战法 - 报告生成
"""

import os
import json
import datetime
import numpy as np
from config import REPORTS_DIR


class NumpyEncoder(json.JSONEncoder):
    """处理numpy类型的JSON编码器"""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def generate_scan_report(scan_result):
    """生成选股扫描报告"""
    candidates = scan_result.get("candidates", [])
    market = scan_result.get("market", {})
    filter_log = scan_result.get("filter_log", [])
    scan_time = scan_result.get("scan_time", "")

    lines = []
    lines.append("=" * 70)
    lines.append("📊 杨永兴短线战法 - 尾盘选股扫描报告")
    lines.append(f"📅 扫描时间：{scan_time}")
    lines.append("=" * 70)

    # 大盘环境
    lines.append("\n📈 大盘环境")
    lines.append("-" * 40)
    trend = market.get("trend", "unknown")
    trend_emoji = {"up": "🟢 上升", "down": "🔴 下降", "flat": "🟡 横盘"}.get(trend, "⚪ 未知")
    lines.append(f"  趋势：{trend_emoji}")
    if market.get("change_pct") is not None:
        lines.append(f"  涨跌幅：{market['change_pct']:.2f}%")
    if market.get("is_crash"):
        lines.append("  ⚠️ 大盘放量大跌，建议空仓！")

    # 过滤步骤
    if filter_log:
        lines.append("\n🔍 筛选过程")
        lines.append("-" * 40)
        for log in filter_log:
            filtered = log.get("filtered", 0)
            lines.append(
                f"  步骤{log['step']}：{log['action']} → "
                f"过滤 {filtered} 只，剩余 {log['count_after']} 只"
            )

    # 候选股
    if not candidates:
        lines.append("\n❌ 今日无符合条件的候选股")
    else:
        lines.append(f"\n✅ 符合条件的候选股（共{len(candidates)}只）")
        lines.append("=" * 70)
        lines.append(
            f"{'序号':<4} {'代码':<8} {'名称':<10} {'现价':<8} "
            f"{'涨幅%':<8} {'量比':<6} {'换手%':<8} {'流通市值(亿)':<12}"
        )
        lines.append("-" * 70)
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"{i:<4} {c.get('code', ''):<8} {c.get('name', ''):<10} "
                f"{c.get('price', 0):<8.2f} {c.get('change_pct', 0):<8.2f} "
                f"{c.get('volume_ratio', 0):<6.2f} {c.get('turnover_rate', 0):<8.2f} "
                f"{c.get('circ_mv_billion', 0):<12.1f}"
            )
        lines.append("-" * 70)

        # 操作建议
        lines.append("\n💡 操作建议")
        lines.append("-" * 40)
        lines.append("  1. 14:30-14:50 观察候选股走势")
        lines.append("  2. 重点关注：创新高大单拉升 → 第一买点")
        lines.append("  3. 回踩不破均价线勾头向上 → 第二买点")
        lines.append("  4. 突破短期前高 → 第三买点")
        lines.append("  5. ⚠️ 次日早盘10:30前必须清仓！")

    # 存量提示
    lines.append("\n" + "=" * 70)
    lines.append("⚠️ 免责声明：本报告仅供学习研究，不构成投资建议。")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    # 保存到文件
    today = datetime.date.today().strftime("%Y%m%d")
    filepath = os.path.join(REPORTS_DIR, f"scan_{today}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    # 同时保存JSON数据
    json_filepath = os.path.join(REPORTS_DIR, f"scan_{today}.json")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(scan_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)

    return report_text, filepath


def generate_sepa_report(sepa_result):
    """生成SEPA策略选股报告"""
    candidates = sepa_result.get("candidates", [])
    filter_log = sepa_result.get("filter_log", [])
    scan_time = sepa_result.get("scan_time", "")

    lines = []
    lines.append("=" * 70)
    lines.append("📊 米勒维尼SEPA策略 + 杨永兴战法 - 选股扫描报告")
    lines.append(f"📅 扫描时间：{scan_time}")
    lines.append("=" * 70)

    # 策略说明
    lines.append("\n📖 策略说明")
    lines.append("-" * 40)
    lines.append("  基于马克·米勒维尼《股票魔法师》SEPA策略：")
    lines.append("  1. 剔除ST和上市不满1年的次新股")
    lines.append("  2. 最近季度营收同比增长率 > 25%")
    lines.append("  3. 最近季度净利润同比增长率 > 30%，且环比为正")
    lines.append("  4. 当前股价在50日均线和150日均线之上")
    lines.append("  5. 最近10个交易日平均成交量 > 120日均量（放量）")
    lines.append("  6. 净资产收益率（ROE）> 15%")
    lines.append("  7. 最近三年净利润复合增长率 > 20%")

    # 过滤步骤
    if filter_log:
        lines.append("\n🔍 筛选过程")
        lines.append("-" * 40)
        for log in filter_log:
            filtered = log.get("filtered", 0)
            lines.append(
                f"  步骤{log['step']}：{log['action']} → "
                f"过滤 {filtered} 只，剩余 {log['count_after']} 只"
            )

    # 候选股
    if not candidates:
        lines.append("\n❌ 今日无符合SEPA策略条件的候选股")
    else:
        lines.append(f"\n✅ 符合SEPA策略条件的候选股（共{len(candidates)}只）")
        lines.append("=" * 70)
        lines.append(
            f"{'序号':<4} {'代码':<8} {'名称':<10} {'现价':<8} "
            f"{'涨幅%':<8} {'营收增长%':<10} {'净利增长%':<10} {'ROE%':<8}"
        )
        lines.append("-" * 70)
        for i, c in enumerate(candidates, 1):
            rev_g = f"{c['revenue_growth_yoy']:.1f}" if c.get("revenue_growth_yoy") is not None else "N/A"
            profit_g = f"{c['profit_growth_yoy']:.1f}" if c.get("profit_growth_yoy") is not None else "N/A"
            roe = f"{c['roe']:.1f}" if c.get("roe") is not None else "N/A"
            price_str = f"{c['price']:.2f}" if c.get("price") is not None else "N/A"
            change_str = f"{c['change_pct']:.2f}" if c.get("change_pct") is not None else "N/A"
            lines.append(
                f"{i:<4} {c.get('code', ''):<8} {c.get('name', ''):<10} "
                f"{price_str:<8} {change_str:<8} "
                f"{rev_g:<10} {profit_g:<10} {roe:<8}"
            )
        lines.append("-" * 70)

        # 操作建议
        lines.append("\n💡 操作建议")
        lines.append("-" * 40)
        lines.append("  1. SEPA策略侧重基本面成长性，适合中长线趋势跟踪")
        lines.append("  2. 结合杨永兴战法尾盘买入，可提高短线胜率")
        lines.append("  3. 关注VCP（波动率收缩形态）突破买点")
        lines.append("  4. 趋势交易纪律：截断亏损，让利润奔跑")

    lines.append("\n" + "=" * 70)
    lines.append("⚠️ 免责声明：本报告仅供学习研究，不构成投资建议。")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    # 保存到文件
    today = datetime.date.today().strftime("%Y%m%d")
    filepath = os.path.join(REPORTS_DIR, f"sepa_scan_{today}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    # 同时保存JSON数据
    json_filepath = os.path.join(REPORTS_DIR, f"sepa_scan_{today}.json")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(sepa_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)

    return report_text, filepath


def generate_combined_report(combined_result):
    """生成SEPA+杨永兴联合扫描报告"""
    final_candidates = combined_result.get("final_candidates", [])
    sepa_candidates = combined_result.get("sepa_candidates", [])
    filter_log = combined_result.get("filter_log", [])
    market = combined_result.get("market", {})
    market_status = combined_result.get("market_status", {})
    scan_time = combined_result.get("scan_time", "")
    warning = combined_result.get("warning", "")

    lines = []
    lines.append("=" * 70)
    lines.append("📊 SEPA策略 + 杨永兴战法 - 联合扫描报告")
    lines.append(f"📅 扫描时间：{scan_time}")
    lines.append("=" * 70)

    # 策略说明
    lines.append("\n📖 联合策略说明")
    lines.append("-" * 40)
    lines.append("  第一阶段 - SEPA七步基本面筛选（米勒维尼《股票魔法师》）：")
    lines.append("    1.剔除ST和次新股 2.营收增长>25% 3.净利增长>30%且环比正")
    lines.append("    4.股价>MA50/MA150 5.10日均量>120日均量 6.ROE>15% 7.3年CAGR>20%")
    lines.append("  第二阶段 - 杨永兴九步技术面筛选：")
    lines.append("    1.涨幅3%-5% 2.近20天有涨停 3.量比≥1 4.流通市值50-200亿")
    lines.append("    5.换手率5%-10% 6.振幅≤8% 7.K线无压力 8.分时站均价线上方")

    # 大盘环境
    lines.append("\n📈 大盘环境")
    lines.append("-" * 40)
    trend = market.get("trend", "unknown")
    trend_emoji = {"up": "🟢 上升", "down": "🔴 下降", "flat": "🟡 横盘"}.get(trend, "⚪ 未知")
    lines.append(f"  趋势：{trend_emoji}")
    if market.get("change_pct") is not None:
        lines.append(f"  涨跌幅：{market['change_pct']:.2f}%")
    if market_status.get("is_crash"):
        lines.append("  ⚠️ 大盘放量大跌，建议空仓！")
    if warning:
        lines.append(f"  ⚠️ {warning}")

    # 筛选步骤
    if filter_log:
        lines.append("\n🔍 筛选过程")
        lines.append("-" * 40)
        sepa_logs = [l for l in filter_log if l.get("phase") == "SEPA"]
        yang_logs = [l for l in filter_log if l.get("phase") == "杨永兴"]

        if sepa_logs:
            lines.append("  【第一阶段：SEPA基本面】")
            for log in sepa_logs:
                filtered = log.get("filtered", 0)
                lines.append(
                    f"    步骤{log['step']}：{log['action']} → "
                    f"过滤 {filtered} 只，剩余 {log['count_after']} 只"
                )

        if yang_logs:
            lines.append("  【第二阶段：杨永兴技术面】")
            for log in yang_logs:
                filtered = log.get("filtered", 0)
                lines.append(
                    f"    步骤{log['step']}：{log['action']} → "
                    f"过滤 {filtered} 只，剩余 {log['count_after']} 只"
                )

    # SEPA候选
    lines.append(f"\n✅ SEPA七步筛选通过：{len(sepa_candidates)} 只")
    if sepa_candidates:
        for i, c in enumerate(sepa_candidates, 1):
            rev_g = f"{c['revenue_growth_yoy']:.1f}%" if c.get("revenue_growth_yoy") is not None else "N/A"
            profit_g = f"{c['profit_growth_yoy']:.1f}%" if c.get("profit_growth_yoy") is not None else "N/A"
            roe = f"{c['roe']:.1f}%" if c.get("roe") is not None else "N/A"
            price_str = f"{c['price']:.2f}" if c.get("price") is not None else "N/A"
            lines.append(f"  {i}. {c['code']} {c['name']} 价格:{price_str} 营收+{rev_g} 净利+{profit_g} ROE:{roe}")

    # 最终候选
    if not final_candidates:
        lines.append(f"\n🎯 SEPA + 杨永兴联合筛选：0 只")
        lines.append("\n💡 SEPA候选股基本面优秀但今日不满足杨永兴短线技术面要求，")
        lines.append("   可关注后续回调/放量时的买入时机。")
    else:
        lines.append(f"\n🌟 SEPA + 杨永兴联合筛选通过：{len(final_candidates)} 只（最高确定性）")
        lines.append("=" * 70)
        for i, c in enumerate(final_candidates, 1):
            rev_g = f"{c['revenue_growth_yoy']:.1f}%" if c.get("revenue_growth_yoy") is not None else "N/A"
            profit_g = f"{c['profit_growth_yoy']:.1f}%" if c.get("profit_growth_yoy") is not None else "N/A"
            roe = f"{c['roe']:.1f}%" if c.get("roe") is not None else "N/A"
            price_str = f"{c['price']:.2f}" if c.get("price") is not None else "N/A"
            chg = f"{c.get('change_pct', 0):.2f}" if c.get("change_pct") is not None else "N/A"
            lines.append(f"  {i}. {c['code']} {c['name']} 价格:{price_str} 涨幅:{chg}%")
            lines.append(f"     基本面: 营收+{rev_g} 净利+{profit_g} ROE:{roe}")
            vol_r = f"{c.get('volume_ratio', 'N/A')}"
            turn = f"{c.get('turnover_rate', 'N/A')}"
            mv = f"{c.get('circ_mv_billion', 'N/A')}"
            lines.append(f"     技术面: 量比:{vol_r} 换手:{turn}% 市值:{mv}亿")
        lines.append("-" * 70)
        lines.append("\n💡 操作建议")
        lines.append("-" * 40)
        lines.append("  1. 这些股票同时满足基本面+技术面，确定性最高")
        lines.append("  2. 14:30-14:50观察走势，选择买点")
        lines.append("  3. 次日早盘10:30前必须清仓（杨永兴铁律）")
        lines.append("  4. 若无联合候选，关注SEPA候选的回调买点")

    lines.append("\n" + "=" * 70)
    lines.append("⚠️ 免责声明：本报告仅供学习研究，不构成投资建议。")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    # 保存
    today = datetime.date.today().strftime("%Y%m%d")
    filepath = os.path.join(REPORTS_DIR, f"combined_scan_{today}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    json_filepath = os.path.join(REPORTS_DIR, f"combined_scan_{today}.json")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(combined_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder, default=str)

    return report_text, filepath


def generate_sell_report(sell_result):
    """生成卖出信号报告"""
    signals = sell_result.get("signals", [])
    check_time = sell_result.get("check_time", "")

    lines = []
    lines.append("=" * 70)
    lines.append("🔔 杨永兴短线战法 - 次日卖出信号检查")
    lines.append(f"📅 检查时间：{check_time}")
    lines.append("=" * 70)

    if not signals:
        lines.append("\n📋 当前无持仓，无需检查")
    else:
        sell_signals = [s for s in signals if s.get("action") == "sell"]
        watch_signals = [s for s in signals if s.get("action") == "watch"]
        hold_signals = [s for s in signals if s.get("action") == "hold"]

        # 需要卖出的
        if sell_signals:
            lines.append(f"\n🔴 需要卖出（{len(sell_signals)}只）")
            lines.append("-" * 60)
            for s in sell_signals:
                urgency = {"critical": "‼️紧急", "urgent": "⚠️重要", "normal": "📌普通"}.get(
                    s.get("urgency", "normal"), "📌普通"
                )
                profit = s.get("profit_pct", "")
                profit_str = f"（盈亏 {profit:+.2f}%）" if isinstance(profit, (int, float)) else ""
                lines.append(f"  {urgency} {s.get('code', '')} {s.get('name', '')}{profit_str}")
                lines.append(f"       原因：{s.get('reason', '')}")
                lines.append(f"       现价：{s.get('current_price', 0):.2f}  开盘类型：{s.get('open_type', '')}")

        # 需要观察的
        if watch_signals:
            lines.append(f"\n🟡 需要观察（{len(watch_signals)}只）")
            lines.append("-" * 60)
            for s in watch_signals:
                profit = s.get("profit_pct", "")
                profit_str = f"（盈亏 {profit:+.2f}%）" if isinstance(profit, (int, float)) else ""
                lines.append(f"  📌 {s.get('code', '')} {s.get('name', '')}{profit_str}")
                lines.append(f"       {s.get('reason', '')}")

        # 继续持有的
        if hold_signals:
            lines.append(f"\n🟢 继续持有观察（{len(hold_signals)}只）")
            lines.append("-" * 60)
            for s in hold_signals:
                profit = s.get("profit_pct", "")
                profit_str = f"（盈亏 {profit:+.2f}%）" if isinstance(profit, (int, float)) else ""
                lines.append(f"  📌 {s.get('code', '')} {s.get('name', '')}{profit_str}")
                lines.append(f"       {s.get('reason', '')}")

    lines.append("\n" + "=" * 70)
    lines.append("⚠️ 铁律：次日早盘必须清仓，除非缩量涨停或一字涨停！")
    lines.append("=" * 70)

    report_text = "\n".join(lines)

    # 保存
    today = datetime.date.today().strftime("%Y%m%d")
    filepath = os.path.join(REPORTS_DIR, f"sell_{today}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    json_filepath = os.path.join(REPORTS_DIR, f"sell_{today}.json")
    with open(json_filepath, "w", encoding="utf-8") as f:
        json.dump(sell_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)

    return report_text, filepath
