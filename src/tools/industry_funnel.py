#!/usr/bin/env python3
"""
行业漏斗筛选 — 基于 ai-berkshire industry-funnel 框架的量化实现

功能：
  1. 获取东方财富行业板块，映射股票池股票到各行业
  2. 对行业进行多维度评分（覆盖度 + 动量 + 质量 + 活跃度 + 集中度）
  3. 输出行业排名 + 每个优选的股票

用法：
  python3 -m src.tools.industry_funnel                # 完整运行
  python3 -m src.tools.industry_funnel --top 10        # 输出前10行业
  python3 -m src.tools.industry_funnel --output funnel.json  # 指定JSON输出路径

集成到凤雏：
  1. 每日收盘后运行一次（算力中心或凤雏均可）
  2. 输出 JSON 被凤雏读取，调整各行业扫描权重
  3. 刘秀日报包含行业排名摘要
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

# 加入项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

logger = logging.getLogger(__name__)

# ── 缓存路径 ──
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
INDUSTRY_CACHE = os.path.join(CACHE_DIR, "industry_boards.json")
INDUSTRY_CONST_CACHE_DIR = os.path.join(CACHE_DIR, "industry_constituents")

# ── 输出路径 ──
FUNNEL_OUTPUT = os.path.join(BASE_DIR, "data", "industry_funnel.json")
REPORT_OUTPUT = os.path.join(BASE_DIR, "data", "industry_funnel_report.md")

# ── 评分权重 ──
WEIGHTS = {
    "momentum": 0.30,       # 短期动量
    "quality": 0.30,        # 质量（ROE+毛利率+OCF通过率）
    "activity": 0.15,       # 成交活跃度
    "coverage": 0.10,       # 股票池覆盖度
    "concentration": 0.15,  # 龙头集中度
}

# ── 板块常量 ──
_akshare_available = None


def _check_akshare() -> bool:
    """检查 akshare 是否可用"""
    global _akshare_available
    if _akshare_available is not None:
        return _akshare_available
    try:
        import akshare as ak
        _akshare_available = True
        return True
    except ImportError:
        _akshare_available = False
        logger.warning("akshare 不可用")
        return False


def _ak_call(func, timeout=30):
    """带超时的 akshare 调用包装"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(func)
        return future.result(timeout=timeout)


def load_stock_pool() -> List[Dict[str, str]]:
    """加载股票池"""
    pool_path = os.path.join(BASE_DIR, "data", "stock_pool.json")
    if os.path.exists(pool_path):
        with open(pool_path, "r", encoding="utf-8") as f:
            return json.load(f)
    logger.warning("股票池文件不存在，使用空池")
    return []


# ── 1. 行业板块获取 ──

def fetch_industry_boards(force_refresh: bool = False) -> pd.DataFrame:
    """获取东方财富行业板块列表，带缓存"""
    import akshare as ak

    if not force_refresh and os.path.exists(INDUSTRY_CACHE):
        # 检查缓存是否过期（7天）
        mtime = os.path.getmtime(INDUSTRY_CACHE)
        if datetime.now().timestamp() - mtime < 7 * 86400:
            with open(INDUSTRY_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"行业板块缓存加载: {len(data)} 个")
            return pd.DataFrame(data)

    df = _ak_call(lambda: ak.stock_board_industry_name_em())
    if df is not None and not df.empty:
        with open(INDUSTRY_CACHE, "w", encoding="utf-8") as f:
            json.dump(df.to_dict("records"), f, ensure_ascii=False)
        logger.info(f"行业板块已获取: {len(df)} 个")
    return df


def fetch_board_constituents(board_name: str) -> List[str]:
    """获取行业板块的成分股代码列表，带缓存"""
    import akshare as ak

    os.makedirs(INDUSTRY_CONST_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(INDUSTRY_CONST_CACHE_DIR, f"{board_name}.json")

    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if datetime.now().timestamp() - mtime < 7 * 86400:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)

    try:
        df = _ak_call(lambda: ak.stock_board_industry_cons_em(symbol=board_name))
        if df is not None and not df.empty and "代码" in df.columns:
            codes = [str(c).zfill(6) for c in df["代码"].tolist()]
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(codes, f, ensure_ascii=False)
            time.sleep(0.15)
            return codes
    except Exception as e:
        logger.warning(f"获取 {board_name} 成分股失败: {e}")

    return []


# ── 2. 行业评分 ──

def _compute_momentum_score(codes: List[str], stock_pool_set: set) -> float:
    """计算行业动量分：近5日涨幅均值"""
    import akshare as ak

    returns = []
    sampled = [c for c in codes if c in stock_pool_set][:10]  # 取前10只
    if not sampled:
        return 0.0

    for code in sampled:
        try:
            df = _ak_call(
                lambda c=code: ak.stock_zh_a_hist(
                    symbol=c, period="daily", start_date=(datetime.now() - timedelta(days=10)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"), adjust="qfq"
                )
            )
            if df is not None and len(df) >= 3:
                close = df["收盘"].values
                ret = (close[-1] - close[0]) / close[0] * 100
                returns.append(ret)
            time.sleep(0.1)
        except Exception:
            continue

    if not returns:
        return 0.0
    return float(np.mean(returns))


def _compute_quality_score(codes: List[str], stock_pool_set: set, quality_results: Dict) -> float:
    """计算行业质量分：通过 quality_screen 的比例"""
    in_pool = [c for c in codes if c in stock_pool_set]
    if not in_pool:
        return 0.0

    # 统计已有的 quality 结果
    passed = 0
    checked = 0
    for code in in_pool:
        if code in quality_results:
            checked += 1
            if quality_results[code].get("pass", False):
                passed += 1

    if checked == 0:
        return 0.5  # 无数据时给中值
    return passed / checked


def _compute_activity_score(codes: List[str], stock_pool_set: set) -> float:
    """计算行业活跃度分：成交量 vs 均量"""
    import akshare as ak

    ratios = []
    sampled = [c for c in codes if c in stock_pool_set][:10]
    if not sampled:
        return 0.0

    for code in sampled:
        try:
            df = _ak_call(
                lambda c=code: ak.stock_zh_a_hist(
                    symbol=c, period="daily", start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"), adjust="qfq"
                )
            )
            if df is not None and len(df) >= 10:
                vol = df["成交量"].values
                recent_avg = vol[-5:].mean()
                hist_avg = vol[-30:-5].mean() if len(vol) > 10 else vol.mean()
                if hist_avg > 0:
                    ratios.append(recent_avg / hist_avg)
            time.sleep(0.1)
        except Exception:
            continue

    if not ratios:
        return 0.0
    avg_ratio = float(np.mean(ratios))
    # 映射到 0~1：正常1.0=0.5分，放量2.0=0.8分，缩量0.5=0.2分
    return min(1.0, max(0.0, avg_ratio * 0.4))


def _compute_coverage_score(codes: List[str], stock_pool_set: set, total_pool: int) -> float:
    """计算行业覆盖度分：该行业在股票池中的占比"""
    count = len([c for c in codes if c in stock_pool_set])
    ratio = count / max(total_pool, 1)
    # 映射：1%以下=0.2, 1-3%=0.5, 3-5%=0.7, 5%+=0.9
    if ratio < 0.01:
        return 0.2
    elif ratio < 0.03:
        return 0.5
    elif ratio < 0.05:
        return 0.7
    else:
        return 0.9


def _compute_concentration_score(codes: List[str], stock_pool_set: set, quality_results: Dict) -> float:
    """计算行业集中度分：龙头是否清晰"""
    in_pool = [c for c in codes if c in stock_pool_set]
    n_stocks = len(in_pool)
    if n_stocks < 3:
        return 0.3  # 行业太小，集中度无意义

    # 用市值作为proxy（从quality_results里提取分数排序）
    scored = []
    for code in in_pool:
        qr = quality_results.get(code, {})
        scores = qr.get("scores", {})
        roe = scores.get("ROE", 0)
        if isinstance(roe, (int, float)):
            scored.append((code, roe))

    scored.sort(key=lambda x: x[1], reverse=True)
    if len(scored) >= 3:
        top3_share = sum(s[1] for s in scored[:3]) / max(sum(s[1] for s in scored), 1)
        return min(1.0, top3_share * 1.5)  # 前3占30%以上=0.45
    return 0.5


# ── 3. 主漏斗 ──

def run_funnel(stock_pool: List[Dict] = None, top_n: int = 10,
               quality_results: Dict = None, force_refresh: bool = False) -> Dict:
    """运行完整行业漏斗

    Args:
        stock_pool: 股票池列表，None时自动加载
        top_n: 返回前N个行业
        quality_results: 已有的quality_screen结果 {code: result}，None时自动计算
        force_refresh: 强制刷新行业缓存

    Returns:
        {"timestamp": "...", "industries": [...], "top_industries": [...]}
    """
    if not _check_akshare():
        return {"timestamp": datetime.now().isoformat(), "industries": [], "top_industries": []}

    if stock_pool is None:
        stock_pool = load_stock_pool()

    pool_codes = set(s["code"] for s in stock_pool)

    # 获取行业板块
    boards = fetch_industry_boards(force_refresh=force_refresh)
    if boards is None or boards.empty:
        logger.error("无法获取行业板块数据")
        return {"timestamp": datetime.now().isoformat(), "industries": [], "top_industries": []}

    # 获取行业名列表
    board_names = boards["板块名称"].tolist() if "板块名称" in boards.columns else []
    logger.info(f"共 {len(board_names)} 个行业板块，开始扫描...")

    # 对每个行业评分
    industry_scores = []
    for i, name in enumerate(board_names):
        codes = fetch_board_constituents(name)
        if not codes:
            continue

        # 过滤有股票池中的股票
        in_pool = [c for c in codes if c in pool_codes]
        if len(in_pool) < 3:
            continue  # 少于3只在池中，忽略

        momentum = _compute_momentum_score(codes, pool_codes)
        quality = _compute_quality_score(codes, pool_codes, quality_results or {})
        activity = _compute_activity_score(codes, pool_codes)
        coverage = _compute_coverage_score(codes, pool_codes, len(pool_codes))
        concentration = _compute_concentration_score(codes, pool_codes, quality_results or {})

        composite = (
            WEIGHTS["momentum"] * momentum +
            WEIGHTS["quality"] * quality +
            WEIGHTS["activity"] * activity +
            WEIGHTS["coverage"] * coverage +
            WEIGHTS["concentration"] * concentration
        )

        # 选出行业内池中最好3只
        in_pool_stocks = [s for s in stock_pool if s["code"] in in_pool][:10]
        top_stocks = sorted(in_pool_stocks,
                           key=lambda s: quality_results.get(s["code"], {}).get("pass", False),
                           reverse=True)[:3]

        industry_scores.append({
            "board_name": name,
            "n_pool": len(in_pool),
            "n_total": len(codes),
            "score_momentum": round(momentum, 2),
            "score_quality": round(quality, 2),
            "score_activity": round(activity, 2),
            "score_coverage": round(coverage, 2),
            "score_concentration": round(concentration, 2),
            "composite_score": round(composite, 3),
            "top_stocks": [{"code": s["code"], "name": s.get("name", "")} for s in top_stocks],
        })

        if (i + 1) % 20 == 0:
            logger.info(f"  已扫描 {i+1}/{len(board_names)} 个行业...")

    # 排序
    industry_scores.sort(key=lambda x: x["composite_score"], reverse=True)
    top = industry_scores[:top_n]

    result = {
        "timestamp": datetime.now().isoformat(),
        "total_industries": len(industry_scores),
        "total_stocks_in_pool": len(pool_codes),
        "top_n": top_n,
        "industries": industry_scores,
        "top_industries": top,
    }
    return result


# ── 4. 报告生成 ──

def generate_report(result: Dict) -> str:
    """生成 Markdown 格式的行业漏斗报告"""
    lines = []

    # 头部
    ts = result.get("timestamp", "")[:10]
    lines.append(f"# 行业漏斗筛选报告 {ts}")
    lines.append("")
    lines.append(f"**扫描行业**: {result.get('total_industries', 0)} 个 | "
                 f"**股票池**: {result.get('total_stocks_in_pool', 0)} 只")
    lines.append("")

    # 排名表
    lines.append("## 行业排名 Top 10")
    lines.append("")
    lines.append("| 排名 | 行业 | 综合分 | 动量 | 质量 | 活跃度 | 覆盖度 | 集中度 | 池中数 | 龙头股 |")
    lines.append("|------|------|--------|------|------|--------|--------|--------|--------|--------|")

    top = result.get("top_industries", [])
    for rank, ind in enumerate(top, 1):
        name = ind["board_name"][:12]
        cs = ind["composite_score"]
        sm = ind["score_momentum"]
        sq = ind["score_quality"]
        sa = ind["score_activity"]
        sc = ind["score_coverage"]
        scc = ind["score_concentration"]
        np_ = ind["n_pool"]
        top_s = ind["top_stocks"][0]["name"] if ind["top_stocks"] else "—"
        lines.append(f"| {rank} | {name} | {cs:.2f} | {sm:+.1f}% | {sq:.0%} | {sa:.2f} | {sc:.1f} | {scc:.2f} | {np_} | {top_s} |")

    lines.append("")

    # 前3名详细
    lines.append("## 前 3 行业优选标的")
    lines.append("")
    for rank, ind in enumerate(top[:3], 1):
        name = ind["board_name"]
        lines.append(f"### {rank}. {name}（{ind['composite_score']:.2f}分）")
        lines.append("")
        lines.append(f"- **池中/总数**: {ind['n_pool']}/{ind['n_total']}")
        lines.append(f"- **动量**: {ind['score_momentum']:+.1f}% | **质量**: {ind['score_quality']:.0%} | "
                     f"**活跃度**: {ind['score_activity']:.2f}")
        lines.append("")
        lines.append("| # | 代码 | 名称 |")
        lines.append("|---|------|------|")
        for si, s in enumerate(ind["top_stocks"], 1):
            lines.append(f"| {si} | {s['code']} | {s['name']} |")
        lines.append("")

    # 警告
    lines.append("## 注意事项")
    lines.append("")
    lines.append("- 本报告基于东方财富行业板块数据，并非所有行业都有完整覆盖")
    lines.append("- 动量基于近5日涨跌幅，可能受短期事件干扰")
    lines.append("- 质量分基于 quality_screen 结果，仅反映基本面达标比例")
    lines.append("- 建议结合行业政策、产业周期等定性判断使用")
    lines.append("")

    return "\n".join(lines)


# ── 5. 保存输出 ──

def save_results(result: Dict, json_path: str = None, md_path: str = None):
    """保存漏斗结果"""
    if json_path is None:
        json_path = FUNNEL_OUTPUT
    if md_path is None:
        md_path = REPORT_OUTPUT

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已保存: {json_path}")

    report = generate_report(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"报告已保存: {md_path}")


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="行业漏斗筛选")
    parser.add_argument("--top", type=int, default=10, help="返回前N个行业")
    parser.add_argument("--output", type=str, default=None, help="JSON输出路径")
    parser.add_argument("--force-refresh", action="store_true", help="强制刷新缓存")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not _check_akshare():
        logger.error("akshare 不可用，无法运行行业漏斗")
        sys.exit(1)

    logger.info("开始行业漏斗筛选...")

    # 1. 加载股票池
    pool = load_stock_pool()
    logger.info(f"股票池: {len(pool)} 只")

    # 2. 运行漏斗
    result = run_funnel(pool, top_n=args.top, force_refresh=args.force_refresh)
    logger.info(f"漏斗完成: {result.get('total_industries', 0)} 个行业")

    # 3. 保存
    save_results(result, json_path=args.output)
    print(f"\n行业漏斗完成！详见:")
    print(f"  JSON: {args.output or FUNNEL_OUTPUT}")
    print(f"  报告: {REPORT_OUTPUT}")

    # 打印前5
    print(f"\n--- 行业 Top {min(5, len(result.get('top_industries', [])))} ---")
    for i, ind in enumerate(result.get("top_industries", [])[:5], 1):
        print(f"  {i}. {ind['board_name']:12s} 综合:{ind['composite_score']:.2f}  "
              f"动量:{ind['score_momentum']:+.1f}% 质量:{ind['score_quality']:.0%}")
        top3 = [s["name"] for s in ind.get("top_stocks", [])]
        if top3:
            print(f"     龙头: {', '.join(top3)}")


if __name__ == "__main__":
    main()
