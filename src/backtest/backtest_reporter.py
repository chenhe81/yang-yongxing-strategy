"""
回测报告模块 — 格式化输出回测结果

设计：
  - 终端表格输出（美观易读）
  - 可选 CSV/JSON 导出
  - 交易明细 + 汇总指标
"""
import csv
import json
import logging
import os
from datetime import datetime
from typing import List

from src.backtest.backtest_engine import BacktestResult, BacktestTrade

logger = logging.getLogger(__name__)


# ── 终端格式化输出 ──

def _fmt_pct(value: float, color: bool = True) -> str:
    """格式化百分比，带颜色标记"""
    if not color:
        return f"{value:+.2f}%"
    if value > 0:
        return f"\033[32m{value:+.2f}%\033[0m"
    elif value < 0:
        return f"\033[31m{value:+.2f}%\033[0m"
    return f"{value:+.2f}%"


def _fmt_value(value: float) -> str:
    """格式化数字"""
    if abs(value) >= 1e8:
        return f"{value/1e8:.2f}亿"
    elif abs(value) >= 1e4:
        return f"{value/1e4:.2f}万"
    return f"{value:.2f}"


def print_result_header(result: BacktestResult):
    """打印单个回测结果的标题"""
    config = result.config
    print(f"\n{'='*70}")
    print(f"  📊 {config.name}")
    print(f"{'='*70}")


def print_result_summary(result: BacktestResult):
    """打印汇总指标"""
    print(f"\n  ▸ 总收益率:      {_fmt_pct(result.total_return_pct)}")
    print(f"  ▸ 年化收益率:    {_fmt_pct(result.annual_return_pct)}")
    print(f"  ▸ 胜率:          {_fmt_pct(result.win_rate, color=False)}")
    print(f"  ▸ 盈亏比:        {result.profit_loss_ratio:.2f}" if result.profit_loss_ratio != float("inf") else "  ▸ 盈亏比:        ∞")
    print(f"  ▸ 最大回撤:      {_fmt_pct(-result.max_drawdown_pct, color=False)}")
    print(f"  ▸ 夏普比率:      {result.sharpe_ratio:.2f}")
    print(f"  ▸ 交易次数:      {result.trade_count} (胜:{result.win_count} 负:{result.loss_count})")

    # 交易明细摘要
    if result.trades:
        pnl_values = [t.pnl_pct for t in result.trades]
        print(f"  ▸ 单笔盈亏范围:  {min(pnl_values):+.2f}% ~ {max(pnl_values):+.2f}%")

        # 平均持仓盈亏
        avg_pnl = sum(pnl_values) / len(pnl_values)
        print(f"  ▸ 平均单笔盈亏:  {_fmt_pct(avg_pnl)}")


def print_trade_details(result: BacktestResult, max_trades: int = 20):
    """打印交易明细"""
    if not result.trades:
        print("  (无交易)")
        return

    trades = result.trades[:max_trades]
    print(f"\n  交易明细 ({min(len(result.trades), max_trades)}/{len(result.trades)} 笔):")
    print(f"  {'日期':<12} {'代码':<8} {'名称':<10} {'买入价':<10} {'卖出价':<10} {'盈亏%':<10} {'评分':<6}")
    print(f"  {'-'*66}")

    for t in trades:
        marker = "✅" if t.pnl > 0 else "❌"
        print(f"  {t.buy_date:<12} {t.code:<8} {t.name:<10} "
              f"{t.buy_price:<10.2f} {t.sell_price:<10.2f} "
              f"{marker} {t.pnl_pct:<+7.1f}%  {t.score:<4}")

    if len(result.trades) > max_trades:
        print(f"  ... 还有 {len(result.trades) - max_trades} 笔交易未显示")


def print_comparison_table(results: List[BacktestResult]):
    """打印多组参数对比表"""
    if len(results) <= 1:
        return

    print(f"\n{'='*70}")
    print(f"  📊 参数对比汇总")
    print(f"{'='*70}")
    print(f"  {'参数组':<18} {'总收益率':<12} {'胜率':<10} {'盈亏比':<10} {'最大回撤':<12} {'夏普':<8} {'交易':<6}")
    print(f"  {'-'*76}")

    for r in results:
        dd_str = f"{r.max_drawdown_pct:.1f}%"
        pl_str = f"{r.profit_loss_ratio:.2f}" if r.profit_loss_ratio != float("inf") else "∞"
        tot_str = f"{r.total_return_pct:+.2f}%"
        win_str = f"{r.win_rate:.1f}%"
        sharpe_str = f"{r.sharpe_ratio:.2f}"
        print(f"  {r.config.name:<18} {tot_str:<12} {win_str:<10} {pl_str:<10} {dd_str:<12} {sharpe_str:<8} {r.trade_count:<6}")

    # 找最优
    if results:
        best_return = max(results, key=lambda r: r.total_return_pct)
        best_sharpe = max(results, key=lambda r: r.sharpe_ratio)
        best_win = max(results, key=lambda r: r.win_rate)
        print(f"\n  最优总收益率:  {best_return.config.name} ({best_return.total_return_pct:+.2f}%)")
        print(f"  最优夏普比率:  {best_sharpe.config.name} ({best_sharpe.sharpe_ratio:.2f})")
        print(f"  最高胜率:      {best_win.config.name} ({best_win.win_rate:.1f}%)")


def print_full_report(results: List[BacktestResult], trading_days_range: str = ""):
    """打印完整回测报告"""
    print(f"\n{'#'*70}")
    print(f"#  凤雏策略回测报告")
    if trading_days_range:
        print(f"#  回测区间: {trading_days_range}")
    print(f"{'#'*70}")
    print(f"  报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if len(results) == 1:
        r = results[0]
        print_result_header(r)
        print_result_summary(r)
        print_trade_details(r)
    else:
        for i, r in enumerate(results):
            print_result_header(r)
            print_result_summary(r)
            print_trade_details(r)
        print_comparison_table(results)

    print(f"\n{'#'*70}\n")


# ── 文件导出 ──

def export_results_csv(results: List[BacktestResult], output_path: str = None):
    """导出回测结果到 CSV"""
    if output_path is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "output", "backtest")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir,
                                   f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # 汇总表
        writer.writerow(["参数组", "总收益率%", "年化收益率%", "胜率%", "盈亏比",
                         "最大回撤%", "夏普比率", "交易次数", "盈利次数", "亏损次数"])
        for r in results:
            pl = r.profit_loss_ratio if r.profit_loss_ratio != float("inf") else 999
            writer.writerow([
                r.config.name,
                r.total_return_pct,
                r.annual_return_pct,
                r.win_rate,
                pl,
                r.max_drawdown_pct,
                r.sharpe_ratio,
                r.trade_count,
                r.win_count,
                r.loss_count,
            ])

        # 空行
        writer.writerow([])
        writer.writerow([])

        # 交易明细表
        writer.writerow(["参数组", "买入日期", "卖出日期", "代码", "名称",
                         "买入价", "卖出价", "数量", "盈亏", "盈亏%", "评分"])
        for r in results:
            for t in r.trades:
                writer.writerow([
                    r.config.name,
                    t.buy_date,
                    t.sell_date,
                    t.code,
                    t.name,
                    t.buy_price,
                    t.sell_price,
                    t.shares,
                    t.pnl,
                    t.pnl_pct,
                    t.score,
                ])

    logger.info(f"回测结果已导出: {output_path}")
    return output_path


def export_results_json(results: List[BacktestResult], output_path: str = None):
    """导出回测结果到 JSON"""
    if output_path is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "output", "backtest")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir,
                                   f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    data = []
    for r in results:
        trades_data = []
        for t in r.trades:
            trades_data.append({
                "code": t.code,
                "name": t.name,
                "buy_date": t.buy_date,
                "sell_date": t.sell_date,
                "buy_price": t.buy_price,
                "sell_price": t.sell_price,
                "shares": t.shares,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "score": t.score,
            })

        config_data = {
            k: getattr(r.config, k) for k in dir(r.config)
            if not k.startswith("_")
        }

        data.append({
            "config": {k: v for k, v in config_data.items() if not callable(v)},
            "summary": {
                "total_return_pct": r.total_return_pct,
                "annual_return_pct": r.annual_return_pct,
                "win_rate": r.win_rate,
                "profit_loss_ratio": r.profit_loss_ratio,
                "max_drawdown_pct": r.max_drawdown_pct,
                "sharpe_ratio": r.sharpe_ratio,
                "trade_count": r.trade_count,
                "win_count": r.win_count,
                "loss_count": r.loss_count,
            },
            "trades": trades_data,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"回测结果已导出: {output_path}")
    return output_path
