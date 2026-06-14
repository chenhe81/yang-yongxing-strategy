"""
OpenViking 适配层 - 为选股Skill提供上下文管理能力
功能：
  1. 自动记忆召回（每轮对话前，从OpenViking检索相关记忆）
  2. 扫描结果自动同步（扫描完成后，结果存储到OpenViking）
  3. 用户偏好自动捕获（从对话中提取用户投资偏好）
  4. 操作经验自动积累（对比扫描结果与后续表现）

设计原则：
  - 优雅降级：OpenViking 不可用时，所有功能自动回退，不影响核心选股
  - 零侵入：核心扫描代码无需修改，仅通过适配层调用
"""

import logging
import datetime
import os
import json
import time
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

# ============ 配置 ============

OPENVIKING_ENABLED = os.environ.get("OPENVIKING_ENABLED", "false").lower() == "true"
OPENVIKING_URL = os.environ.get("OPENVIKING_URL", "http://localhost:1933")
OPENVIKING_TIMEOUT = int(os.environ.get("OPENVIKING_TIMEOUT", "5"))  # 秒


class OpenVikingAdapter:
    """OpenViking 适配层 - 为选股Skill提供上下文管理"""

    def __init__(self, url: str = None, enabled: bool = None):
        self.url = url or OPENVIKING_URL
        self._enabled = enabled if enabled is not None else OPENVIKING_ENABLED
        self._client = None
        self._initialized = False
        self._available = False

        if self._enabled:
            self._try_connect()

    def _try_connect(self) -> bool:
        """尝试连接 OpenViking 服务"""
        try:
            import openviking as ov
            self._client = ov.SyncHTTPClient(url=self.url)
            self._client.initialize()
            # 健康检查
            import requests
            resp = requests.get(f"{self.url}/health", timeout=OPENVIKING_TIMEOUT)
            if resp.status_code == 200:
                self._available = True
                self._initialized = True
                logger.info(f"✅ OpenViking 已连接: {self.url}")
            else:
                logger.warning(f"OpenViking 健康检查失败: {resp.status_code}")
        except ImportError:
            logger.warning("openviking 包未安装，上下文管理功能不可用")
        except Exception as e:
            logger.warning(f"OpenViking 连接失败: {e}，上下文管理功能不可用")

        if not self._available:
            logger.info("💡 提示：启动OpenViking可启用记忆和经验积累功能")
            logger.info("   安装: pip install openviking")
            logger.info("   启动: openviking-server")
            logger.info("   使用: OPENVIKING_ENABLED=true python run.py combined-scan")

        return self._available

    @property
    def available(self) -> bool:
        """OpenViking 是否可用"""
        return self._available and self._initialized

    # ============ 核心功能1：自动记忆召回 ============

    def auto_recall(self, user_message: str, limit: int = 6) -> str:
        """
        每轮对话前，自动召回相关记忆
        返回格式化的XML记忆块，直接注入到用户消息中
        """
        if not self.available:
            return ""

        try:
            results = []

            # 双路检索：用户记忆 + Agent经验
            for target_uri, label in [
                ("viking://user/memories/", "用户偏好"),
                ("viking://agent/memories/", "选股经验"),
                ("viking://resources/", "策略知识"),
            ]:
                try:
                    search_results = self._client.find(
                        query=user_message,
                        target_uri=target_uri,
                    )
                    if search_results and hasattr(search_results, 'resources'):
                        for r in search_results.resources:
                            results.append({
                                "uri": r.uri,
                                "score": getattr(r, 'score', 0),
                                "content": getattr(r, 'content', getattr(r, 'abstract', ''))[:500],
                                "source": label,
                            })
                except Exception as e:
                    logger.debug(f"检索 {target_uri} 失败: {e}")

            if not results:
                return ""

            # 按相关性排序，取 top N
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            results = results[:limit]

            # 格式化为XML
            xml_parts = ["<relevant-memories>"]
            for m in results:
                xml_parts.append(f'  <memory uri="{m["uri"]}" score="{m["score"]:.2f}" source="{m["source"]}">')
                xml_parts.append(f'    {m["content"]}')
                xml_parts.append("  </memory>")
            xml_parts.append("</relevant-memories>")

            logger.info(f"📋 自动召回 {len(results)} 条相关记忆")
            return "\n".join(xml_parts)

        except Exception as e:
            logger.debug(f"自动召回失败: {e}")
            return ""

    # ============ 核心功能2：扫描结果自动同步 ============

    def sync_scan_result(self, scan_result: dict) -> bool:
        """
        扫描完成后，自动同步到 OpenViking
        存储路径: viking://agent/memories/scan_history/{date}_{strategy}
        """
        if not self.available:
            return False

        try:
            today = datetime.date.today().strftime("%Y-%m-%d")
            strategy = scan_result.get("strategy", "combined")

            # 构建扫描摘要
            sepa = scan_result.get("sepa_candidates", [])
            final = scan_result.get("final_candidates", [])
            market = scan_result.get("market", {})
            market_status = scan_result.get("market_status", {})

            content = f"""# 选股扫描报告 - {today}

## 扫描信息
- 日期: {today}
- 策略: {strategy}
- 大盘趋势: {market.get('trend', 'unknown')}
- 大盘涨跌: {market.get('change_pct', 'N/A')}%

## 筛选结果
- SEPA候选: {len(sepa)}只
- 双战法通过: {len(final)}只

## SEPA候选股
"""
            for c in sepa[:20]:
                code = c.get("code", "")
                name = c.get("name", "")
                price = c.get("price", "N/A")
                chg = c.get("change_pct", 0)
                rev = c.get("revenue_growth_yoy", 0)
                profit = c.get("profit_growth_yoy", 0)
                roe = c.get("roe", 0)
                content += f"- {code} {name} 价格:{price} 涨幅:{chg:.1f}% 营收+{rev:.1f}% 净利+{profit:.1f}% ROE:{roe:.1f}%\n"

            content += "\n## 双战法通过\n"
            for c in final[:20]:
                code = c.get("code", "")
                name = c.get("name", "")
                price = c.get("price", "N/A")
                chg = c.get("change_pct", 0)
                vol_r = c.get("volume_ratio", "N/A")
                turn = c.get("turnover_rate", "N/A")
                content += f"- {code} {name} 价格:{price} 涨幅:{chg:.1f}% 量比:{vol_r} 换手:{turn}%\n"

            if market_status.get("is_crash"):
                content += "\n⚠️ 大盘放量大跌，建议空仓！\n"

            # 通过临时文件方式添加资源
            self._add_memory_resource(
                uri=f"viking://agent/memories/scan_history/{today}_{strategy}",
                content=content,
                title=f"扫描报告 {today} {strategy}",
                metadata={
                    "date": today,
                    "strategy": strategy,
                    "sepa_count": len(sepa),
                    "final_count": len(final),
                    "type": "scan_result",
                }
            )

            logger.info(f"📁 扫描结果已同步到 OpenViking: {today}_{strategy}")
            return True

        except Exception as e:
            logger.debug(f"扫描结果同步失败: {e}")
            return False

    # ============ 核心功能3：用户偏好捕获 ============

    def capture_user_preference(self, preferences: Dict[str, Any]) -> bool:
        """
        手动存储用户偏好到 OpenViking
        支持的偏好类型: risk_tolerance, focus_sectors, capital_scale, trading_style
        """
        if not self.available:
            return False

        try:
            for key, value in preferences.items():
                self._add_memory_resource(
                    uri=f"viking://user/memories/preferences/{key}",
                    content=f"# 用户偏好: {key}\n\n{value}",
                    title=f"偏好: {key}",
                    metadata={"type": "user_preference", "key": key}
                )

            logger.info(f"📝 用户偏好已同步: {list(preferences.keys())}")
            return True

        except Exception as e:
            logger.debug(f"用户偏好同步失败: {e}")
            return False

    # ============ 核心功能4：操作经验积累 ============

    def sync_experience(self, date: str, experience: str, exp_type: str = "general") -> bool:
        """
        存储选股经验到 OpenViking
        """
        if not self.available:
            return False

        try:
            self._add_memory_resource(
                uri=f"viking://agent/memories/experience/{exp_type}/{date}",
                content=f"# 选股经验 - {date}\n\n{experience}",
                title=f"经验: {exp_type} {date}",
                metadata={"type": "experience", "exp_type": exp_type, "date": date}
            )

            logger.info(f"💡 选股经验已同步: {exp_type}/{date}")
            return True

        except Exception as e:
            logger.debug(f"选股经验同步失败: {e}")
            return False

    # ============ 核心功能5：查询历史扫描 ============

    def query_history(self, query: str, days: int = 30) -> List[Dict]:
        """
        查询历史扫描记录和经验
        """
        if not self.available:
            return []

        try:
            results = []
            search_results = self._client.find(
                query=query,
                target_uri="viking://agent/memories/",
            )
            if search_results and hasattr(search_results, 'resources'):
                for r in search_results.resources:
                    results.append({
                        "uri": r.uri,
                        "score": getattr(r, 'score', 0),
                        "content": getattr(r, 'content', getattr(r, 'abstract', ''))[:1000],
                    })

            return results[:20]

        except Exception as e:
            logger.debug(f"历史查询失败: {e}")
            return []

    # ============ 辅助方法 ============

    def _add_memory_resource(self, uri: str, content: str, title: str = "",
                             metadata: Dict = None) -> bool:
        """
        添加记忆资源到 OpenViking
        优先使用API，降级到本地文件存储
        """
        try:
            # 尝试通过API添加
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False,
                                              encoding='utf-8') as f:
                f.write(content)
                temp_path = f.name

            try:
                result = self._client.add_resource(temp_path)
                return True
            finally:
                os.unlink(temp_path)

        except Exception as e:
            # 降级到本地文件存储
            logger.debug(f"API添加失败，降级到本地存储: {e}")
            return self._add_local_memory(uri, content, metadata)

    def _add_local_memory(self, uri: str, content: str, metadata: Dict = None) -> bool:
        """
        降级方案：将记忆存储到本地文件
        路径: {DATA_DIR}/openviking_memories/{uri_path}
        """
        try:
            # 将 viking:// URI 转为本地路径
            from config import DATA_DIR
            uri_path = uri.replace("viking://", "").replace("/", os.sep)
            local_dir = os.path.join(DATA_DIR, "openviking_memories", os.path.dirname(uri_path))
            local_file = os.path.join(local_dir, os.path.basename(uri_path) + ".md")

            os.makedirs(local_dir, exist_ok=True)

            with open(local_file, 'w', encoding='utf-8') as f:
                if metadata:
                    f.write(f"---\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n---\n\n")
                f.write(content)

            logger.debug(f"记忆已存储到本地: {local_file}")
            return True

        except Exception as e:
            logger.debug(f"本地记忆存储失败: {e}")
            return False

    def get_status(self) -> Dict:
        """获取 OpenViking 状态信息"""
        status = {
            "enabled": self._enabled,
            "available": self.available,
            "url": self.url,
        }

        if self.available:
            try:
                import requests
                resp = requests.get(f"{self.url}/health", timeout=OPENVIKING_TIMEOUT)
                status["server_health"] = resp.json() if resp.status_code == 200 else "unhealthy"
            except Exception:
                status["server_health"] = "unreachable"

        return status

    def close(self):
        """关闭连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass


# ============ 单例模式 ============

_instance: Optional[OpenVikingAdapter] = None


def get_openviking() -> OpenVikingAdapter:
    """获取 OpenViking 适配器单例"""
    global _instance
    if _instance is None:
        _instance = OpenVikingAdapter()
    return _instance


def init_openviking(enabled: bool = None, url: str = None) -> OpenVikingAdapter:
    """初始化 OpenViking 适配器"""
    global _instance
    _instance = OpenVikingAdapter(url=url, enabled=enabled)
    return _instance
