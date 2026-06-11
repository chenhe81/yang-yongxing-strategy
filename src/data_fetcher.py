"""
数据获取模块 — 多数据源混合策略

策略：
  1. 股票列表: ak.stock_info_a_code_name() 获取全部代码
  2. 实时行情: 批量查询 push2.eastmoney.com/api/qt/ulist.np/get
  3. 历史K线: 直接调用 push2his.eastmoney.com KLine API
  4. 板块数据: 直接调用 push2.eastmoney.com/api/qt/clist/get
"""
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict

import akshare as ak
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── HTTP 会话（自定义，避免 akshare 的 HTTP 兼容性问题）──
_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
_session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})

# 永久排除清单
PERMANENT_EXCLUDE_CODES = {"688039"}


def is_permanently_excluded(code: str) -> bool:
    if code in PERMANENT_EXCLUDE_CODES:
        return True
    if code.startswith(("8", "4")) and len(code) == 6:
        return True
    if code.startswith(("688", "689")):
        return True
    if code.startswith(("300", "301")):
        return True
    return False


def _em_get(url: str, params: dict = None, max_retries: int = 3) -> dict:
    """东方财富 API GET 请求（带重试 + 退避）"""
    for attempt in range(max_retries):
        try:
            resp = _session.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            logger.debug(f"HTTP {resp.status_code} for {url}")
        except Exception as e:
            logger.debug(f"请求失败 (尝试 {attempt+1}/{max_retries}): {type(e).__name__}")
            if attempt < max_retries - 1:
                time.sleep(1 + attempt * 2)
    return {}


# ── 交易日历 ──
def get_trade_calendar() -> pd.DataFrame:
    df = pd.DataFrame()
    try:
        raw = ak.tool_trade_date_hist_sina()
        if not raw.empty:
            df = raw.copy()
            df["trade_date"] = pd.to_datetime(df["trade_date"])
    except Exception as e:
        logger.warning(f"交易日历获取失败: {e}")
    return df


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
    """获取全市场股票列表（代码+名称，排除禁止股）"""
    try:
        df = ak.stock_info_a_code_name()
        df = df.rename(columns={"code": "code", "name": "name"})
        df["code"] = df["code"].astype(str).str.zfill(6)
        # 应用排除过滤
        df = df[~df["code"].apply(is_permanently_excluded)]
        df = df[~df["name"].str.contains("ST|退市", na=False)]
        return df
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return pd.DataFrame()


# ── 实时行情 ──
def _batch_query_ulist(codes: List[str], max_batch: int = 100) -> pd.DataFrame:
    """批量查询实时行情 — push2 的 ulist API (更稳定)"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    base_fields = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21"

    all_rows = []
    for i in range(0, len(codes), max_batch):
        batch = codes[i:i + max_batch]
        secids = [f"1.{c}" if c.startswith(("6", "9")) else f"0.{c}" for c in batch]
        params = {"fltt": "2", "fields": base_fields, "secids": ",".join(secids)}
        data = _em_get(url, params)
        if data and "data" in data and "diff" in data["data"]:
            all_rows.extend(data["data"]["diff"])

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
    return df


# ── 个股历史 ──
def fetch_stock_history(code: str, days: int = 60) -> pd.DataFrame:
    """获取个股历史日线 — KLine API"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    end = datetime.now().strftime("%Y%m%d")
    secid = f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"
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
    return df


# ── 行业板块 ──
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


# ── 涨停判断 ──
def has_20d_limit_up(code: str) -> bool:
    """检查过去20天是否有涨停"""
    hist = fetch_stock_history(code, days=30)
    if hist.empty:
        return False
    recent = hist.tail(20)
    if recent.empty:
        return False
    return (recent["pct_change"] >= 9.5).any()


# ── 过滤 ──
def filter_market_data(df: pd.DataFrame) -> pd.DataFrame:
    """通用过滤"""
    if df.empty:
        return df
    code_col = "code" if "code" in df.columns else df.columns[0]
    name_col = "name" if "name" in df.columns else None
    mask = ~df[code_col].apply(is_permanently_excluded)
    if name_col and name_col in df.columns:
        mask &= ~df[name_col].astype(str).str.contains("ST|退市", na=False)
    return df[mask].copy()
def _batch_query_ulist(codes: List[str], max_batch: int = 100) -> pd.DataFrame:
    """批量查询实时行情 — push2 的 ulist API (更稳定)"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    base_fields = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21"

    all_rows = []
    total_batches = (len(codes) + max_batch - 1) // max_batch
    for i in range(0, len(codes), max_batch):
        batch = codes[i:i + max_batch]
        secids = [f"1.{c}" if c.startswith(("6", "9")) else f"0.{c}" for c in batch]
        params = {"fltt": "2", "fields": base_fields, "secids": ",".join(secids)}
        data = _em_get(url, params)
        if data and "data" in data and data["data"] and "diff" in data["data"]:
            all_rows.extend(data["data"]["diff"])
        else:
            logger.warning(f"批 {i//max_batch+1}/{total_batches} 无数据，跳过")

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

    for col in ["price", "pct_change", "volume", "amount", "turnover",
                "volume_ratio", "float_mv", "total_mv", "amplitude"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df
