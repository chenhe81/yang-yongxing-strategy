#!/usr/bin/env python3
"""
宏观分析 API 服务 — 在算力中心 (183.131.24.109) 上运行
对外提供宏观分析结果查询接口
凤雏/刘秀通过 HTTP 读取宏观结果
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE = Path(__file__).parent
OUTPUT_DIR = BASE / "output"
LATEST_PATH = OUTPUT_DIR / "latest.json"
MACRO_SCRIPT = BASE / "macro_analyst.py"

app = FastAPI(title="宏观分析中心", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


@app.get("/macro/status")
def macro_status():
    """返回最新宏观分析结果"""
    if not LATEST_PATH.exists():
        raise HTTPException(status_code=404, detail="尚无宏观分析数据，收盘后自动生成")

    with open(LATEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@app.post("/macro/run")
def macro_run():
    """手动触发宏观分析（调试用）"""
    try:
        result = subprocess.run(
            [sys.executable, str(MACRO_SCRIPT)],
            capture_output=True, text=True, timeout=180,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
