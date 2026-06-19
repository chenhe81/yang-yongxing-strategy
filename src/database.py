"""
本地 SQLite 数据缓存层

设计思路：
  - 收盘后一次性构建日线缓存，之后所有查询走本地
  - 实时快照按需拉取，缓存 5 分钟内复用
  - 减少对上游 API（东方财富 push2）的依赖频率
"""
import sqlite3
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict

import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "market_cache.db")


class MarketDB:
    """本地市场数据库 — SQLite 缓存"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, *args):
        self.close()

    def init_db(self):
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_klines (
                code TEXT NOT NULL, date TEXT NOT NULL,
                open REAL, close REAL, high REAL, low REAL,
                volume REAL, amount REAL,
                amplitude REAL, pct_change REAL, change REAL, turnover REAL,
                PRIMARY KEY (code, date)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_kline_date ON daily_klines(date);
            CREATE INDEX IF NOT EXISTS idx_daily_kline_code_date
                ON daily_klines(code, date);
            CREATE TABLE IF NOT EXISTS stock_list (
                code TEXT PRIMARY KEY, name TEXT
            );
            CREATE TABLE IF NOT EXISTS sector_ranks (
                sector_name TEXT NOT NULL, date TEXT NOT NULL,
                rank INTEGER DEFAULT 0,
                PRIMARY KEY (sector_name, date)
            );
            CREATE TABLE IF NOT EXISTS stock_sector_map (
                code TEXT PRIMARY KEY, sector_name TEXT
            );
            CREATE TABLE IF NOT EXISTS market_snapshot (
                code TEXT PRIMARY KEY, name TEXT,
                price REAL, pct_change REAL,
                volume REAL, amount REAL,
                turnover REAL, volume_ratio REAL,
                float_mv REAL, total_mv REAL,
                high REAL, low REAL,
                snapshot_date TEXT, snapshot_time TEXT
            );
        """)
        conn.commit()

    def save_klines(self, code: str, df: pd.DataFrame):
        if df.empty:
            return
        conn = self._connect()
        rows = []
        for _, r in df.iterrows():
            d = r["date"]
            ds = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
            rows.append((
                code, ds,
                float(r.get("open", 0)), float(r.get("close", 0)),
                float(r.get("high", 0)), float(r.get("low", 0)),
                float(r.get("volume", 0)), float(r.get("amount", 0)),
                float(r.get("amplitude", 0)), float(r.get("pct_change", 0)),
                float(r.get("change", 0)), float(r.get("turnover", 0)),
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO daily_klines
            (code, date, open, close, high, low, volume, amount,
             amplitude, pct_change, change, turnover)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()

    def get_klines(self, code: str, days: int = 60) -> pd.DataFrame:
        conn = self._connect()
        cur = conn.execute("""
            SELECT date, open, close, high, low, volume, amount,
                   amplitude, pct_change, change, turnover
            FROM daily_klines WHERE code = ?
            ORDER BY date DESC LIMIT ?
        """, (code, days + 5))
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        records = [{k: r[k] for k in r.keys()} for r in rows]
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        return df

    def has_klines(self, code: str, min_days: int = 30) -> bool:
        conn = self._connect()
        cur = conn.execute(
            "SELECT COUNT(*) FROM daily_klines WHERE code = ?", (code,))
        return cur.fetchone()[0] >= min_days

    def save_stock_list(self, df: pd.DataFrame):
        if df.empty:
            return
        conn = self._connect()
        rows = [(r["code"], r.get("name", "")) for _, r in df.iterrows()]
        conn.executemany(
            "INSERT OR REPLACE INTO stock_list (code, name) VALUES (?, ?)", rows)
        conn.commit()

    def get_stock_list(self) -> pd.DataFrame:
        conn = self._connect()
        cur = conn.execute("SELECT code, name FROM stock_list")
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def save_sector_ranks(self, ranks: dict, date: str):
        conn = self._connect()
        rows = [(name, date, rank) for name, rank in ranks.items()]
        conn.executemany(
            "INSERT OR REPLACE INTO sector_ranks VALUES (?, ?, ?)", rows)
        conn.commit()

    def get_sector_ranks(self, date: str) -> Dict[str, int]:
        conn = self._connect()
        cur = conn.execute(
            "SELECT sector_name, rank FROM sector_ranks WHERE date = ?", (date,))
        return {r["sector_name"]: r["rank"] for r in cur.fetchall()}

    def save_sector_map(self, sector_map: dict):
        if not sector_map:
            return
        conn = self._connect()
        rows = list(sector_map.items())
        conn.executemany(
            "INSERT OR REPLACE INTO stock_sector_map VALUES (?, ?)", rows)
        conn.commit()

    def get_sector_map(self) -> Dict[str, str]:
        conn = self._connect()
        cur = conn.execute("SELECT code, sector_name FROM stock_sector_map")
        return {r["code"]: r["sector_name"] for r in cur.fetchall()}

    def save_snapshot(self, df: pd.DataFrame, snapshot_date: str):
        if df.empty:
            return
        conn = self._connect()
        now = datetime.now().strftime("%H:%M")
        rows = []
        for _, r in df.iterrows():
            rows.append((
                r.get("code", ""), r.get("name", ""),
                float(r.get("price", 0)), float(r.get("pct_change", 0)),
                float(r.get("volume", 0)), float(r.get("amount", 0)),
                float(r.get("turnover", 0)), float(r.get("volume_ratio", 0)),
                float(r.get("float_mv", 0)), float(r.get("total_mv", 0)),
                float(r.get("high", 0)), float(r.get("low", 0)),
                snapshot_date, now,
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO market_snapshot
            (code, name, price, pct_change, volume, amount,
             turnover, volume_ratio, float_mv, total_mv,
             high, low, snapshot_date, snapshot_time)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()

    def get_snapshot(self, date: str) -> pd.DataFrame:
        conn = self._connect()
        cur = conn.execute(
            "SELECT * FROM market_snapshot WHERE snapshot_date = ?", (date,))
        rows = cur.fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def snapshot_exists(self, date: str) -> bool:
        conn = self._connect()
        cur = conn.execute(
            "SELECT COUNT(*) FROM market_snapshot WHERE snapshot_date = ?", (date,))
        return cur.fetchone()[0] > 0

    def stats(self) -> dict:
        conn = self._connect()
        sc = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_list").fetchone()[0]
        kc = conn.execute("SELECT COUNT(*) FROM daily_klines").fetchone()[0]
        ks = conn.execute("SELECT COUNT(DISTINCT code) FROM daily_klines").fetchone()[0]
        cr = conn.execute("SELECT MIN(date), MAX(date) FROM daily_klines").fetchone()
        dr = f"{cr[0]} ~ {cr[1]}" if cr[0] else "无"
        return {"股票": sc, "日线记录": kc, "有日线股票": ks, "数据范围": dr}


_db: Optional[MarketDB] = None


def get_db() -> MarketDB:
    global _db
    if _db is None:
        _db = MarketDB()
        _db.init_db()
    return _db


def build_daily_cache(date: str = None, max_workers: int = 10) -> dict:
    """全市场日线缓存构建（收盘后运行）"""
    from src.data_fetcher import fetch_stock_list, fetch_stock_history
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    db = get_db()
    stock_df = fetch_stock_list()
    if stock_df.empty:
        return {"error": "无法获取股票列表"}

    codes = stock_df["code"].tolist()
    total = len(codes)
    logger.info(f"开始构建日线缓存: {total} 只股票")

    cached = 0
    fetched = 0
    errors = 0

    need_fetch = []
    for code in codes:
        if db.has_klines(code, min_days=30):
            cached += 1
        else:
            need_fetch.append(code)

    logger.info(f"已缓存: {cached}, 需拉取: {len(need_fetch)}")

    def _worker(code):
        try:
            df = fetch_stock_history(code, days=260)
            if not df.empty:
                db.save_klines(code, df)
                return True
        except Exception:
            pass
        return False

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for f in as_completed([pool.submit(_worker, c) for c in need_fetch]):
            done += 1
            if f.result():
                fetched += 1
            else:
                errors += 1
            if done % 100 == 0:
                logger.info(f"  进度: {done}/{len(need_fetch)} | "
                            f"成功:{fetched} 失败:{errors}")

    logger.info(f"缓存构建完成: 成功{fetched}, 失败{errors}, 已有{cached}")
    return {"cached": cached, "fetched": fetched, "errors": errors, "total": total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s")
    r = build_daily_cache(max_workers=10)
    print("结果:", r)
    print("统计:", get_db().stats())
