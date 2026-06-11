"""
刘秀策略 — 基于 Serenity 紫苏叶理论 + SEPA 过滤法

来源：
  - 股票池分层管理规则 v1.0 算法B（五因子评分）
  - SEPA 过滤法完整规则手册.md
  - A股市场特色分析指南.md

双周定投 + 基本面筛选，中线持有（1周左右）
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# ── SEPA 趋势模板 ──
SEPA_CONFIG = {
    "均线短期": 50,
    "均线中期": 150,
    "均线长期": 200,
    "RS评级门槛": 80,
    "52周高点门槛_pct": 0.75,
}


def check_sepa_trend_template(df_hist: pd.DataFrame) -> dict:
    """SEPA 趋势模板 8 条件检查"""
    if df_hist.empty or len(df_hist) < 250:
        return {"passed": False, "detail": "历史数据不足"}

    last = df_hist.iloc[-1]
    close = last["close"]
    ma50 = df_hist["close"].rolling(SEPA_CONFIG["均线短期"]).mean().iloc[-1]
    ma150 = df_hist["close"].rolling(SEPA_CONFIG["均线中期"]).mean().iloc[-1]
    ma200 = df_hist["close"].rolling(SEPA_CONFIG["均线长期"]).mean().iloc[-1]

    high_52w = df_hist["high"].tail(252).max()
    low_52w = df_hist["low"].tail(252).min()

    passed = True
    details = {}

    # ① 股价 > 150日均线
    cond1 = close > ma150
    passed &= cond1
    details["股价>150日均线"] = cond1

    # ② 股价 > 200日均线
    cond2 = close > ma200
    passed &= cond2
    details["股价>200日均线"] = cond2

    # ③ 150日均线 > 200日均线
    cond3 = ma150 > ma200
    passed &= cond3
    details["150日>200日均线"] = cond3

    # ④ 200日均线至少上涨1个月
    ma200_1m_ago = df_hist["close"].rolling(200).mean().iloc[-22] if len(df_hist) >= 222 else ma200
    cond4 = ma200 >= ma200_1m_ago
    passed &= cond4
    details["200日均线趋势向上"] = cond4

    # ⑤ 50日均线 > 150日和200日均线
    cond5 = ma50 > ma150 and ma50 > ma200
    passed &= cond5
    details["50日>150日>200日均线"] = cond5

    # ⑥ 股价 > 50日均线
    cond6 = close > ma50
    passed &= cond6
    details["股价>50日均线"] = cond6

    # ⑦ 股价 > 52周低点的130%
    cond7 = close > low_52w * 1.3 if low_52w > 0 else False
    passed &= cond7
    details["股价>52周低点130%"] = cond7

    # ⑧ 股价 > 52周高点的75%
    cond8 = close > high_52w * 0.75 if high_52w > 0 else False
    passed &= cond8
    details["股价>52周高点75%"] = cond8

    return {
        "passed": passed,
        "close": close,
        "ma50": ma50,
        "ma150": ma150,
        "ma200": ma200,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "detail": details,
    }


def estimate_fundamental_score(code: str) -> dict:
    """估算基本面因子评分（五因子模型简化版）"""
    result = {
        "确定需求": 0,
        "受限供给": 0,
        "低关注度": 0,
        "价值捕获": 0,
        "催化剂": 0,
        "total": 0,
        "detail": {},
    }

    try:
        # 获取财务数据
        financials = ak.stock_financial_abstract(symbol=code)
        if not financials.empty:
            latest = financials.iloc[0]
            eps = latest.get("基本每股收益", 0)
            revenue = latest.get("营业收入", 0)
            profit = latest.get("净利润", 0)

            # 简化评分：基于行业和财务指标推断
            # 确定需求：看营收增速
            rev_growth = latest.get("营收同比", 0)
            if isinstance(rev_growth, (int, float)):
                if rev_growth > 30:
                    result["确定需求"] = 20
                elif rev_growth > 15:
                    result["确定需求"] = 15
                elif rev_growth > 0:
                    result["确定需求"] = 10
                else:
                    result["确定需求"] = 5
                result["detail"]["营收同比"] = f"{rev_growth:.1f}%"

            # 价值捕获：看毛利率
            gross_margin = latest.get("毛利率", 0)
            if isinstance(gross_margin, (int, float)):
                if gross_margin > 50:
                    result["价值捕获"] = 18
                elif gross_margin > 30:
                    result["价值捕获"] = 14
                elif gross_margin > 15:
                    result["价值捕获"] = 10
                else:
                    result["价值捕获"] = 5
                result["detail"]["毛利率"] = f"{gross_margin:.1f}%"

    except Exception as e:
        logger.debug(f"获取 {code} 财务数据失败: {e}")

    # 受限供给 - 基于行业判断（简化处理）
    # 可在外部调用时根据行业信息传入
    result.setdefault("受限供给", 15)
    result.setdefault("低关注度", 10)
    result.setdefault("催化剂", 10)

    result["total"] = (result["确定需求"] + result["受限供给"] +
                       result["低关注度"] + result["价值捕获"] + result["催化剂"])
    return result


def run_sepa_screening(df_market: pd.DataFrame, df_histories: Dict[str, pd.DataFrame],
                       sector_rank_info: Dict[str, int]) -> List[dict]:
    """执行 SEPA 趋势模板 + 基本面筛选"""
    results = []
    for _, row in df_market.iterrows():
        code = row["code"]
        hist = df_histories.get(code)
        if hist is None or hist.empty:
            continue

        # SEPA 趋势模板
        sepa = check_sepa_trend_template(hist)
        if not sepa["passed"]:
            continue

        # 基本面评分
        fund = estimate_fundamental_score(code)
        total_score = sepa.get("score_override", 0) or fund["total"]

        # VCP 形态检查（简版：看波动是否收缩）
        recent_volatility = hist["close"].tail(20).std() / hist["close"].tail(20).mean()
        is_vcp = recent_volatility < 0.05  # 波动率 < 5% 为紧凑形态

        results.append({
            "code": code,
            "name": row.get("name", ""),
            "price": row.get("price", 0),
            "total_score": total_score,
            "sepa_passed": True,
            "sepa_detail": sepa["detail"],
            "fundamental": fund,
            "is_vcp": is_vcp,
            "sector": row.get("sector", ""),
            "pct_change_5d": row.get("pct_5d", 0),
            "pct_change_60d": row.get("pct_60d", 0),
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results
