#!/usr/bin/env python3
"""加载YAML策略配置并运行回测

用法:
  python3 run_strategy.py --config config/区间交易_strategy.yaml
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.factors.yaml_loader import task_from_yaml
from src.factors.engine import Engine


def main():
    parser = argparse.ArgumentParser(description="策略回测入口")
    parser.add_argument("--config", required=True, help="YAML策略配置文件路径")
    args = parser.parse_args()

    task = task_from_yaml(args.config)
    print(f"加载策略: {task.name}")
    print(f"初始资金: {task.capital:.0f}")
    print(f"时间范围: {task.start_date} ~ {task.end_date or '今天'}")
    print()

    engine = Engine(task)
    result = engine.run()

    if result:
        print(f"\n{'='*55}")
        print(f"  {result['name']}")
        print(f"{'='*55}")
        for k, v in result.items():
            if k != 'name':
                print(f"  {k}: {v}")
        pnl = result['final_capital'] - task.capital
        print(f"  净盈亏: {pnl:+.0f}元 ({result['total_return_pct']:+.2f}%)")
    else:
        print("回测失败")


if __name__ == "__main__":
    main()
