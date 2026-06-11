"""
凤雏早盘卖出脚本 — 09:30-10:00 执行

规则（凤雏战法执行手册 第六章）：
  - 次日 09:30-10:00 必须卖出（除涨停）
  - +3% 止盈 → 立即市价卖出
  - -2% 止损 → 立即市价卖出
  - 10:00 未达止盈止损，时间止损强制清仓
"""
import json
import logging
import os
import sys
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.data_fetcher import fetch_stock_history, is_trading_day
from src.simulation import SimulationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def morning_sell(date_str: str = None):
    """早盘卖出：用今日开盘价卖出昨日持仓"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    if not is_trading_day(date_str):
        logger.info(f"{date_str} 不是交易日，跳过卖出")
        return

    engine = SimulationEngine("fengchu", initial_capital=1_000_000)

    # 读取持仓
    if not os.path.exists(engine.portfolio_file):
        logger.info("无持仓文件，无需卖出")
        return

    with open(engine.portfolio_file) as f:
        portfolio = json.load(f)

    positions = portfolio.get("positions", [])
    if not positions:
        logger.info("无持仓，无需卖出")
        return

    logger.info(f"=== 凤雏早盘卖出 [{date_str}] 持仓 {len(positions)} 只 ===")

    sold_count = 0
    for pos in positions:
        code = pos["code"]
        name = pos["name"]
        buy_price = pos["buy_price"]

        # 获取今日开盘价（09:30 的第一笔成交价）
        hist = fetch_stock_history(code, days=5)
        sell_price = 0
        if not hist.empty:
            today_row = hist[hist["date"] == pd.Timestamp(date_str)]
            if not today_row.empty:
                sell_price = today_row.iloc[0]["open"]  # 09:30 开盘价

        if sell_price <= 0:
            logger.warning(f"{name}({code}) 无法获取开盘价，使用最新价(需手动确认)")
            continue

        pnl_pct = (sell_price - buy_price) / buy_price * 100

        # 规则：+3%止盈 / -2%止损 / 时间止损
        if pnl_pct >= 3:
            reason = f"止盈 +{pnl_pct:.1f}% ✅"
        elif pnl_pct <= -2:
            reason = f"止损 {pnl_pct:.1f}% ❌"
        else:
            reason = f"10:00 时间止损 {pnl_pct:+.1f}% ⏰"

        engine.sell(code, sell_price, date_str, reason)
        sold_count += 1
        print(f"  {'✅' if pnl_pct >= 0 else '❌'} {name}({code}) "
              f"买入:{buy_price:.2f} → 卖出:{sell_price:.2f} "
              f"盈亏:{pnl_pct:+.1f}% | {reason}")

    logger.info(f"早盘卖出完成: {sold_count} 笔")

    # 输出资金状态
    summary = engine.get_summary()
    print(f"\n  ── 资金状态 ──")
    print(f"  现金: {summary['cash']:,.0f}")
    print(f"  已实现盈亏: {summary['realized_pnl']:+,.0f} ({summary['realized_pnl_pct']:+.2f}%)")
    print(f"  总资产: {summary['total_assets']:,.0f}")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    morning_sell(date_arg)
