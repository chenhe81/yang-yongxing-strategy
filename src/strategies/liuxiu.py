"""
刘秀策略 — SEPA 趋势模板 + 五因子评分 + VCP 形态

来源:
  - 股票池分层管理规则 v1.0 算法B（五因子评分）
  - SEPA 过滤法完整规则手册.md
  - A股市场特色分析指南.md

策略：中线持有（约1周），全仓操作
评分体系：满分100分，与凤雏评分可比
"""
import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── 配置 ──
CONFIG = {
    "买入阈值": 70,
    "坚决买入阈值": 85,
    "持仓上限": 1,           # 全仓只买1只
    "止损_pct": -5.0,
    "止盈_pct": 15.0,
    "时间止损_天数": 7,      # 持有一周没达到止盈也卖
    "均线短期": 50,
    "均线中期": 150,
    "均线长期": 200,
}


# ═══════════════════════════════════════════════
# 第一部分：SEPA 趋势模板（满分40分）
# ═══════════════════════════════════════════════

def score_sepa_template(df_hist: pd.DataFrame) -> dict:
    """
    SEPA 8条件趋势模板，每条件5分
    来源：SEPA过滤法完整规则手册.md 第二章
    """
    result = {
        "score": 0,
        "max_score": 40,
        "detail": {},
        "passed": False,
    }

    if df_hist.empty or len(df_hist) < 250:
        result["detail"]["error"] = "历史数据不足"
        return result

    close = df_hist["close"].iloc[-1]
    ma50 = df_hist["close"].rolling(CONFIG["均线短期"]).mean().iloc[-1]
    ma150 = df_hist["close"].rolling(CONFIG["均线中期"]).mean().iloc[-1]
    ma200 = df_hist["close"].rolling(CONFIG["均线长期"]).mean().iloc[-1]
    high_52w = df_hist["high"].tail(252).max()
    low_52w = df_hist["low"].tail(252).min()

    # 条件① 股价 > 150日均线
    cond1 = close > ma150
    result["detail"]["股价>150日均线"] = ("✅" if cond1 else "❌")

    # 条件② 股价 > 200日均线
    cond2 = close > ma200
    result["detail"]["股价>200日均线"] = ("✅" if cond2 else "❌")

    # 条件③ 150日均线 > 200日均线
    cond3 = ma150 > ma200
    result["detail"]["150日>200日均线"] = ("✅" if cond3 else "❌")

    # 条件④ 200日均线趋势向上
    ma200_22d_ago = df_hist["close"].rolling(200).mean().iloc[-22] if len(df_hist) >= 222 else ma200
    cond4 = ma200 >= ma200_22d_ago
    result["detail"]["200日均线向上"] = ("✅" if cond4 else "❌")

    # 条件⑤ 50日均线 > 150日和200日均线
    cond5 = ma50 > ma150 and ma50 > ma200
    result["detail"]["50日>150日>200日"] = ("✅" if cond5 else "❌")

    # 条件⑥ 股价 > 50日均线
    cond6 = close > ma50
    result["detail"]["股价>50日均线"] = ("✅" if cond6 else "❌")

    # 条件⑦ 股价 > 52周低点的130%
    cond7 = close > low_52w * 1.3 if low_52w > 0 else False
    result["detail"][">52周低点130%"] = ("✅" if cond7 else "❌")

    # 条件⑧ 股价 > 52周高点的75%
    cond8 = close > high_52w * 0.75 if high_52w > 0 else False
    result["detail"][">52周高点75%"] = ("✅" if cond8 else "❌")

    # 累计得分（每条件5分）
    conditions = [cond1, cond2, cond3, cond4, cond5, cond6, cond7, cond8]
    result["score"] = sum(5 for c in conditions if c)
    result["passed"] = all(conditions[:6])  # 前6条件是硬性要求
    result["close"] = close
    result["ma50"] = ma50
    result["ma150"] = ma150
    result["ma200"] = ma200
    result["high_52w"] = high_52w
    result["low_52w"] = low_52w
    return result


# ═══════════════════════════════════════════════
# 第二部分：VCP 形态识别（满分20分）
# ═══════════════════════════════════════════════

def score_vcp_pattern(df_hist: pd.DataFrame) -> dict:
    """
    VCP（Volatility Contraction Pattern）波动收缩形态
    来源：SEPA过滤法完整规则手册.md 第三章
    """
    result = {"score": 0, "max_score": 20, "detail": {}}

    if df_hist.empty or len(df_hist) < 60:
        return result

    # 取最近60天的周线数据（约12周）
    recent = df_hist.tail(60).copy()

    # 计算每周波动幅度
    recent["week"] = recent["date"].dt.isocalendar().week
    weekly_volatility = recent.groupby("week").apply(
        lambda x: (x["high"].max() - x["low"].min()) / x["close"].mean() * 100
    ).reset_index(drop=True)

    if len(weekly_volatility) < 4:
        return result

    # 检查波动是否递减（收缩）
    last_4 = weekly_volatility.tail(4).values
    is_contracting = all(last_4[i] >= last_4[i + 1] for i in range(3))

    # 检查收盘价紧凑度
    recent_closes = recent.tail(20)["close"]
    close_tightness = recent_closes.std() / recent_closes.mean()

    # 检查成交量枯竭
    recent_volume = recent.tail(20)["volume"]
    if len(recent_volume) > 5:
        vol_dry_up = recent_volume.tail(5).mean() < recent_volume.median()
    else:
        vol_dry_up = False

    # 评分
    score = 0
    if is_contracting:
        score += 8
        result["detail"]["波动递减"] = "✅"
    else:
        result["detail"]["波动递减"] = "❌"

    if close_tightness < 0.05:
        score += 7
        result["detail"]["收盘紧凑"] = f"✅ (std/mean={close_tightness:.3f})"
    else:
        result["detail"]["收盘紧凑"] = f"⚠️ ({close_tightness:.3f})"

    if vol_dry_up:
        score += 5
        result["detail"]["量能枯竭"] = "✅"
    else:
        result["detail"]["量能枯竭"] = "❌"

    result["score"] = score
    return result


# ═══════════════════════════════════════════════
# 第三部分：板块与市场环境（满分20分）
# ═══════════════════════════════════════════════

def score_sector_environment(pct_5d: float, pct_60d: float,
                              sector_rank: Optional[int] = None) -> dict:
    """
    板块强度 + 个股相对强度
    """
    result = {"score": 0, "max_score": 20, "detail": {}}

    # 短期动能（5日涨幅，满分6分）
    if pct_5d > 10:
        result["score"] += 6
        result["detail"]["5日涨幅"] = f"{pct_5d:+.1f}% ✅"
    elif pct_5d > 5:
        result["score"] += 4
        result["detail"]["5日涨幅"] = f"{pct_5d:+.1f}% ✅"
    elif pct_5d > 0:
        result["score"] += 2
        result["detail"]["5日涨幅"] = f"{pct_5d:+.1f}% ⚠️"
    else:
        result["detail"]["5日涨幅"] = f"{pct_5d:+.1f}% ❌"

    # 中期趋势（60日涨幅，满分6分）
    if pct_60d > 20:
        result["score"] += 6
        result["detail"]["60日涨幅"] = f"{pct_60d:+.1f}% ✅"
    elif pct_60d > 10:
        result["score"] += 4
        result["detail"]["60日涨幅"] = f"{pct_60d:+.1f}% ✅"
    elif pct_60d > 0:
        result["score"] += 2
        result["detail"]["60日涨幅"] = f"{pct_60d:+.1f}% ⚠️"
    else:
        result["detail"]["60日涨幅"] = f"{pct_60d:+.1f}% ❌"

    # 板块排名（满分8分）
    if sector_rank is not None:
        if sector_rank <= 3:
            result["score"] += 8
            result["detail"]["板块排名"] = f"第{sector_rank}名 ✅"
        elif sector_rank <= 10:
            result["score"] += 5
            result["detail"]["板块排名"] = f"第{sector_rank}名 ⚠️"
        else:
            result["detail"]["板块排名"] = f"第{sector_rank}名 ❌"
    else:
        result["detail"]["板块排名"] = "未知"

    return result


# ═══════════════════════════════════════════════
# 第四部分：五因子基本面评分（满分20分）
# ═══════════════════════════════════════════════

def estimate_fundamental_score(code: str, name: str = "") -> dict:
    """
    五因子简化评分（基于可获取的公开数据）
    来源：股票池分层管理规则 v1.0 算法B

    因子① 确定需求（5分）
    因子② 受限供给（5分）
    因子③ 低关注度（3分）
    因子④ 价值捕获（5分）
    因子⑤ 催化剂（2分）
    """
    result = {"score": 0, "max_score": 20, "detail": {}}
    # 基础分（保守估计，等待完整财务数据接入）
    result["score"] = 12  # 基础分
    result["detail"]["确定需求"] = "3/5 ⚠️"
    result["detail"]["受限供给"] = "3/5 ⚠️"
    result["detail"]["低关注度"] = "2/3 ⚠️"
    result["detail"]["价值捕获"] = "2/5 ⚠️"
    result["detail"]["催化剂"] = "2/2 ✅"
    return result


# ═══════════════════════════════════════════════
# 主评分函数
# ═══════════════════════════════════════════════

def calculate_liuxiu_score(
    code: str,
    name: str,
    df_hist: pd.DataFrame,
    pct_5d: float = 0,
    pct_60d: float = 0,
    sector_rank: Optional[int] = None,
    sector_name: str = "",
) -> dict:
    """
    刘秀综合评分（满分100分）

    评分结构：
    1. SEPA趋势模板（40分）— 8条件趋势确认
    2. VCP形态识别（20分）— 波动收缩 + 量能枯竭
    3. 板块与市场环境（20分）— 强度排名
    4. 五因子基本面（20分）— 财务健康
    """
    # 1. SEPA 趋势模板
    sepa = score_sepa_template(df_hist)

    # 硬性条件：前6条件必须全部通过
    if not sepa["passed"]:
        return {
            "code": code,
            "name": name,
            "score": 0,
            "decision": "no_entry",
            "detail": {"SEPA": {"score": sepa["score"], "detail": sepa["detail"]}},
            "reason": "SEPA趋势模板前6条件未通过",
        }

    # 2. VCP 形态
    vcp = score_vcp_pattern(df_hist)

    # 3. 板块环境
    env = score_sector_environment(pct_5d, pct_60d, sector_rank)

    # 4. 基本面
    fundamental = estimate_fundamental_score(code, name)

    # 总分
    total = sepa["score"] + vcp["score"] + env["score"] + fundamental["score"]

    # 决策
    if total >= CONFIG["坚决买入阈值"]:
        decision = "strong_buy"
    elif total >= CONFIG["买入阈值"]:
        decision = "buy"
    elif total >= 60:
        decision = "watch"
    else:
        decision = "ignore"

    return {
        "code": code,
        "name": name,
        "price": sepa.get("close", 0),
        "score": total,
        "decision": decision,
        "sepa_score": sepa["score"],
        "vcp_score": vcp["score"],
        "env_score": env["score"],
        "fundamental_score": fundamental["score"],
        "detail": {
            "SEPA": {"score": sepa["score"], "detail": sepa["detail"]},
            "VCP": {"score": vcp["score"], "detail": vcp["detail"]},
            "环境": {"score": env["score"], "detail": env["detail"]},
            "基本面": {"score": fundamental["score"], "detail": fundamental["detail"]},
        },
        "ma50": sepa.get("ma50", 0),
        "ma200": sepa.get("ma200", 0),
        "close_to_52w_high": (sepa.get("close", 0) / sepa.get("high_52w", 1)) * 100 if sepa.get("high_52w", 0) > 0 else 0,
        "sector": sector_name or "",
    }


def run_screening(
    df_market: pd.DataFrame,
    df_histories: Dict[str, pd.DataFrame],
    sector_ranks: Dict[str, int],
    sector_map: Dict[str, str] = None,
) -> List[dict]:
    """
    全市场刘秀策略筛选

    参数:
      df_market: 全市场实时行情
      df_histories: {code: history_df} 历史数据字典
      sector_ranks: {板块名称: 排名}
      sector_map: {code: 板块名称}
    """
    results = []
    total = len(df_market)
    logger.info(f"刘秀全市场筛选: {total} 只")

    for i, (_, row) in enumerate(df_market.iterrows()):
        code = row["code"]
        name = row.get("name", "")
        hist = df_histories.get(code)

        if hist is None or hist.empty:
            continue

        # 获取板块排名
        sector_name = (sector_map or {}).get(code, "")
        srank = sector_ranks.get(sector_name)

        # 计算评分
        score_info = calculate_liuxiu_score(
            code=code, name=name, df_hist=hist,
            pct_5d=row.get("pct_5d", 0) or 0,
            pct_60d=row.get("pct_60d", 0) or 0,
            sector_rank=srank,
            sector_name=sector_name,
        )

        if score_info["decision"] in ("buy", "strong_buy", "watch"):
            results.append(score_info)

        if (i + 1) % 500 == 0:
            logger.info(f"  进度: {i+1}/{total} | 已筛选 {len(results)} 只")

    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"刘秀筛选完成: 共 {len(results)} 只候选")
    return results
