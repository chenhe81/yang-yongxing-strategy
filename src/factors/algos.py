"""算法类 — 执行控制、选股、权重、再平衡"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

class RunDaily:
    def __call__(self, target): return True

class RunOnce:
    def __init__(self): self.has_run = False
    def __call__(self, target):
        if not self.has_run: self.has_run = True; return True
        return False

class RunEveryNPeriods:
    def __init__(self, n, run_on_last_date=True):
        self.n = n; self.last_date = None; self.run_on_last_date = run_on_last_date
    def __call__(self, target):
        cd = target.datetime.date(0)
        if self.last_date is None: self.last_date = cd; return True
        if (cd - self.last_date).days >= self.n: self.last_date = cd; return True
        return False

class SelectAll:
    def __call__(self, target):
        target.temp["selected"] = []
        return True

class SelectWhere:
    def __init__(self, signal: pd.DataFrame): self.signal = signal
    def __call__(self, target):
        cd = target.datetime.date(0)
        if cd in self.signal.index:
            today = self.signal.loc[cd]
            target.temp["selected"] = today[today > 0].index.tolist()
        return True

class SelectTopK:
    def __init__(self, signal: pd.DataFrame = None, K: int = 1,
                 drop_top_n: int = 0, b_ascending: bool = False):
        self.signal = signal; self.K = K; self.drop_top_n = drop_top_n; self.b_ascending = b_ascending
    def __call__(self, target):
        cd = target.datetime.date(0)
        symbols = target.temp.get("selected", [])
        if self.signal is not None and cd in self.signal.index and symbols:
            today = self.signal.loc[cd]
            valid = today[today.index.isin(symbols)].dropna()
            sorted_s = valid.sort_values(ascending=self.b_ascending)
            result = sorted_s.iloc[self.drop_top_n:self.drop_top_n+self.K].index.tolist()
            target.temp["selected"] = result
        return True

class WeightEqually:
    def __call__(self, target):
        symbols = target.temp.get("selected", [])
        if symbols: target.temp["weights"] = {s: 1/len(symbols) for s in symbols}
        return True

class WeightFix:
    def __init__(self, weights_dict: dict): self.weights = weights_dict
    def __call__(self, target):
        symbols = target.temp.get("selected", [])
        target.temp["weights"] = {s: self.weights.get(s, 0) for s in symbols}
        return True

class ReBalance:
    def __init__(self, force_update=False): self.force_update = force_update
    def __call__(self, target):
        weights = target.temp.get("weights", {})
        total = sum(weights.values()) if weights else 0
        if total > 0:
            target.temp["weights"] = {k: v/total for k, v in weights.items()}
            for s, w in target.temp["weights"].items():
                target.weights[s] = f"{w*100:.0f}%"
        return True
