"""
杨永兴短线战法 - 行情数据获取层
基于 腾讯股票API + 新浪数据 + akshare 封装，提供：
- 实时涨幅排行（腾讯接口优先，最稳定快速）
- 个股详细数据
- 大盘趋势判断
- 涨停记录查询
- 分时数据
- 日K线数据

数据源优先级（已移除东方财富，避免频繁限流/封禁）：
  实时行情：腾讯(qt.gtimg.cn) > 新浪(stock_zh_a_spot)
  日K线：  腾讯(web.ifzq.gtimg.cn) > 新浪(stock_zh_a_daily)
  基本信息：腾讯(交易所代码列表) > 新浪(stock_zh_a_spot)
  涨停数据：腾讯实时行情筛选(涨幅≥9.8%) > 新浪日K筛选
  分时数据：腾讯分时接口 > 新浪(stock_intraday_sina)
  大盘指数：腾讯(stock_zh_index_daily_tx) > 新浪(stock_zh_index_daily)
"""

import akshare as ak
import pandas as pd
import datetime
import time
import logging
import requests
import json
import re

logger = logging.getLogger(__name__)


def _retry(func, retries=3, delay=2):
    """带重试的函数调用"""
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            if i < retries - 1:
                logger.warning(f"第{i+1}次重试: {e}")
                time.sleep(delay)
            else:
                raise


# ============ 大盘数据 ============

def get_market_trend():
    """
    判断大盘趋势：近5日均线方向
    数据源优先级：腾讯指数接口 > 新浪指数接口
    返回: dict { trend: "up"/"down"/"flat", ma5: float, close: float, change_pct: float }
    """
    try:
        # 尝试方案1：腾讯指数日K线
        try:
            df = _retry(lambda: ak.stock_zh_index_daily_tx(symbol="sh000001"))
        except Exception:
            # 方案2：新浪指数日K线
            df = _retry(lambda: ak.stock_zh_index_daily(symbol="sh000001"))

        if df is None or df.empty:
            return {"trend": "unknown", "reason": "无法获取大盘数据"}

        # 统一列名：腾讯用amount，新浪用volume
        if "amount" in df.columns and "volume" not in df.columns:
            df["volume"] = df["amount"]

        # 先按日期升序计算均线，再取最近数据
        df = df.sort_values("date", ascending=True)
        df["ma5"] = df["close"].rolling(5).mean()
        df_recent = df.tail(10)

        latest = df_recent.iloc[-1]
        prev = df_recent.iloc[-2] if len(df_recent) > 1 else latest

        # 近5日均线走势（最新MA5 vs 前一日MA5）
        ma5_latest = latest["ma5"]
        ma5_prev = df_recent.iloc[-2]["ma5"] if len(df_recent) > 1 and pd.notna(df_recent.iloc[-2]["ma5"]) else None

        if pd.notna(ma5_latest) and ma5_prev is not None:
            if ma5_latest > ma5_prev:
                trend = "up"
            elif ma5_latest < ma5_prev:
                trend = "down"
            else:
                trend = "flat"
        else:
            trend = "unknown"

        change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100

        return {
            "trend": trend,
            "close": latest["close"],
            "ma5": round(ma5_latest, 2) if pd.notna(ma5_latest) else None,
            "change_pct": round(change_pct, 2),
            "volume": latest.get("volume", 0),
        }
    except Exception as e:
        logger.error(f"获取大盘趋势失败: {e}")
        return {"trend": "unknown", "reason": str(e)}


def get_market_status():
    """
    获取当日大盘状态（是否放量大跌等）
    数据源优先级：腾讯指数接口 > 新浪指数接口
    返回: dict { is_crash: bool, volume_ratio: float, change_pct: float }
    """
    try:
        # 尝试方案1：腾讯指数日K线
        try:
            df = _retry(lambda: ak.stock_zh_index_daily_tx(symbol="sh000001"))
        except Exception:
            # 方案2：新浪指数日K线
            df = _retry(lambda: ak.stock_zh_index_daily(symbol="sh000001"))

        if df is None or df.empty:
            return {"is_crash": False, "reason": "无法获取数据"}

        # 统一列名：腾讯用amount，新浪用volume
        if "amount" in df.columns and "volume" not in df.columns:
            df["volume"] = df["amount"]

        df = df.sort_values("date", ascending=False).head(10)
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        latest = df.iloc[0]
        avg_volume = df.iloc[1:6]["volume"].mean()
        latest_vol = pd.to_numeric(latest["volume"], errors="coerce")
        volume_ratio = latest_vol / avg_volume if avg_volume > 0 and pd.notna(avg_volume) else 1.0

        prev = df.iloc[1] if len(df) > 1 else latest
        change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100

        # 放量大跌判定：跌幅>2% 且 量比>1.5
        is_crash = change_pct < -2.0 and volume_ratio > 1.5

        return {
            "is_crash": is_crash,
            "volume_ratio": round(volume_ratio, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        logger.error(f"获取大盘状态失败: {e}")
        return {"is_crash": False, "reason": str(e)}


# ============ 个股数据 ============

def get_realtime_quotes():
    """
    获取全市场实时行情（涨幅排行）
    数据源优先级：腾讯(qt.gtimg.cn) > 新浪(stock_zh_a_spot)
    腾讯接口全市场仅需约3秒，稳定性最佳
    返回 DataFrame: 包含代码、名称、涨跌幅、成交量、换手率等
    """
    # 尝试方案1（首选）：腾讯股票接口（最稳定快速，全市场约3秒）
    try:
        df = _get_realtime_quotes_tencent()
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"腾讯行情接口失败: {e}")

    # 尝试方案2：新浪数据（列较少，但稳定性好）
    try:
        df = _retry(lambda: ak.stock_zh_a_spot())
        if df is not None and not df.empty:
            return _normalize_quotes_sina(df)
    except Exception as e:
        logger.warning(f"新浪行情接口也失败: {e}")

    logger.error("所有行情接口均不可用")
    return pd.DataFrame()


def _get_realtime_quotes_tencent():
    """
    通过腾讯股票接口(qt.gtimg.cn)获取全市场实时行情
    步骤：
      1. 用akshare新浪接口获取股票代码列表（含sh/sz/bj前缀）
      2. 分批调用腾讯接口获取实时行情
    优点：全市场约3秒，比东方财富/新浪快5-10倍，且更稳定
    """
    # 第一步：获取股票代码列表
    try:
        code_df = _retry(lambda: ak.stock_zh_a_spot())
    except Exception:
        code_df = None

    if code_df is None or code_df.empty:
        return pd.DataFrame()

    # 获取带市场前缀的代码列表（sh600000/sz000001/bj830000）
    raw_codes = code_df["代码"].astype(str).tolist() if "代码" in code_df.columns else []
    if not raw_codes:
        return pd.DataFrame()

    # 第二步：分批获取腾讯实时行情
    all_stocks = []
    batch_size = 700  # 腾讯接口单次最多约800只

    for i in range(0, len(raw_codes), batch_size):
        batch = raw_codes[i:i + batch_size]
        query = ",".join(batch)
        url = f"http://qt.gtimg.cn/q={query}"

        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue

            lines = resp.text.strip().split(";")
            for line in lines:
                if "=" not in line or "~" not in line:
                    continue
                _, val = line.split("=", 1)
                val = val.strip('"')
                fields = val.split("~")
                if len(fields) < 40 or not fields[1]:
                    continue

                try:
                    stock = {
                        "code": fields[2],          # 纯数字代码
                        "name": fields[1],           # 股票名称
                        "price": _safe_float(fields[3]),        # 最新价
                        "pre_close": _safe_float(fields[4]),    # 昨收
                        "open": _safe_float(fields[5]),         # 今开
                        "volume": _safe_float(fields[6]),       # 成交量（手）
                        "amount": _safe_float(fields[37]) if len(fields) > 37 else None,  # 成交额（万）
                        "high": _safe_float(fields[33]) if len(fields) > 33 else None,    # 最高
                        "low": _safe_float(fields[34]) if len(fields) > 34 else None,     # 最低
                        "change_pct": _safe_float(fields[32]) if len(fields) > 32 else None,  # 涨跌幅%
                        "change_amt": _safe_float(fields[31]) if len(fields) > 31 else None,  # 涨跌额
                        "amplitude": None,           # 振幅（需计算）
                        "volume_ratio": _safe_float(fields[49]) if len(fields) > 49 else None,  # 量比
                        "turnover_rate": None,       # 换手率（需计算）
                        "circ_mv": _safe_float(fields[44]) * 1e8 if len(fields) > 44 and _safe_float(fields[44]) else None,  # 流通市值
                        "total_mv": _safe_float(fields[45]) * 1e8 if len(fields) > 45 and _safe_float(fields[45]) else None,  # 总市值
                        "pe": _safe_float(fields[39]) if len(fields) > 39 else None,  # 市盈率
                        "pb": None,                  # 市净率
                    }
                    # 计算振幅
                    if stock["high"] and stock["low"] and stock["pre_close"] and stock["pre_close"] > 0:
                        stock["amplitude"] = round((stock["high"] - stock["low"]) / stock["pre_close"] * 100, 2)
                    # 换手率
                    stock["turnover_rate"] = _safe_float(fields[43]) if len(fields) > 43 else None
                    # 流通市值（亿元）
                    stock["circ_mv_billion"] = stock["circ_mv"] / 1e8 if stock["circ_mv"] else None

                    all_stocks.append(stock)
                except (IndexError, ValueError, TypeError):
                    continue

        except requests.RequestException:
            continue

    if not all_stocks:
        return pd.DataFrame()

    df = pd.DataFrame(all_stocks)

    # 确保代码为纯数字（去掉可能残留的前缀）
    df["code"] = df["code"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)

    logger.info(f"腾讯行情接口获取成功: {len(df)} 只股票")
    return df


def _safe_float(val):
    """安全转换为浮点数"""
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _normalize_quotes_sina(df):
    """统一新浪行情数据列名（列较少，需要补充计算）"""
    # stock_zh_a_spot 的列名
    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌额": "change_amt",
        "涨跌幅": "change_pct",
        "昨收": "pre_close",
        "今开": "open",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
    }
    df = df.rename(columns=col_map)

    # 新浪代码带市场前缀（sh600000/sz000001/bj830000），统一为纯数字
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True)

    for col in ["change_pct", "amount", "price", "pre_close", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 新浪数据缺少以下字段，需要计算或设为NaN
    if "amplitude" not in df.columns and all(c in df.columns for c in ["high", "low", "pre_close"]):
        df["amplitude"] = ((df["high"] - df["low"]) / df["pre_close"] * 100).round(2)

    # 量比和换手率无法从新浪数据计算，设为NaN（后续步骤会跳过这些过滤）
    if "volume_ratio" not in df.columns:
        df["volume_ratio"] = float("nan")
    if "turnover_rate" not in df.columns:
        df["turnover_rate"] = float("nan")
    if "circ_mv_billion" not in df.columns:
        df["circ_mv_billion"] = float("nan")

    return df


def get_limit_up_history(days=20, target_codes=None):
    """
    获取近N天的涨停股票记录
    如果指定target_codes，只检查这些股票；否则用腾讯实时行情中的高涨幅股票近似判断
    返回 dict: { 日期: [股票代码列表] }
    """
    try:
        result = {}

        if target_codes:
            # 只检查指定股票的日K线
            for code in target_codes:
                try:
                    df = get_stock_kline(code, days=days + 5)
                    if df is None or df.empty:
                        continue

                    # 涨跌幅需要自行计算（腾讯K线不提供change_pct）
                    df = df.sort_values("date", ascending=True)
                    if "close" in df.columns and len(df) > 1:
                        df["pct"] = df["close"].pct_change() * 100
                        recent = df.tail(days + 2)
                        for _, row in recent.iterrows():
                            pct = row.get("pct", None)
                            if pd.notna(pct) and pct >= 9.8:
                                date_val = row.get("date", "")
                                if date_val:
                                    date_str = str(date_val).replace("-", "")[:8]
                                    if date_str not in result:
                                        result[date_str] = []
                                    result[date_str].append(code)
                except Exception:
                    continue
            return result

        # 没有指定目标代码时，用实时行情中涨幅较高的股票近似判断
        # 获取实时行情中涨幅>5%的股票，这些更有可能有涨停历史
        try:
            quotes = get_realtime_quotes()
            if quotes is not None and not quotes.empty and "change_pct" in quotes.columns:
                high_change = quotes[quotes["change_pct"] >= 5.0]
                if "code" in high_change.columns:
                    target_codes = high_change["code"].tolist()[:100]  # 取涨幅最大的100只
                    return get_limit_up_history(days=days, target_codes=target_codes)
        except Exception:
            pass

        return result
    except Exception as e:
        logger.error(f"获取涨停历史失败: {e}")
        return {}


def get_limit_up_today():
    """
    获取今日涨停股票列表
    通过腾讯实时行情筛选（涨幅≥9.8%视为涨停）
    返回 list: 股票代码列表
    """
    try:
        df = get_realtime_quotes()
        if df is None or df.empty:
            return []
        # 筛选涨幅≥9.8%的股票（考虑四舍五入，9.8%即视为涨停）
        if "change_pct" in df.columns:
            limit_up = df[df["change_pct"] >= 9.8]
            return limit_up["code"].tolist() if "code" in limit_up.columns else []
        return []
    except Exception as e:
        logger.warning(f"获取今日涨停列表失败: {e}")
        return []


def get_intraday_data(code):
    """
    获取个股分时数据
    数据源优先级：腾讯分时接口 > 新浪(stock_intraday_sina)
    返回 dict: { avg_price: 均价, above_avg: 是否全天在均价线上方, current_vs_avg: 当前价vs均价 }
    """
    # 尝试方案1：腾讯分时接口
    try:
        result = _get_intraday_data_tencent(code)
        if result.get("avg_price") is not None:
            return result
    except Exception as e:
        logger.warning(f"腾讯分时获取{code}失败: {e}")

    # 尝试方案2：新浪分时接口
    try:
        prefix = _get_market_prefix(code)
        symbol = f"{prefix}{code}"
        today_str = datetime.date.today().strftime("%Y%m%d")
        df = _retry(lambda s=symbol, d=today_str: ak.stock_intraday_sina(symbol=s, date=d))
        if df is None or df.empty:
            return {"avg_price": None, "above_avg": None, "reason": "无分时数据"}

        # 计算成交均价
        avg_price = None
        if "成交额" in df.columns and "成交量" in df.columns:
            total_amount = df["成交额"].sum()
            total_volume = df["成交量"].sum()
            avg_price = total_amount / total_volume / 100 if total_volume > 0 else None

        current_price = None
        above_avg = None
        price_col = None
        for col_name in ["最新价", "price", "成交价"]:
            if col_name in df.columns:
                price_col = col_name
                break

        if avg_price and price_col:
            prices = df[price_col].dropna()
            current_price = prices.iloc[-1] if len(prices) > 0 else None
            if len(prices) > 0:
                above_avg = (prices >= avg_price * 0.995).all()

        return {
            "avg_price": round(avg_price, 2) if avg_price else None,
            "above_avg": above_avg,
            "current_price": current_price,
        }
    except Exception as e:
        logger.error(f"获取{code}分时数据失败: {e}")
        return {"avg_price": None, "above_avg": None, "reason": str(e)}


def _get_intraday_data_tencent(code):
    """通过腾讯接口获取个股分时数据"""
    prefix = _get_market_prefix(code)
    full_code = f"{prefix}{code}"

    url = f"http://web.ifzq.gtimg.cn/appstock/app/minute/query?code={full_code}"
    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        return {"avg_price": None, "above_avg": None, "reason": "请求失败"}

    data = json.loads(resp.content)
    stk = data.get("data", {}).get(full_code, {})
    if not stk:
        return {"avg_price": None, "above_avg": None, "reason": "无数据"}

    # 腾讯分时数据格式: "20260421093001,10.50,1000" → 时间,价格,成交量
    minute_data = stk.get("data", "")
    if not minute_data:
        return {"avg_price": None, "above_avg": None, "reason": "无分时数据"}

    prices = []
    volumes = []
    for line in minute_data.split(";"):
        parts = line.split(",")
        if len(parts) >= 3:
            try:
                price = float(parts[1])
                vol = float(parts[2])
                prices.append(price)
                volumes.append(vol)
            except (ValueError, IndexError):
                continue

    if not prices:
        return {"avg_price": None, "above_avg": None, "reason": "无法解析分时数据"}

    # 计算成交均价（用简单均价近似）
    total_vol = sum(volumes)
    if total_vol > 0:
        avg_price = sum(p * v for p, v in zip(prices, volumes)) / total_vol
    else:
        avg_price = sum(prices) / len(prices)

    current_price = prices[-1]
    above_avg = all(p >= avg_price * 0.995 for p in prices)

    return {
        "avg_price": round(avg_price, 2),
        "above_avg": above_avg,
        "current_price": current_price,
    }


def get_stock_kline(code, days=30):
    """
    获取个股日K数据
    数据源优先级：腾讯(web.ifzq.gtimg.cn) > 新浪(stock_zh_a_daily)
    返回 DataFrame: 包含日期、开高低收、成交量等
    """
    # 尝试方案1（首选）：腾讯K线接口（最稳定）
    try:
        df = _get_stock_kline_tencent(code, days=days)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.warning(f"腾讯K线获取{code}失败: {e}")

    # 尝试方案2：新浪日K线接口（稳定性好）
    try:
        prefix = _get_market_prefix(code)
        symbol = f"{prefix}{code}"
        df = _retry(lambda s=symbol: ak.stock_zh_a_daily(symbol=s, adjust="qfq"))
        if df is not None and not df.empty:
            df = df.sort_values("date", ascending=False).head(days)
            return df
    except Exception as e:
        logger.warning(f"新浪K线获取{code}失败: {e}")

    logger.error(f"获取{code}日K数据失败: 所有接口不可用")
    return pd.DataFrame()


def _get_stock_kline_tencent(code, days=30):
    """通过腾讯接口获取个股日K数据（前复权）"""
    # 确定市场前缀
    prefix = _get_market_prefix(code)
    full_code = f"{prefix}{code}"

    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full_code},day,,,{days},qfq"

    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        return pd.DataFrame()

    data = json.loads(resp.content)
    stk = data.get("data", {}).get(full_code, {})
    if not stk:
        return pd.DataFrame()

    # 个股返回qfqday，指数返回day
    key = "qfqday" if "qfqday" in stk else "day"
    klines = stk.get(key, [])
    if not klines:
        return pd.DataFrame()

    df = pd.DataFrame(klines, columns=["date", "open", "close", "high", "low", "volume"])
    for col in ["open", "close", "high", "low", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 按日期降序排列
    df = df.sort_values("date", ascending=False).head(days)
    return df


def _get_market_prefix(code):
    """根据股票代码判断市场前缀（sh/sz/bj）"""
    code = str(code)
    if code.startswith("6") or code.startswith("9"):
        return "sh"  # 沪市主板/科创板
    elif code.startswith("0") or code.startswith("3"):
        return "sz"  # 深市主板/创业板
    elif code.startswith("8") or code.startswith("4"):
        return "bj"  # 北交所
    else:
        return "sz"  # 默认深市


def get_stock_info(code):
    """
    获取个股基本信息
    数据源优先级：腾讯接口 > 新浪行情接口
    返回 dict
    """
    # 尝试方案1（首选）：腾讯接口
    try:
        info = _get_stock_info_tencent(code)
        if info:
            return info
    except Exception as e:
        logger.warning(f"腾讯获取{code}基本信息失败: {e}")

    # 尝试方案2：新浪行情接口补充名称
    try:
        df = _retry(lambda: ak.stock_zh_a_spot())
        if df is not None and not df.empty and "代码" in df.columns:
            match = df[df["代码"].astype(str) == str(code)]
            if not match.empty:
                info = {}
                name_col = "名称" if "名称" in match.columns else None
                if name_col:
                    info["股票简称"] = match.iloc[0][name_col]
                return info
    except Exception as e:
        logger.warning(f"新浪获取{code}基本信息失败: {e}")

    return {}


def _get_stock_info_tencent(code):
    """通过腾讯相关接口获取股票基本信息（上市时间等）"""
    info = {}

    # 从交易所代码列表获取上市时间
    prefix = _get_market_prefix(code)
    try:
        if prefix == "sh":
            df = ak.stock_info_sh_name_code(symbol="主板A股")
            if df is not None and not df.empty:
                row = df[df["证券代码"] == code]
                if not row.empty:
                    info["上市时间"] = str(row.iloc[0].get("上市日期", ""))
                    info["股票简称"] = row.iloc[0].get("证券简称", "")
        elif prefix == "sz":
            df = ak.stock_info_sz_name_code()
            if df is not None and not df.empty:
                # 深市代码可能是数字格式
                match = df[df["A股代码"].astype(str) == code]
                if match.empty:
                    match = df[df["公司代码"].astype(str) == code]
                if not match.empty:
                    info["上市时间"] = str(match.iloc[0].get("A股上市日期", ""))
                    info["股票简称"] = match.iloc[0].get("公司简称", "")
    except Exception:
        pass

    # 用腾讯实时行情补充名称
    if "股票简称" not in info:
        try:
            url = f"http://qt.gtimg.cn/q={prefix}{code}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and "~" in resp.text:
                fields = resp.text.split("~")
                if len(fields) > 2:
                    info["股票简称"] = fields[1]
        except Exception:
            pass

    return info
