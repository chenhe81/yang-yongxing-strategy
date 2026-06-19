#!/usr/bin/env python3
"""
凤雏策略参数化回测命令行入口

用法：
  # 默认回测60天，跑全部预设参数对比
  python run_backtest_fengchu.py

  # 指定天数
  python run_backtest_fengchu.py --days 30

  # 指定日期范围
  python run_backtest_fengchu.py --start 2026-03-01 --end 2026-06-01

  # 只跑默认配置（不对比）
  python run_backtest_fengchu.py --no-compare

  # 指定参数组（JSON格式）
  python run_backtest_fengchu.py --params '[{"换手下限":3,"换手上限":10,"name":"自定义"}]'

  # 导出到 CSV/JSON
  python run_backtest_fengchu.py --export-csv --export-json

  # 详细交易明细
  python run_backtest_fengchu.py --verbose

  # 模拟真实场景：之前 7 笔全亏的区间
  python run_backtest_fengchu.py --start 2026-06-11 --end 2026-06-17
"""
import argparse
import json
import logging
import sys
from datetime import datetime

from src.backtest.fengchu_backtest import (
    get_default_config, get_test_param_groups, run_fengchu_backtest,
)
from src.backtest.backtest_reporter import (
    print_full_report, print_trade_details, print_comparison_table,
    export_results_csv, export_results_json,
)
from src.backtest.backtest_engine import BacktestConfig, run_param_grid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="凤雏策略参数化回测 — 验证参数优化效果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_backtest_fengchu.py --days 60
  python run_backtest_fengchu.py --start 2026-03-01 --end 2026-06-01
  python run_backtest_fengchu.py --no-compare --verbose
  python run_backtest_fengchu.py --export-csv
        """,
    )

    # 时间范围
    time_group = parser.add_argument_group("时间范围")
    time_group.add_argument("--days", type=int, default=60,
                            help="回测天数（从今天往回数），默认 60")
    time_group.add_argument("--start", type=str,
                            help="起始日期 YYYY-MM-DD（覆盖 --days）")
    time_group.add_argument("--end", type=str,
                            help="截止日期 YYYY-MM-DD，默认今天")

    # 运行模式
    mode_group = parser.add_argument_group("运行模式")
    mode_group.add_argument("--no-compare", action="store_true",
                            help="只跑当前配置，不做参数对比")
    mode_group.add_argument("--params", type=str,
                            help="自定义参数覆盖 JSON 数组")
    mode_group.add_argument("--only", type=str,
                            help="只跑指定参数组（逗号分隔的名称或序号）")

    # 输出控制
    output_group = parser.add_argument_group("输出控制")
    output_group.add_argument("--verbose", "-v", action="store_true",
                              help="显示所有交易明细（默认只显示20笔）")
    output_group.add_argument("--export-csv", action="store_true",
                              help="导出回测结果到 CSV")
    output_group.add_argument("--export-json", action="store_true",
                              help="导出回测结果到 JSON")

    # 资金
    parser.add_argument("--capital", type=float, default=1_000_000,
                        help="初始资金，默认100万")

    return parser.parse_args()


def main():
    args = parse_args()

    # 解析自定义参数
    custom_params = None
    if args.params:
        try:
            custom_params = json.loads(args.params)
            logger.info(f"使用自定义参数组: {len(custom_params)} 组")
        except json.JSONDecodeError as e:
            logger.error(f"参数 JSON 解析失败: {e}")
            sys.exit(1)

    # 确定日期范围描述
    if args.start and args.end:
        date_range = f"{args.start} ~ {args.end}"
    elif args.start:
        date_range = f"{args.start} ~ 今天"
    else:
        date_range = f"最近 {args.days} 个交易日"

    print(f"\n{'#'*70}")
    print(f"#  凤雏策略回测")
    print(f"#  时间范围: {date_range}")
    print(f"#  初始资金: {args.capital:.0f} 元")
    print(f"{'#'*70}\n")

    # 运行回测
    logger.info("开始加载数据并运行回测...")
    results = run_fengchu_backtest(
        days=args.days,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        compare_all=not args.no_compare,
        custom_params=custom_params,
    )

    if not results:
        logger.warning("回测未产生任何交易结果")
        return

    # 过滤指定参数组
    if args.only:
        names = [n.strip() for n in args.only.split(",")]
        indices = []
        for n in names:
            if n.isdigit():
                idx = int(n) - 1
                if 0 <= idx < len(results):
                    indices.append(idx)
            else:
                for i, r in enumerate(results):
                    if n.lower() in r.config.name.lower():
                        indices.append(i)
        results = [results[i] for i in sorted(set(indices))]
        logger.info(f"筛选后: {len(results)} 组参数")

    # 打印报告
    print_full_report(results, date_range)

    # 详细交易明细
    if args.verbose and results:
        for r in results:
            if r.trades:
                print(f"\n{'─'*70}")
                print(f"  {r.config.name} - 完整交易明细")
                print(f"{'─'*70}")
                print_trade_details(r, max_trades=len(r.trades))

    # 导出
    if args.export_csv:
        path = export_results_csv(results)
        print(f"\n  CSV 导出: {path}")

    if args.export_json:
        path = export_results_json(results)
        print(f"  JSON 导出: {path}")


if __name__ == "__main__":
    main()
