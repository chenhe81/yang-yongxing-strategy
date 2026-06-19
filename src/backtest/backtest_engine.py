"""
参数化回测引擎 — 基于 SimulationEngine 的配置驱动回测

设计：
  - 通过 ParamGrid 定义多组参数组合
  - 每次回测复用真实的 simulation 模块
  - 读取 SQLite 日线缓存，盘中快照缺失时用 K线模拟
"""
import copy
import itertools
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Callable

import pandas as pd

from src.database import get_db
from src.data_fetcher import (
    get_trade_calendar, fetch_stock_history, fetch_stock_list,
    fetch_all_stocks_spot, filter_market_data, has_20d_limit_up,
    is_permanently_excluded,
)

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 数据结构 ──

@dataclass
class BacktestConfig:
    """单次回测参数配置"""
    # 筛选参数
    涨幅下限: float = 3.0
    涨幅上限: float = 5.0
    量比下限: float = 1.0
    换手下限: float = 5.0
    换手上限: float = 10.0
    成交额下限_万: float = 0.0          # 0 表示不限制
    振幅上限: float = 100.0             # 100% 表示不限制
    市值下限_亿: float = 50.0
    市值上限_亿: float = 200.0
    # 风控参数
    止损_pct: float = -2.0
    止盈_pct: float = 3.0
    同时持仓上限: int = 1
    单只仓位_pct: float = 100.0         # 单只占用可用资金比例
    # 评分阈值
    买入阈值: float = 70.0
    坚决买入阈值: float = 80.0
    # 名称
    name: str = "default"


@dataclass
class BacktestTrade:
    """一笔完整的买入→卖出交易"""
    code: str
    name: str
    buy_date: str
    sell_date: str
    buy_price: float
    sell_price: float
    shares: int
    pnl: float
    pnl_pct: float
    hold_days: int
    score: int = 0
    reason: str = ""


@dataclass
class BacktestResult:
    """单次回测结果"""
    config: BacktestConfig
    trades: List[BacktestTrade] = field(default_factory=list)
    # 汇总指标
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    # 基准
    benchmark_return_pct: float = 0.0


def _resolve_trading_days(days: int = 60, start_date: str = None, end_date: str = None) -> list:
    """获取回测需要的交易日列表"""
    df = get_trade_calendar()
    if df.empty:
        raise RuntimeError("无法获取交易日历，请检查网络")

    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    target_end = pd.Timestamp(end_date)
    calendar = df[df["trade_date"] <= target_end].sort_values("trade_date")

    if start_date:
        target_start = pd.Timestamp(start_date)
        calendar = calendar[calendar["trade_date"] >= target_start]
        dates = calendar["trade_date"].tolist()
    else:
        dates = calendar["trade_date"].tail(days + 5).tolist()

    return [d.strftime("%Y-%m-%d") for d in sorted(set(dates)) if d <= target_end]


def _get_stock_spot_history(code: str, date: str) -> Optional[dict]:
    """
    获取某只股票在历史某天的"快照"数据。
    优先从快照表读，否则从日线缓存反推。
    """
    db = get_db()

    # 尝试快照表
    snapshot = db.get_snapshot(date)
    if not snapshot.empty:
        row = snapshot[snapshot["code"] == code]
        if not row.empty:
            r = row.iloc[0]
            return {
                "code": code,
                "name": r.get("name", ""),
                "price": float(r.get("price", 0)),
                "pct_change": float(r.get("pct_change", 0)),
                "volume": float(r.get("volume", 0)),
                "amount": float(r.get("amount", 0)),
                "turnover": float(r.get("turnover", 0)),
                "volume_ratio": float(r.get("volume_ratio", 0)),
                "float_mv": float(r.get("float_mv", 0)),
                "high": float(r.get("high", 0)),
                "low": float(r.get("low", 0)),
            }

    # 从日线反推
    klines = db.get_klines(code, 10)
    if klines.empty:
        return None
    kline = klines[klines["date"] == pd.Timestamp(date)]
    if kline.empty:
        return None
    r = kline.iloc[0]
    return {
        "code": code,
        "name": code,
        "price": float(r["close"]),
        "pct_change": float(r["pct_change"]),
        "volume": float(r["volume"]),
        "amount": float(r["amount"]),
        "turnover": float(r["turnover"]),
        "volume_ratio": 1.0,
        "float_mv": 0,
        "high": float(r["high"]),
        "low": float(r["low"]),
    }


def _get_kline_price(code: str, date: str, price_type: str = "open") -> Optional[float]:
    """从日线缓存获取某日某价格（开盘/收盘）"""
    db = get_db()
    klines = db.get_klines(code, 30)
    if klines.empty:
        return None
    kline = klines[klines["date"] == pd.Timestamp(date)]
    if kline.empty:
        return None
    return float(kline.iloc[0][price_type])


def _get_trading_day_pairs(trading_days: list) -> list:
    """生成 (买入日, 次日交易日) 对"""
    pairs = []
    for i in range(len(trading_days) - 1):
        pairs.append((trading_days[i], trading_days[i + 1]))
    return pairs


# ── 核心引擎 ──

class BacktestEngine:
    """
    参数化回测引擎

    用法：
      config = BacktestConfig(涨幅下限=3.0, ...)
      engine = BacktestEngine(config)
      result = engine.run(days=60)
    """

    def __init__(self, config: BacktestConfig, initial_capital: float = 1_000_000):
        self.config = config
        self.initial_capital = initial_capital

    def run(self, days: int = 60, start_date: str = None, end_date: str = None,
            progress_callback: Callable = None) -> BacktestResult:
        """
        运行回测

        Args:
            days: 回测天数（从 end_date 往回数，仅当 start_date 未指定时生效）
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD，默认今天
            progress_callback: 进度回调 func(current, total)

        Returns:
            BacktestResult
        """
        config = self.config
        trading_days = _resolve_trading_days(days, start_date, end_date)

        if len(trading_days) < 3:
            raise ValueError(f"交易日数据不足（{len(trading_days)}），至少需要3个交易日")

        logger.info(f"回测区间: {trading_days[0]} ~ {trading_days[-1]} ({len(trading_days)} 交易日)")
        logger.info(f"参数配置: {config.name}")

        # 获取全市场股票列表
        stock_list = fetch_stock_list()
        all_codes = stock_list["code"].tolist() if not stock_list.empty else []
        logger.info(f"全市场股票: {len(all_codes)} 只")

        trades: List[BacktestTrade] = []
        day_pairs = _get_trading_day_pairs(trading_days)
        total_pairs = len(day_pairs)

        # 逐日模拟
        for idx, (buy_date, sell_date) in enumerate(day_pairs):
            if progress_callback:
                progress_callback(idx + 1, total_pairs)

            candidates = self._screen_stocks(buy_date, all_codes)
            if not candidates:
                continue

            # 评分并排序
            scored = self._score_candidates(candidates, buy_date)
            buy_targets = [s for s in scored if s["decision"] in ("buy", "strong_buy")][:config.同时持仓上限]

            if not buy_targets:
                continue

            # 计算每只仓位
            cash_per_position = self.initial_capital * (config.单只仓位_pct / 100.0) / max(config.同时持仓上限, 1)

            for target in buy_targets:
                buy_price = target["price"]
                if buy_price <= 0:
                    continue

                # 获取次日开盘价作为卖出价
                sell_price = _get_kline_price(target["code"], sell_date, "open")
                if sell_price is None or sell_price <= 0:
                    continue

                # 计算仓位（按100股取整）
                position_cash = cash_per_position
                shares = int(position_cash / buy_price)
                shares = (shares // 100) * 100
                if shares < 100:
                    continue

                cost = shares * buy_price
                proceeds = shares * sell_price
                pnl = proceeds - cost
                pnl_pct = (pnl / cost) * 100

                # 应用止盈止损（如果触发则按止盈止损价成交）
                if pnl_pct >= config.止盈_pct:
                    sell_price_actual = buy_price * (1 + config.止盈_pct / 100)
                    pnl = shares * (sell_price_actual - buy_price)
                    pnl_pct = (pnl / (shares * buy_price)) * 100
                    sell_price = sell_price_actual
                elif pnl_pct <= config.止损_pct:
                    sell_price_actual = buy_price * (1 + config.止损_pct / 100)
                    pnl = shares * (sell_price_actual - buy_price)
                    pnl_pct = (pnl / (shares * buy_price)) * 100
                    sell_price = sell_price_actual

                trade = BacktestTrade(
                    code=target["code"],
                    name=target.get("name", target["code"]),
                    buy_date=buy_date,
                    sell_date=sell_date,
                    buy_price=round(buy_price, 2),
                    sell_price=round(sell_price, 2),
                    shares=shares,
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    hold_days=1,
                    score=target["score"],
                    reason=target.get("decision", ""),
                )
                trades.append(trade)

            if (idx + 1) % 10 == 0:
                logger.info(f"  进度: {idx+1}/{total_pairs} 天, 已产生 {len(trades)} 笔交易")

        # 计算汇总指标
        result = self._compute_summary(trades, trading_days)
        return result

    def _screen_stocks(self, date: str, all_codes: List[str]) -> List[dict]:
        """获取某日所有满足基础条件的候选股"""
        candidates = []

        for code in all_codes:
            if is_permanently_excluded(code):
                continue

            spot = _get_stock_spot_history(code, date)
            if spot is None:
                continue

            pct = spot.get("pct_change", 0)
            vr = spot.get("volume_ratio", 0)
            turn = spot.get("turnover", 0)
            amount = spot.get("amount", 0)
            amplitude = abs(spot.get("high", 0) - spot.get("low", 0)) / max(spot.get("price", 1), 0.01) * 100
            mv_亿 = spot.get("float_mv", 0) / 1e8

            # 基础过滤（与策略模块解耦，直接使用引擎参数）
            if not (self.config.涨幅下限 <= pct <= self.config.涨幅上限):
                continue
            if vr < self.config.量比下限:
                continue
            if not (self.config.换手下限 <= turn <= self.config.换手上限):
                continue
            if self.config.成交额下限_万 > 0 and amount < self.config.成交额下限_万 * 10000:
                continue
            if amplitude > self.config.振幅上限:
                continue
            if mv_亿 > 0 and not (self.config.市值下限_亿 <= mv_亿 <= self.config.市值上限_亿):
                continue

            spot["has_limit_up_20d"] = has_20d_limit_up(code)
            spot["above_vwap"] = True
            spot["volume_stable"] = True
            spot["no_resistance"] = True
            spot["sector"] = ""
            candidates.append(spot)

        return candidates

    def _score_candidates(self, candidates: List[dict], date: str) -> List[dict]:
        """对候选股执行凤雏策略评分（跳过硬性检查，已在筛选阶段完成）"""
        from src.strategies.qingluan import calculate_qingluan_score

        results = []
        for stock in candidates:
            score_info = calculate_qingluan_score(stock, sector_rank=None)
            total = score_info["score"]

            decision = "ignore"
            if total >= self.config.坚决买入阈值:
                decision = "strong_buy"
            elif total >= self.config.买入阈值:
                decision = "buy"

            results.append({
                "code": stock["code"],
                "name": stock.get("name", stock["code"]),
                "price": stock.get("price", 0),
                "score": total,
                "details": score_info["details"],
                "decision": decision,
                "pct_change": stock.get("pct_change", 0),
                "volume_ratio": stock.get("volume_ratio", 0),
                "turnover": stock.get("turnover", 0),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _compute_summary(self, trades: List[BacktestTrade], trading_days: list) -> BacktestResult:
        """从交易列表计算汇总指标"""
        result = BacktestResult(config=self.config, trades=trades)

        if not trades:
            return result

        # 基础指标
        total_invested = sum(t.buy_price * t.shares for t in trades)
        total_returned = sum(t.sell_price * t.shares for t in trades)
        total_pnl = total_returned - total_invested
        result.total_return_pct = round((total_pnl / max(total_invested, 1)) * 100, 2) if total_invested > 0 else 0.0

        # 年化
        n_days = len(trading_days)
        if n_days > 0:
            result.annual_return_pct = round(
                ((1 + result.total_return_pct / 100) ** (252 / max(n_days, 1)) - 1) * 100, 2
            )

        # 胜率
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        result.trade_count = len(trades)
        result.win_count = len(wins)
        result.loss_count = len(losses)
        result.win_rate = round((len(wins) / max(len(trades), 1)) * 100, 2)

        # 盈亏比
        avg_win = sum(t.pnl_pct for t in wins) / max(len(wins), 1)
        avg_loss = abs(sum(t.pnl_pct for t in losses)) / max(len(losses), 1)
        result.profit_loss_ratio = round(avg_win / max(avg_loss, 0.01), 2) if losses else float("inf")

        # 最大回撤（基于逐笔交易模拟权益曲线）
        equity = self.initial_capital
        peak = equity
        max_dd = 0.0
        for t in trades:
            equity += t.pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown_pct = round(max_dd, 2)

        # 夏普比率（简化：用每笔交易的收益率）
        if len(trades) >= 2:
            returns = [t.pnl_pct for t in trades]
            avg_r = sum(returns) / len(returns)
            std_r = (sum((r - avg_r) ** 2 for r in returns) / len(returns)) ** 0.5
            result.sharpe_ratio = round(avg_r / max(std_r, 0.01) * (252 ** 0.5), 2) if std_r > 0 else 0.0

        return result


def run_param_grid(base_config: BacktestConfig, param_overrides: List[Dict[str, object]],
                   days: int = 60, start_date: str = None, end_date: str = None,
                   initial_capital: float = 1_000_000) -> List[BacktestResult]:
    """
    运行多组参数对比回测

    Args:
        base_config: 基准配置
        param_overrides: 参数覆盖列表，每项是一个 dict {参数名: 值, name: "显示名"}
        days: 回测天数
        initial_capital: 初始资金

    Returns:
        List[BacktestResult]
    """
    results = []
    total = len(param_overrides)

    for i, overrides in enumerate(param_overrides):
        config = copy.deepcopy(base_config)
        for k, v in overrides.items():
            if hasattr(config, k):
                setattr(config, k, v)
        config.name = overrides.get("name", f"param_{i + 1}")

        logger.info(f"\n[{i + 1}/{total}] 运行参数组: {config.name}")
        engine = BacktestEngine(config, initial_capital=initial_capital)
        result = engine.run(days=days, start_date=start_date, end_date=end_date)
        results.append(result)
        logger.info(f"  → 收益率: {result.total_return_pct:.2f}%, 胜率: {result.win_rate:.2f}%, 交易: {result.trade_count}笔")

    return results
