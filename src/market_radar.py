"""
行情雷达 — 市场状态评分（0-100分）

评分维度：
  趋势状态   40%  — 均线排列 + MA价差（趋势强度）
  波动率     25%  — ATR历史分位（低波加分，高波减分）
  量价健康   20%  — 上涨量比 vs 下跌量比
  市场情绪   15%  — 涨跌家数比 + 整体量比

输出映射：
  70-100 → 动量趋势策略
  40-69  → 均值回归策略
  0-39   → 空仓/轻仓观望
"""
import sqlite3
import json
import os
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE), "data", "market_cache.db")
from src.tools.hmm_regime import HMMRegimeDetector
from src.tools.risk_models import GARCHVolatility
PROFILE_PATH = os.path.join(os.path.dirname(BASE), "data", "cycle_profile.json")


def _load_market_series(sample_size: int = 1063) -> pd.DataFrame:
    """
    从 daily_klines 中读取样本股票的日线数据，
    计算等权市场平均序列（日期 → 均值价）
    返回 DataFrame: date, avg_close, avg_high, avg_low, codes_used
    """
    db = sqlite3.connect(DB_PATH)
    
    # 从 cycle_profile 中取股票代码作为样本
    if os.path.exists(PROFILE_PATH):
        profile = json.load(open(PROFILE_PATH))
        sample_codes = list(profile.keys())[:sample_size]
    else:

        cur = db.execute("SELECT code FROM stock_list LIMIT ?", (sample_size,))
        sample_codes = [r[0] for r in cur.fetchall()]
    
    placeholders = ",".join(["?"] * len(sample_codes))
    
    df = pd.read_sql(
        f"SELECT date, code, close, high, low FROM daily_klines "
        f"WHERE code IN ({placeholders}) ORDER BY date, code",
        db, params=sample_codes
    )
    db.close()
    
    if df.empty:
        return pd.DataFrame()
    
    grouped = df.groupby("date").agg(
        avg_close=("close", "mean"),
        avg_high=("high", "mean"),
        avg_low=("low", "mean"),
        codes_used=("code", "nunique")
    ).reset_index()
    
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped.sort_values("date")


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """计算 ADX（平均趋向指数）"""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=high.index)
    
    tr_smooth = tr.ewm(span=period, adjust=False).mean()
    plus_smooth = plus_dm.ewm(span=period, adjust=False).mean()
    minus_smooth = minus_dm.ewm(span=period, adjust=False).mean()
    
    plus_di = 100 * plus_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100 * minus_smooth / tr_smooth.replace(0, np.nan)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    
    return adx


def _calc_trend_score(ma5: float, ma20: float, ma60: float, adx_val: float) -> tuple:
    """计算趋势状态得分（满分40分）"""
    bull = ma5 > ma20 > ma60
    bear = ma5 < ma20 < ma60
    ma_spread = abs(ma5 - ma60) / max(ma60, 1)
    
    if bull:
        if adx_val > 25:
            score = 35 + min(5, int(ma_spread / 0.02 * 2))
            label = "强多头"
        elif adx_val > 20:
            score = 25 + min(10, int(ma_spread / 0.02 * 3))
            label = "弱多头"
        else:
            score = 20 + min(10, int(ma_spread / 0.02 * 2))
            label = "震荡偏多"
    elif bear:
        if adx_val > 25:
            score = max(0, 10 - int(ma_spread / 0.02 * 3))
            label = "强空头"
        elif adx_val > 20:
            score = max(0, 15 - int(ma_spread / 0.02 * 3))
            label = "弱空头"
        else:
            score = max(0, 20 - int(ma_spread / 0.02 * 2))
            label = "震荡偏空"
    else:

        if ma5 > ma20:
            score = 15 + min(10, int(ma_spread / 0.01 * 2))
            label = "震荡略多"
        elif ma5 < ma20:
            score = 10 + min(10, int(ma_spread / 0.01 * 2))
            label = "震荡略空"
        else:
            score = 15
            label = "震荡持平"
    
    return min(40, max(0, score)), label



def _calc_bb_bandwidth_score(market_df: pd.DataFrame) -> tuple:
    """计算布林带宽分位分（满分：作为趋势维度的微调，±5分影响）"""
    if len(market_df) < 30:
        return 0, "数据不足"
    
    close = market_df["avg_close"]
    bb_period = 20
    upper = close.rolling(bb_period, min_periods=10).mean() + 2 * close.rolling(bb_period, min_periods=10).std()
    lower = close.rolling(bb_period, min_periods=10).mean() - 2 * close.rolling(bb_period, min_periods=10).std()
    middle = close.rolling(bb_period, min_periods=10).mean()
    
    bandwidth = (upper - lower) / middle.replace(0, float('nan'))
    latest_bw = bandwidth.iloc[-1]
    bw_history = bandwidth.dropna().values
    
    if len(bw_history) < 30 or pd.isna(latest_bw):
        return 0, "数据不足"
    
    percentile = (bw_history < latest_bw).mean()
    
    if percentile < 0.2:
        bonus = 5
        label = f"极度缩口(P{percentile:.0%})"
    elif percentile < 0.5:
        bonus = 3
        label = f"缩口(P{percentile:.0%})"
    elif percentile < 0.8:
        bonus = 0
        label = f"正常(P{percentile:.0%})"
    else:
        bonus = -3
        label = f"扩口(P{percentile:.0%})"
    
    # 缩口意味着即将变盘，倾向于震荡策略
    # 扩口意味着趋势已经启动，倾向于趋势策略
    return bonus, label



def _calc_volatility_score(atr_current: float, atr_252: np.ndarray) -> tuple:
    """计算波动率得分（满分25分）"""
    if len(atr_252) < 20 or atr_current <= 0:
        return 12, "数据不足", 0.5
    
    pct = (atr_252 < atr_current).mean()
    
    if pct < 0.2:
        score = 22 + int((0.2 - pct) / 0.2 * 3)
        label = f"低波动(P{pct:.0%})"
    elif pct < 0.5:
        score = 17 + int((0.5 - pct) / 0.3 * 5)
        label = f"中低波动(P{pct:.0%})"
    elif pct < 0.8:
        score = 12 + int((0.8 - pct) / 0.3 * 5)
        label = f"中高波动(P{pct:.0%})"
    else:

        score = max(0, 12 - int((pct - 0.8) / 0.2 * 8))
        label = f"高波动(P{pct:.0%})"
    
    return min(25, max(0, score)), label, pct


def _calc_volume_health_score(market_df: pd.DataFrame) -> tuple:
    """计算量价健康度（满分20分）"""
    if len(market_df) < 5:
        return 10, "数据不足"
    
    latest = market_df.iloc[-1]
    prev = market_df.iloc[-2]
    daily_return = (latest["avg_close"] - prev["avg_close"]) / prev["avg_close"] if prev["avg_close"] > 0 else 0
    
    db = sqlite3.connect(DB_PATH)
    try:
        snap = pd.read_sql("SELECT pct_change, volume, amount FROM market_snapshot", db)
        db.close()
        
        if not snap.empty:
            up_count = (snap["pct_change"] >= 0).sum()
            down_count = (snap["pct_change"] < 0).sum()
            total = len(snap)
            up_ratio = up_count / total if total > 0 else 0.5
            
            if up_ratio > 0.6 and daily_return > 0:
                score = 16 + int(min(4, (up_ratio - 0.6) / 0.4 * 4))
                label = f"量价齐升(U:{up_ratio:.0%})"
            elif up_ratio > 0.4 and daily_return > 0:
                score = 12 + int(min(4, (up_ratio - 0.4) / 0.2 * 4))
                label = f"价升量分歧(U:{up_ratio:.0%})"
            elif up_ratio > 0.6 and daily_return < 0:
                score = 10 + int(min(5, up_ratio * 5))
                label = f"价跌量涨(U:{up_ratio:.0%})"
            elif up_ratio < 0.3 and daily_return < 0:
                score = 0 + int(min(10, (0.3 - up_ratio) / 0.3 * 5))
                label = f"普跌缩量(U:{up_ratio:.0%})"
            else:
                score = 8 + int(daily_return * 100 * 2)
                label = f"中性(U:{up_ratio:.0%})"
        else:
            score = 10
            label = "数据不足"
    except Exception:
        score = 10
        label = "读快照失败"
        try: db.close()
        except: pass
    
    return min(20, max(0, score)), label


def _calc_sentiment_score(market_df: pd.DataFrame) -> tuple:
    """计算市场情绪（满分15分）"""
    if len(market_df) < 5:
        return 7, "数据不足"
    
    db = sqlite3.connect(DB_PATH)
    try:
        snap = pd.read_sql("SELECT pct_change, volume, amount FROM market_snapshot", db)
        db.close()
        
        if not snap.empty:
            up_count = (snap["pct_change"] >= 0).sum()
            down_count = (snap["pct_change"] < 0).sum()
            total = len(snap)
            
            adv_dec_ratio = up_count / max(down_count, 1)
            avg_pct = snap["pct_change"].mean()
            
            sentiment = adv_dec_ratio * abs(avg_pct) * 100
            
            if sentiment > 2.0:
                score = 12 + min(3, int(sentiment / 2))
                label = f"积极(A/D={adv_dec_ratio:.1f})"
            elif sentiment > 1.0:
                score = 9 + min(3, int((sentiment - 1) / 1 * 3))
                label = f"温和(A/D={adv_dec_ratio:.1f})"
            elif sentiment > 0.5:
                score = 6 + min(3, int(sentiment / 0.5 * 3))
                label = f"偏弱(A/D={adv_dec_ratio:.1f})"
            else:
                score = max(0, 6 - int((0.5 - sentiment) / 0.5 * 4))
                label = f"低迷(A/D={adv_dec_ratio:.1f})"
        else:
            score = 7
            label = "数据不足"
    except Exception:
        score = 7
        label = "读快照失败"
        try: db.close()
        except: pass
    
    return min(15, max(0, score)), label


def calculate_radar_score() -> dict:
    """
    计算行情雷达评分

    返回:
        {
            "score": 0-100,
            "strategy": "momentum" / "mean_reversion" / "cash",
            "strategy_cn": "动量趋势策略"/"均值回归策略"/"空仓观望",
            "dimensions": {...},
            "total": 87,
            "timestamp": "2026-06-29 10:00"
        }
    """
    from datetime import datetime
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    # ── 自动补齐市场快照（量价健康/情绪维度依赖） ──
    try:
        from src.data_fetcher import fetch_all_stocks_spot, get_db
        today = now.strftime("%Y-%m-%d")
        if not get_db().snapshot_exists(today):
            print("  ⟳ market_snapshot 为空，正在拉取全市场快照...")
            df = fetch_all_stocks_spot()
            print(f"  ✅ 全市场快照已写入 ({len(df)} 条)")
    except Exception:
        pass
    
    market_df = _load_market_series()
    if market_df.empty or len(market_df) < 60:
        return {
            "score": 50, "strategy": "mean_reversion",
            "strategy_cn": "均值回归策略",
            "dimensions": {}, "total": 50,
            "position_ratio": 0.3,
            "timestamp": now_str, "error": "数据不足, 默认均值回归"
        }
    
    market_df = market_df.tail(252).reset_index(drop=True)
    
    close = market_df["avg_close"]
    high = market_df["avg_high"]
    low = market_df["avg_low"]
    
    ma5 = close.rolling(5, min_periods=3).mean()
    ma20 = close.rolling(20, min_periods=10).mean()
    if len(close) >= 60:
        ma60 = close.rolling(60, min_periods=30).mean()
    else:

        ma60 = close.rolling(len(close)).mean()
    
    adx = _calc_adx(high, low, close, period=14)
    
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(20).mean()
    
    last_ma5 = ma5.iloc[-1]
    last_ma20 = ma20.iloc[-1]
    last_ma60 = ma60.iloc[-1]
    last_adx = adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 15
    last_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0
    atr_history = atr.dropna().values
    
    trend_score, trend_label = _calc_trend_score(last_ma5, last_ma20, last_ma60, last_adx)
    vol_score, vol_label, vol_pct = _calc_volatility_score(last_atr, atr_history)
    # ── GARCH波动率预测（补强波动率评分） ──
    garch_score = 0
    garch_label_extra = "GARCH无数据"
    try:
        _close = market_df["avg_close"]
        if len(_close) > 60:
            _r = _close.pct_change().dropna().values
            _g = GARCHVolatility()
            _g.fit(_r)
            garch_score, garch_label_extra = _g.score_volatility(_r)
            if garch_score > 0:
                vol_score = max(0, min(25, int(vol_score * 0.5 + garch_score * 0.5)))
    except Exception:
        pass
    vol_health_score, vol_health_label = _calc_volume_health_score(market_df)
    sent_score, sent_label = _calc_sentiment_score(market_df)

    # ── 新闻情绪微调（±5分，免费akshare接口） ──
    news_adj = 0
    news_label = "新闻: 无数据"
    try:
        from src.market_sentiment import fetch_news_sentiment
        ns = fetch_news_sentiment()
        if ns:
            news_score = ns.get("score", 50)
            news_label = "新闻: %s(%d多/%d空)" % (
                ns.get("label", "中立"),
                ns.get("bullish_count", 0),
                ns.get("bearish_count", 0),
            )
            news_adj = round((news_score - 50) / 10)
            sent_score = max(0, min(15, sent_score + news_adj))
    except Exception:
        pass
    
    # ── 布林带宽微调（±5分） ──
    bb_bonus, bb_label = _calc_bb_bandwidth_score(market_df)
    if bb_bonus > 0:
        trend_score = min(40, trend_score + bb_bonus)
    
    # ── HMM市场状态识别（补强趋势评分） ──
    hmm_score = 0
    try:
        _c = market_df["avg_close"]
        if len(_c) > 100:
            _rets = (_c.pct_change().dropna().values).reshape(-1, 1)
            _h = HMMRegimeDetector(n_states=3)
            hmm_score = _h.score_regime(_rets[-60:])
            trend_score = max(0, min(40, int(trend_score * 0.6 + hmm_score * 0.4)))
    except Exception:
        pass
    
    total = trend_score + vol_score + vol_health_score + sent_score
    
    if total >= 70:
        strategy = "momentum"
        strategy_cn = "动量趋势策略"
    elif total >= 40:
        strategy = "mean_reversion"
        strategy_cn = "均值回归策略"
    else:

        strategy = "cash"
        strategy_cn = "空仓观望"
    
    # 波动率仓位比例 (Deepseek公式: target = base × (10% / current_vol))
    position_ratio = max(0.25, min(1.0, round(1.0 - vol_pct * 0.75, 2)))
    if garch_score < 12 and garch_score > 0:
        position_ratio = max(0.15, position_ratio * 0.8)
    return {
        "score": total,
        "strategy": strategy,
        "strategy_cn": strategy_cn,
        "dimensions": {
            "trend": {"score": trend_score, "label": trend_label, "weight": 40, "max": 40},
            "volatility": {"score": vol_score, "label": vol_label, "weight": 25, "max": 25},
            "hmm_regime": {"score": hmm_score, "label": "HMM状态", "weight": 16, "max": 40},
            "garch_vol": {"score": garch_score, "label": garch_label_extra, "weight": 12, "max": 25},
            "volume_health": {"score": vol_health_score, "label": vol_health_label, "weight": 20, "max": 20},
            "sentiment": {"score": sent_score, "label": sent_label, "weight": 15, "max": 15},
            "bb_bandwidth": {"score": bb_bonus, "label": bb_label, "weight": 5, "max": 5},
        },
        "total": total,
        "position_ratio": position_ratio,
        "timestamp": now_str,
        "news_adjustment": news_adj,
        "news_label": news_label,
        "market_context": __get_market_context(),
    }


def get_strategy_label(score: int) -> str:
    if score >= 70:
        return "动量趋势策略"
    elif score >= 40:
        return "均值回归策略"
    else:

        return "空仓观望"


def __get_market_context() -> dict:
    """获取市场上下文（板块资金流向 + 热点概念），失败时返回空"""
    try:
        from src.market_sentiment import fetch_sector_fund_flow, fetch_hot_concepts
        return {k: v for k, v in {
            "sector_flow": fetch_sector_fund_flow(),
            "hot_concepts": fetch_hot_concepts(),
        }.items() if v.get("available")}
    except Exception:
        return {}
if __name__ == "__main__":
    result = calculate_radar_score()
    print("=== 行情雷达评分 ===")
    print(f"总分: {result['total']}/100")
    print(f"策略: {result.get('strategy_cn', '?')}")
    print(f"时间: {result['timestamp']}")
    for dim, v in result.get("dimensions", {}).items():
        print(f"  {dim}: {v['score']}/{v['max']} {v['label']}")
