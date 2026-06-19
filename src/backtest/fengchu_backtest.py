"""
凤雏策略 Backtrader 回测适配层

提供：
  - 默认配置加载
  - 预设参数对比组（Alpha-X 参考值）
  - 便捷回测运行函数
"""
import logging
from typing import List, Dict, Optional

from src.backtest.backtest_engine import (
    BacktestConfig, BacktestResult, run_param_grid
)

logger = logging.getLogger(__name__)


def get_default_config() -> BacktestConfig:
    """从 YAML 配置读取当前凤雏策略默认参数"""
    return BacktestConfig(
        涨幅下限=3.0,
        涨幅上限=5.0,
        量比下限=1.0,
        换手下限=5.0,
        换手上限=10.0,
        成交额下限_万=0,
        振幅上限=100,
        市值下限_亿=50,
        市值上限_亿=200,
        止损_pct=-2.0,
        止盈_pct=3.0,
        同时持仓上限=1,
        单只仓位_pct=100,
        买入阈值=70,
        坚决买入阈值=80,
        name="当前配置（默认）",
    )


def get_test_param_groups() -> List[Dict[str, object]]:
    """
    Alpha-X 参考值参数对比组

    返回参数覆盖列表，每项与默认配置合并后形成一组测试
    """
    return [
        # 组1：换手率从5%-10% → 3%-10%
        {
            "name": "T1-换手率3-10%",
            "换手下限": 3.0,
            "换手上限": 10.0,
        },
        # 组2：量比从≥1.0 → ≥1.5
        {
            "name": "T2-量比≥1.5",
            "量比下限": 1.5,
        },
        # 组3：成交额≥3000万
        {
            "name": "T3-成交额≥3000万",
            "成交额下限_万": 3000,
        },
        # 组4：振幅≤8%
        {
            "name": "T4-振幅≤8%",
            "振幅上限": 8.0,
        },
        # 组5：止盈+5%/止损-3%
        {
            "name": "T5-止盈5%止损3%",
            "止盈_pct": 5.0,
            "止损_pct": -3.0,
        },
        # 组6：2只各50%仓位
        {
            "name": "T6-2只各50%",
            "同时持仓上限": 2,
            "单只仓位_pct": 50,
        },
        # 组7：组合优化（多个参数同时调整）
        {
            "name": "T7-组合优化",
            "换手下限": 3.0,
            "换手上限": 10.0,
            "量比下限": 1.5,
            "成交额下限_万": 3000,
            "振幅上限": 8.0,
            "止盈_pct": 5.0,
            "止损_pct": -3.0,
            "同时持仓上限": 2,
            "单只仓位_pct": 50,
        },
        # 组8：保守版（高量比+低换手+止盈止损收紧）
        {
            "name": "T8-保守版",
            "量比下限": 1.8,
            "换手下限": 3.0,
            "换手上限": 8.0,
            "成交额下限_万": 5000,
            "振幅上限": 6.0,
            "止盈_pct": 3.0,
            "止损_pct": -1.5,
        },
    ]


def run_fengchu_backtest(
    days: int = 60,
    start_date: str = None,
    end_date: str = None,
    initial_capital: float = 1_000_000,
    compare_all: bool = True,
    custom_params: List[Dict] = None,
) -> List[BacktestResult]:
    """
    运行凤雏策略回测

    Args:
        days: 回测天数
        start_date: 起始日期
        end_date: 截止日期
        initial_capital: 初始资金
        compare_all: 是否运行所有预设参数对比组
        custom_params: 自定义参数组，覆盖 compare_all

    Returns:
        List[BacktestResult]
    """
    base_config = get_default_config()

    if custom_params:
        param_groups = custom_params
    elif compare_all:
        param_groups = get_test_param_groups()
        # 第一组跑默认配置
        param_groups.insert(0, {"name": "当前配置（默认）"})
    else:
        # 只跑默认配置
        param_groups = [{"name": "当前配置（默认）"}]

    results = run_param_grid(
        base_config=base_config,
        param_overrides=param_groups,
        days=days,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
    )

    return results
