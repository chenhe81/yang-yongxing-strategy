"""
每日市场扫描主入口

用法:
  python run_scan.py --strategy fengchu          # 凤雏日筛
  python run_scan.py --strategy liuxiu           # 刘秀周筛
  python run_scan.py --both                       # 双策略
  python run_scan.py --backtest --days 10        # 回测最近10天
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_fetcher import (
    fetch_all_stocks_spot, fetch_stock_history,
    fetch_sector_top_gainers,
    has_20d_limit_up, is_trading_day,
)
from src.strategies.fengchu import run_screening as fengchu_screen
from src.simulation import SimulationEngine
from src.reporting import (
    generate_daily_report, generate_comparison_report, save_report,
    load_portfolio, load_trades,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def build_sector_ranks() -> dict:
    try:
        sectors = fetch_sector_top_gainers(10)
        return {r["板块名称"]: i + 1 for i, (_, r) in enumerate(sectors.iterrows())}
    except Exception as e:
        logger.warning(f"获取板块排名失败: {e}")
        return {}


def process_fengchu_scan(date_str: str):
    """凤雏：日筛 + 模拟交易"""
    logger.info(f"═══ 凤雏策略日筛 [{date_str}] ═══")

    df = fetch_all_stocks_spot()
    if df.empty:
        logger.error("无法获取市场数据")
        return []

    sector_ranks = build_sector_ranks()

    df_candidates = df[(df["pct_change"] >= 3) & (df["pct_change"] <= 5)].copy()
    logger.info(f"涨幅3-5%候选: {len(df_candidates)}")
    if df_candidates.empty:
        logger.info("无候选股票")
        return []

    stocks = df_candidates.to_dict("records")
    for s in stocks:
        s["has_limit_up_20d"] = has_20d_limit_up(s["code"])
        s["above_vwap"] = True
        s["volume_stable"] = True
        s["no_resistance"] = True

    results = fengchu_screen(stocks, sector_ranks)

    # 保存筛选结果
    out_path = os.path.join(BASE_DIR, "output", "fengchu", "candidates",
                            f"screening_{date_str}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"筛选结果: {len(results)} 只候选")

    # === 模拟交易（先卖后买） ===
    engine = SimulationEngine("fengchu", initial_capital=1_000_000)

    # 步骤1: 卖出昨日持仓 — 使用今日开盘价（模拟09:30卖出）
    old_portfolio = load_portfolio("fengchu")
    if old_portfolio.get("positions"):
        for pos in old_portfolio["positions"]:
            code = pos["code"]
            name = pos["name"]
            buy_price = pos["buy_price"]

            # 优先读取今日开盘价（更接近真实09:30卖出场景）
            hist = fetch_stock_history(code, days=5)
            sell_price = 0
            if not hist.empty:
                today_row = hist[hist["date"] == pd.Timestamp(date_str)]
                if not today_row.empty:
                    sell_price = today_row.iloc[0]["open"]

            # 备用：用当前实时行情价格
            if sell_price <= 0:
                stock_row = df[df["code"] == code]
                if not stock_row.empty:
                    sell_price = stock_row.iloc[0].get("price", 0)

            if sell_price > 0:
                pnl_pct = (sell_price - buy_price) / buy_price * 100

                # 10:00 止盈/止损/时间止损规则
                if pnl_pct >= 3:
                    reason = f"止盈 +{pnl_pct:.1f}% ✅"
                elif pnl_pct <= -2:
                    reason = f"止损 {pnl_pct:.1f}% ❌"
                else:
                    reason = f"10:00时间止损 {pnl_pct:+.1f}% ⏰"

                engine.sell(code, sell_price, date_str, reason)

    # 步骤2: 买入今日新候选
    buy_targets = [r for r in results if r["decision"] in ("buy", "strong_buy")][:2]
    for t in buy_targets:
        engine.buy(
            code=t["code"], name=t["name"],
            price=t.get("price", 0),
            score=t["score"], date=date_str,
            reason=f"评分{t['score']} {t.get('decision','')}",
        )

    # 生成日报
    report = generate_daily_report("fengchu", date_str, results)
    path = save_report(report, "fengchu", date_str, "daily")
    logger.info(f"日报 → {path}")

    summary = engine.get_summary()
    print(f"\n{'═'*50}")
    print(f" 凤雏 [{date_str}] 日报")
    print(f" 候选: {len(results)} 只 | 买入: {len(buy_targets)} 只")
    print(f" 总资产: {summary['total_assets']:,.0f}")
    print(f" 已实现盈亏: {summary['realized_pnl']:+,.0f} "
          f"({summary['realized_pnl_pct']:+.2f}%)")
    print(f"{'═'*50}\n")

    # 打印今日操作
    trades = load_trades("fengchu")
    today_trades = [t for t in trades if t.get("date") == date_str]
    sells_today = [t for t in today_trades if t["type"] == "sell"]
    buys_today = [t for t in today_trades if t["type"] == "buy"]
    if sells_today:
        print("今日卖出:")
        for t in sells_today:
            pnl = t.get("pnl_pct", 0)
            print(f"  {'✅' if pnl >= 0 else '❌'} {t['name']}({t['code']}) "
                  f"盈亏:{pnl:+.1f}%")
    if buys_today:
        print("今日买入:")
        for t in buys_today:
            print(f"  🟢 {t['name']}({t['code']}) 价格:{t['price']:.2f} "
                  f"评分:{t.get('score','N/A')}")
    return results


def process_liuxiu_scan(date_str: str):
    """刘秀：周筛（市场快照）"""
    logger.info(f"═══ 刘秀策略 [{date_str}] ═══")
    report_path = os.path.join(BASE_DIR, "output", "liuxiu", "reports",
                                f"market_snapshot_{date_str}.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    sectors = build_sector_ranks()
    lines = [f"# 刘秀市场快照 {date_str}", "", "## 当日最强板块", ""]
    for name, rank in sorted(sectors.items(), key=lambda x: x[1])[:5]:
        lines.append(f"- {name} (排名:{rank})")
    lines.extend(["", "## 状态", "刘秀策略运行中（周日全量重筛 + 每日增量检查）", ""])
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n{'═'*50}")
    print(f" 刘秀 [{date_str}] 市场快照 → {report_path}")
    print(f"{'═'*50}\n")
    return []


def run_backtest(days: int = 10):
    """回顾式回测"""
    from src.data_fetcher import get_trade_calendar
    logger.info(f"═══ 凤雏策略回测: 最近 {days} 天 ═══")
    engine = SimulationEngine("fengchu_backtest", initial_capital=1_000_000)
    cal = get_trade_calendar()
    today = datetime.now()
    trading_days = sorted(
        cal[cal["trade_date"] <= pd.Timestamp(today)]["trade_date"].tail(days + 1).values
    )
    if len(trading_days) < 2:
        logger.error("交易日数据不足")
        return
    dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in trading_days]

    for i in range(len(dates) - 1):
        buy_date = dates[i]
        sell_date = dates[i + 1]
        logger.info(f"  回测 {buy_date} → {sell_date}")

        df = fetch_all_stocks_spot()
        df_candidates = df[(df["pct_change"] >= 3) & (df["pct_change"] <= 5)]
        stocks = df_candidates.to_dict("records")
        for s in stocks:
            s["has_limit_up_20d"] = has_20d_limit_up(s["code"])
            s["above_vwap"] = True
            s["volume_stable"] = True
            s["no_resistance"] = True

        results = fengchu_screen(stocks, {})
        buy_targets = [r for r in results if r["decision"] in ("buy", "strong_buy")][:2]
        for t in buy_targets:
            engine.buy(t["code"], t["name"], t.get("price", 0),
                       t["score"], buy_date, "回测")

        for pos in list(engine.positions):
            hist = fetch_stock_history(pos["code"], days=5)
            if hist.empty:
                continue
            sell_row = hist[hist["date"] == pd.Timestamp(sell_date)]
            if not sell_row.empty:
                engine.sell(pos["code"], sell_row.iloc[0]["open"],
                           sell_date, "回测次日卖出")

    summary = engine.get_summary()
    trades = load_trades("fengchu_backtest")
    print(f"\n{'═'*60}")
    print(f" 凤雏策略 回测结果")
    print(f" 区间: {dates[0]} ~ {dates[-1]}")
    print(f" 初始资金: {summary['initial_capital']:,.0f}")
    print(f" 最终总资产: {summary['total_assets']:,.0f}")
    print(f" 已实现盈亏: {summary['realized_pnl']:+,.0f} ({summary['realized_pnl_pct']:+.2f}%)")
    print(f" 交易次数: {len([t for t in trades if t['type'] == 'sell'])} 笔")
    print(f"{'═'*60}\n")
    sells = [t for t in trades if t["type"] == "sell"]
    print(f"{'日期':<12} {'代码':<8} {'名称':<10} {'盈亏%':<10}")
    print("-" * 40)
    for t in sells:
        pnl = t.get("pnl_pct", 0)
        print(f"{t['date']:<12} {t['code']:<8} {t['name']:<10} "
              f"{'✅' if pnl >= 0 else '❌'} {pnl:<+.1f}%")
    return summary


def main():
    parser = argparse.ArgumentParser(description="每日市场扫描")
    parser.add_argument("--strategy", choices=["fengchu", "liuxiu", "both"],
                        default="fengchu")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args()
    date_str = args.date

    if args.backtest:
        run_backtest(args.days)
        return

    if not is_trading_day(date_str):
        logger.info(f"{date_str} 不是交易日，跳过")
        return

    f_results = l_results = []
    if args.strategy in ("fengchu", "both"):
        f_results = process_fengchu_scan(date_str)
    if args.strategy in ("liuxiu", "both"):
        l_results = process_liuxiu_scan(date_str)

    if args.strategy == "both":
        report = generate_comparison_report()
        path = save_report(report, "comparison", date_str, "comparison")
        logger.info(f"对比报告 → {path}")
        print(report)


if __name__ == "__main__":
    main()
