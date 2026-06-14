"""
Dify 数据存储模块 — 将扫描结果存入 Dify 知识库

API 说明：
  使用 Dify Knowledge API v1
  - 创建文档: POST /v1/datasets/{dataset_id}/document/create-by-text
  - 更新文档: POST /v1/datasets/{dataset_id}/documents/{document_id}/update-by-text
  - 列出数据集: GET /v1/datasets

配置：
  环境变量 DIFY_API_KEY: Dify API Key
  环境变量 DIFY_BASE_URL: Dify 服务器地址 (默认 https://api.dify.ai/v1)
  
  或在 config/dify_config.yaml 中配置:
    api_key: "your-api-key"
    base_url: "https://api.dify.ai/v1"
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Dict, List

import requests

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Dify 知识库名称映射（自动查找或创建） ──
KNOWLEDGE_BASES = {
    "fengchu": "凤雏每日扫描记录",    # 凤雏日筛结果
    "zhongda": "仲达每周扫描记录",     # 仲达周筛结果
    "kongming": "孔明复盘报告",       # 孔明对比报告
    "pool_rules": "股票池分层管理规则", # 已有知识库
}

# ── 已有知识库ID（缓存，运行时自动发现） ──
_knowledge_base_ids: Dict[str, str] = {}


def _load_config() -> dict:
    """加载 Dify 配置"""
    # 环境变量优先
    api_key = os.environ.get("DIFY_API_KEY")
    base_url = os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")

    # 其次检查配置文件
    if not api_key:
        config_path = os.path.join(BASE_DIR, "config", "dify_config.yaml")
        if os.path.exists(config_path):
            try:
                import yaml
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                api_key = cfg.get("api_key", api_key)
                base_url = cfg.get("base_url", base_url)
            except Exception as e:
                logger.debug(f"读取 Dify 配置失败: {e}")

    return {"api_key": api_key, "base_url": base_url.rstrip("/")}


def _headers() -> Optional[dict]:
    """获取 API 请求头"""
    config = _load_config()
    if not config["api_key"]:
        logger.warning("DIFY_API_KEY 未配置，跳过 Dify 存储")
        return None
    return {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }


def _api_post(path: str, data: dict) -> Optional[dict]:
    """Dify API POST 请求"""
    config = _load_config()
    headers = _headers()
    if not headers:
        return None
    url = f"{config['base_url']}{path}"
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code in (200, 201):
            return resp.json()
        logger.warning(f"Dify API POST {path} 失败: {resp.status_code} {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"Dify API 请求异常: {e}")
        return None


def _api_get(path: str) -> Optional[dict]:
    """Dify API GET 请求"""
    config = _load_config()
    headers = _headers()
    if not headers:
        return None
    url = f"{config['base_url']}{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.warning(f"Dify API GET 请求异常: {e}")
        return None


def discover_knowledge_bases() -> Dict[str, str]:
    """发现已有知识库，返回 {名称: ID} 映射"""
    headers = _headers()
    if not headers:
        return {}

    data = _api_get("/datasets?page=1&limit=100")
    if not data or "data" not in data:
        logger.warning("无法获取知识库列表")
        return {}

    result = {}
    for kb in data["data"]:
        result[kb["name"]] = kb["id"]
    return result


def get_knowledge_base_id(kb_name: str) -> Optional[str]:
    """获取知识库 ID，如果不存在则返回 None（需要用户手动创建）"""
    global _knowledge_base_ids
    if not _knowledge_base_ids:
        _knowledge_base_ids = discover_knowledge_bases()

    kb_id = _knowledge_base_ids.get(kb_name)
    if kb_id:
        return kb_id

    # 尝试模糊匹配
    for name, kid in _knowledge_base_ids.items():
        if kb_name in name or name in kb_name:
            return kid
    return None


def upload_document_to_kb(kb_name: str, title: str, content: str,
                          doc_type: str = "text") -> bool:
    """
    将文档上传到 Dify 知识库
    kb_name: 知识库名称
    title: 文档标题
    content: 文档内容（markdown 格式）
    doc_type: 文档类型
    """
    kb_id = get_knowledge_base_id(kb_name)
    if not kb_id:
        logger.warning(f"知识库 '{kb_name}' 不存在，跳过上传")
        return False

    data = {
        "name": title,
        "text": content,
        "indexing_technique": "semantic",
        "process_rule": {
            "mode": "automatic"
        },
        "doc_type": doc_type,
    }
    result = _api_post(f"/datasets/{kb_id}/document/create-by-text", data)
    if result and result.get("document", {}).get("id"):
        logger.info(f"✅ 文档 '{title}' 已上传到知识库 '{kb_name}' (ID: {result['document']['id']})")
        return True
    logger.warning(f"文档上传失败: {result}")
    return False


# ── 专用上传函数 ──


def upload_fengchu_scan(date: str, results: list, trades: list) -> bool:
    """上传凤雏日筛结果到 Dify"""
    lines = [f"# 凤雏每日扫描报告 — {date}", ""]
    lines.append(f"## 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"## 候选股数量: {len(results)}")
    lines.append("")

    if results:
        lines.append("## 候选股详情")
        lines.append("")
        lines.append("| 代码 | 名称 | 评分 | 涨幅 | 量比 | 换手率 | 决策 |")
        lines.append("|------|------|------|------|------|--------|------|")
        for r in results:
            lines.append(f"| {r['code']} | {r['name']} | {r['score']} | "
                         f"{r.get('pct_change', 0):+.1f}% | "
                         f"{r.get('volume_ratio', 0):.2f} | "
                         f"{r.get('turnover', 0):.1f}% | {r['decision']} |")
        lines.append("")

    if trades:
        buys = [t for t in trades if t["type"] == "buy"]
        sells = [t for t in trades if t["type"] == "sell"]

        if buys:
            lines.append("## 模拟买入")
            for t in buys:
                lines.append(f"- {t['name']}({t['code']}) 价格:{t['price']:.2f} 数量:{t['shares']}")
        if sells:
            lines.append("## 模拟卖出")
            for t in sells:
                pnl = t.get("pnl_pct", 0)
                lines.append(f"- {'✅' if pnl >= 0 else '❌'} {t['name']}({t['code']}) "
                             f"盈亏:{pnl:+.1f}%")

    return upload_document_to_kb("凤雏每日扫描记录",
                                 f"凤雏日筛_{date}", "\n".join(lines))


def upload_zhongda_scan(date: str, results: list) -> bool:
    """上传仲达周筛结果到 Dify"""
    lines = [f"# 仲达每周扫描报告 — {date}", ""]
    lines.append(f"## 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"## 候选股数量: {len(results)}")
    lines.append("")

    if results:
        lines.append("## SEPA趋势模板通过股")
        for r in results:
            lines.append(f"- {r.get('name', '')}({r.get('code', '')}) "
                         f"评分:{r.get('total_score', 0)} "
                         f"VCP形态:{'是' if r.get('is_vcp') else '否'}")

    return upload_document_to_kb("仲达每周扫描记录",
                                 f"仲达周筛_{date}", "\n".join(lines))


def upload_kongming_report(date: str, report: str) -> bool:
    """上传孔明复盘报告到 Dify"""
    return upload_document_to_kb("孔明复盘报告",
                                 f"孔明复盘_{date}", report)


def is_configured() -> bool:
    """检查 Dify 是否已配置"""
    config = _load_config()
    return bool(config["api_key"])
