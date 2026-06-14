"""
青鸾策略 — 基于杨永兴战法的技术面日筛 + 隔夜套利

来源：
  - 青鸾战法执行手册.md
  - 杨永兴-十步尾盘买入法原文.md
  - 股票池分层管理规则 v1.0 算法A
"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── 硬性条件阈值 ──
CONFIG = {
    "涨幅下限": 3.0,
    "涨幅上限": 5.0,
    "量比下限": 1.0,
    "换手下限": 5.0,
    "换手上限": 10.0,
    "市值下限_亿": 50,
    "市值上限_亿": 200,
    "板块排名上限": 3,
    "买入评分阈值": 70,
    "坚决买入阈值": 80,
    "同时持仓上限": 2,
}


def score_price_change(pct: float) -> int:
    if 3.0 <= pct <= 5.0:
        return 25
    if 2.5 <= pct < 3.0:
        return 15
    return 0


def score_volume_ratio(vr: float) -> int:
    if vr > 1.5:
        return 15
    if vr >= 1.0:
        return 10
    return 0


def score_above_vwap(vwap_ok: bool, mostly_ok: bool = False) -> int:
    if vwap_ok:
        return 15
    if mostly_ok:
        return 10
    return 0


def score_turnover(turn: float) -> int:
    if 5.0 <= turn <= 8.0:
        return 15
    if 8.0 < turn <= 10.0:
        return 10
    if 10.0 < turn <= 15.0:
        return 5
    return 0


def score_market_cap(mv_亿: float) -> int:
    if 80 <= mv_亿 <= 150:
        return 15
    if 50 <= mv_亿 < 80 or 150 < mv_亿 <= 200:
        return 10
    if mv_亿 < 50:
        return 5
    return 0


def score_history(has_limit_up: bool, volume_stable: bool, no_resistance: bool) -> int:
    s = 0
    if has_limit_up:
        s += 10
    if volume_stable:
        s += 5
    if no_resistance:
        s += 5
    return s


def check_hard_conditions(row: dict) -> tuple:
    """检查硬性条件是否全部满足，返回 (通过, 失败原因)"""
    pct = row.get("pct_change", 0)
    vr = row.get("volume_ratio", 0)
    turn = row.get("turnover", 0)
    mv = row.get("float_mv", 0)

    if not (CONFIG["涨幅下限"] <= pct <= CONFIG["涨幅上限"]):
        return False, f"涨幅 {pct:.1f}% 不在 {CONFIG['涨幅下限']}-{CONFIG['涨幅上限']}%"
    if vr < CONFIG["量比下限"]:
        return False, f"量比 {vr:.2f} < {CONFIG['量比下限']}"
    if not (CONFIG["换手下限"] <= turn <= CONFIG["换手上限"]):
        return False, f"换手 {turn:.1f}% 不在 {CONFIG['换手下限']}-{CONFIG['换手上限']}%"
    mv_亿 = mv / 1e8
    if not (CONFIG["市值下限_亿"] <= mv_亿 <= CONFIG["市值上限_亿"]):
        return False, f"市值 {mv_亿:.0f}亿 不在 {CONFIG['市值下限_亿']}-{CONFIG['市值上限_亿']}亿"
    return True, ""


def calculate_qingluan_score(row: dict, sector_rank: Optional[int] = None) -> dict:
    """计算青鸾评分，返回完整评分明细"""
    pct = row.get("pct_change", 0)
    vr = row.get("volume_ratio", 0)
    turn = row.get("turnover", 0)
    mv = row.get("float_mv", 0)
    mv_亿 = mv / 1e8

    s_pct = score_price_change(pct)
    s_vr = score_volume_ratio(vr)
    s_vwap = score_above_vwap(row.get("above_vwap", False))
    s_turn = score_turnover(turn)
    s_mv = score_market_cap(mv_亿)
    s_hist = score_history(
        row.get("has_limit_up_20d", False),
        row.get("volume_stable", True),
        row.get("no_resistance", True),
    )
    total = s_pct + s_vr + s_vwap + s_turn + s_mv + s_hist

    # 板块加分
    sector_bonus = 0
    if sector_rank is not None:
        if sector_rank == 1:
            sector_bonus = 10
        elif sector_rank == 2:
            sector_bonus = 5
        elif sector_rank == 3:
            sector_bonus = 3

    return {
        "score": total + sector_bonus,
        "details": {
            "涨幅分": s_pct,
            "量比分": s_vr,
            "均价线上方分": s_vwap,
            "换手分": s_turn,
            "市值分": s_mv,
            "历史加分": s_hist,
            "板块加分": sector_bonus,
        },
        "price_change": f"{pct:.1f}%",
        "volume_ratio": f"{vr:.2f}",
        "turnover": f"{turn:.1f}%",
        "market_cap": f"{mv_亿:.0f}亿",
    }


def run_screening(candidates: List[dict], sector_ranks: Dict[str, int]) -> List[dict]:
    """
    对候选股执行青鸾评分筛选
    candidates: 经过基础过滤的股票列表（含 pct_change, volume_ratio, turnover, float_mv, code, name 等）
    sector_ranks: {板块名称: 当日排名}
    返回: 评分结果列表，已排序
    """
    results = []
    for stock in candidates:
        ok, reason = check_hard_conditions(stock)
        if not ok:
            continue

        sector = stock.get("sector", "")
        srank = sector_ranks.get(sector)
        if srank is not None and srank > CONFIG["板块排名上限"]:
            continue

        score_info = calculate_qingluan_score(stock, sector_rank=srank)
        decision = "ignore"
        if score_info["score"] >= CONFIG["坚决买入阈值"]:
            decision = "strong_buy"
        elif score_info["score"] >= CONFIG["买入评分阈值"]:
            decision = "buy"

        results.append({
            "code": stock["code"],
            "name": stock.get("name", ""),
            "price": stock.get("price", 0),
            "score": score_info["score"],
            "details": score_info["details"],
            "decision": decision,
            "pct_change": stock.get("pct_change", 0),
            "volume_ratio": stock.get("volume_ratio", 0),
            "turnover": stock.get("turnover", 0),
            "market_cap": stock.get("float_mv", 0),
            "sector": sector,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results
