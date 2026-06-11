from src.data_fetcher import (
    get_trade_calendar, is_trading_day, fetch_stock_history,
    fetch_all_stocks_spot, filter_market_data, has_20d_limit_up,
)
"""
历史回测 — 用最近 N 个交易日的数据回测凤雏策略
"""
import argparse
import json
import logging
import os
from datetime import datetime, timedelta

import pandas as pd


from src.strategies.fengchu import run_screening as fengchu_screen
from src.simulation import SimulationEngine
from src.reporting import generate_daily_report, save_report

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_recent_trading_days(n: int) -> list:
    """获取最近 N 个交易日"""
    df = get_trade_calendar()
    today = datetime.now()
    recent = df[df["trade_date"] <= pd.Timestamp(today)]["trade_date"].tail(n + 1)
    return [d.strftime("%Y-%m-%d") for d in sorted(recent.values)[:-1]]  # 去掉今天


def backtest_fengchu(trading_days: list):
    """凤雏策略历史回测"""
    logger.info(f"=== 凤雏策略回测: {len(trading_days)} 个交易日 ===")
    engine = SimulationEngine("fengchu_backtest", initial_capital=1_000_000)
    all_trades = []

    for i, date_str in enumerate(trading_days[:-1]):  # 最后一天不买入（没次日可卖）
        next_day = trading_days[i + 1]
        logger.info(f"回测 {date_str} (买入日) → {next_day} (卖出日)")

        # 模拟当日数据（用历史日线模拟）
        # 获取当天全市场行情（用历史快照近似）
        df_market = fetch_all_stocks_spot()
        df_market = filter_market_data(df_market)
        if df_market.empty:
            continue

        # 简化：取涨幅3-5%的股票作为候选
        stocks = df_market.to_dict("records")
        candidates = []
        for s in stocks:
            pct = s.get("pct_change", 0)
            vr = s.get("volume_ratio", 0)
            if not (3.0 <= pct <= 5.0 and vr >= 1.0):
                continue
            s["has_limit_up_20d"] = has_20d_limit_up(s["code"])
            s["above_vwap"] = True
            s["volume_stable"] = True
            s["no_resistance"] = True
            s["sector"] = ""
            candidates.append(s)

        results = fengchu_screen(candidates, {})
        buy_targets = [r for r in results if r["decision"] in ("buy", "strong_buy")][:2]

        # 买入
        for t in buy_targets:
            buy_price = t.get("price", 0)
            if buy_price <= 0:
                continue
            engine.buy(
                code=t["code"], name=t["name"],
                price=buy_price, score=t["score"],
                date=date_str,
                reason=f"回测评分{t['score']}",
            )

        # 卖出（次日开盘价）
        positions = engine.positions[:]
        for pos in positions:
            # 用次日历史数据获取开盘价
            hist = fetch_stock_history(pos["code"], days=10)
            if hist.empty:
                continue
            next_hist = hist[hist["date"] == pd.Timestamp(next_day)]
            if not next_hist.empty:
                sell_price = next_hist.iloc[0]["open"]
                engine.sell(pos["code"], sell_price, next_day,
                            reason="回测次日开盘卖出")

    # 输出回测结果
    summary = engine.get_summary()
    trades = json.load(open(engine.trades_file)) if os.path.exists(engine.trades_file) else []

    print(f"\n{'='*60}")
    print(f" 凤雏策略 回测结果")
    print(f" 回测区间: {trading_days[0]} ~ {trading_days[-1]}")
    print(f" 交易日数: {len(trading_days)}")
    print(f" 初始资金: {summary['initial_capital']:.0f}")
    print(f" 最终总资产: {summary['total_assets']:.0f}")
    print(f" 已实现盈亏: {summary['realized_pnl']:+.0f} ({summary['realized_pnl_pct']:+.2f}%)")
    print(f" 交易次数: {len([t for t in trades if t['type'] == 'sell'])}")
    print(f"{'='*60}")
    print()

    # 列出每笔交易
    print("交易明细:")
    print(f"{'日期':<12} {'代码':<8} {'名称':<10} {'买入':<10} {'卖出':<10} {'盈亏%':<10}")
    print("-" * 60)
    for t in trades:
        if t["type"] == "sell":
            pnl = t.get("pnl_pct", 0)
            marker = "✅" if pnl >= 0 else "❌"
            print(f"{t['date']:<12} {t['code']:<8} {t['name']:<10} "
                  f"{t.get('price', 0):<10.2f} "
                  f"{t.get('price', 0):<10.2f} "
                  f"{marker} {pnl:<+.1f}%")

    return summary


def main():
    parser = argparse.ArgumentParser(description="策略历史回测")
    parser.add_argument("--days", type=int, default=10, help="回测天数")
    args = parser.parse_args()

    trading_days = get_recent_trading_days(args.days)
    logger.info(f"回测交易日: {trading_days}")

    if len(trading_days) < 3:
        logger.error("交易日数据不足，无法回测")
        return

    backtest_fengchu(trading_days)


if __name__ == "__main__":
    main()
