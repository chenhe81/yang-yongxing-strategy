"""因子表达式解析与计算引擎"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from src.factors.indicators import FUNCTION_REGISTRY

class FactorExpr:
    """因子表达式计算引擎"""
    
    def __init__(self):
        self.functions = dict(FUNCTION_REGISTRY)
    
    def prepare_data(self, df: pd.DataFrame, col_map: dict = None) -> dict:
        """将宽表数据转换为计算所需的数据字典"""
        if col_map is None:
            col_map = {}
        ns = {}
        for std_name, col_name in col_map.items():
            if col_name in df.columns:
                ns[std_name] = df[col_name]
        ns.update(self.functions)
        ns.update({
            "AND": lambda a, b: (a.astype(bool) & b.astype(bool)).astype(float),
            "OR": lambda a, b: (a.astype(bool) | b.astype(bool)).astype(float),
            "NOT": lambda a: (~a.astype(bool)).astype(float),
        })
        return ns
    
    def calc(self, df: pd.DataFrame, formula: str, col_map: dict = None) -> pd.DataFrame:
        """计算单个公式"""
        ns = self.prepare_data(df, col_map)
        result = eval(formula, {"__builtins__": {}}, ns)
        if isinstance(result, tuple):
            return result[0] if len(result) > 0 else pd.DataFrame()
        return result
    
    def calc_formulas(self, df: pd.DataFrame, formulas: List[str],
                      col_map: dict = None) -> pd.DataFrame:
        """批量计算公式"""
        results = {}
        for formula in formulas:
            try:
                key = formula.replace(" ", "_")[:64]
                results[key] = self.calc(df, formula, col_map)
            except Exception:
                results[formula[:32]] = None
        valid = {k: v for k, v in results.items()
                 if v is not None and isinstance(v, (pd.DataFrame, pd.Series))}
        if not valid:
            return pd.DataFrame()
        return pd.DataFrame(valid)
