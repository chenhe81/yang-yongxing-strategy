#!/usr/bin/env python3

"""
凤雏自主交易主程序 v2.5 — 交易日 09:35~14:55 每5分钟轮询 (含 BB 六句口诀集成)

行为：
  1. 每5分钟扫描持仓 + 股票池行情
  2. 止损/止盈 -> 硬逻辑判断，只在边界情况问刘秀
  3. 周期低位买入 -> 硬逻辑判断
  4. 每轮记录到 Dify
  5. 有操作时推飞书（凤雏→你）

凤雏 ↔ 刘秀协作：
  刘秀只负责"边界风控" — 正常止损止盈凤雏自己做。
  只有触及以下条件才问刘秀：
    - 浮亏在 -4% ~ -5% 之间（接近止损但没到，问刘秀要不要提前跑）
    - 浮盈在 +7% ~ +8% 之间（接近止盈但没到，问刘秀要不要锁定）
    - 刘秀离线或超时 -> 凤雏自行决定（按硬逻辑处理）
"""
import json
import math
import random
import numpy as np
import pandas as pd
import shutil
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error
import csv
import re
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
# ── 因子模块 ──
sys.path.insert(0, BASE)
try:
    from src.market_radar import calculate_radar_score
    from src.factors.bb_position_signal import generate_bb_signal, batch_bb_signal
    from src.factors.deepseek_multi_factor import calc_cross_sectional_scores, calc_composite_score
    from src.factors.quality_screen import check_quality
    from src.tools.fibonacci import calc_fibonacci_score
    from src.tools.factor_pca import FactorPCA
    from src.tools.portfolio_opt import half_kelly, allocate_by_kelly, kelly_criterion
    from src.data_fetcher import fetch_stock_history as _fetch_daily_data
    from src.stock_pool import load_stock_pool as _load_state_owned_pool
    IMPORT_OK = True
except Exception as e:
    IMPORT_OK = False
    print(f"  ⚠️ 因子模块加载失败: {e}")

LOG_DIR = os.path.join(BASE, "logs")
DATA_DIR = os.path.join(BASE, "data")
CONFIG_DIR = os.path.join(BASE, "config")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "trades"), exist_ok=True)

# ── 路径 ──
CYCLE_PROFILE_PATH = os.path.join(DATA_DIR, "cycle_profile.json")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "trades", "portfolio.json")
TRADE_LOG_PATH = os.path.join(DATA_DIR, "trades", "trade_log.csv")
COOLDOWN_PATH = os.path.join(DATA_DIR, "trades", "cooldown.json")
DEFENSIVE_POOL_PATH = os.path.join(DATA_DIR, "defensive_pool.json")
MOMENTUM_POOL_PATH = os.path.join(DATA_DIR, "momentum_pool.json")
CUSTOM_POOL_PATH = os.path.join(DATA_DIR, "custom_pool.json")
STOCK_SCORE_CACHE_PATH = os.path.join(DATA_DIR, "stock_score_cache.json")

# ── 交易参数 ──
INIT_CAPITAL = 100000
INIT_CAPITAL_FALLBACK = 100000  # portfolio.json 无 initial_capital 时的默认值
MAX_POSITIONS = 10
POSITION_PCT = 10
STOP_LOSS_PCT = -5.0
TAKE_PROFIT_PCT = 8.0
BUY_ZONE_PCT = 0.25
BUY_VOL_MIN = 0.5
HOLD_DAYS_MAX = 45
COOLDOWN_DAYS = 5
DEFAULT_FAST_CYCLE_DAYS = 7
MIN_TRADE_INTERVAL_DAYS = 3
EXCLUDED_CODES = {"600519"}  # 贵州茅台（高溢价，不适用量价逻辑）

# ── 新风控参数 ──
SINGLE_LOSS_PCT = -2.0     # 单笔亏损不超过2%（Deepseek风控）
DAILY_LOSS_PCT = -6.0      # 单日亏损不超过6%
COOLDOWN_SELL_DAYS = 3     # 止损后冷却天数
TRAILING_STOP_ACTIVATE = 8.0   # 浮盈超过8%启动移动止损
PRICE_PERCENTILE_HIGH = 0.80   # 3年价格分位>80%跳过（放宽，弱势市场避免零候选）

# ── 硬熔断（独立于模型的物理闸门） ──
HARD_STOP_SINGLE_PCT = -7.0       # 单只个股浮亏-7%强制平仓
HARD_STOP_DAILY_DRAWDOWN_PCT = -3.0  # 日内总回撤-3%强制全部平仓

# ── 动量回调参数 ──
MOMENTUM_STRENGTH_TOP_PCT = 0.20  # 动量强度前20%
MOMENTUM_PULLBACK_MIN = -1.5      # 当日回调下限（%）
MOMENTUM_PULLBACK_MAX = 0.5       # 当日回调上限（%）

# ── 首仓试探系数（放宽条件后用轻仓位试探） ──
HALF_KELLY_COEFF = 0.3           # 半凯利系数降到0.3，广撒网轻仓位

# ── 基本面质量筛选参数 ──
CHECK_QUALITY = True          # 启用/禁用基本面七指标质量筛选

# ── 刘秀边界区间（在这个区间内才问刘秀） ──
LIUXIU_LOSS_ZONE = (-5.0, -4.0)   # 浮亏 -4%~-5% 问刘秀
LIUXIU_PROFIT_ZONE = (7.0, 8.0)   # 浮盈 +7%~+8% 问刘秀

# ── 刘秀 API ──
LIUXIU_API = "http://10.26.0.5:11434/api/chat"
LIUXIU_MODEL = "qwen3:8b"
LIUXIU_TIMEOUT = 120

# ── 凤雏飞书配置 ──
FENGCHU_CONFIG_PATH = os.path.join(CONFIG_DIR, "feishu_fengchu.json")
FENGCHU_FEISHU_BASE = "https://open.feishu.cn/open-apis"
FENGCHU_TOKEN_CACHE = {"token": "", "expires_at": 0}
FENGCHU_CONFIG = {}
if os.path.exists(FENGCHU_CONFIG_PATH):
    try:
        FENGCHU_CONFIG = json.load(open(FENGCHU_CONFIG_PATH))
    except Exception:
        pass

# ── Dify ──
sys.path.insert(0, BASE)
try:
    from src.dify_storage import upload_monitor_scan, is_configured as dify_configured
except Exception:
    def upload_monitor_scan(*args, **kwargs): return False
    def dify_configured(): return False


# ═══════════════════════════════════════════════
#  数据
# ═══════════════════════════════════════════════

def load_portfolio() -> dict:
    try:
        if os.path.exists(PORTFOLIO_PATH):
            pf = json.load(open(PORTFOLIO_PATH))
            if "initial_capital" not in pf:
                inferred = pf.get("capital", 0) + pf.get("total_buy", 0) - pf.get("total_sell", 0)
                if inferred > 0 and inferred < 10000000:
                    pf["initial_capital"] = inferred
                else:
                    pf["initial_capital"] = INIT_CAPITAL_FALLBACK
            return pf
    except Exception:
        pass
    return {"positions": [], "capital": INIT_CAPITAL, "trades": [],
            "total_buy": 0, "total_sell": 0, "realized_pnl": 0,
            "initial_capital": INIT_CAPITAL_FALLBACK}


def save_portfolio(pf: dict):
    if "initial_capital" not in pf:
        pf["initial_capital"] = INIT_CAPITAL_FALLBACK
    pf["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    json.dump(pf, open(PORTFOLIO_PATH, "w"), indent=2, ensure_ascii=False)


def load_cycle_profile() -> dict:
    """加载周期分析池 + 自定义股票池（合并）"""
    result = {}
    try:
        result.update(json.load(open(CYCLE_PROFILE_PATH)))
    except Exception:
        pass
    try:
        result.update(json.load(open(CUSTOM_POOL_PATH)))
    except Exception:
        pass
    return result


def load_fast_pool() -> set:
    """加载 206只 4~10天短周期高胜率池，返回代码集合"""
    path = os.path.join(DATA_DIR, "fast_cycle_pool.json")
    try:
        data = json.load(open(path))
        if isinstance(data, dict):
            return set(data.keys())
        return {s["code"] for s in data if isinstance(s, dict)}
    except:
        return set()

def load_cooldown() -> dict:
    """加载冷却期数据"""
    try:
        if os.path.exists(COOLDOWN_PATH):
            return json.load(open(COOLDOWN_PATH))
    except Exception:
        pass
    return {}


def save_cooldown(cd: dict):
    json.dump(cd, open(COOLDOWN_PATH, "w"), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════
#  股票池加载
# ═══════════════════════════════════════════════

def load_defensive_pool() -> dict:
    """加载防御池（国资+低波动+高股息），返回 {code: name}"""
    global DEFENSIVE_POOL_CACHE
    if DEFENSIVE_POOL_CACHE:
        return DEFENSIVE_POOL_CACHE
    try:
        if os.path.exists(DEFENSIVE_POOL_PATH):
            data = json.load(open(DEFENSIVE_POOL_PATH))
            if isinstance(data, dict):
                DEFENSIVE_POOL_CACHE = data
                return data
            return {s["code"]: s["name"] for s in data if isinstance(s, dict)}
    except Exception:
        pass
    return {}


def load_momentum_pool() -> dict:
    """加载动量池（国资+趋势+放量），返回 {code: name}"""
    global MOMENTUM_POOL_CACHE
    if MOMENTUM_POOL_CACHE:
        return MOMENTUM_POOL_CACHE
    try:
        if os.path.exists(MOMENTUM_POOL_PATH):
            data = json.load(open(MOMENTUM_POOL_PATH))
            if isinstance(data, dict):
                MOMENTUM_POOL_CACHE = data
                return data
            return {s["code"]: s["name"] for s in data if isinstance(s, dict)}
    except Exception:
        pass
    return {}


# ═══════════════════════════════════════════════
#  AI评分
# ═══════════════════════════════════════════════

def fetch_stock_scores(codes: list) -> dict:
    """批量获取个股评分（从 Dify 增强评分 API / 本地缓存）
    
    返回: {code: {"score": float, "signal": str, "code": str, "name": str}}
    """
    if not codes:
        return {}
    # 优先本地缓存
    cache = {}
    if os.path.exists(STOCK_SCORE_CACHE_PATH):
        try:
            cache = json.load(open(STOCK_SCORE_CACHE_PATH))
        except Exception:
            pass
    
    today = datetime.now().strftime("%Y-%m-%d")
    result = {}
    uncached = []
    for c in codes:
        if c in cache and cache[c].get("date") == today:
            result[c] = cache[c]
        else:
            uncached.append(c)
    
    if uncached:
        try:
            # 尝试 Dify API
            import urllib.request, urllib.error
            api_url = "http://10.26.0.5:3004/api/stock/batch-score"
            payload = json.dumps({"codes": uncached}).encode("utf-8")
            req = urllib.request.Request(api_url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST")
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read())
            if isinstance(data, dict):
                scores = data.get("scores", {}) if "scores" in data else data
                for c in uncached:
                    if c in scores:
                        entry = scores[c]
                        if isinstance(entry, dict):
                            entry["date"] = today
                            cache[c] = entry
                            result[c] = entry
                        else:
                            result[c] = {"score": 50.0, "signal": "neutral", "code": c, "name": "", "date": today}
                    else:
                        result[c] = {"score": 50.0, "signal": "neutral", "code": c, "name": "", "date": today}
        except Exception as e:
            print(f"  ⚠️ stock_scores API: {e}")
            for c in uncached:
                result[c] = {"score": 50.0, "signal": "neutral", "code": c, "name": "", "date": today}
    
    # 写缓存
    try:
        json.dump(cache, open(STOCK_SCORE_CACHE_PATH, "w"), ensure_ascii=False)
    except Exception:
        pass
    
    return result


# ── 宏观状态（通过 SSH 读取算力中心 183.131.24.109 的宏观分析结果，每个交易日缓存一次） ──
_MACRO_CACHE = None
_MACRO_CACHE_DATE = None
_MACRO_TRIED_TODAY = False

def _fetch_macro_status() -> dict | None:
    """读取算力中心宏观分析结果，缓存一天"""
    global _MACRO_CACHE, _MACRO_CACHE_DATE, _MACRO_TRIED_TODAY
    today = datetime.now().strftime("%Y-%m-%d")
    if _MACRO_CACHE_DATE == today:
        if _MACRO_CACHE is not None:
            return _MACRO_CACHE
        if _MACRO_TRIED_TODAY:
            return None  # 今天已尝试过，不再浪费SSH
    else:
        _MACRO_TRIED_TODAY = False
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", "-p", "3100",
             "arcvideo@183.131.24.109",
             "cat /home/arcvideo/macro_analysis/output/latest.json"],
            capture_output=True, text=True, timeout=10
        )
        _MACRO_TRIED_TODAY = True
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        if data.get("date") != today:
            return None
        _MACRO_CACHE = data
        _MACRO_CACHE_DATE = today
        return data
    except Exception as e:
        _MACRO_TRIED_TODAY = True
        print(f"  ⚠️ 读取宏观数据失败: {e}", flush=True)
        return None
def fetch_enhanced_score() -> dict:
    """获取增强评分（含热点板块、行业趋势等）
    
    返回: {
        "score": float,           # 综合评分
        "strategy": str,          # momentum/mean_reversion/cash
        "top_sectors": [str],     # 热点板块列表
        "market_regime": str,     # 市场状态
        "score_details": {...}
    }
    """
    default = {"score": 50, "strategy": "mean_reversion", "top_sectors": [],
               "market_regime": "unknown", "score_details": {}}
    try:
        # 优先用本地雷达评分
        radar = calculate_radar_score()
        if radar and "score" in radar:
            result = {
                "score": radar.get("score", 50),
                "strategy": radar.get("strategy", "mean_reversion"),
                "strategy_cn": radar.get("strategy_cn", ""),
                "top_sectors": [],
                "market_regime": radar.get("strategy_cn", "unknown"),
                "score_details": radar.get("dimensions", {}),
                "position_ratio": radar.get("position_ratio", 1.0),
            }

            # 宏观状态融合（算力中心 qwen3-coder:30b 分析，权重20%）
            try:
                macro_data = _fetch_macro_status()
                if macro_data:
                    analysis = macro_data.get("analysis", {})
                    ms = analysis.get("market_state", "neutral")
                    rl = analysis.get("risk_level", 5)
                    pr = analysis.get("position_ratio", 0.5)

                    state_adj = {"bullish": 6, "neutral": 0, "bearish": -4, "extreme_bearish": -10}
                    macro_adj = state_adj.get(ms, 0) + (5 - int(rl))

                    result["score"] = max(0, min(100, result["score"] + macro_adj))
                    result["macro_adjustment"] = macro_adj
                    result["macro_state"] = ms
                    result["macro_risk"] = int(rl)
                    result["position_ratio"] = min(result.get("position_ratio", 1.0), float(pr))

                    if ms == "extreme_bearish" and int(rl) >= 8:
                        result["strategy"] = "cash"
                        result["strategy_cn"] = "空仓观望"
                        result["position_ratio"] = 0.0

                    if "score_details" in result and isinstance(result["score_details"], dict):
                        result["score_details"]["macro"] = {"adj": macro_adj, "state": ms, "risk": int(rl)}

                    print(f"    宏观状态: {ms}(风险{rl}) 调整={macro_adj:+d}", flush=True)
            except Exception as macro_e:
                print(f"    \u26a0\ufe0f 宏观融合失败: {macro_e}", flush=True)

            return result
    except Exception as e:
        print(f"  ⚠️ 增强评分失败: {e}")
    return default


def fetch_yin_xian_scores(codes: list) -> dict:
    """阴线战法评分（10日线阴线法）
    
    返回: {code: {"score": 0-100, "signal": "buy"/"hold"/"pass", "detail": str}}
    """
    result = {}
    for code in codes:
        try:
            df = fetch_daily_data(code, days=30)
            if df.empty or len(df) < 15:
                result[code] = {"score": 0, "signal": "pass", "detail": "数据不足"}
                continue
            close = df["close"].values
            if len(close) < 10:
                result[code] = {"score": 0, "signal": "pass", "detail": "数据不足"}
                continue
            # 简单阴线检测：连续下跌后第10日出现阴线
            cur = close[-1]
            ma10 = np.mean(close[-10:])
            prev = close[-2] if len(close) >= 2 else cur
            is_yin = cur < prev
            price_pctile = calc_price_percentile(code, cur, 250)
            if is_yin and price_pctile < 0.4 and cur < ma10:
                result[code] = {"score": 65, "signal": "buy", "detail": f"阴线低位 ma10={ma10:.2f} pctile={price_pctile:.2f}"}
            elif is_yin and price_pctile < 0.5:
                result[code] = {"score": 45, "signal": "hold", "detail": f"阴线观察 ma10={ma10:.2f}"}
            else:
                result[code] = {"score": 20, "signal": "pass", "detail": "阴线条件不满足"}
        except Exception as e:
            result[code] = {"score": 0, "signal": "pass", "detail": str(e)}
    return result


def score_momentum_stocks(codes: list, prices: dict) -> dict:
    """使用 DeepSeek 多因子模型评分候选股
    
    返回: {code: {"score": float, "name": str, "ds_score": float, 
                  "bb_signal": str, "detail": str}}
    """
    result = {}
    for code in codes:
        try:
            df = fetch_daily_data(code, days=60)
            if df.empty or len(df) < 25:
                result[code] = {"score": 0.0, "name": prices.get(code, {}).get("name", ""),
                                "ds_score": 0.0, "bb_signal": "hold", "detail": "数据不足"}
                continue
            
            # DeepSeek 多因子评分
            close = df["close"] if isinstance(df["close"], pd.Series) else pd.Series(df["close"].values)
            volume = df["volume"] if isinstance(df["volume"], pd.Series) else pd.Series(df["volume"].values)
            
            from src.factors.deepseek_multi_factor import calc_composite_score
            ds_score = calc_composite_score(close, volume)
            
            # BB 信号
            bb = generate_bb_signal(close, prices.get(code, {}).get("price"))
            bb_action = bb.get("action", "hold")
            
            # 斐波那契评分
            fib = calc_fibonacci_score(close.values)
            fib_score = fib.get("score", 50)
            
            # 综合评分 (DS + Fib + 价格分位修正)
            price_pctile = calc_price_percentile(code, close.iloc[-1], 250)
            composite = ds_score * 30 + fib_score * 0.3
            if price_pctile < 0.3:
                composite += 10  # 低位加分
            elif price_pctile > 0.6:
                composite -= 10  # 高位减分
            
            result[code] = {
                "score": round(composite, 1),
                "name": prices.get(code, {}).get("name", ""),
                "ds_score": round(ds_score, 3),
                "bb_signal": bb_action,
                "fib_score": fib_score,
                "price_pctile": round(price_pctile, 3),
                "detail": f"DS={ds_score:.3f} Fib={fib_score:.1f} 分位={price_pctile:.2f}",
            }
        except Exception as e:
            result[code] = {"score": 0.0, "name": "", "ds_score": 0.0,
                            "bb_signal": "hold", "detail": str(e)}
    return result


# ═══════════════════════════════════════════════
#  风控
# ═══════════════════════════════════════════════

def check_daily_loss_limit(pf: dict) -> bool:
    """检查是否触发单日6%亏损限制
    
    返回: True=触发限制，应该停止交易
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if pf.get("daily_loss_date") != today:
        pf["daily_loss"] = 0
        pf["daily_loss_date"] = today
        return False
    
    daily_loss_pct = pf.get("daily_loss", 0) / max(pf.get("initial_capital", 1), 1) * 100
    return daily_loss_pct <= DAILY_LOSS_PCT


# ═══════════════════════════════════════════════
#  行情
# ═══════════════════════════════════════════════

def fetch_prices(codes: list) -> dict:
    if not codes:
        return {}
    symbols = []
    for c in codes:
        p = "sh" if c.startswith(("6", "9")) else "sz"
        symbols.append(f"{p}{c}")
    results = {}
    for i in range(0, len(symbols), 80):
        batch = symbols[i:i + 80]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode("gbk")
            for line in raw.split(";"):
                line = line.strip()
                if "=" not in line or "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 40:
                    continue
                sym = parts[0].split("=")[0].strip().removeprefix("v_")
                code = sym.replace("sh", "").replace("sz", "")
                results[code] = {
                    "name": parts[1],
                    "price": float(parts[3] or 0),
                    "pre_close": float(parts[4] or 0),
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "volume": float(parts[6] or 0),
                    "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                    "turnover": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                    "pct_change": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                }
        except Exception as e:
            print(f"  ⚠️ 行情: {e}")
    return results


# ═══════════════════════════════════════════════
#  日线数据
# ═══════════════════════════════════════════════

def fetch_daily_data(code: str, days: int = 120) -> pd.DataFrame:
    """获取个股日线数据，返回包含 close/open/high/low/volume 的 DataFrame"""
    try:
        df = _fetch_daily_data(code, days=days, use_cache=True)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"  ⚠️ {code} 日线获取失败: {e}")
    return pd.DataFrame()


def calc_price_percentile(code: str, cur_price: float = None, lookback: int = 750) -> float:
    """计算当前价格在近N个交易日内的分位值 (0~1)"""
    df = fetch_daily_data(code, days=lookback + 30)
    if df.empty or len(df) < 60:
        return 0.5
    highs = df["high"].max()
    lows = df["low"].min()
    if cur_price is None:
        cur_price = df["close"].iloc[-1]
    if highs == lows:
        return 0.5
    return (cur_price - lows) / (highs - lows)


# ═══════════════════════════════════════════════
#  刘秀风控（仅边界情况调用）
# ═══════════════════════════════════════════════

def consult_liuxiu_async(action_type: str, detail: str) -> dict:
    """问刘秀是否操作。刘秀离线或超时 -> 凤雏自行决定（返回默认批准）"""
    prompt = (
        f"你是刘秀，凤雏的风控审核官。时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"操作：{action_type}\n"
        f"详情：{detail}\n\n"
        f"请判断是否批准。规则：\n"
        f"1. 接近止损线(浮亏-4%~-5%) -> 如果趋势可能继续跌则批准卖出\n"
        f"2. 接近止盈线(浮盈+7%~+8%) -> 如果趋势可能回调则批准卖出\n"
        f"3. 其他 -> 谨慎判断\n"
        f"只返回JSON：{{\"approve\": true/false, \"reason\": \"一句话理由\"}}"
    )
    try:
        payload = json.dumps({
            "model": LIUXIU_MODEL, "keep_alive": -1,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False, "options": {"temperature": 0.1}
        })
        result = subprocess.run(
            ["curl", "-s", "--max-time", "120",
             "-X", "POST", "-H", "Content-Type: application/json",
             "-d", payload, LIUXIU_API],
            capture_output=True, timeout=130, text=True
        )
        if result.returncode != 0:
            raise Exception(f"curl {result.returncode}")
        data = json.loads(result.stdout)
        content = data.get("message", {}).get("content", "")
        m = re.search(r'\{[^}]+\}', content)
        if m:
            return json.loads(m.group())
        return {"approve": True, "reason": "解析失败，凤雏自行决定"}
    except Exception as e:
        print(f"  ⚠️ 刘秀: {e}")
        return {"approve": True, "reason": "刘秀离线，凤雏自行决定"}


# ═══════════════════════════════════════════════
#  飞书
# ═══════════════════════════════════════════════

def fengchu_get_token() -> str:
    now = time.time()
    if FENGCHU_TOKEN_CACHE["token"] and now < FENGCHU_TOKEN_CACHE["expires_at"] - 60:
        return FENGCHU_TOKEN_CACHE["token"]
    app_id = FENGCHU_CONFIG.get("app_id", "")
    app_secret = FENGCHU_CONFIG.get("app_secret", "")
    if not app_id or not app_secret:
        return None
    url = f"{FENGCHU_FEISHU_BASE}/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        token = data.get("tenant_access_token", "")
        FENGCHU_TOKEN_CACHE["token"] = token
        FENGCHU_TOKEN_CACHE["expires_at"] = now + data.get("expire", 7200)
        return token
    except Exception:
        return None


def push_to_feishu(message_body: str):
    token = fengchu_get_token()
    receive_id = FENGCHU_CONFIG.get("union_id", "") or FENGCHU_CONFIG.get("user_id", "")
    id_type = "union_id" if FENGCHU_CONFIG.get("union_id", "") else "open_id"
    if token and receive_id:
        url = f"{FENGCHU_FEISHU_BASE}/im/v1/messages?receive_id_type={id_type}"
        payload = json.dumps({
            "receive_id": receive_id, "msg_type": "text",
            "content": json.dumps({"text": message_body})
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"
        })
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            if json.loads(resp.read()).get("code") == 0:
                print("  ✅ 已推送飞书（凤雏）")
                return
        except:
            pass
    print("  ⚠️ 飞书不可用")


# ═══════════════════════════════════════════════
#  交易记录
# ═══════════════════════════════════════════════

def log_trade(date: str, code: str, name: str, action: str, price: float,
              shares: int, pnl: float = 0, pnl_pct: float = 0, reason: str = ""):
    file_exists = os.path.exists(TRADE_LOG_PATH)
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    with open(TRADE_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["日期", "时间", "代码", "名称", "操作", "价格", "股数", "盈亏", "盈亏%", "原因"])
        w.writerow([date, datetime.now().strftime("%H:%M"), code, name, action,
                    f"{price:.2f}", shares, f"{pnl:.2f}", f"{pnl_pct:.2f}%", reason])


# ═══════════════════════════════════════════════
#  卖出
# ═══════════════════════════════════════════════

def check_sells(pf: dict, prices: dict, now: datetime, today: str,
                 strategy: str = "mean_reversion",
                 bb_signals: dict = None) -> list:
    """增强版卖出检查 — 集成 BB 信号、防御池辅助、移动止损、收盘价止损、连续止损冷却"""
    trades_done = []
    cd = load_cooldown()
    need_liuxiu = False
    liuxiu_detail = ""
    pending_liuxiu = []
    # 连续止损检测
    consecutive_stops = cd.get("_consecutive_stops", [])
    recent_stops = [s for s in consecutive_stops 
                    if (now - datetime.strptime(s, "%Y-%m-%d")).days <= COOLDOWN_SELL_DAYS]
    if len(recent_stops) >= 3:
        print(f"  ⚠️ 连续止损{len(recent_stops)}次，暂停卖出（冷却{COOLDOWN_SELL_DAYS}天）", flush=True)
        # 只执行强制卖出（BB strong_sell）
        for pos in list(pf["positions"]):
            code = pos["code"]
            if bb_signals and code in bb_signals:
                bs = bb_signals[code]
                if bs.get("action") == "strong_sell":
                    mp = prices.get(code)
                    if not mp: continue
                    cur_price = mp["price"]
                    shares = pos["shares"]
                    amount = shares * cur_price
                    pnl = (cur_price - pos["buy_price"]) * shares
                    pnl_pct = (cur_price - pos["buy_price"]) / pos["buy_price"] * 100
                    pf["capital"] += amount
                    pf["total_sell"] += amount
                    pf["realized_pnl"] += pnl
                    pf["positions"].remove(pos)
                    log_trade(today, code, pos["name"], "卖出(BB强卖)", cur_price, shares, pnl, pnl_pct,
                              f"BB开口向下 {bs.get('signal','')}")
                    trades_done.append({"code": code, "name": pos["name"], "action": "卖出(BB强卖)",
                                        "price": cur_price, "shares": shares, "pnl": round(pnl,2),
                                        "pnl_pct": round(pnl_pct,2), "reason": "BB strong_sell 强制卖出"})
                    print(f"  🚨 BB强卖 {pos['name']}({code}) @ {cur_price:.2f} {pnl_pct:+.1f}%", flush=True)
        return trades_done

    for pos in list(pf["positions"]):
        code = pos["code"]
        mp = prices.get(code)
        if not mp:
            continue

        cur_price = mp["price"]
        buy_price = pos["buy_price"]
        pnl_pct = (cur_price - buy_price) / buy_price * 100
        hold_days = (now - datetime.strptime(pos["buy_date"], "%Y-%m-%d")).days if "buy_date" in pos else 0
        need_sell = False
        reason = ""
        need_liuxiu_check = False

        # 0. BB 信号 — strong_sell 强制卖出（最高优先级）
        if bb_signals and code in bb_signals:
            bs = bb_signals[code]
            if bs.get("action") == "strong_sell":
                need_sell = True
                reason = f"BB开口向下 {bs.get('signal','')}"

        # 1. 收盘价止损（硬逻辑）
        if not need_sell and pnl_pct <= STOP_LOSS_PCT:
            need_sell = True
            reason = f"止损 {pnl_pct:.1f}%"

        # 2. 止盈（硬逻辑）
        elif not need_sell and pnl_pct >= TAKE_PROFIT_PCT:
            need_sell = True
            reason = f"止盈 +{pnl_pct:.1f}%"

        # 3. 边界区间 -> 问刘秀
        elif LIUXIU_LOSS_ZONE[0] <= pnl_pct <= LIUXIU_LOSS_ZONE[1]:
            need_liuxiu_check = True
            liuxiu_detail = (f"接近止损 {pos['name']}({code}) 浮亏{pnl_pct:.1f}%, "
                             f"买入{buy_price:.2f}→当前{cur_price:.2f}, 持仓{hold_days}天")
            pending_liuxiu.append({"pos": pos, "cur_price": cur_price, "buy_price": buy_price, "pnl_pct": pnl_pct, "pnl": (cur_price - buy_price) * pos["shares"], "reason_label": "刘秀批准止损"})
        elif LIUXIU_PROFIT_ZONE[0] <= pnl_pct <= LIUXIU_PROFIT_ZONE[1]:
            need_liuxiu_check = True
            liuxiu_detail = (f"接近止盈 {pos['name']}({code}) 浮盈{pnl_pct:.1f}%, "
                             f"买入{buy_price:.2f}→当前{cur_price:.2f}, 持仓{hold_days}天")
            pending_liuxiu.append({"pos": pos, "cur_price": cur_price, "buy_price": buy_price, "pnl_pct": pnl_pct, "pnl": (cur_price - buy_price) * pos["shares"], "reason_label": "刘秀批准止盈"})

        # 4. 移动止损（浮盈超过 TRAILING_STOP_ACTIVATE% 后上移至成本价）
        elif pnl_pct >= TRAILING_STOP_ACTIVATE:
            trail_stop = pos.get("trailing_stop", 0)
            if trail_stop == 0:
                pos["trailing_stop"] = buy_price  # 上移至成本价
                print(f"  🔼 移动止损激活 {pos['name']}({code}) 保本位={buy_price:.2f}", flush=True)
            elif cur_price <= trail_stop:
                need_sell = True
                reason = f"移动止损触发 (保本)"

        # 5. 时间止损
        elif hold_days >= HOLD_DAYS_MAX:
            need_sell = True
            reason = f"时间止损 (持仓{hold_days}天)"

        if need_liuxiu_check:
            need_liuxiu = True
            continue

        if not need_sell:
            continue

        # 执行卖出
        shares = pos["shares"]
        amount = shares * cur_price
        pnl = (cur_price - buy_price) * shares
        # 更新日亏损
        if pnl < 0:
            pf["daily_loss"] = pf.get("daily_loss", 0) + abs(pnl)
        pf["capital"] += amount
        pf["total_sell"] += amount
        pf["realized_pnl"] += pnl
        pf["positions"].remove(pos)
        pf["total_trades"] = pf.get("total_trades", 0) + 1
        
        # 冷却期记录
        cd[code] = today
        if pnl < 0:
            consecutive_stops.append(today)
            cd["_consecutive_stops"] = consecutive_stops[-10:]  # 只保留最近10次
        save_cooldown(cd)
        
        log_trade(today, code, pos["name"], "卖出", cur_price, shares, pnl, pnl_pct, reason)
        trades_done.append({"code": code, "name": pos["name"], "action": "卖出",
                            "price": cur_price, "shares": shares, "pnl": round(pnl, 2),
                            "pnl_pct": round(pnl_pct, 2), "reason": reason})
        print(f"  🔴 卖出 {pos['name']}({code}) ×{shares} @ {cur_price:.2f} {pnl_pct:+.1f}% {reason}", flush=True)

    # 边界情况问刘秀（一次请求，批量判断）
    if need_liuxiu and liuxiu_detail:
        print(f"  🤔 边界情况，咨询刘秀...", flush=True)
        liuxiu = consult_liuxiu_async("sell_boundary", liuxiu_detail)
        print(f"  📢 刘秀: {liuxiu.get('reason', '')} {'✅执行' if liuxiu.get('approve') else '⏸️跳过'}", flush=True)
        if liuxiu.get('approve'):
            for item in list(pending_liuxiu):
                p = item["pos"]
                if p not in pf["positions"]: continue
                code = p["code"]; shares = p["shares"]
                cur_price = item["cur_price"]; pnl_pct = item["pnl_pct"]
                pnl = item["pnl"]; amount = shares * cur_price
                if pnl < 0:
                    pf["daily_loss"] = pf.get("daily_loss", 0) + abs(pnl)
                pf["capital"] += amount; pf["total_sell"] += amount
                pf["realized_pnl"] += pnl; pf["positions"].remove(p)
                pf["total_trades"] = pf.get("total_trades", 0) + 1
                cd[code] = today; save_cooldown(cd)
                log_trade(today, code, p["name"], "卖出", cur_price, shares, pnl, pnl_pct, item["reason_label"])
                trades_done.append({"code": code, "name": p["name"], "action": "卖出", "price": cur_price, "shares": shares, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2), "reason": item["reason_label"]})
                print(f"  🔴 卖出 {p['name']}({code}) x{shares} @ {cur_price:.2f} {pnl_pct:+.1f}% {item['reason_label']}", flush=True)

    save_portfolio(pf)
    return trades_done



def _check_hard_stops(pf: dict, prices: dict, now: datetime, today: str) -> list:
    """硬熔断（物理闸门，独立于模型）

    1. 单只浮亏 <= HARD_STOP_SINGLE_PCT -> 强制平仓
    2. 总回撤 <= HARD_STOP_DAILY_DRAWDOWN_PCT -> 强制全部平仓

    返回: 已强制卖出的列表
    """
    forced_sells = []
    initial_capital = pf.get("initial_capital", INIT_CAPITAL_FALLBACK)

    # 1. 单只硬止损
    for pos in list(pf["positions"]):
        code = pos["code"]
        mp = prices.get(code)
        if not mp:
            continue
        cur_price = mp["price"]
        pnl_pct = (cur_price - pos["buy_price"]) / pos["buy_price"] * 100
        if pnl_pct <= HARD_STOP_SINGLE_PCT:
            shares = pos["shares"]
            amount = shares * cur_price
            pnl = (cur_price - pos["buy_price"]) * shares
            pf["capital"] += amount
            pf["total_sell"] += amount
            pf["realized_pnl"] += pnl
            pf["positions"].remove(pos)
            pf["total_trades"] = pf.get("total_trades", 0) + 1
            log_trade(today, code, pos["name"], "卖出(硬熔断)", cur_price, shares, pnl, pnl_pct,
                      f"硬止损 {pnl_pct:.1f}% <= {HARD_STOP_SINGLE_PCT}%")
            forced_sells.append({"code": code, "name": pos["name"], "action": "卖出(硬熔断)",
                                "price": cur_price, "shares": shares, "pnl": round(pnl, 2),
                                "pnl_pct": round(pnl_pct, 2),
                                "reason": f"硬止损 {pnl_pct:.1f}% <= {HARD_STOP_SINGLE_PCT}%"})
            print(f"  \U0001f6a8 硬熔断 {pos['name']}({code}) x{shares} @ {cur_price:.2f} {pnl_pct:+.1f}%", flush=True)

    # 2. 总回撤硬熔断（检查全部平仓）
    total_pos_value = sum(
        prices.get(p["code"], {}).get("price", p["buy_price"]) * p["shares"]
        for p in pf["positions"]
    )
    total_assets = pf["capital"] + total_pos_value
    drawdown_pct = (total_assets - initial_capital) / initial_capital * 100

    if drawdown_pct <= HARD_STOP_DAILY_DRAWDOWN_PCT and pf["positions"]:
        print(f"  \U0001f6a8 总回撤硬熔断触发: {drawdown_pct:.2f}% <= {HARD_STOP_DAILY_DRAWDOWN_PCT}%，强制全部平仓", flush=True)
        for pos in list(pf["positions"]):
            code = pos["code"]
            mp = prices.get(code, {})
            cur_price = mp.get("price", pos["buy_price"]) if mp else pos["buy_price"]
            shares = pos["shares"]
            amount = shares * cur_price
            pnl = (cur_price - pos["buy_price"]) * shares
            pnl_pct = (cur_price - pos["buy_price"]) / pos["buy_price"] * 100
            pf["capital"] += amount
            pf["total_sell"] += amount
            pf["realized_pnl"] += pnl
            pf["positions"].remove(pos)
            pf["total_trades"] = pf.get("total_trades", 0) + 1
            log_trade(today, code, pos["name"], "卖出(总回撤熔断)", cur_price, shares, pnl, pnl_pct,
                      f"总回撤 {drawdown_pct:.2f}% 强制平仓")
            forced_sells.append({"code": code, "name": pos["name"], "action": "卖出(总回撤熔断)",
                                "price": cur_price, "shares": shares, "pnl": round(pnl, 2),
                                "pnl_pct": round(pnl_pct, 2),
                                "reason": f"总回撤 {drawdown_pct:.2f}% 强制平仓"})
            print(f"  \U0001f6a8 熔断平仓 {pos['name']}({code}) x{shares} @ {cur_price:.2f} {pnl_pct:+.1f}%", flush=True)

    if forced_sells:
        save_portfolio(pf)

    return forced_sells


# ═══════════════════════════════════════════════
#  策略买入（三策略分发）
# ═══════════════════════════════════════════════

def _check_buys_mean_reversion(pf: dict, prices: dict, now: datetime, today: str,
                                hot_codes: set = None, bb_signals: dict = None,
                                profile: dict = None, radar_score: float = 50) -> list:
    """均值回归策略买入 — 基于周期低位 + 价格分位 + BB信号"""
    if profile is None:
        profile = load_cycle_profile()
    if not profile:
        return []
    
    # 动态 zone 阈值（根据雷达分数调整）
    if radar_score >= 80:
        zone_threshold = 0.20
    elif radar_score >= 60:
        zone_threshold = 0.25
    elif radar_score >= 40:
        zone_threshold = 0.35
    else:
        zone_threshold = 0.45
    if zone_threshold != BUY_ZONE_PCT:
        print(f"   动态阈值: radar={radar_score} zone<={zone_threshold}", flush=True)
    
    cd = load_cooldown()
    existing_codes = {p["code"] for p in pf["positions"]}
    trades_done = []
    
    # 候选筛选
    candidates = []
    for code, p in profile.items():
        if code in existing_codes or code in cd:
            continue
        if code in EXCLUDED_CODES:
            continue
        if cd.get(code) and (now - datetime.strptime(cd[code], "%Y-%m-%d")).days < COOLDOWN_DAYS:
            continue
        if p.get("zone_pct", 1) > zone_threshold:
            continue
        vol = p.get("vol_ratio", 1)
        if vol < BUY_VOL_MIN:
            continue
        
        # 价格分位过滤器（3年价格分位 > 40% 跳过）
        cur_price = prices.get(code, {}).get("price", 0)
        if cur_price > 0:
            price_pctile = calc_price_percentile(code, cur_price, 750)
            if price_pctile > PRICE_PERCENTILE_HIGH:
                continue
        
        # BB 信号门：wait/strong_sell 跳过
        bb_action = "hold"
        if bb_signals and code in bb_signals:
            bb_action = bb_signals[code].get("action", "hold")
            if bb_action in ("wait", "strong_sell"):
                continue
        
        candidates.append((code, p, bb_action))
    
    if not candidates:
        return []
    
    candidates.sort(key=lambda x: x[1]["zone_pct"])
    candidates = candidates[:MAX_POSITIONS * 2]
    
    for code, p, bb_action in candidates:
        if len(pf["positions"]) + len(trades_done) >= MAX_POSITIONS:
            break
        
        mp = prices.get(code)
        if not mp:
            continue
        cur_price = mp["price"]
        
        # 不追高
        if mp.get("pct_change", 0) > 3:
            continue
        
        # 热点加分
        score_bonus = 0
        if hot_codes and code in hot_codes:
            score_bonus = 10
        
        # BB 信号加分
        if bb_action == "strong_buy":
            score_bonus += 15
        elif bb_action == "buy":
            score_bonus += 5
        
        # 计算买入量（首仓试探：放宽状态下用半凯利降低仓位）
        kelly_coeff = HALF_KELLY_COEFF if zone_threshold > BUY_ZONE_PCT else 1.0
        per_position = pf["capital"] * POSITION_PCT / 100 * kelly_coeff
        shares = int(per_position / cur_price / 100) * 100
        if shares < 100:
            shares = 100
        cost = shares * cur_price
        if cost > pf["capital"]:
            shares = int(pf["capital"] / cur_price / 100) * 100
            if shares < 100:
                continue
            cost = shares * cur_price

        # 基本面质量筛选
        if CHECK_QUALITY and IMPORT_OK:
            mkt_ = "SH" if code.startswith("6") else "SZ"
            qc = check_quality(code, p["name"], mkt_)
            if not qc["pass"]:
                print(f"  ⛔ 质量筛除 {p['name']}({code}): {','.join(qc['fails'])}", flush=True)
                continue
        
        pf["capital"] -= cost
        pf["total_buy"] += cost
        pos = {
            "code": code, "name": p["name"],
            "buy_price": cur_price, "shares": shares,
            "buy_date": today, "strategy": "mean_reversion",
            "target_pct": [int(TAKE_PROFIT_PCT * 0.6), int(TAKE_PROFIT_PCT)],
            "zone_at_buy": p["zone_label"],
            "trailing_stop": 0,
        }
        pf["positions"].append(pos)
        pf["total_trades"] = pf.get("total_trades", 0) + 1
        log_trade(today, code, p["name"], "买入", cur_price, shares, 0, 0,
                  f"均值回归 {p['zone_label']} zone={p['zone_pct']:.1%}")
        trades_done.append({"code": code, "name": p["name"], "action": "买入",
                            "price": cur_price, "shares": shares, "strategy": "mean_reversion",
                            "reason": f"均值回归低位 zone={p['zone_pct']:.1%} bonus={score_bonus}"})
        print(f"  🟢 均值回归买入 {p['name']}({code}) ×{shares} @ {cur_price:.2f} "
              f"zone={p['zone_pct']:.1%} bonus={score_bonus}", flush=True)
    
    return trades_done


def _check_buys_momentum(pf: dict, prices: dict, now: datetime, today: str,
                          hot_codes: set = None, bb_signals: dict = None,
                          profile: dict = None) -> list:
    """动量趋势策略买入 — 基于 DeepSeek 多因子评分 + BB 信号确认"""
    if profile is None:
        profile = load_cycle_profile()
    if not profile:
        return []
    

    cd = load_cooldown()
    existing_codes = {p["code"] for p in pf["positions"]}
    trades_done = []
    
    # 筛选候选
    candidates = []
    for code, p in profile.items():
        if code in existing_codes or code in EXCLUDED_CODES:
            continue
        if cd.get(code) and (now - datetime.strptime(cd[code], "%Y-%m-%d")).days < COOLDOWN_DAYS:
            continue
        # 动量策略只选涨幅适中的
        mp = prices.get(code)
        if not mp:
            continue
        pct_day = mp.get("pct_change", 0)
        if pct_day <= 0:
            continue  # 动量策略要求当日涨幅>0
        candidates.append((code, p))
    
    if not candidates:
        return []
    
    # 多因子评分
    candidate_codes = [c[0] for c in candidates]
    scores = score_momentum_stocks(candidate_codes, prices)
    
    scored = []
    for code, p in candidates:
        if code not in scores:
            continue
        s = scores[code]
        # BB 信号门
        bb_action = s.get("bb_signal", "hold")
        if bb_signals and code in bb_signals:
            bb_action = bb_signals[code].get("action", "hold")
        if bb_action in ("wait", "strong_sell"):
            continue
        
        # 热点加分
        bonus = 0
        if hot_codes and code in hot_codes:
            bonus = 10
        if bb_action == "strong_buy":
            bonus += 15
        
        scored.append((code, p, s["score"] + bonus, bonus, bb_action))
    
    if not scored:
        return []
    
    scored.sort(key=lambda x: x[2], reverse=True)
    scored = scored[:MAX_POSITIONS]
    
    for code, p, total_score, bonus, bb_action in scored:
        if len(pf["positions"]) + len(trades_done) >= MAX_POSITIONS:
            break
        
        mp = prices.get(code)
        if not mp:
            continue
        cur_price = mp["price"]
        
        per_position = pf["capital"] * POSITION_PCT / 100
        shares = int(per_position / cur_price / 100) * 100
        if shares < 100:
            shares = 100
        cost = shares * cur_price
        if cost > pf["capital"]:
            shares = int(pf["capital"] / cur_price / 100) * 100
            if shares < 100:
                continue
            cost = shares * cur_price

        # 基本面质量筛选
        if CHECK_QUALITY and IMPORT_OK:
            mkt_ = "SH" if code.startswith("6") else "SZ"
            qc = check_quality(code, p["name"], mkt_)
            if not qc["pass"]:
                print(f"  ⛔ 质量筛除 {p['name']}({code}): {','.join(qc['fails'])}", flush=True)
                continue
        
        pf["capital"] -= cost
        pf["total_buy"] += cost
        pos = {
            "code": code, "name": p["name"],
            "buy_price": cur_price, "shares": shares,
            "buy_date": today, "strategy": "momentum",
            "target_pct": [int(TAKE_PROFIT_PCT * 0.6), int(TAKE_PROFIT_PCT)],
            "zone_at_buy": p["zone_label"],
            "trailing_stop": 0,
        }
        pf["positions"].append(pos)
        pf["total_trades"] = pf.get("total_trades", 0) + 1
        log_trade(today, code, p["name"], "买入", cur_price, shares, 0, 0,
                  f"动量趋势 score={total_score:.1f} bonus={bonus}")
        trades_done.append({"code": code, "name": p["name"], "action": "买入",
                            "price": cur_price, "shares": shares, "strategy": "momentum",
                            "reason": f"动量趋势 score={total_score:.1f} bonus={bonus}"})
        print(f"  🟢 动量买入 {p['name']}({code}) ×{shares} @ {cur_price:.2f} "
              f"score={total_score:.1f} bonus={bonus}", flush=True)
    
    return trades_done



def _check_buys_momentum_callback(pf: dict, prices: dict, now: datetime, today: str,
                                   hot_codes: set = None, bb_signals: dict = None,
                                   profile: dict = None) -> list:
    """动量回调策略 — 弱势市场中，筛选5日强势回调股
	
    筛选逻辑：
    1. 从股票池中选出 zone_pct > 0.3（非深度超跌）的个股
    2. 当日盘中回调幅度在 -1.5% ~ +0.5% 之间
    3. BB 信号 not wait/strong_sell
	
    返回: [(code, p, pct_day), ...] 候选列表
    """
    if profile is None:
        profile = load_cycle_profile()
    if not profile:
        return []
    cd = load_cooldown()
    existing_codes = {p["code"] for p in pf["positions"]}
    candidates = []
	
    for code, p in profile.items():
        if code in existing_codes or code in EXCLUDED_CODES:
            continue
        if cd.get(code) and (now - datetime.strptime(cd[code], "%Y-%m-%d")).days < COOLDOWN_DAYS:
            continue
        mp = prices.get(code)
        if not mp:
            continue
		
        # 条件1: 非深度超跌（zone_pct > 0.3，说明近期有走强迹象）
        zone_pct = p.get("zone_pct", 1)
        if zone_pct <= 0.3:
            continue
		
        # 条件2: 当日盘中回调在 -1.5% ~ +0.5%
        pct_day = mp.get("pct_change", 0)
        if not (MOMENTUM_PULLBACK_MIN <= pct_day <= MOMENTUM_PULLBACK_MAX):
            continue
		
        # 条件3: BB 信号检查
        if bb_signals and code in bb_signals:
            bb_action = bb_signals[code].get("action", "hold")
            if bb_action in ("wait", "strong_sell"):
                continue
		
        candidates.append((code, p, pct_day, zone_pct))
	
    if not candidates:
        return []
	
    # 按 zone_pct 从高到低排序（越接近超买越强）
    candidates.sort(key=lambda x: x[3], reverse=True)
	
    # 只取动量强度前20%
    top_n = max(1, int(len(candidates) * MOMENTUM_STRENGTH_TOP_PCT))
    candidates = candidates[:top_n]
	
    # 打印候选
    print(f"   动量回调候选: {len(candidates)} 只", flush=True)
    for code, p, pct_day, z in candidates:
        print(f"     {p['name']:8s}({code}) zone={z:.2f} pct={pct_day:+.1f}%", flush=True)
	
    return [(c[0], c[1], c[2]) for c in candidates]



def _check_buys_defensive(pf: dict, prices: dict, now: datetime, today: str,
                           hot_codes: set = None, bb_signals: dict = None,
                           profile: dict = None) -> list:
    """防御策略买入 — 空仓/轻仓观望，只在特定条件下买入"""
    # 防御模式不主动买入
    return []


def check_buys(pf: dict, prices: dict, now: datetime, today: str,
               strategy: str = "mean_reversion",
               hot_codes: set = None, bb_signals: dict = None,
               radar_score: float = 50) -> list:
    """买入入口 — 双池仲裁（动量回调优先，均值回归后备）
    
    Args:
        strategy: "momentum" / "mean_reversion" / "cash"
        radar_score: 雷达评分，用于动态阈值
    """
    # 日亏损限制检查
    if check_daily_loss_limit(pf):
        print(f"  ⛔ 单日亏损已达{DAILY_LOSS_PCT}%上限，停止买入", flush=True)
        return []
    
    profile = load_cycle_profile()
    if not profile:
        return []
    
    # 排除代码
    profile = {k: v for k, v in profile.items() if k not in EXCLUDED_CODES}
    print(f"  ℹ️  候选池: {len(profile)} 只国资股", flush=True)
    
    if strategy == "momentum":
        return _check_buys_momentum(pf, prices, now, today, hot_codes, bb_signals, profile)
    elif strategy == "mean_reversion":
        # 双池仲裁：动量回调优先，均值回归后备
        momentum_candidates = _check_buys_momentum_callback(
            pf, prices, now, today, hot_codes, bb_signals, profile)
        
        if momentum_candidates:
            print(f"  🏆 动量回调候选: {len(momentum_candidates)} 只，优先执行", flush=True)
            mr_result = _check_buys_mean_reversion(
                pf, prices, now, today, hot_codes, bb_signals,
                profile={c[0]: profile[c[0]] for c in momentum_candidates},
                radar_score=radar_score)
            if mr_result:
                return mr_result
        
        return _check_buys_mean_reversion(
            pf, prices, now, today, hot_codes, bb_signals, profile,
            radar_score=radar_score)
    else:
        return _check_buys_defensive(pf, prices, now, today, hot_codes, bb_signals, profile)
def scan_once(skip_time_check: bool = False, strategy: str = None) -> dict:
    """增强版主扫描 — 集成行情雷达、BB 信号、凯利仓位"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M")

    if not skip_time_check:
        if now.weekday() >= 5:
            return {"status": "skip", "reason": "非交易日"}
        if now.hour < 9 or now.hour >= 15:
            return {"status": "skip", "reason": "非交易时间"}

    print(f"\n{'='*55}  {now_str}  {'='*55}")
    
    # ── 行情雷达（市场状态判断） ──
    radar = fetch_enhanced_score()
    radar_score = radar.get("score", 50)
    if not strategy:
        strategy = radar.get("strategy", "mean_reversion")
    strategy_cn = radar.get("strategy_cn", "均值回归策略")
    position_ratio = radar.get("position_ratio", 1.0)
    print(f"  📡 雷达评分: {radar.get('score', 50)}/100 → {strategy_cn} (仓位{position_ratio:.0%})", flush=True)
    
    pf = load_portfolio()
    
    # 调整最大持仓数（根据雷达评分）
    global MAX_POSITIONS
    actual_max = max(1, int(MAX_POSITIONS * position_ratio))
    _saved_max = MAX_POSITIONS
    MAX_POSITIONS = actual_max
    
    profile = load_cycle_profile()

    # 行情
    all_codes = list(set(
        [p["code"] for p in pf["positions"]] +
        [c for c in profile.keys()]
    ))
    prices = fetch_prices(all_codes)
    print(f"  行情: {len(prices)}/{len(all_codes)} 只", flush=True)
    
    # ── 热点板块 ──
    hot_codes = set()
    try:
        top_sectors = radar.get("top_sectors", [])
        if top_sectors:
            for sec in top_sectors:
                # 简化：不做板块到个股映射，保留为加分
                pass
    except Exception:
        pass
    
    # ── 持仓 BB 信号 ──
    bb_signals = {}
    try:
        pos_codes = [p["code"] for p in pf["positions"]]
        for code in pos_codes:
            df = fetch_daily_data(code, days=60)
            if not df.empty:
                sig = generate_bb_signal(df["close"] if isinstance(df["close"], pd.Series) else pd.Series(df["close"].values),
                                         prices.get(code, {}).get("price"))
                bb_signals[code] = sig
                pos = next((p for p in pf["positions"] if p["code"] == code), None)
                if pos:
                    bb_a = sig.get("action", "hold")
                    bb_s = sig.get("signal", "")
                    bb_adv = sig.get("advice", "")
                    print(f"    📊 {pos['name']:8s}({code}) BB={bb_a:10s} {bb_s}", flush=True)
    except Exception as e:
        print(f"  ⚠️ BB信号: {e}", flush=True)
    
    # 卖出
    sells = check_sells(pf, prices, now, today, strategy=strategy, bb_signals=bb_signals)
    if sells:
        print(f"  📉 本轮回合卖出: {len(sells)} 笔", flush=True)
    
    # ⭐ 硬熔断检查（独立于模型的物理闸门）
    hard_stops = _check_hard_stops(pf, prices, now, today)
    if hard_stops:
        print(f"  🚨 硬熔断触发: {len(hard_stops)} 笔强制平仓", flush=True)
        for hs in hard_stops:
            sells.append(hs)
    
    # 买入
    buys = check_buys(pf, prices, now, today, strategy=strategy, hot_codes=hot_codes,
                      bb_signals=bb_signals, radar_score=radar_score)
    if buys:
        print(f"  📈 本轮回合买入: {len(buys)} 笔", flush=True)
    
    # 恢复最大持仓
    MAX_POSITIONS = _saved_max

    # 资金概况
    total_pos_value = 0
    for pos in pf["positions"]:
        mp = prices.get(pos["code"], {})
        cur = mp.get("price", pos["buy_price"]) if mp else pos["buy_price"]
        total_pos_value += cur * pos["shares"]

    total_assets = pf["capital"] + total_pos_value
    initial_capital = pf.get("initial_capital", INIT_CAPITAL_FALLBACK)
    total_pnl_amount = total_assets - initial_capital
    total_pnl_pct = total_pnl_amount / initial_capital * 100 if initial_capital > 0 else 0
    realized = pf.get("realized_pnl", 0)

    print(f"\n  💰 ¥{pf['capital']:.0f}+¥{total_pos_value:.0f}=¥{total_assets:.0f} "
          f"({total_pnl_pct:+.2f}%) 持仓{len(pf['positions'])}/{_saved_max} "
          f"初始¥{initial_capital:.0f} 实现¥{realized:.0f}", flush=True)

    # 当前持仓
    if pf["positions"]:
        print(f"  持仓明细:")
        for pos in pf["positions"]:
            mp = prices.get(pos["code"], {})
            cur = mp.get("price", pos["buy_price"]) if mp else pos["buy_price"]
            pnl = (cur - pos["buy_price"]) / pos["buy_price"] * 100
            icon = "🟢" if pnl >= 0 else "🔴"
            strategy_n = pos.get("strategy", "?")
            print(f"    {icon} {pos['name']:8s}({pos['code']}) 买{pos['buy_price']:.2f}→{cur:.2f} {pnl:+.2f}% ×{pos['shares']} [{strategy_n}]")

    # 推送（有操作时）
    if sells or buys:
        msg_lines = [f"**🐦 凤雏交易操作 | {now.strftime('%H:%M')}**", ""]
        for s in sells:
            emoji = "🟢" if s.get("pnl", 0) >= 0 else "🔴"
            msg_lines.append(f"{emoji} 卖出 {s['name']}({s['code']}) @ {s['price']:.2f} "
                             f"盈亏{s.get('pnl_pct',0):+.1f}% | {s['reason']}")
        for b in buys:
            msg_lines.append(f"🟢 买入 {b['name']}({b['code']}) @ {b['price']:.2f} ×{b['shares']}股 [{b.get('strategy','?')}] | {b['reason']}")
        msg_lines.append("")
        msg_lines.append(f"💰 总资产: ¥{total_assets:.0f} ({total_pnl_pct:+.2f}%) 初始¥{initial_capital:.0f} 持仓{len(pf['positions'])}只")
        msg_lines.append(f"📡 雷达: {radar.get('score', 50)}/100 → {strategy_cn}")
        msg_lines.append(f"凤雏执行 | 刘秀风控")
        push_to_feishu("\n".join(msg_lines))
    else:
        print(f"  ✅ 无操作")

    # Dify
    if dify_configured():
        try:
            enriched = []
            for pos in pf["positions"]:
                mp = prices.get(pos["code"], {})
                cur = mp.get("price", pos["buy_price"]) if mp else pos["buy_price"]
                pnl = (cur - pos["buy_price"]) / pos["buy_price"] * 100
                enriched.append({**pos, "cur_price": cur, "pnl_pct": round(pnl, 2)})
            upload_monitor_scan(
                scan_time=now_str, positions=enriched,
                alerts=[f"{s['name']} {s['action']} @ {s['price']}" for s in sells] +
                       [f"{b['name']} {b['action']} @ {b['price']}" for b in buys],
                cash=pf["capital"], pos_value=total_pos_value,
                total=total_assets, total_pnl_pct=total_pnl_pct,
                realized_pnl=realized,
            )
        except Exception:
            pass

    return {"status": "ok", "time": now_str, "positions": len(pf["positions"]),
            "total": round(total_assets, 2), "pnl_pct": round(total_pnl_pct, 2),
            "sells": len(sells), "buys": len(buys), "strategy": strategy}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="凤雏自动交易 v2.5")
    parser.add_argument("--once", action="store_true", help="单次扫描")
    parser.add_argument("--simulate", action="store_true", help="模拟模式")
    parser.add_argument("--strategy", type=str, default=None,
                        choices=["momentum", "mean_reversion", "cash", None],
                        help="指定策略（默认由雷达自动选择）")
    args = parser.parse_args()

    if args.simulate:
        print("\n===== 🧪 模拟模式 =====\n")
        bak = PORTFOLIO_PATH + ".bak"
        if os.path.exists(PORTFOLIO_PATH):
            shutil.copy2(PORTFOLIO_PATH, bak)
        
        # 模拟用持仓（使用真实行情中能找到的代码）
        sim = {
            "positions": [],
            "capital": 50000, "trades": [], "total_buy": 0,
            "total_sell": 0, "realized_pnl": 0,
            "initial_capital": 100000, "daily_loss": 0,
            "daily_loss_date": datetime.now().strftime("%Y-%m-%d"),
        }
        # 使用一个能找到的股票做模拟
        test_prices = fetch_prices(["600519", "000858", "600036", "601398", "600900"])
        test_positions = []
        cap = 50000
        for code, name in [("600519", "贵州茅台"), ("000858", "五粮液"), 
                           ("600036", "招商银行"), ("601398", "工商银行"),
                           ("600900", "长江电力")]:
            mp = test_prices.get(code)
            if mp and mp["price"] > 0:
                price = mp["price"]
                shares = max(100, int(10000 / price / 100) * 100)
                cost = shares * price
                if cap >= cost:
                    test_positions.append({
                        "code": code, "name": mp.get("name", name),
                        "buy_price": price * (1 + random.uniform(-0.03, 0.03)),
                        "shares": shares,
                        "buy_date": (datetime.now() - timedelta(days=random.randint(1, 10))).strftime("%Y-%m-%d"),
                        "strategy": "mean_reversion",
                        "trailing_stop": 0,
                    })
                    cap -= cost
        
        sim["positions"] = test_positions
        sim["capital"] = cap
        json.dump(sim, open(PORTFOLIO_PATH, "w"), indent=2, ensure_ascii=False)
        print(f"  模拟持仓: {len(test_positions)} 只, 现金 ¥{cap:.0f}")
        
        try:
            # 跑一次完整扫描
            result = scan_once(skip_time_check=True, strategy=args.strategy)
        finally:
            if os.path.exists(bak):
                shutil.move(bak, PORTFOLIO_PATH)
                print("\n✅ 恢复真实持仓")
        return
    # ── 轮询模式（默认） ──
    if args.once:
        scan_once(strategy=args.strategy)
        return

    # 连续轮询：每 300 秒扫描一次
    POLL_INTERVAL = 300
    log_dir = os.path.join(BASE, "logs")
    os.makedirs(log_dir, exist_ok=True)
    today_str = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"fengchu_daemon_{today_str}.log")
    run_log = os.path.join(log_dir, f"fengchu_run_{today_str}.log")

    # 守护进程模式：自动将 stdout/stderr 重定向到日志文件（不依赖外部 nohup）
    import sys
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(log_dir, f"fengchu_error_{today_str}.log")),
            logging.StreamHandler(sys.stderr),
        ],
    )
    f_out = open(run_log, "a", encoding="utf-8", buffering=1)
    os.dup2(f_out.fileno(), sys.stdout.fileno())
    os.dup2(f_out.fileno(), sys.stderr.fileno())

    # 全局异常捕获：防止无声崩溃
    def _daemon_excepthook(exc_type, exc_value, exc_tb):
        import traceback
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] UNHANDLED {exc_type.__name__}: {exc_value}\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _daemon_excepthook

    # 信号处理：优雅退出前记录状态
    def _handle_signal(sig, frame):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 收到信号 {sig}，守护进程退出\n")
        sys.exit(0)
    import concurrent.futures
    import signal
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGHUP, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(f"  🌀 凤雏轮询守护进程启动，间隔 {POLL_INTERVAL}s", flush=True)
    print(f"  📝 日志: {log_file}", flush=True)
    while True:
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        # 非交易日不跑，但守护进程不退出（静默等待）
        if now.weekday() >= 5:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] 周末跳过\n")
            time.sleep(POLL_INTERVAL)
            continue
        try:
            # 全局扫描超时保护：防止单个 akshare 调用挂死整轮扫描
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(scan_once, strategy=args.strategy)
                result = future.result(timeout=240)  # 4 分钟超时
            status = result.get("status", "ok") if isinstance(result, dict) else "ok"
        except concurrent.futures.TimeoutError:
            status = "timeout"
            print(f"  ⏰ 扫描超时（>240s），跳过本轮", flush=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] 扫描超时（>240s），跳过本轮\n")
        except Exception as e:
            status = f"error: {e}"
            print(f"  ❌ 扫描异常: {e}", flush=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] 扫描完成: 状态={status}\n")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
