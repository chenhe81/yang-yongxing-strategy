#!/usr/bin/env python3
"""
GARCH波动率分析 Worker — 部署在算力中心 (183.131.24.109)

功能：
  1. 用 akshare 拉取上证指数日线（1990~至今）
  2. 拟合 GARCH(1,1) 波动率模型
  3. 输出当前波动率评分 (0-25) 和年度化波动率

输出：
  /home/arcvideo/garch_analysis/output/latest.json
  /home/arcvideo/garch_analysis/output/YYYYMMDD_HHMMSS.json

依赖：
  pip install akshare arch numpy pandas

运行：
  python3 garch_worker.py
  python3 garch_worker.py --output /path
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

DEFAULT_OUTPUT_DIR = "/home/arcvideo/garch_analysis/output"


class GARCHVolatility:
    """GARCH(1,1)波动率预测（与凤雏 src/tools/risk_models.py 逻辑一致）"""

    def __init__(self, p=1, q=1):
        from arch import arch_model
        self.p, self.q = p, q
        self.results = None
        self._fitted = False
        self._arch_model = arch_model

    def fit(self, returns: np.ndarray) -> "GARCHVolatility":
        clean = returns[~np.isnan(returns)]
        if len(clean) < 60:
            return self
        try:
            am = self._arch_model(clean * 100, vol="Garch", p=self.p, q=self.q,
                                  dist="normal", mean="Zero")
            self.results = am.fit(disp="off", update_freq=0)
            self._fitted = True
        except Exception:
            self._fitted = False
        return self

    def predict(self, n_steps=5) -> float:
        """预测年化波动率(%)"""
        if not self._fitted or self.results is None:
            return 0.0
        try:
            forecast = self.results.forecast(horizon=n_steps)
            variance = forecast.variance.iloc[-1, 0]
            daily_vol = np.sqrt(variance) / 100
            annual_vol = daily_vol * np.sqrt(252) * 100
            return round(float(annual_vol), 2)
        except Exception:
            return 0.0

    def score_volatility(self, returns: np.ndarray) -> tuple:
        """返回 (0-25得分, 标签)，对齐雷达波动率维度"""
        self.fit(returns)
        pv = self.predict(n_steps=5)
        if pv <= 0:
            return 12, "GARCH无数据"
        if pv < 15:
            s = min(25, 22 + int((15 - pv) / 15 * 3))
            lbl = f"GARCH低波({pv:.1f}%)"
        elif pv < 25:
            s = 12 + int((25 - pv) / 10 * 9)
            lbl = f"GARCH中波({pv:.1f}%)"
        else:
            s = max(0, 12 - int((pv - 25) / 20 * 10))
            lbl = f"GARCH高波({pv:.1f}%)"
        return min(25, max(0, s)), lbl


def fetch_index_data() -> dict:
    """拉取上证指数日线"""
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sh000001")
    if df.empty:
        raise ValueError("上证指数数据为空")
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  📊 上证指数日线: {df['date'].min().date()} ~ {df['date'].max().date()}, {len(df)} 行")
    return df


def main():
    parser = argparse.ArgumentParser(description="GARCH波动率分析 Worker")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-save-history", action="store_true")
    args = parser.parse_args()

    print("=" * 50, flush=True)
    print("  GARCH 波动率分析启动", flush=True)
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 50, flush=True)

    # 1. 拉取数据
    print("  [1/3] 拉取上证指数日线...", flush=True)
    df = fetch_index_data()
    close = df["close"].values
    rets = pd.Series(close).pct_change().dropna().values

    # 2. GARCH 拟合
    print("  [2/3] GARCH(1,1) 拟合 + 预测...", flush=True)
    garch = GARCHVolatility()
    garch_score, garch_label = garch.score_volatility(rets)
    pred_vol = garch.predict(n_steps=5)

    print(f"  → 年化波动率: {pred_vol:.2f}%", flush=True)
    print(f"  → GARCH 雷达分: {garch_score}/25", flush=True)
    print(f"  → 标签: {garch_label}", flush=True)

    # 额外：近期波动统计
    recent_vol = float(rets[-60:].std() * np.sqrt(252) * 100) if len(rets) >= 60 else 0
    full_vol = float(rets.std() * np.sqrt(252) * 100)

    now = datetime.now()
    result = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": "000001.SH",
        "symbol_name": "上证指数",
        "garch_score": garch_score,              # 0-25 雷达分
        "garch_label": garch_label,
        "pred_annual_vol_pct": pred_vol,         # 年化波动率 %
        "recent_60d_vol_pct": round(recent_vol, 2),
        "full_history_vol_pct": round(full_vol, 2),
        "index_close": round(float(close[-1]), 2),
        "n_samples": int(len(rets)),
    }

    # 3. 保存
    print("  [3/3] 保存输出...", flush=True)
    os.makedirs(args.output, exist_ok=True)

    latest_path = os.path.join(args.output, "latest.json")
    with open(latest_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  ✅ latest.json → {latest_path}")

    if not args.no_save_history:
        ts = now.strftime("%Y%m%d_%H%M%S")
        history_path = os.path.join(args.output, f"{ts}.json")
        with open(history_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 历史归档 → {history_path}")

    print("=" * 50, flush=True)
    print("  GARCH 分析完成", flush=True)
    print("=" * 50, flush=True)


if __name__ == "__main__":
    main()
