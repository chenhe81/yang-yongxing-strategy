"""
财联社快讯工具 — 基于 cls.cn v1 API + 本地签名

功能:
  - cls_telegraph() → 实时财经快讯列表

数据源: 财联社直连 (cls.cn)，本地签名无需 API Key
"""
import hashlib
import json
import time
from datetime import datetime
from typing import Optional

_requests_ok = False
try:
    import requests
    _requests_ok = True
except ImportError:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_CLS_LAST_CALL = [0.0]
_CLS_MIN_INTERVAL = 0.5


def cls_telegraph(page_size: int = 50) -> list[dict]:
    """
    财联社电报（全市场实时快讯）。v1 API + 本地签名，零 key。
    返回: [{title, content, time}]  time 已转为 'YYYY-MM-DD HH:MM:SS'
    """
    if not _requests_ok:
        return []

    params = {
        "appName": "CailianpressWeb",
        "os": "web",
        "sv": "7.7.5",
        "last_time": "",
        "refresh_type": "1",
        "rn": str(page_size),
    }
    # 签名：md5(sha1(按 key 字典序拼接的 query 串))，纯本地算、无需 key
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sign = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    url = f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}"
    headers = {"User-Agent": UA, "Referer": "https://www.cls.cn/"}

    # 节流
    wait = _CLS_MIN_INTERVAL - (time.time() - _CLS_LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)
    _CLS_LAST_CALL[0] = time.time()

    try:
        r = requests.get(url, headers=headers, timeout=10)
        d = r.json()
    except Exception:
        return []

    rows = []
    for item in d.get("data", {}).get("roll_data", []) or []:
        ts = item.get("ctime")
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        rows.append({
            "title": item.get("title", "") or item.get("brief", ""),
            "content": item.get("content", "") or item.get("brief", ""),
            "time": t,
        })
    return rows


def check_imports_ok() -> bool:
    return _requests_ok


if __name__ == "__main__":
    news = cls_telegraph(page_size=10)
    print(f"财联社快讯 {len(news)} 条:")
    for n in news[:5]:
        print(f"  {n['time']} | {n['title'][:60]}")
