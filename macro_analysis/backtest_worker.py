#!/usr/bin/env python3
"""
并行回测 Worker — 部署在算力中心 (183.131.24.109)

功能：
  1. 从凤雏同步最新 SQLite 数据库（market_cache.db）
  2. 使用 24 核 CPU 并行运行多参数组回测
  3. 输出回测结果 JSON（汇总 + 交易明细）

架构：
  - multiprocessing.Pool 并行化参数组
  - 每个 worker 独立读取 SQLite（只读，无锁冲突）
  - 主进程聚合结果并输出报告

运行方式：
  python3 backtest_worker.py                           # 跑所有预设参数组
  python3 backtest_worker.py --days 120                # 指定回测天数
  python3 backtest_worker.py --start 2026-01-01        # 指定起始日期
  python3 backtest_worker.py --no-sync                 # 跳过数据库同步

输出：
  /home/arcvideo/backtest_analysis/output/latest.json
"""
import argparse
import json
import logging
import multiprocessing as mp
import os
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime
from dataclasses import asdict, fields
from typing import List, Dict, Optional

# ── 路径 ──
WORKER_DIR = os.path.dirname(os.path.abspath(__file__))
if WORKER_DIR not in sys.path:
    sys.path.insert(0, WORKER_DIR)

DATA_DIR = os.path.join(WORKER_DIR, "data")
OUTPUT_DIR = os.path.join(WORKER_DIR, "output")
DB_PATH = os.path.join(DATA_DIR, "market_cache.db")

# ── 凤雏 SSH 配置 ──
FENGCHU_HOST = "10.26.0.7"
FENGCHU_PORT = 22
FENGCHU_USER = "alien"
FENGCHU_DB_PATH = "/home/alien/股票市场扫描规则/data/market_cache.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backtest_worker")


# ── 公共函数（必须顶层，multiprocessing 可 pickle） ──

def _run_one_param(args: tuple) -> dict:
    """运行一组参数的回测（multiprocessing 入口点）"""
    overrides, days, start_date, end_date, capital, db_path = args

    # 每个 worker 独立设置 DB 路径
    os.environ["MARKET_DB_PATH"] = db_path

    from src.backtest.fengchu_backtest import get_default_config
    from src.backtest.backtest_engine import BacktestEngine

    config = get_default_config()
    for k, v in overrides.items():
        if hasattr(config, k):
            setattr(config, k, v)
    config.name = overrides.get("name", config.name)

    engine = BacktestEngine(config, initial_capital=capital)
    try:
        result = engine.run(days=days, start_date=start_date, end_date=end_date)
        return _serialize_result(result, config.name)
    except Exception as e:
        logger.error(f"  [{config.name}] 回测失败: {e}")
        return {
            "config_name": config.name,
            "error": str(e),
            "total_return_pct": 0,
            "trade_count": 0,
        }


def _serialize_result(result, config_name: str) -> dict:
    """将 BacktestResult 转换为 JSON 可序列化字典"""
    from src.backtest.backtest_engine import BacktestTrade

    return {
        "config_name": config_name,
        "total_return_pct": result.total_return_pct,
        "annual_return_pct": result.annual_return_pct,
        "win_rate": result.win_rate,
        "profit_loss_ratio": result.profit_loss_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "trade_count": result.trade_count,
        "win_count": result.win_count,
        "loss_count": result.loss_count,
        "trades": [
            {
                "code": t.code,
                "name": t.name,
                "buy_date": t.buy_date,
                "sell_date": t.sell_date,
                "buy_price": t.buy_price,
                "sell_price": t.sell_price,
                "shares": t.shares,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "hold_days": t.hold_days,
                "score": t.score,
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }


def sync_db() -> bool:
    """从凤雏同步最新 SQLite 数据库"""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        logger.info(f"从凤雏同步数据库...")
        result = subprocess.run(
            ["scp", "-P", str(FENGCHU_PORT),
             f"{FENGCHU_USER}@{FENGCHU_HOST}:{FENGCHU_DB_PATH}",
             DB_PATH],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
            logger.info(f"  数据库同步成功 ({size_mb:.0f} MB)")
            return True
        else:
            logger.warning(f"  数据库同步失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        logger.warning(f"  数据库同步异常: {e}")
        return False


def get_default_param_groups() -> List[Dict]:
    """获取凤雏预设参数对比组"""
    return [
        {"name": "当前配置（默认）"},
        {"name": "T1-换手率3-10%", "换手下限": 3.0, "换手上限": 10.0},
        {"name": "T2-量比≥1.5", "量比下限": 1.5},
        {"name": "T3-成交额≥3000万", "成交额下限_万": 3000},
        {"name": "T4-振幅≤8%", "振幅上限": 8.0},
        {"name": "T5-止盈5%止损3%", "止盈_pct": 5.0, "止损_pct": -3.0},
        {"name": "T6-2只各50%", "同时持仓上限": 2, "单只仓位_pct": 50},
        {
            "name": "T7-组合优化",
            "换手下限": 3.0, "换手上限": 10.0, "量比下限": 1.5,
            "成交额下限_万": 3000, "振幅上限": 8.0,
            "止盈_pct": 5.0, "止损_pct": -3.0,
            "同时持仓上限": 2, "单只仓位_pct": 50,
        },
        {
            "name": "T8-保守版",
            "量比下限": 1.8, "换手下限": 3.0, "换手上限": 8.0,
            "成交额下限_万": 5000, "振幅上限": 6.0,
            "止盈_pct": 3.0, "止损_pct": -1.5,
        },
    ]


def main():
    parser = argparse.ArgumentParser(description="并行回测 Worker")
    parser.add_argument("--days", type=int, default=60, help="回测天数")
    parser.add_argument("--start", type=str, help="起始日期")
    parser.add_argument("--end", type=str, help="截止日期")
    parser.add_argument("--capital", type=float, default=1_000_000, help="初始资金")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"并行数（默认: CPU 核数 {mp.cpu_count()}）")
    parser.add_argument("--no-sync", action="store_true", help="跳过数据库同步")
    parser.add_argument("--params", type=str, help="自定义参数 JSON")
    parser.add_argument("--output", default=OUTPUT_DIR, help="输出目录")

    args = parser.parse_args()
    n_workers = args.workers or mp.cpu_count()
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # ── DB 同步 ──
    if not args.no_sync:
        sync_ok = sync_db()
        if not sync_ok and not os.path.exists(DB_PATH):
            logger.error("数据库不存在且同步失败，退出")
            sys.exit(1)
        if not sync_ok:
            logger.warning("使用本地缓存数据库")
    elif not os.path.exists(DB_PATH):
        logger.error(f"数据库不存在: {DB_PATH}")
        sys.exit(1)

    # 注入 DB 路径
    os.environ["MARKET_DB_PATH"] = DB_PATH

    # ── 参数组 ──
    if args.params:
        param_groups = json.loads(args.params)
    else:
        param_groups = get_default_param_groups()
    logger.info(f"参数组数: {len(param_groups)}")
    logger.info(f"并行数: {n_workers}")
    logger.info(f"日期范围: {'最近' + str(args.days) + '天' if not args.start else args.start + ' ~ ' + (args.end or '今天')}")

    # ── 构建并行参数列表 ──
    worker_args = [
        (overrides, args.days, args.start, args.end, args.capital, DB_PATH)
        for overrides in param_groups
    ]

    # ── 并行执行 ──
    logger.info(f"开始并行回测...")
    t0 = time.time()

    with mp.Pool(n_workers) as pool:
        results = pool.map(_run_one_param, worker_args)

    elapsed = time.time() - t0
    logger.info(f"并行回测完成 ({len(results)} 组, 耗时 {elapsed:.1f}s)")

    # ── 输出 ──
    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "params_count": len(param_groups),
        "workers": n_workers,
        "elapsed_seconds": round(elapsed, 1),
        "database_date": args.end or datetime.now().strftime("%Y-%m-%d"),
        "results": results,
    }

    # 最新
    latest_path = os.path.join(output_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"结果输出: {latest_path}")

    # 历史归档
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_path = os.path.join(output_dir, f"{ts}.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"历史归档: {history_path}")

    # 控制台摘要
    print(f"\n{'='*70}")
    print(f"  并行回测结果 — {summary['date']}")
    print(f"{'='*70}")
    best_return = -999
    best_name = ""
    for r in results:
        ret = r.get("total_return_pct", 0)
        trades = r.get("trade_count", 0)
        wr = r.get("win_rate", 0)
        pl = r.get("profit_loss_ratio", 0)
        err = r.get("error")
        marker = " ⚠️" if err else ""
        print(f"  {r['config_name']:20s}  收益:{ret:>+7.2f}%  "
              f"胜率:{wr:>5.1f}%  盈亏比:{pl:>5.1f}  交易:{trades}笔{marker}")
        if not err and ret > best_return:
            best_return = ret
            best_name = r["config_name"]
    print(f"{'='*70}")
    print(f"  最佳: {best_name} ({best_return:+.2f}%)")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
