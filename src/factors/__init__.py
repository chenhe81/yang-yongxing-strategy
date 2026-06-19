"""因子表达式引擎 — 因子计算、策略定义、回测"""
from .expr import FactorExpr
from .algos import (
    RunDaily, RunOnce, RunEveryNPeriods,
    SelectAll, SelectWhere, SelectTopK,
    WeightEqually, WeightFix, ReBalance,
)
from .engine import Task, Engine
from .indicators import (
    MA, EMA, WMA, RSI, MACD, KDJ, BOLL, ATR, WR, BIAS,
    CROSS, COUNT, EVERY, EXIST, BBI, VWAP, RETURNS,
    OBV, MFI, PSY, HHVBARS, LLVBARS, SLOPE, FILTER,
    RANK, STDDEV, CORRELATION,
    ABS, LOG, POWER, SIGN, MIN, MAX, IF,
    DELAY, REF, DIFF, SUM, TS_MEAN, TS_MAX, TS_MIN,
    FUNCTION_REGISTRY,
)
