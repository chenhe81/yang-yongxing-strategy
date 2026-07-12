"""
神经网络信号检测器（公式10：高维神经网络）

注意: 当前为框架预留，需GPU训练数据后加载模型使用

已迁移至算力中心 (183.131.24.109):
  macro_analysis/neural_worker.py (GPU MLP 训练)
  交易日 09:10 cron 自动运行
  输出: /home/arcvideo/neural_analysis/output/latest.json
本地 (凤雏): 通过 _fetch_neural_status() SSH 读取

旧版 detect() 始终返回 0，仅为向后兼容保留。
"""
import numpy as np
import subprocess
import json
from datetime import datetime


_NEURAL_CACHE = None
_NEURAL_CACHE_DATE = None
_NEURAL_TRIED_TODAY = False


def fetch_remote_neural_status(use_cache: bool = True) -> dict | None:
    """SSH 读取算力中心神经网络信号分析结果

    返回: {
        "neural_score": int,          # 0-40 雷达分
        "neural_score_label": str,    # 看涨/看跌/中性
        "signal": int,                # 1=看涨 -1=看跌 0=中性
        "up_probability": float,      # 上涨概率
        "confidence": float,          # 置信度
        "validation_accuracy": float, # 验证准确率
        "date": str,
    }
    """
    global _NEURAL_CACHE, _NEURAL_CACHE_DATE, _NEURAL_TRIED_TODAY
    today = datetime.now().strftime("%Y-%m-%d")
    if use_cache:
        if _NEURAL_CACHE_DATE == today:
            if _NEURAL_CACHE is not None:
                return _NEURAL_CACHE
            if _NEURAL_TRIED_TODAY:
                return None
        else:
            _NEURAL_TRIED_TODAY = False
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", "-p", "3100",
             "arcvideo@183.131.24.109",
             "cat /home/arcvideo/neural_analysis/output/latest.json"],
            capture_output=True, text=True, timeout=10
        )
        if use_cache:
            _NEURAL_TRIED_TODAY = True
        if result.returncode != 0 or not result.stdout.strip():
            return None
        data = json.loads(result.stdout)
        if data.get("date") != today:
            return None
        if use_cache:
            _NEURAL_CACHE = data
            _NEURAL_CACHE_DATE = today
        return data
    except Exception as e:
        if use_cache:
            _NEURAL_TRIED_TODAY = True
        print(f"  ⚠️ 读取神经网络信号失败: {e}", flush=True)
        return None


class NeuralSignalDetector:
    """神经网络信号检测器（框架预留）"""

    def __init__(self, model_path=None):
        self.model_path = model_path
        self._loaded = False

    def load_model(self, path):
        self.model_path = path
        self._loaded = False
        return False

    def detect(self, df):
        """返回: 0=无信号, 1=买入, -1=卖出"""
        if not self._loaded:
            return 0
        return 0

    def extract_market_features(self, df):
        features = []
        if df is not None and len(df) >= 20:
            closes = df["close"].values
            volumes = df["volume"].values
            rets = np.diff(closes) / closes[:-1]
            features = [
                float(np.mean(rets[-5:])),
                float(np.std(rets[-20:])),
                float(closes[-1] / np.mean(closes[-20:]) - 1),
                float(volumes[-1] / np.mean(volumes[-20:]) - 1),
            ]
        return np.array(features, dtype=np.float32)


if __name__ == "__main__":
    d = NeuralSignalDetector()
    print(f"神经网络: loaded={d._loaded}, signal={d.detect(None)}")
    print("提示: 需GPU训练数据后加载模型启用")
