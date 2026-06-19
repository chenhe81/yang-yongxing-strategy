"""国资股票池 — 筛选国资控股、上市>3年、排除ST/科创板/创业板/北交所

数据源：
  1. 巨潮资讯-实际控制人信息（akshare.stock_hold_control_cninfo）
  2. 本地 SQLite 日线缓存（有数据即视为可交易）
  3. 兜底方案：仅用排除列表过滤全市场

用法：
  python3 -m src.stock_pool                    # 重新拉取生成
  python3 -m src.stock_pool --skip-fetch       # 仅用本地缓存生成
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

from src.database import get_db

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_POOL_PATH = os.path.join(BASE_DIR, "data", "stock_pool.json")

# 国资关键词（用于匹配实际控制人名称）
STATE_OWNED_KEYWORDS = [
    "国务院", "国资委", "国有", "国有资产", "国家", "中央",
    "中科院", "财政部", "人民政府", "教育部", "工信部", "交通部",
    "国投", "国网", "国电", "国铁", "中车", "中粮", "中化", "中船",
    "中石油", "中石化", "中海油", "中核", "中航", "中兵", "中电",
    "省", "市", "自治", "县", "区",
]

# 永久排除的代码前缀
EXCLUDE_PREFIXES = ("8", "4", "688", "689", "300", "301")

# ST 后缀
EXCLUDE_SUFFIXES = ("ST", "退")


def _is_excluded(code: str) -> bool:
    """检查股票代码是否属于排除范围"""
    c = str(code).zfill(6)
    return any(c.startswith(p) for p in EXCLUDE_PREFIXES)


def fetch_state_owned_stocks(max_retries: int = 3) -> Optional[pd.DataFrame]:
    """从巨潮资讯拉取全市场实际控制人信息，返回国资控股股票"""
    import akshare as ak

    for i in range(max_retries):
        try:
            df = ak.stock_hold_control_cninfo(symbol="全部")
            if df is None or df.empty:
                logger.warning(f"第{i+1}次尝试返回空数据")
                time.sleep(2)
                continue

            logger.info(f"获取实际控制人数据: {len(df)} 条")

            # 过滤国资控股
            mask = df["实际控制人名称"].apply(
                lambda x: any(kw in str(x) for kw in STATE_OWNED_KEYWORDS)
                if pd.notna(x) else False
            )
            state_df = df[mask].copy()
            logger.info(f"国资控股: {len(state_df)} 只")
            return state_df

        except Exception as e:
            logger.warning(f"第{i+1}次尝试失败: {e}")
            if i < max_retries - 1:
                time.sleep(3)

    logger.error("获取实际控制人数据全部失败")
    return None


def build_stock_pool() -> List[Dict[str, str]]:
    """构建国资股票池"""
    db = get_db()
    conn = db._connect()

    # 获取有日线数据的股票（即可交易股票）
    cur = conn.execute("SELECT code, name FROM stock_list")
    stock_map = {r[0].zfill(6): r[1] for r in cur.fetchall()}
    logger.info(f"股票列表: {len(stock_map)} 只")

    # 尝试从巨潮获取国资数据
    state_df = fetch_state_owned_stocks()

    if state_df is not None and not state_df.empty:
        # 从国资数据中提取代码
        codes = set()
        for c in state_df["证券代码"].dropna().unique():
            c_str = str(int(c)).zfill(6)
            codes.add(c_str)
        logger.info(f"国资候选: {len(codes)} 只")
    else:
        # 兜底：使用全市场股票，仅排除创业板/科创板/北交所/ST
        logger.warning("巨潮数据不可用，使用全市场排除列表兜底")
        codes = set(stock_map.keys())

    # 逐只过滤
    pool = []
    for code in sorted(codes):
        # 排除科创板/创业板/北交所
        if _is_excluded(code):
            continue
        # 必须在本地有数据
        if code not in stock_map:
            continue
        # 排除ST
        name = stock_map.get(code, "")
        if name and any(s in name for s in EXCLUDE_SUFFIXES):
            continue

        pool.append({"code": code, "name": name.strip()})

    logger.info(f"最终股票池: {len(pool)} 只")
    return pool


def save_stock_pool(pool: List[Dict[str, str]], path: str = None):
    """保存股票池到 JSON"""
    if path is None:
        path = STOCK_POOL_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存到 {path}")


def load_stock_pool(path: str = None) -> List[Dict[str, str]]:
    """加载股票池 JSON"""
    if path is None:
        path = STOCK_POOL_PATH
    if not os.path.exists(path):
        logger.warning(f"股票池文件不存在: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_stock_codes(path: str = None) -> List[str]:
    """获取股票池代码列表（便捷方法）"""
    return [s["code"] for s in load_stock_pool(path)]


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    pool = build_stock_pool()
    save_stock_pool(pool)
    print(f"股票池: {len(pool)} 只")
    for s in pool[:10]:
        print(f"  {s['code']} {s['name']}")
    if len(pool) > 10:
        print(f"  ... 共{len(pool)}只")
