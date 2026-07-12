#!/usr/bin/env python3
"""
从算力中心拉取各模块分析结果到本地缓存

功能:
  1. SCP 拉取 HMM/GARCH/PCA/Neural/Macro 的 latest.json
  2. 保存到 data/computing_analysis/{module}/latest.json
  3. 返回状态摘要

运行方式:
  python3 scripts/pull_computing_results.py          # 拉取全部
  python3 scripts/pull_computing_results.py --quiet  # 静默模式（cron）

依赖:
  - 凤雏 → 算力中心 SSH 免密（key: ~/.ssh/id_bt）
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE, "data", "computing_analysis")

# 算力中心信息
SERVER = "arcvideo@183.131.24.109"
PORT = 3100
SSH_KEY = os.path.expanduser("~/.ssh/id_bt")

# 需要拉取的模块
WORKERS = {
    "hmm": {
        "name": "HMM 市场状态",
        "remote": "/home/arcvideo/hmm_analysis/output/latest.json",
        "timeout": 15,
    },
    "garch": {
        "name": "GARCH 波动率",
        "remote": "/home/arcvideo/garch_analysis/output/latest.json",
        "timeout": 15,
    },
    "pca": {
        "name": "PCA 因子降维",
        "remote": "/home/arcvideo/pca_analysis/output/latest.json",
        "timeout": 15,
    },
    "neural": {
        "name": "神经信号",
        "remote": "/home/arcvideo/neural_analysis/output/latest.json",
        "timeout": 15,
    },
    "macro": {
        "name": "宏观分析",
        "remote": "/home/arcvideo/macro_analysis/output/latest.json",
        "timeout": 15,
    },
}


def pull_module(module_id: str, info: dict, quiet: bool = False) -> dict:
    """拉取单个模块的 latest.json"""
    cache_path = os.path.join(CACHE_DIR, module_id, "latest.json")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    cmd = [
        "scp",
        "-i", SSH_KEY,
        "-P", str(PORT),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{SERVER}:{info['remote']}",
        cache_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=info["timeout"])
        if result.returncode == 0 and os.path.getsize(cache_path) > 0:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            if not quiet:
                print(f"  ✅ {info['name']}: cached → {cache_path}")
            return {"module": module_id, "status": "ok", "data": data, "cached_at": datetime.now().isoformat()}
        else:
            if not quiet:
                print(f"  ⚠️ {info['name']}: 拉取失败 (rc={result.returncode})")
            return {"module": module_id, "status": "fail", "error": result.stderr.strip() or "scp 返回非零"}
    except subprocess.TimeoutExpired:
        if not quiet:
            print(f"  ⚠️ {info['name']}: 超时")
        return {"module": module_id, "status": "timeout", "error": "timeout"}
    except json.JSONDecodeError as e:
        if not quiet:
            print(f"  ⚠️ {info['name']}: JSON 解析失败: {e}")
        return {"module": module_id, "status": "parse_error", "error": str(e)}
    except Exception as e:
        if not quiet:
            print(f"  ⚠️ {info['name']}: {e}")
        return {"module": module_id, "status": "error", "error": str(e)}


def load_cached_results() -> dict:
    """读取本地缓存的所有算力分析结果"""
    results = {}
    for module_id in WORKERS:
        cache_path = os.path.join(CACHE_DIR, module_id, "latest.json")
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            try:
                with open(cache_path, encoding="utf-8") as f:
                    results[module_id] = json.load(f)
            except Exception:
                results[module_id] = None
        else:
            results[module_id] = None
    return results


def format_hmm(data: dict) -> str:
    """格式化 HMM 市场状态"""
    if not data:
        return "暂无数据"
    label = data.get("current_state_label", "?")
    conf = data.get("confidence", 0)
    score = data.get("hmm_score", "?")
    return f"{label}(置信度{conf:.0%}), 分={score}/40"


def format_garch(data: dict) -> str:
    if not data:
        return "暂无数据"
    vol = data.get("pred_annual_vol_pct", "?")
    score = data.get("garch_score", "?")
    return f"年化波动{vol}%, 分={score}/25"


def format_pca(data: dict) -> str:
    if not data:
        return "暂无数据"
    w = data.get("pca_weights_dict", {})
    ev = data.get("first_component_var_ratio", 0)
    parts = [f"{k}={v:.0%}" for k, v in w.items()]
    return f"权重{'/'.join(parts)}, 解释方差{ev:.0%}"


def format_neural(data: dict) -> str:
    if not data:
        return "暂无数据"
    score = data.get("neural_score", "?")
    label = data.get("neural_score_label", "?")
    signal = data.get("signal", "?")
    conf = data.get("confidence", 0)
    return f"{label}(分={score}), 信号={'看多' if signal==1 else '看空' if signal==-1 else '中性'}, 置信度{conf:.0%}"


def format_macro(data: dict) -> str:
    if not data:
        return "暂无数据"
    analysis = data.get("analysis", {})
    risk = analysis.get("risk_level", "?")
    position = analysis.get("position_ratio", "?")
    strategy = analysis.get("recommended_strategy", "?")
    market_state = analysis.get("market_state", "?")
    return f"市场判断:{market_state}, 风险等级:{risk}, 建议策略:{strategy}, 建议仓位:{position}"


def format_all(cached: dict) -> list:
    """生成所有模块的格式化文本行"""
    lines = []
    formatters = {
        "hmm": format_hmm,
        "garch": format_garch,
        "pca": format_pca,
        "neural": format_neural,
        "macro": format_macro,
    }
    names = {
        "hmm": "HMM",
        "garch": "GARCH",
        "pca": "PCA",
        "neural": "神经信号",
        "macro": "宏观分析",
    }
    for mod in ["hmm", "garch", "pca", "neural", "macro"]:
        data = cached.get(mod)
        fmt = formatters[mod](data)
        lines.append(f"{names[mod]}: {fmt}")
    return lines


def main():
    parser = argparse.ArgumentParser(description="拉取算力中心分析结果")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    args = parser.parse_args()

    if not args.quiet:
        print(f"📡 拉取算力中心分析结果 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        print("=" * 50)

    all_ok = True
    results = []
    for mod_id, info in WORKERS.items():
        r = pull_module(mod_id, info, quiet=args.quiet)
        results.append(r)
        if r["status"] != "ok":
            all_ok = False

    if not args.quiet:
        print("=" * 50)
        ok_count = sum(1 for r in results if r["status"] == "ok")
        fail_count = len(results) - ok_count
        print(f"  拉取完成: {ok_count}/{len(results)} 成功", end="")
        if fail_count > 0:
            print(f", {fail_count} 失败", end="")
        print()

        # 显示格式化的结果
        cached = load_cached_results()
        print()
        print("📊 算力分析摘要:")
        for line in format_all(cached):
            print(f"  {line}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
