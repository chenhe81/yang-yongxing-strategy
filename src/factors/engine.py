
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import numpy as np
import json, logging

from src.factors.expr import FactorExpr
from src.factors.algos import SelectWhere, SelectTopK, WeightEqually, RunDaily
from src.database import get_db

logger = logging.getLogger(__name__)

@dataclass
class Task:
    name: str = "策略"
    symbols: List[str] = field(default_factory=list)
    start_date: str = "20260101"
    end_date: str = ""
    capital: float = 1000000.0
    select_buy: List[str] = field(default_factory=list)
    buy_at_least_count: int = 0
    select_sell: List[str] = field(default_factory=list)
    sell_at_least_count: int = 1
    order_by_signal: str = ""
    order_by_topK: int = 2
    order_by_DESC: bool = True
    weight: str = "WeightEqually"
    period: str = "RunDaily"
    hold_days_max: int = 10
    loss_stop_pct: float = -5.0
    profit_target_pct: float = 8.0
    # Stock pool
    exclude_st: bool = True
    min_market_cap_yi: float = 50
    max_market_cap_yi: float = 500
    min_amount_wan: float = 0


@dataclass
class TradeRecord:
    code: str; name: str
    buy_date: str; sell_date: str
    buy_price: float; sell_price: float
    shares: int; pnl: float; pnl_pct: float
    hold_days: int; reason: str = ""


class Engine:
    def __init__(self, task: Task):
        self.task = task
        self.expr = FactorExpr()
        self.trades: List[TradeRecord] = []
        self._active: Dict[str, dict] = {}
        self.cash = task.capital
        self.daily_values: List[dict] = []
    
    def _load_data(self, start: str, end: str):
        db = get_db()
        conn = db._connect()
        # Convert YYYYMMDD to YYYY-MM-DD if needed
        def _fmt(d):
            d = str(d)
            if len(d) == 8 and d.isdigit():
                return f"{d[:4]}-{d[4:6]}-{d[6:]}"
            return d
        start_fmt = _fmt(start)
        end_fmt = _fmt(end)
        sql = """SELECT code, date, open, high, low, close, volume, amount
                 FROM daily_klines WHERE date >= ? AND date <= ?
                 ORDER BY date, code"""
        cur = conn.execute(sql, (start_fmt, end_fmt))
        rows = cur.fetchall()
        if not rows: return pd.DataFrame()
        df = pd.DataFrame([dict(r) for r in rows])
        for c in ["open","high","low","close","volume","amount"]:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    
    def _pivot(self, df: pd.DataFrame, col: str) -> pd.DataFrame:
        return df.pivot_table(values=col, index="date", columns="code")
    
    def run(self):
        t = self.task
        if not t.end_date: t.end_date = datetime.now().strftime("%Y%m%d")
        data = self._load_data(t.start_date, t.end_date)
        if data.empty:
            logger.warning("无数据"); return None
        
        # Pivot all price columns once
        pivoted = {c: self._pivot(data, c) for c in ["open","high","low","close","volume","amount"]}
        dates = sorted(pivoted["close"].index)
        n_dates = len(dates)
        logger.info(f"数据范围: {dates[0]} ~ {dates[-1]}, 共{n_dates}天")
        logger.info(f"股票数: {len(pivoted["close"].columns)}")
        
        # Build full-data ns for factor computation
        ns = {"close": pivoted["close"], "high": pivoted["high"],
              "low": pivoted["low"], "open": pivoted["open"],
              "volume": pivoted["volume"], "amount": pivoted["amount"]}
        for name,func in self.expr.functions.items():
            ns[name] = func
        ns.update({"AND": lambda a,b: (a.astype(bool)&b.astype(bool)).astype(float),
                   "OR": lambda a,b: (a.astype(bool)|b.astype(bool)).astype(float)})
        
        # Pre-compute buy/sell signals
        buy_signal = None
        if t.select_buy:
            sigs = []
            for f in t.select_buy:
                try:
                    r = eval(f, {"__builtins__": {}}, ns)
                    if isinstance(r, tuple): r = r[0]
                    if r is not None: sigs.append(r.astype(bool))
                except Exception as e:
                    logger.debug(f"购买因子计算失败: {e}")
            if sigs:
                threshold = t.buy_at_least_count or len(t.select_buy)
                buy_signal = sum(sigs) >= threshold
        
        sell_signal = None
        if t.select_sell:
            sigs = []
            for f in t.select_sell:
                try:
                    r = eval(f, {"__builtins__": {}}, ns)
                    if isinstance(r, tuple): r = r[0]
                    if r is not None: sigs.append(r.astype(bool))
                except Exception as e:
                    logger.debug(f"卖出因子计算失败: {e}")
            if sigs:
                sell_signal = sum(sigs) >= t.sell_at_least_count
        
        order_signal = None
        if t.order_by_signal:
            try:
                order_signal = eval(t.order_by_signal, {"__builtins__": {}}, ns)
            except Exception as e:
                logger.debug(f"排序因子计算失败: {e}")
        
        # Run day-by-day
        for idx, day in enumerate(dates):
            today_close = pivoted["close"].loc[day]
            today_open = pivoted["open"].loc[day]
            valid_stocks = today_close.dropna().index.tolist()
            
            # Sell signals
            for code in list(self._active.keys()):
                pos = self._active[code]
                reason = ""
                should_sell = False
                
                if code not in pos["name_mapping"]:
                    pos["name_mapping"][code] = code
                
                # Daily price update
                if code in today_close.index and pd.notna(today_close[code]):
                    cur_price = today_close[code]
                    pnl_pct = (cur_price / pos["buy_price"] - 1) * 100
                    pos["current_pnl_pct"] = pnl_pct
                    
                    # Check sell conditions
                    if sell_signal is not None and code in sell_signal.columns:
                        sig_val = sell_signal.loc[day, code] if day in sell_signal.index else False
                        if sig_val:
                            reason = "信号卖出"; should_sell = True
                    
                    if not should_sell and t.loss_stop_pct and pnl_pct <= t.loss_stop_pct:
                        reason = f"止损{pnl_pct:.1f}%"; should_sell = True
                    
                    if not should_sell and t.profit_target_pct and pnl_pct >= t.profit_target_pct:
                        reason = f"止盈{pnl_pct:.1f}%"; should_sell = True
                    
                    hold = idx - pos["buy_idx"]
                    if not should_sell and t.hold_days_max and hold >= t.hold_days_max:
                        reason = f"持仓{hold}天时间止损"; should_sell = True
                
                if should_sell and code in today_close.index:
                    sp = today_close[code]
                    pnl = (sp - pos["buy_price"]) * pos["shares"]
                    self.cash += sp * pos["shares"]
                    self.trades.append(TradeRecord(
                        code=code, name=pos.get("name", code),
                        buy_date=pos["buy_date"], sell_date=day,
                        buy_price=pos["buy_price"], sell_price=sp,
                        shares=pos["shares"], pnl=pnl,
                        pnl_pct=(sp/pos["buy_price"]-1)*100,
                        hold_days=idx - pos["buy_idx"], reason=reason))
                    del self._active[code]
            
            # Buy signals
            if buy_signal is not None and day in buy_signal.index:
                buy_candidates = []
                for code in valid_stocks:
                    if code in self._active: continue
                    if code not in buy_signal.columns: continue
                    sig_val = buy_signal.loc[day, code]
                    if sig_val:
                        buy_candidates.append(code)
                
                if buy_candidates:
                    if order_signal is not None:
                        sorted_codes = sorted(buy_candidates,
                            key=lambda c: (order_signal.loc[day, c] if c in order_signal.columns and day in order_signal.index else 0) if t.order_by_DESC else -(order_signal.loc[day, c] if c in order_signal.columns and day in order_signal.index else 0),
                            reverse=True)
                        buy_candidates = sorted_codes[:t.order_by_topK]
                    else:
                        buy_candidates = buy_candidates[:t.order_by_topK]
                    
                    for code in buy_candidates:
                        price = today_close[code]
                        if pd.isna(price) or price <= 0: continue
                        shares = int(self.cash * 0.95 / price / 100) * 100
                        if shares < 100: continue
                        cost = shares * price
                        self.cash -= cost
                        self._active[code] = {
                            "code": code, "name": code,
                            "buy_date": day, "buy_price": price,
                            "shares": shares, "cost": cost,
                            "buy_idx": idx, "current_pnl_pct": 0.0,
                            "name_mapping": {code: code},
                        }
            
            # Track daily value
            pos_val = 0
            for code, pos in list(self._active.items()):
                if code in today_close.index and pd.notna(today_close[code]):
                    pos_val += pos["shares"] * today_close[code]
            total = self.cash + pos_val
            self.daily_values.append({"date": day, "equity": total, "cash": self.cash, "pos": pos_val})
        
        # Close remaining positions on last day
        last_day = dates[-1]
        for code in list(self._active.keys()):
            pos = self._active.pop(code)
            sp = pos["buy_price"]
            if code in pivoted["close"].loc[last_day].index and pd.notna(pivoted["close"].loc[last_day][code]):
                sp = pivoted["close"].loc[last_day][code]
            self.cash += sp * pos["shares"]
            pnl = (sp - pos["buy_price"]) * pos["shares"]
            self.trades.append(TradeRecord(
                code=code, name=pos.get("name", code),
                buy_date=pos["buy_date"], sell_date=last_day,
                buy_price=pos["buy_price"], sell_price=sp,
                shares=pos["shares"], pnl=pnl,
                pnl_pct=(sp/pos["buy_price"]-1)*100,
                hold_days=len(dates)-pos["buy_idx"], reason="期末平仓"))
        
        return self._summary()
    
    def _summary(self):
        sells = [t for t in self.trades if t.reason]
        if not sells: return {"name": self.task.name, "trades": 0}
        wins = sum(1 for t in sells if t.pnl > 0)
        total_pnl = sum(t.pnl for t in sells)
        init = self.task.capital
        ret = round((self.cash - init) / init * 100, 2)
        win_rate = round(wins / len(sells) * 100, 1) if sells else 0
        peak = init
        max_dd = 0
        for v in self.daily_values:
            if v["equity"] > peak: peak = v["equity"]
            dd = (peak - v["equity"]) / peak * 100 if peak > 0 else 0
            if dd > max_dd: max_dd = dd
        daily_ret = []
        prev = init
        for v in self.daily_values:
            if v["equity"] != prev:
                daily_ret.append((v["equity"] - prev) / prev)
                prev = v["equity"]
        sharpe = round(np.mean(daily_ret)/np.std(daily_ret)*np.sqrt(252), 2) if daily_ret and np.std(daily_ret) > 0 else 0
        
        return {
            "name": self.task.name,
            "total_return_pct": ret, "win_rate": win_rate,
            "max_drawdown_pct": round(max_dd, 2), "sharpe_ratio": sharpe,
            "total_trades": len(sells), "wins": wins, "losses": len(sells)-wins,
            "final_capital": round(self.cash, 2),
        }
