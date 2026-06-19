"""
数据获取模块 — 多数据源混合策略

策略：
  1. 股票列表: ak.stock_info_a_code_name() 获取全部代码
  2. 实时行情: 批量查询 push2.eastmoney.com/api/qt/ulist.np/get
  3. 历史K线: 直接调用 push2his.eastmoney.com KLine API
  4. 板块数据: 直接调用 push2.eastmoney.com/api/qt/clist/get
  5. HTTP问题: Python3.14上urllib3有兼容问题，自动降级到subprocess+curl
"""
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import akshare as ak
import pandas as pd
import requests

from src.database import get_db
logger = logging.getLogger(__name__)

# ── HTTP 会话 ──
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
_session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

# 是否使用 curl 降级（Python 3.14 urllib3 兼容问题）
_use_curl_fallback = False


def is_permanently_excluded(code) -> bool:
    code = str(code).zfill(6)
    if code.startswith(("8", "4")) and len(code) == 6:
        return True
    if code.startswith(("688", "689")):
        return True
    if code.startswith(("300", "301")):
        return True
    return False


def _em_get_requests(url: str, params: dict = None) -> Optional[dict]:
    """requests 方式请求"""
    for attempt in range(3):
        try:
            resp = _session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"requests 失败 (尝试 {attempt+1}/3): {type(e).__name__}")
            if attempt < 2:
                time.sleep(1 + attempt * 2)
    return None


def _em_get_curl(url: str, params: dict = None) -> Optional[dict]:
    """curl 方式降级请求"""
    cmd = ["curl", "-s", "-m", "10", url, "-H", "User-Agent: Mozilla/5.0"]
    if params:
        for k, v in params.items():
            cmd.extend(["--data-urlencode", f"{k}={v}"])
    for attempt in range(3):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                return json.loads(result.stdout)
        except Exception as e:
            logger.debug(f"curl 失败 (尝试 {attempt+1}/3): {type(e).__name__}")
            if attempt < 2:
                time.sleep(1)
    return None


def _em_get(url: str, params: dict = None) -> Optional[dict]:
    """智能请求：先 requests，失败则降级到 curl"""
    global _use_curl_fallback
    if _use_curl_fallback:
        return _em_get_curl(url, params)
    data = _em_get_requests(url, params)
    if data is None:
        logger.debug("requests 失败，降级到 curl")
        _use_curl_fallback = True
        return _em_get_curl(url, params)
    return data


# ── 交易日历 ──
def get_trade_calendar() -> pd.DataFrame:
    try:
        raw = ak.tool_trade_date_hist_sina()
        if not raw.empty:
            df = raw.copy()
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            return df
    except Exception as e:
        logger.warning(f"交易日历获取失败: {e}")
    return pd.DataFrame()


def is_trading_day(date_str: str) -> bool:
    df = get_trade_calendar()
    if df.empty:
        return False
    return pd.Timestamp(date_str) in df["trade_date"].values


def get_prev_trading_day(date_str: str) -> str:
    df = get_trade_calendar()
    target = pd.Timestamp(date_str)
    trading_days = sorted(t for t in df["trade_date"].values if t <= target)
    return pd.Timestamp(trading_days[-2]).strftime("%Y-%m-%d") if len(trading_days) >= 2 else date_str


def get_next_trading_day(date_str: str) -> Optional[str]:
    df = get_trade_calendar()
    target = pd.Timestamp(date_str)
    trading_days = sorted(t for t in df["trade_date"].values if t >= target)
    return pd.Timestamp(trading_days[1]).strftime("%Y-%m-%d") if len(trading_days) >= 2 else None


# ── 股票列表 ──
def fetch_stock_list() -> pd.DataFrame:
    """获取全市场股票列表（已排除禁止股）"""
    try:
        db = get_db()
        cached = db.get_stock_list()
        if not cached.empty and len(cached) > 100:
            logger.info(f"从缓存读取股票列表 ({len(cached)} 只)")
            return cached
    except Exception:
        pass
    try:
        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].astype(str).str.zfill(6)
        df = df[~df["code"].apply(is_permanently_excluded)]
        df = df[~df["name"].str.contains("ST|退市", na=False)]
        try:
            get_db().save_stock_list(df)
            logger.info(f"股票列表已缓存 ({len(df)} 只)")
        except Exception:
            pass
        return df
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


# ── 实时行情 ──
def _batch_query_ulist(codes: List[str], max_batch: int = 100) -> pd.DataFrame:
    """批量查询实时行情"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    base_fields = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21"

    all_rows = []
    total = len(codes)
    for i in range(0, total, max_batch):
        batch = codes[i:i + max_batch]
        secids = [f"1.{c}" if c.startswith(("6", "9")) else f"0.{c}" for c in batch]
        params = {"fltt": "2", "fields": base_fields, "secids": ",".join(secids)}
        data = _em_get(url, params)
        if data and "data" in data and data["data"] and "diff" in data["data"]:
            all_rows.extend(data["data"]["diff"])
        else:
            logger.warning(f"批 {i//max_batch+1}/{(total+max_batch-1)//max_batch} 无数据")

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    rename = {
        "f2": "price", "f3": "pct_change", "f4": "change",
        "f5": "volume", "f6": "amount", "f7": "amplitude",
        "f8": "turnover", "f9": "pe", "f10": "volume_ratio",
        "f12": "code", "f14": "name",
        "f15": "high", "f16": "low", "f17": "open", "f18": "pre_close",
        "f20": "total_mv", "f21": "float_mv",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["code"] = df["code"].astype(str).str.zfill(6)

    for col in ["price", "pct_change", "volume", "amount", "turnover",
                "volume_ratio", "float_mv", "total_mv", "amplitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def fetch_all_stocks_spot() -> pd.DataFrame:
    """获取全市场实时行情"""
    stock_list = fetch_stock_list()
    if stock_list.empty:
        return pd.DataFrame()
    codes = stock_list["code"].tolist()
    logger.info(f"共 {len(codes)} 只候选股票，正在获取实时行情...")
    df = _batch_query_ulist(codes)
    logger.info(f"获取到 {len(df)} 只实时行情")
    if not df.empty:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            get_db().save_snapshot(df, today)
        except Exception:
            pass
    return df


# ── 个股历史 ──
def fetch_stock_history(code: str, days: int = 60, use_cache: bool = True) -> pd.DataFrame:
    """获取个股历史日线 — KLine API"""
    if use_cache:
        try:
            db = get_db()
            cached = db.get_klines(code, days + 10)
            if not cached.empty and len(cached) >= min(days, 20):
                logger.debug(f"{code} 日线缓存命中 ({len(cached)} 天)")
                return cached
        except Exception:
            pass
    
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    end = datetime.now().strftime("%Y%m%d")
    secid = f"1.{code}" if str(code).startswith(("6", "9")) else f"0.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1",
        "end": end, "lmt": days + 30,
    }
    data = _em_get(url, params)
    if not data or "data" not in data or "klines" not in data["data"]:
        logger.debug(f"获取 {code} K线失败")
        return pd.DataFrame()

    klines = data["data"]["klines"]
    records = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 11:
            records.append({
                "date": parts[0], "open": float(parts[1]),
                "close": float(parts[2]), "high": float(parts[3]),
                "low": float(parts[4]), "volume": float(parts[5]),
                "amount": float(parts[6]), "amplitude": float(parts[7]),
                "pct_change": float(parts[8]), "change": float(parts[9]),
                "turnover": float(parts[10]),
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        try:
            get_db().save_klines(code, df)
        except Exception:
            pass
    return df


# ── 板块数据 ──
def fetch_sector_top_gainers(top_n: int = 5) -> pd.DataFrame:
    """获取当日涨幅前N的行业板块"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": top_n, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f14",
    }
    data = _em_get(url, params)
    if not data or "data" not in data or "diff" not in data["data"]:
        logger.warning("获取板块排行失败")
        return pd.DataFrame()

    df = pd.DataFrame(data["data"]["diff"])
    if not df.empty:
        df = df.rename(columns={"f14": "板块名称", "f3": "涨跌幅", "f12": "代码", "f2": "最新价"})
    return df


def fetch_stock_sector_map() -> dict:
    """获取个股所属板块映射"""
    try:
        cached = get_db().get_sector_map()
        if cached:
            logger.info(f"从缓存读取板块映射 ({len(cached)} 个板块)")
            return cached
    except Exception:
        pass
    
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 6000, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:3",
        "fields": "f12,f14",
    }
    data = _em_get(url, params)
    if not data or "data" not in data:
        return {}
    result = {item["f12"]: item.get("f14", "") for item in data["data"].get("diff", [])}
    try:
        get_db().save_sector_map(result)
    except Exception:
        pass
    return result


# ── 涨停判断 ──
def has_20d_limit_up(code: str) -> bool:
    """判断最近20个交易日是否有涨停（>=9.5%）"""
    try:
        # 优先从缓存读
        db = get_db()
        cached = db.get_klines(code, 35)
        if not cached.empty and len(cached) >= 20:
            return (cached.tail(20)["pct_change"] >= 9.5).any()
    except Exception:
        pass
    hist = fetch_stock_history(code, days=30)
    if hist.empty:
        return False
    return (hist.tail(20)["pct_change"] >= 9.5).any()


# ── 过滤 ──
def filter_market_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    code_col = "code" if "code" in df.columns else df.columns[0]
    name_col = "name" if "name" in df.columns else None
    mask = ~df[code_col].apply(is_permanently_excluded)
    if name_col and name_col in df.columns:
        mask &= ~df[name_col].astype(str).str.contains("ST|退市", na=False)
    return df[mask].copy()
