"""
模拟交易引擎 — 跟踪虚拟持仓、盈亏计算

青鸾规则：
  - 尾盘买入（14:30-14:55），以当日收盘价作为买入价
  - 次日早盘卖出（09:30-10:00），以次日开盘价作为卖出价
  - 止损 -2%，止盈+3%，时间止损 10:00
  - 同时持仓上限 2 只

仲达规则：
  - 中线持仓（1周），周日选股周一开盘买入
  - 止损 -5%，止盈 +15%
"""
import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SimulationEngine:
    """模拟交易引擎"""

    def __init__(self, strategy_name: str, initial_capital: float = 1_000_000):
        self.strategy = strategy_name
        self.initial_capital = initial_capital
        self.trades_file = os.path.join(BASE_DIR, "data", "trades", f"{strategy_name}_trades.json")
        self.portfolio_file = os.path.join(BASE_DIR, "data", "trades", f"{strategy_name}_portfolio.json")
        self._load_state()

    def _load_state(self):
        """加载持仓状态"""
        if os.path.exists(self.portfolio_file):
            with open(self.portfolio_file, "r") as f:
                data = json.load(f)
        else:
            data = {
                "strategy": self.strategy,
                "initial_capital": self.initial_capital,
                "cash": self.initial_capital,
                "positions": [],
                "total_buy_value": 0,
                "total_sell_value": 0,
                "realized_pnl": 0,
            }
        self.cash = data.get("cash", self.initial_capital)
        self.positions = data.get("positions", [])
        self.total_buy_value = data.get("total_buy_value", 0)
        self.total_sell_value = data.get("total_sell_value", 0)
        self.realized_pnl = data.get("realized_pnl", 0)

    def _save_state(self):
        """保存持仓状态"""
        data = {
            "strategy": self.strategy,
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "positions": self.positions,
            "total_buy_value": self.total_buy_value,
            "total_sell_value": self.total_sell_value,
            "realized_pnl": self.realized_pnl,
        }
        os.makedirs(os.path.dirname(self.portfolio_file), exist_ok=True)
        with open(self.portfolio_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _append_trade(self, trade: dict):
        """记录交易"""
        os.makedirs(os.path.dirname(self.trades_file), exist_ok=True)
        trades = []
        if os.path.exists(self.trades_file):
            with open(self.trades_file, "r") as f:
                trades = json.load(f)
        trades.append(trade)
        with open(self.trades_file, "w") as f:
            json.dump(trades, f, ensure_ascii=False, indent=2)

    def get_open_value(self, current_prices: Dict[str, float]) -> float:
        """计算当前持仓市值"""
        total = 0
        for pos in self.positions:
            price = current_prices.get(pos["code"], pos["buy_price"])
            total += price * pos["shares"]
        return total

    def get_total_assets(self, current_prices: Dict[str, float] = None) -> float:
        """计算总资产 = 现金 + 持仓市值"""
        if not current_prices:
            return self.cash + sum(p["buy_price"] * p["shares"] for p in self.positions)
        return self.cash + self.get_open_value(current_prices)

    def buy(self, code: str, name: str, price: float, score: int,
            date: str, reason: str = "") -> bool:
        """模拟买入，按青鸾规则：评分>=70，单只上限15%资金"""
        if len(self.positions) >= 1:
            logger.info(f"[{date}] 持仓已满(2只)，跳过 {name}({code})")
            return False

        # 全仓：把所有现金打进去
        max_position = self.cash * 0.95  # 留5%缓冲区
        shares = int(max_position / price)
        cost = shares * price

        # 按 100 股取整
        shares = (shares // 100) * 100
        if shares < 100:
            logger.info(f"[{date}] 资金不足以买100股 {name}({code})，跳过")
            return False

        cost = shares * price
        if cost > self.cash:
            shares = int(self.cash / price)
            shares = (shares // 100) * 100
            if shares < 100:
                return False
            cost = shares * price

        cost = shares * price
        self.cash -= cost
        self.total_buy_value += cost

        pos = {
            "code": code,
            "name": name,
            "buy_date": date,
            "buy_price": round(price, 2),
            "shares": shares,
            "cost": round(cost, 2),
            "score": score,
            "reason": reason,
            "sell_date": None,
            "sell_price": None,
            "pnl": None,
            "pnl_pct": None,
        }
        self.positions.append(pos)

        trade = {
            "date": date,
            "type": "buy",
            "code": code,
            "name": name,
            "price": round(price, 2),
            "shares": shares,
            "amount": round(cost, 2),
            "score": score,
            "reason": reason,
        }
        self._append_trade(trade)
        self._save_state()
        logger.info(f"[{date}] 买入 {name}({code}) 价格:{price:.2f} 数量:{shares} 金额:{cost:.0f}")
        return True

    def sell(self, code: str, sell_price: float, sell_date: str,
             reason: str = "常规卖出") -> Optional[dict]:
        """模拟卖出"""
        for i, pos in enumerate(self.positions):
            if pos["code"] == code and pos["sell_date"] is None:
                proceeds = sell_price * pos["shares"]
                pnl = proceeds - pos["cost"]
                pnl_pct = (pnl / pos["cost"]) * 100

                # 更新持仓
                pos["sell_date"] = sell_date
                pos["sell_price"] = round(sell_price, 2)
                pos["pnl"] = round(pnl, 2)
                pos["pnl_pct"] = round(pnl_pct, 2)
                pos["sell_reason"] = reason

                self.cash += proceeds
                self.total_sell_value += proceeds
                self.realized_pnl += pnl

                trade = {
                    "date": sell_date,
                    "type": "sell",
                    "code": code,
                    "name": pos["name"],
                    "price": round(sell_price, 2),
                    "shares": pos["shares"],
                    "amount": round(proceeds, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": reason,
                }
                self._append_trade(trade)

                # 移除持仓
                self.positions.pop(i)
                self._save_state()
                logger.info(f"[{sell_date}] 卖出 {pos['name']}({code}) 盈亏:{pnl_pct:+.1f}%")
                return pos
        return None

    def sell_all_positions(self, prices: Dict[str, float], date: str, reason: str = "强制平仓"):
        """卖出所有持仓"""
        for pos in list(self.positions):
            price = prices.get(pos["code"])
            if price:
                self.sell(pos["code"], price, date, reason)

    def get_summary(self) -> dict:
        """获取模拟交易摘要"""
        return {
            "strategy": self.strategy,
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "position_count": len(self.positions),
            "total_buy_value": round(self.total_buy_value, 2),
            "total_sell_value": round(self.total_sell_value, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "realized_pnl_pct": round((self.realized_pnl / self.initial_capital) * 100, 2) if self.initial_capital else 0,
            "total_assets": round(self.cash + sum(p["cost"] for p in self.positions), 2),
            "未实现盈亏": round(sum(p["cost"] for p in self.positions), 2),
        }
