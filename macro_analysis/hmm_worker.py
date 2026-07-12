#!/usr/bin/env python3
"""
HMM市场状态分析 Worker — 部署在算力中心 (183.131.24.109)

功能：
  1. 用 akshare 拉取上证指数日线（1990~至今）
  2. 拟合 HMM（3状态：下跌/震荡/上涨）
  3. 预测当前市场状态，输出 JSON

输出：
  /home/arcvideo/hmm_analysis/output/latest.json  （最新，供凤雏 SSH 读取）
  /home/arcvideo/hmm_analysis/output/YYYYMMDD_HHMMSS.json  （历史归档）

依赖：
  pip install akshare hmmlearn numpy pandas

运行方式：
  python3 hmm_worker.py                    # 普通运行
  python3 hmm_worker.py --output /path     # 指定输出目录
  python3 hmm_worker.py --no-save-history  # 不保存历史版本
"""
import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ── 路径 ──
DEFAULT_OUTPUT_DIR = "/home/arcvideo/hmm_analysis/output"


class HMMRegimeDetector:
    """隐马尔可夫市场状态检测器（与凤雏 src/tools/hmm_regime.py 逻辑一致）"""

    def __init__(self, n_states=3, n_iter=100, random_state=42):
        from hmmlearn import hmm
        self.n_states = n_states
        self.model = hmm.GaussianHMM(
            n_components=n_states, covariance_type="diag",
            n_iter=n_iter, random_state=random_state, tol=1e-4
        )
        self._fitted = False
        self._state_map = {}

    def fit(self, returns: np.ndarray) -> "HMMRegimeDetector":
        if returns.ndim == 1:
            X = returns.reshape(-1, 1)
        else:
            X = returns
        X = X[~np.isnan(X).any(axis=1)]
        if len(X) < 50:
            return self
        self.model.fit(X)
        self._fitted = True
        means = self.model.means_.flatten()
        sorted_idx = np.argsort(means)
        self._state_map = {sorted_idx[0]: 0, sorted_idx[1]: 1, sorted_idx[2]: 2}
        return self

    def predict(self, returns: np.ndarray) -> tuple:
        """返回 (state, probs)  state: 0=下跌, 1=震荡, 2=上涨"""
        if not self._fitted:
            return 1, np.array([0.0, 1.0, 0.0])
        if returns.ndim == 1:
            X = returns.reshape(-1, 1)
        else:
            X = returns
        states = self.model.predict(X)
        probs = self.model.predict_proba(X)
        latest_state = self._state_map.get(states[-1], 1)
        return latest_state, probs[-1]

    def score_regime(self, returns: np.ndarray) -> int:
        """返回0-40的得分（对齐雷达趋势维度满分40分）"""
        state, probs = self.predict(returns)
        confidence = float(probs.max())
        if state == 2:
            return min(40, 30 + int(confidence * 10))
        elif state == 1:
            return 15 + int(confidence * 10)
        else:
            return max(0, 10 - int((1 - confidence) * 10))


def fetch_index_data() -> pd.DataFrame:
    """用 akshare 拉取上证指数日线"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df.empty:
            raise ValueError("上证指数数据为空")
        df = df.rename(columns={"date": "date", "close": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        print(f"  📊 上证指数日线: {df['date'].min().date()} ~ {df['date'].max().date()}, {len(df)} 行")
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        print(f"  ❌ 数据拉取失败: {e}", flush=True)
        raise


def analyze_hmm(df: pd.DataFrame) -> dict:
    """对指数日线做 HMM 分析，返回完整结果"""
    close = df["close"].values
    rets = pd.Series(close).pct_change().dropna().values.reshape(-1, 1)

    # 全量拟合
    detector = HMMRegimeDetector(n_states=3)
    detector.fit(rets)

    # 当前状态（最近60天）
    recent_rets = rets[-60:] if len(rets) >= 60 else rets
    state, probs = detector.predict(recent_rets)

    # 各状态均值（辅助判断市场特征）
    means = detector.model.means_.flatten().tolist()

    # 历史状态分布
    all_states = detector.model.predict(rets)
    state_labels = {0: "下跌", 1: "震荡", 2: "上涨"}
    state_counts = {int(k): int((all_states == k).sum()) for k in range(detector.n_states)}

    # 未来1日收益预测（当前状态转移分布）
    transition = detector.model.transmat_.tolist()

    hmm_score = detector.score_regime(recent_rets)

    now = datetime.now()
    result = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": "000001.SH",
        "symbol_name": "上证指数",
        "n_states": 3,
        "n_samples": int(len(rets)),
        "current_state": int(state),
        "current_state_label": state_labels.get(state, "未知"),
        "confidence": round(float(probs.max()), 4),
        "state_probs": [round(float(p), 4) for p in probs],
        "hmm_score": hmm_score,              # 0-40 雷达分
        "state_means": [round(m, 6) for m in means],
        "state_distribution": state_counts,
        "transition_matrix": transition,
        "index_close": round(float(close[-1]), 2),
        "index_pct_change": round(float(pd.Series(close).pct_change().iloc[-1]) * 100, 2) if len(close) > 1 else 0,
    }
    return result


def save_output(result: dict, output_dir: str, save_history: bool = True):
    """保存 HMM 分析结果"""
    os.makedirs(output_dir, exist_ok=True)

    # latest.json（凤雏 SSH 读取用）
    latest_path = os.path.join(output_dir, "latest.json")
    with open(latest_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  ✅ latest.json → {latest_path}")

    # 历史归档
    if save_history:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        history_path = os.path.join(output_dir, f"{ts}.json")
        with open(history_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  ✅ 历史归档 → {history_path}")


def main():
    parser = argparse.ArgumentParser(description="HMM市场状态分析 Worker")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR, help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--no-save-history", action="store_true", help="不保存历史版本")
    args = parser.parse_args()

    print("=" * 50, flush=True)
    print("  HMM 市场状态分析启动", flush=True)
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 50, flush=True)

    # 1. 拉取数据
    print("  [1/3] 拉取上证指数日线...", flush=True)
    df = fetch_index_data()

    # 2. HMM 分析
    print("  [2/3] HMM 拟合 + 预测...", flush=True)
    result = analyze_hmm(df)
    print(f"  → 市场状态: {result['current_state_label']}", flush=True)
    print(f"  → 置信度: {result['confidence']:.2%}", flush=True)
    print(f"  → HMM 雷达分: {result['hmm_score']}/40", flush=True)
    print(f"  → 指数: {result['index_close']} ({result['index_pct_change']:+.2f}%)", flush=True)

    # 3. 保存
    print("  [3/3] 保存输出...", flush=True)
    save_output(result, args.output, save_history=not args.no_save_history)

    print("=" * 50, flush=True)
    print("  HMM 分析完成", flush=True)
    print("=" * 50, flush=True)


if __name__ == "__main__":
    main()
