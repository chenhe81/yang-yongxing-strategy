#!/usr/bin/env python3
"""
导入策略知识到 OpenViking 上下文数据库
将杨永兴战法和SEPA策略的完整知识体系导入 OpenViking 的 resources 目录
"""

import os
import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 项目路径
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCES_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "references")


# ============ 策略知识定义 ============

STRATEGY_KNOWLEDGE = {
    "viking://resources/yang_yongxing/": {
        "title": "杨永兴短线战法",
        "abstract": "杨永兴隔夜套利法：尾盘14:30买入，次日10:30前卖出，九步过滤法筛选高确定性标的",
        "overview": """杨永兴短线战法核心规则：
1. 尾盘14:30-14:50买入，次日9:30-10:30卖出
2. 九步过滤：涨幅3-5% → 近20天涨停 → 量比≥1 → 市值50-200亿 → 换手5-10% → 振幅≤8% → K线无压力 → 分时站均价线
3. 铁律：持股不超2小时，止损3%，大盘放量大跌空仓
4. 适用场景：A股主板，非ST非次新股""",
        "files": {
            "九步筛选规则.md": """# 杨永兴九步选股筛选规则

## 步骤详解

### 步骤1：今日涨幅 3%-5%
- 涨幅太小：资金关注度不够
- 涨幅太大：追高风险大
- 3%-5%是黄金区间：既有资金关注，又有上涨空间

### 步骤2：近20天有涨停记录
- 涨停基因：说明有资金愿意封板
- 涨停后的回调整理是买点
- 近期涨停的股票更容易再次涨停

### 步骤3：量比 ≥ 1
- 量比=1：成交量与过去5日平均持平
- 量比>1：放量，资金介入
- 量比<1：缩量，缺乏资金关注
- 量比>5需警惕：可能是主力对倒

### 步骤4：流通市值 50-200亿
- 太小(<50亿)：流动性差，容易被操纵
- 太大(>200亿)：拉升需要大量资金
- 50-200亿：游资和机构都能参与

### 步骤5：换手率 5%-10%
- <5%：交易不够活跃
- 5-10%：活跃度适中
- >10%：可能过度投机

### 步骤6：振幅 ≤ 8%
- 振幅大=波动大=风险高
- 振幅≤8%：走势相对稳定

### 步骤7：K线上方无压力
- 无长上影线
- 上方无密集套牢区
- 量价配合健康

### 步骤8：分时站均价线上方
- 全天大部分时间站均价线上方
- 说明买盘持续强于卖盘
- 尾盘不跳水
""",
            "量比分析技巧.md": """# 量比分析技巧

## 量比的定义
量比 = 当日即时成交量 / 过去5日同一时刻平均成交量

## 量比区间解读
| 量比范围 | 含义 |
|---------|------|
| < 0.5 | 严重缩量，无人关注 |
| 0.5-1.0 | 缩量运行 |
| 1.0-1.5 | 温和放量 |
| 1.5-2.5 | 明显放量 |
| 2.5-5.0 | 剧烈放量 |
| > 5.0 | 异常放量，需警惕 |

## 杨永兴量比策略
- 量比≥1是最低要求
- 理想区间：1.5-3.0
- 量比>5时谨慎：可能是主力对倒或诱多
- 量比突然放大配合涨停：可重点跟踪
""",
            "分时形态判断.md": """# 分时形态判断

## 理想分时形态
1. 早盘快速拉高后横盘
2. 全天站均价线上方
3. 尾盘不跳水
4. 分时线平滑无锯齿

## 危险分时形态
1. 早盘冲高后持续回落
2. 长时间在均价线下方运行
3. 尾盘快速跳水
4. 分时线锯齿状波动

## 操作时间窗口
- 买入：14:30-14:50
- 观察均价线位置
- 确认尾盘不跳水再买入
""",
        }
    },
    "viking://resources/sepa/": {
        "title": "SEPA策略（米勒维尼《股票魔法师》）",
        "abstract": "SEPA策略7步基本面筛选：营收增长>25%、净利增长>30%、ROE>15%、3年CAGR>20%",
        "overview": """SEPA策略核心规则：
1. 剔除ST和上市不满1年的次新股
2. 最近季度营收同比增长>25%
3. 最近季度净利同比增长>30%，且环比为正
4. 当前股价在50日/150日均线之上
5. 近10日均量>120日均量（放量）
6. ROE>15%
7. 近3年净利润CAGR>20%

核心买入信号：VCP形态（波动率收缩形态）
- 价格波动从左到右逐渐收窄
- 成交量同步萎缩
- 从最后一个收缩区向上突破时买入""",
        "files": {
            "七步筛选规则.md": """# SEPA七步基本面筛选规则

## 步骤1：剔除ST和次新股
- ST/*ST股票：公司经营异常
- 上市不满1年：缺乏足够历史数据验证
- 次新股波动大，不适合趋势策略

## 步骤2：营收增长 >25%
- 营收是企业增长的根基
- 单季度营收同比增长需>25%
- 营收增长持续性好于利润增长

## 步骤3：净利增长 >30% 且环比为正
- 净利润增长要快于营收（说明利润率提升）
- 环比增长为正（排除季节性因素）
- 净利加速增长是超强信号

## 步骤4：股价在MA50/MA150之上
- MA50：中期趋势线
- MA150：长期趋势线
- 股价同时在两条均线之上=上升趋势
- 这是SEPA最重要的技术条件

## 步骤5：放量
- 近10日均量>120日均量
- 放量说明资金在流入
- 缩量上涨不可靠

## 步骤6：ROE >15%
- ROE衡量资本使用效率
- >15%说明公司盈利能力强
- 连续高ROE比单次更重要

## 步骤7：3年净利润CAGR >20%
- CAGR = 复合年增长率
- 3年CAGR>20%说明增长具有持续性
- 计算公式：CAGR = (末年/首年)^(1/年数) - 1
""",
            "VCP形态分析.md": """# VCP形态（波动率收缩形态）

## VCP的核心特征
1. 价格波动从左到右逐渐收窄
2. 成交量同步萎缩
3. 每次收缩的幅度递减

## VCP的买点
- 价格从最后一个收缩区向上突破时
- 突破日成交量需明显放大
- 止损位：收缩区下沿

## VCP的结合使用
- 先用SEPA 7步筛选基本面
- 再在候选股中寻找VCP形态
- VCP突破+SEPA基本面=最强买点
- 结合杨永兴：在VCP突破当天尾盘确认买入
""",
        }
    },
    "viking://resources/market_basics/": {
        "title": "A股市场基础知识",
        "abstract": "A股交易规则、涨跌停制度、T+1交易制度等基础知识",
        "overview": "A股市场基础交易规则：T+1交易、10%涨跌停（创业板/科创板20%）、集合竞价规则",
        "files": {
            "交易规则.md": """# A股交易规则

## 基本规则
- 交易时间：9:30-11:30, 13:00-15:00
- T+1交易：当日买入次日方可卖出
- 涨跌停：主板±10%，创业板/科创板±20%，ST±5%
- 集合竞价：9:15-9:25（开盘），14:57-15:00（收盘）

## 对杨永兴战法的影响
- T+1是隔夜套利法的前提
- 涨跌停限制影响选股范围
- 集合竞价时段可用于观察开盘情绪
""",
        }
    }
}


def import_to_openviking(knowledge: dict):
    """将策略知识导入 OpenViking"""
    try:
        import openviking as ov
        client = ov.SyncHTTPClient(url=os.environ.get("OPENVIKING_URL", "http://localhost:1933"))
        client.initialize()
        
        imported = 0
        for base_uri, data in knowledge.items():
            # 添加摘要和概览（通过临时文件）
            for level, content_key in [("abstract", "abstract"), ("overview", "overview")]:
                if content_key in data:
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
                        f.write(data[content_key])
                        temp_path = f.name
                    try:
                        client.add_resource(temp_path)
                        imported += 1
                        logger.info(f"  ✅ 导入 {base_uri} [{content_key}]")
                    finally:
                        os.unlink(temp_path)
            
            # 添加详细文件
            for filename, content in data.get("files", {}).items():
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
                    f.write(content)
                    temp_path = f.name
                try:
                    client.add_resource(temp_path)
                    imported += 1
                    logger.info(f"  ✅ 导入 {base_uri}{filename}")
                finally:
                    os.unlink(temp_path)
        
        client.close()
        return imported
        
    except Exception as e:
        logger.error(f"OpenViking 导入失败: {e}")
        return 0


def import_to_local(knowledge: dict):
    """降级方案：将策略知识存储到本地文件"""
    from config import DATA_DIR
    
    base_dir = os.path.join(DATA_DIR, "openviking_memories", "resources")
    imported = 0
    
    for base_uri, data in knowledge.items():
        uri_path = base_uri.replace("viking://resources/", "").rstrip("/")
        dir_path = os.path.join(base_dir, uri_path)
        os.makedirs(dir_path, exist_ok=True)
        
        # 写入摘要
        if "abstract" in data:
            with open(os.path.join(dir_path, ".abstract"), 'w', encoding='utf-8') as f:
                f.write(data["abstract"])
            imported += 1
        
        # 写入概览
        if "overview" in data:
            with open(os.path.join(dir_path, ".overview"), 'w', encoding='utf-8') as f:
                f.write(data["overview"])
            imported += 1
        
        # 写入详细文件
        for filename, content in data.get("files", {}).items():
            filepath = os.path.join(dir_path, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            imported += 1
            logger.info(f"  ✅ 本地存储 {uri_path}/{filename}")
    
    return imported


def main():
    """主入口"""
    logger.info("🚀 开始导入策略知识到上下文数据库...")
    
    # 先尝试 OpenViking
    try:
        import requests
        resp = requests.get("http://localhost:1933/health", timeout=3)
        if resp.status_code == 200:
            logger.info("✅ OpenViking 服务可用，导入到 OpenViking...")
            count = import_to_openviking(STRATEGY_KNOWLEDGE)
            if count > 0:
                logger.info(f"🎉 成功导入 {count} 个知识文件到 OpenViking")
                return
    except Exception:
        pass
    
    # 降级到本地存储
    logger.info("⚠️ OpenViking 服务不可用，降级到本地存储...")
    count = import_to_local(STRATEGY_KNOWLEDGE)
    logger.info(f"🎉 成功导入 {count} 个知识文件到本地 ({os.path.join(os.path.dirname(SCRIPTS_DIR), 'data', 'openviking_memories', 'resources')})")


if __name__ == "__main__":
    main()
