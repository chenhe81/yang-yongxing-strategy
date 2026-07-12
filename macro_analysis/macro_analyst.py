#!/usr/bin/env python3
"""
宏观分析管道 — 在算力中心 (183.131.24.109) 上运行
收盘后自动拉取宏观数据 → qwen3-coder:30b 分析 → 结构化 JSON 输出
凤雏在开盘前读取结果，融入雷达评分
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).parent
OUTPUT_DIR = BASE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
LATEST_PATH = OUTPUT_DIR / "latest.json"
HISTORY_DIR = OUTPUT_DIR / "history"
HISTORY_DIR.mkdir(exist_ok=True)

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen3-coder:30b"
OLLAMA_TIMEOUT = 120


def fetch_macro_data() -> dict:
    """采集宏观数据 — 每个失败单独捕获，不影响整体"""
    result = {}
    errors = []

    import akshare as ak

    # 1. 市场指数
    try:
        idx = ak.stock_zh_index_daily(symbol="sh000001")
        if not idx.empty:
            last = idx.iloc[-1]
            prev = idx.iloc[-5] if len(idx) >= 5 else idx.iloc[0]
            result["sh_index"] = {
                "close": float(last["close"]),
                "change_pct": round((last["close"] - prev["close"]) / prev["close"] * 100, 2),
                "volume": float(last["volume"]),
            }
        cy = ak.stock_zh_index_daily(symbol="sz399006")
        if not cy.empty:
            cl = cy.iloc[-1]
            result["cy_index"] = {"close": float(cl["close"]), "volume": float(cl["volume"])}
    except Exception as e:
        errors.append(f"指数: {e}")

    # 2. 北向资金
    try:
        north = ak.stock_hsgt_fund_flow_summary_em()
        if not north.empty:
            north_in = north[north["资金方向"] == "北向"].copy()
            if not north_in.empty:
                total = north_in["成交净买额"].sum()
                latest_date = north_in["交易日"].iloc[0]
                result["north_flow"] = {
                    "date": str(latest_date)[:10],
                    "value": round(float(total), 2),
                }
    except Exception as e:
        errors.append(f"北向: {e}")

    # 3. 涨跌家数
    try:
        today = datetime.now().strftime("%Y%m%d")
        zt = ak.stock_zt_pool_em(date=today)
        dt = ak.stock_zt_pool_dtgc_em(date=today)
        result["market_breadth"] = {
            "涨停": len(zt) if not zt.empty else 0,
            "跌停": len(dt) if not dt.empty else 0,
        }
    except Exception as e:
        errors.append(f"涨跌家数: {e}")

    # 4. 板块涨跌榜
    try:
        sectors = ak.stock_board_industry_spot_em()
        if not sectors.empty and "涨跌幅" in sectors.columns:
            top3 = sectors.nlargest(3, "涨跌幅")[["板块名称", "涨跌幅"]].to_dict("records")
            bot3 = sectors.nsmallest(3, "涨跌幅")[["板块名称", "涨跌幅"]].to_dict("records")
            result["sectors"] = {"top3": top3, "bottom3": bot3}
    except Exception as e:
        errors.append(f"板块: {e}")

    result["errors"] = errors
    result["fetch_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return result


def build_prompt(macro: dict) -> str:
    """构建 LLM 分析提示词"""
    idx = macro.get("sh_index", {})
    cy = macro.get("cy_index", {})
    north = macro.get("north_flow", {})
    breadth = macro.get("market_breadth", {})
    sectors = macro.get("sectors", {})

    prompt = f"""你是一个专业的A股市场宏观分析师。请基于以下数据，对当前市场状态进行分析判断。

=== 今日宏观数据 ({macro.get('fetch_time', 'N/A')}) ===

上证指数: {idx.get('close', 'N/A')}  涨跌幅: {idx.get('change_pct', 'N/A')}%
创业板指: {cy.get('close', 'N/A')}
市场成交: 上证量 {idx.get('volume', 'N/A')}
北向资金: {north.get('value', 'N/A')} 亿元
涨跌家数: 涨停 {breadth.get('涨停', 'N/A')}  跌停 {breadth.get('跌停', 'N/A')}

领涨板块: {json.dumps(sectors.get('top3', []), ensure_ascii=False)}
领跌板块: {json.dumps(sectors.get('bottom3', []), ensure_ascii=False)}

请输出严格的JSON格式，不要包含其他文字：
{{
  "market_state": "bullish/bearish/neutral/extreme_bearish",
  "risk_level": "0-10的整数（10=最高风险）",
  "recommended_strategy": "momentum/mean_reversion/cash",
  "position_ratio": "0.0-1.0的浮点数（建议仓位比例）",
  "key_factors": ["因素1", "因素2", "因素3"],
  "summary": "一句话总结当前市场状态"
}}"""
    return prompt


def call_llm(prompt: str) -> dict:
    """调用 Ollama qwen3-coder:30b 分析宏观数据"""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        if "{" in content and "}" in content:
            content = content[content.index("{"):content.rindex("}")+1]
        elif "{" in content:
            content = content[content.index("{"):] + "}"  # 修复截断的JSON
        analysis = json.loads(content)
        defaults = {
            "market_state": "neutral",
            "risk_level": 5,
            "recommended_strategy": "mean_reversion",
            "position_ratio": 0.5,
        }
        for k, v in defaults.items():
            if k not in analysis:
                analysis[k] = v
        return analysis
    except Exception as e:
        return {
            "market_state": "neutral",
            "risk_level": 5,
            "recommended_strategy": "mean_reversion",
            "position_ratio": 0.5,
            "key_factors": [f"LLM分析失败: {e}"],
            "summary": "LLM分析异常，使用默认值",
            "_llm_error": str(e),
        }


def run_analysis() -> dict:
    """完整分析管道"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始宏观数据采集...", flush=True)
    macro = fetch_macro_data()
    fetch_errors = macro.pop("errors", [])
    if fetch_errors:
        for e in fetch_errors:
            print(f"  ⚠️ {e}", flush=True)

    print(f"  数据采集完成: {len(macro)} 项", flush=True)
    print(f"  [qwen3-coder:30b] 开始 LLM 分析...", flush=True)

    prompt = build_prompt(macro)
    analysis = call_llm(prompt)

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "macro_data": {k: v for k, v in macro.items() if k != "errors"},
        "analysis": analysis,
    }

    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    history_path = HISTORY_DIR / f"{result['date']}.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 分析完成 → {LATEST_PATH}", flush=True)
    print(f"     市场状态: {analysis.get('market_state')}", flush=True)
    print(f"     风险等级: {analysis.get('risk_level')}/10", flush=True)
    print(f"     推荐策略: {analysis.get('recommended_strategy')}", flush=True)
    print(f"     建议仓位: {analysis.get('position_ratio', 0):.0%}", flush=True)
    return result


if __name__ == "__main__":
    run_analysis()
