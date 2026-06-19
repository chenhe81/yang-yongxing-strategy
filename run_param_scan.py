#!/usr/bin/env python3
"""参数网格扫描 — 自动跑所有参数组合对比"""
import argparse, sys, os, json, csv
from itertools import product
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.factors.yaml_loader import task_from_yaml
from src.factors.engine import Task, Engine

def main():
    parser = argparse.ArgumentParser(description="参数网格扫描")
    parser.add_argument("--config", required=True)
    parser.add_argument("--param-grid", required=True, help='JSON: {"key": [val1, val2]}')
    args = parser.parse_args()
    
    base = task_from_yaml(args.config)
    grid = json.loads(args.param_grid)
    keys = list(grid.keys())
    results = []
    
    print(f"参数网格扫描: {len(list(product(*[grid[k] for k in keys])))} 组")
    print()
    
    for vals in product(*[grid[k] for k in keys]):
        params = dict(zip(keys, vals))
        # 从base复制参数
        cfg = {k: getattr(base, k) for k in Task.__dataclass_fields__}
        # 覆盖网格参数
        for k, v in params.items():
            if k in cfg:
                cfg[k] = v
        task = Task(**cfg)
        result = Engine(task).run()
        if result:
            result["params_str"] = str(params)
            results.append(result)
        print(f"  {params} → 收益{result['total_return_pct']:+.2f}% "
              f"胜率{result['win_rate']:.1f}% 回撤{result['max_drawdown_pct']:.2f}%"
              f" 夏普{result['sharpe_ratio']:.2f}")
    
    # CSV输出
    os.makedirs("output", exist_ok=True)
    path = "output/param_scan_results.csv"
    fields = ["params_str", "total_return_pct", "win_rate", "max_drawdown_pct",
              "sharpe_ratio", "total_trades", "wins", "losses"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\n结果已保存: {path}")
    
    if results:
        best_sharpe = max(results, key=lambda x: x.get("sharpe_ratio", -99))
        best_return = max(results, key=lambda x: x.get("total_return_pct", -99))
        print(f"\n最优夏普: {best_sharpe['params_str']} → {best_sharpe['total_return_pct']:+.2f}% 夏普{best_sharpe['sharpe_ratio']:.2f}")
        print(f"最优收益: {best_return['params_str']} → {best_return['total_return_pct']:+.2f}% 夏普{best_return['sharpe_ratio']:.2f}")

if __name__ == "__main__":
    main()
