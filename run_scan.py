"""
每日市场扫描主入口

用法:
  python run_scan.py --strategy fengchu          # 凤雏日筛
  python run_scan.py --strategy liuxiu           # 刘秀周筛
  python run_scan.py --both                       # 双策略
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
    fetch_sector_top_gainers, fetch_stock_sector_map,
    has_20d_limit_up, is_trading_day, get_next_trading_day,
)
from src.strategies.fengchu import run_screening as fengchu_screen
from src.strategies.liuxiu import calculate_liuxiu_score, score_sepa_template
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
    except:
        return {}


def process_fengchu_scan(date_str: str):
    """青鸾：日筛 + 全仓模拟交易"""
    logger.info(f"═══ 青鸾策略日筛 [{date_str}] ═══")

    df = fetch_all_stocks_spot()
    if df.empty:
        return []

    sector_ranks = build_sector_ranks()
    df_cand = df[(df["pct_change"] >= 3) & (df["pct_change"] <= 5)].copy()
    logger.info(f"涨幅3-5%候选: {len(df_cand)}")

    if df_cand.empty:
        return []

    stocks = df_cand.to_dict("records")
    for s in stocks:
        s["has_limit_up_20d"] = has_20d_limit_up(s["code"])
        s["above_vwap"] = True
        s["volume_stable"] = True
        s["no_resistance"] = True

    results = fengchu_screen(stocks, sector_ranks)

    out_path = os.path.join(BASE_DIR, "output", "fengchu", "candidates",
                            f"screening_{date_str}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    engine = SimulationEngine("fengchu", initial_capital=2000)

    # 先卖出昨日持仓
    old_portfolio = load_portfolio("fengchu")
    if old_portfolio.get("positions"):
        for pos in old_portfolio["positions"]:
            code = pos["code"]
            hist = fetch_stock_history(code, days=5)
            sell_price = 0
            if not hist.empty:
                today_row = hist[hist["date"] == pd.Timestamp(date_str)]
                if not today_row.empty:
                    sell_price = today_row.iloc[0]["open"]
            if sell_price <= 0:
                stock_row = df[df["code"] == code]
                if not stock_row.empty:
                    sell_price = stock_row.iloc[0].get("price", 0)
            if sell_price > 0:
                pnl = (sell_price - pos["buy_price"]) / pos["buy_price"] * 100
                if pnl >= 3:
                    r = f"止盈+{pnl:.1f}% ✅"
                elif pnl <= -2:
                    r = f"止损{pnl:.1f}% ❌"
                else:
                    r = f"时间止损{pnl:+.1f}% ⏰"
                engine.sell(code, sell_price, date_str, r)

    # 全仓买入 #1
    buy_targets = [r for r in results if r["decision"] in ("buy", "strong_buy")][:1]
    for t in buy_targets:
        engine.buy(code=t["code"], name=t["name"],
                   price=t.get("price", 0), score=t["score"],
                   date=date_str, reason=f"评分{t['score']} 全仓")

    report = generate_daily_report("fengchu", date_str, results)
    path = save_report(report, "fengchu", date_str, "daily")
    logger.info(f"青鸾日报 → {path}")

    summary = engine.get_summary()
    print(f"\n【青鸾 {date_str}】全仓第{1 if buy_targets else 0}笔")
    for t in buy_targets:
        print(f"  🟢 {t['name']}({t['code']}) 评分:{t['score']} 价格:{t.get('price',0):.2f}")
    print(f"  现金:{summary['cash']:.0f} 总资产:{summary['total_assets']:.0f}")
    return results


def process_liuxiu_scan(date_str: str):
    """仲达：SEPA周筛 + 全仓模拟交易"""
    logger.info(f"═══ 仲达策略周筛 [{date_str}] ═══")

    df = fetch_all_stocks_spot()
    if df.empty:
        return []

    sector_ranks = build_sector_ranks()
    sector_map = fetch_stock_sector_map()

    # 候选范围：60日上涨 > 10% + 有量
    df_cand = df[(df.get("pct_60d", 0) > 10) & (df["amount"] > 5000_0000)].copy()
    if df_cand.empty:
        logger.info("60日上涨>10%的候选为空，放宽条件")
        df_cand = df[df["amount"] > 3000_0000].head(200).copy()

    df_cand = df_cand.head(100)  # 取前100只评分
    logger.info(f"仲达候选: {len(df_cand)} 只（将获取历史数据评分）")

    results = []
    stocks = df_cand.to_dict("records")
    for i, s in enumerate(stocks):
        code = s["code"]
        hist = fetch_stock_history(code, days=260)
        if hist.empty or len(hist) < 200:
            continue

        sector_name = sector_map.get(code, "")
        srank = sector_ranks.get(sector_name)
        pct_5d = s.get("pct_5d", 0) or 0
        pct_60d = s.get("pct_60d", 0) or 0

        score_info = calculate_liuxiu_score(
            code=code, name=s.get("name", ""),
            df_hist=hist, pct_5d=float(pct_5d),
            pct_60d=float(pct_60d),
            sector_rank=srank, sector_name=sector_name,
        )
        if score_info["score"] >= 60:
            results.append(score_info)
        if (i + 1) % 20 == 0:
            logger.info(f"  评分进度: {i+1}/{len(stocks)}")

    results.sort(key=lambda x: x["score"], reverse=True)

    out_path = os.path.join(BASE_DIR, "output", "liuxiu", "candidates",
                            f"screening_{date_str}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    # 模拟交易（全仓买入#1）
    engine = SimulationEngine("liuxiu", initial_capital=2000)
    buy_targets = [r for r in results if r["decision"] in ("buy", "strong_buy")][:1]
    for t in buy_targets:
        engine.buy(code=t["code"], name=t["name"],
                   price=t.get("price", 0), score=t["score"],
                   date=date_str, reason=f"刘秀周筛 评分{t['score']} 全仓")

    # 打印结果
    print(f"\n【仲达 {date_str}】SEPA周筛")
    print(f"  筛选: {len(results)} 只通过")
    for r in results[:5]:
        dec = {"strong_buy":"🟢","buy":"🟡","watch":"⚪","ignore":"⚫"}.get(r["decision"],"⚫")
        print(f"  {dec} {r['name']}({r['code']}) 评分:{r['score']} "
              f"SEPA:{r.get('sepa_score',0)} VCP:{r.get('vcp_score',0)} "
              f"环境:{r.get('env_score',0)} 基本面:{r.get('fundamental_score',0)}")
    if buy_targets:
        summary = engine.get_summary()
        print(f"  买入: {buy_targets[0]['name']}({buy_targets[0]['code']}) "
              f"全仓 {summary['total_buy_value']:.0f}元")
    else:
        print(f"  本次无符合条件的买入")

    # 保存快照
    report_path = os.path.join(BASE_DIR, "output", "liuxiu", "reports",
                                f"market_snapshot_{date_str}.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    sectors_info = dict(list(sector_ranks.items())[:5])
    lines = [f"# 刘秀周筛 {date_str}", "",
             f"候选: {len(results)} 只 | 买入: {len(buy_targets)} 只",
             f"板块: {sectors_info}", ""]
    if buy_targets:
        lines.append(f"持仓: {buy_targets[0]['name']}({buy_targets[0]['code']}) 评分:{buy_targets[0]['score']}")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    return results


def main():
    parser = argparse.ArgumentParser(description="每日市场扫描")
    parser.add_argument("--strategy", choices=["fengchu", "liuxiu", "both"], default="fengchu")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    date_str = args.date

    if not is_trading_day(date_str):
        logger.info(f"{date_str} 不是交易日")
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
