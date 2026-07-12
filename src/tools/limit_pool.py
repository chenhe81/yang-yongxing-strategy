"""
涨停板/跌停板/炸板板池 — 基于 a-stock-data V3.4.0 的东财 push2ex 接口

功能:
  - em_zt_pool(date)  → 今日涨停池（含连板数、封板资金、炸板次数）
  - em_dt_pool(date)  → 今日跌停池（含封单资金、连续跌停）
  - em_zb_pool(date)  → 今日炸板池（涨停后开板）
  - em_yzt_pool(date) → 昨日涨停今日表现

数据源: 东财 push2ex (内置 em_get 限流，≥1s间隔+随机抖动)
"""
import hashlib
import random
import time
from datetime import datetime

_requests_ok = False
try:
    import requests
    from requests.adapters import HTTPAdapter
    _requests_ok = True
except ImportError:
    pass

# ── 常量 ──
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"

# ── 东财防封：全局节流 + 会话复用 ──
_EM_SESSION = None
_EM_MIN_INTERVAL = 1.0       # 两次东财请求最小间隔(秒)
_EM_LAST_CALL = [0.0]        # 模块级上次请求时间戳（list 绕闭包）

def _ensure_session():
    """懒初始化 requests session + 自动重试适配器"""
    global _EM_SESSION
    if _EM_SESSION is not None:
        return
    if not _requests_ok:
        return
    _EM_SESSION = requests.Session()
    _EM_SESSION.headers.update({"User-Agent": UA})
    try:
        from urllib3.util.retry import Retry
        adapter = HTTPAdapter(max_retries=Retry(
            total=2, connect=2, backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]))
        _EM_SESSION.mount("https://", adapter)
        _EM_SESSION.mount("http://", adapter)
    except Exception:
        pass  # 老版本降级

def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA"""
    _ensure_session()
    wait = _EM_MIN_INTERVAL - (time.time() - _EM_LAST_CALL[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.3))
    try:
        if _EM_SESSION is not None:
            return _EM_SESSION.get(url, params=params, headers=headers,
                                    timeout=timeout, **kwargs)
        # fallback: 裸 requests（无 session 复用、无重试）
        return requests.get(url, params=params, headers=headers or {"User-Agent": UA},
                             timeout=timeout, **kwargs)
    finally:
        _EM_LAST_CALL[0] = time.time()

# ── 涨停板函数 ──

def _fmt_zt_time(t) -> str:
    """涨停板时间整数 → HH:MM:SS（92500 → 09:25:00）"""
    s = str(int(t)).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"

def _em_zt_api(endpoint: str, sort: str, date: str) -> list[dict]:
    """东财涨停板行情中心通用请求（push2ex，走 em_get 限流）。
    endpoint: getTopicZTPool / getTopicZBPool / getTopicDTPool / getYesterdayZTPool
    返回 data.pool 原始列表（data 为 null = 非交易日/参数错）"""
    if not _requests_ok:
        return []
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception:
        return []

def em_zt_pool(date: str) -> list[dict]:
    """涨停池。date=YYYYMMDD（交易日）。
    返回每只: code/name/price/pct/amount/float_cap/turnover/limit_days(连板数)/
    first_seal/last_seal(封板时间)/seal_fund(封板资金,元)/break_times(炸板次数)/
    industry/zt_stat(N天M板)"""
    out = []
    for p in _em_zt_api("getTopicZTPool", "fbt:asc", date):
        try:
            out.append({
                "code": p["c"], "name": p["n"],
                "price": p["p"] / 1000,
                "pct": round(p["zdp"], 2),
                "amount": p.get("amount", 0),
                "float_cap": p.get("ltsz", 0),
                "turnover": round(p.get("hs", 0), 2),
                "limit_days": p.get("lbc", 0),
                "first_seal": _fmt_zt_time(p["fbt"]),
                "last_seal": _fmt_zt_time(p.get("lbt", 0)),
                "seal_fund": p.get("fund", 0),
                "break_times": p.get("zbc", 0),
                "industry": p.get("hybk", ""),
                "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out

def em_zb_pool(date: str) -> list[dict]:
    """炸板池（涨停后开板）"""
    out = []
    for p in _em_zt_api("getTopicZBPool", "fbt:asc", date):
        try:
            out.append({
                "code": p["c"], "name": p["n"],
                "price": p["p"] / 1000,
                "limit_price": p["ztp"] / 1000,
                "pct": round(p["zdp"], 2),
                "turnover": round(p.get("hs", 0), 2),
                "first_seal": _fmt_zt_time(p["fbt"]),
                "break_times": p.get("zbc", 0),
                "amplitude": round(p.get("zf", 0), 2),
                "speed": round(p.get("zs", 0), 2),
                "industry": p.get("hybk", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out

def em_dt_pool(date: str) -> list[dict]:
    """跌停池"""
    out = []
    for p in _em_zt_api("getTopicDTPool", "fund:asc", date):
        try:
            out.append({
                "code": p["c"], "name": p["n"],
                "price": p["p"] / 1000,
                "pct": round(p["zdp"], 2),
                "turnover": round(p.get("hs", 0), 2),
                "pe": p.get("pe"),
                "seal_fund": p.get("fund", 0),
                "last_seal": _fmt_zt_time(p.get("lbt", 0)),
                "dt_days": p.get("days", 0),
                "open_times": p.get("oc", 0),
                "industry": p.get("hybk", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out

def em_yzt_pool(date: str) -> list[dict]:
    """昨日涨停池（昨涨停今表现，算晋级率/赚钱效应）"""
    out = []
    for p in _em_zt_api("getYesterdayZTPool", "zs:desc", date):
        try:
            out.append({
                "code": p["c"], "name": p["n"],
                "price": p["p"] / 1000,
                "pct": round(p["zdp"], 2),
                "turnover": round(p.get("hs", 0), 2),
                "amplitude": round(p.get("zf", 0), 2),
                "speed": round(p.get("zs", 0), 2),
                "y_first_seal": _fmt_zt_time(p.get("yfbt", 0)),
                "y_limit_days": p.get("ylbc", 0),
                "industry": p.get("hybk", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


def check_imports_ok() -> bool:
    """检查是否可导入 requests（非强制性，部分模块降级运行）"""
    return _requests_ok


if __name__ == "__main__":
    # 测试
    test_date = datetime.now().strftime("%Y%m%d")
    print(f"测试日期: {test_date}")
    zt = em_zt_pool(test_date)
    print(f"今日涨停 {len(zt)} 只")
    for s in zt[:5]:
        print(f"  {s['name']}({s['code']}) {s['zt_stat']} 封板{s['seal_fund']/1e8:.2f}亿 {s['industry']}")
    dt = em_dt_pool(test_date)
    print(f"今日跌停 {len(dt)} 只")
