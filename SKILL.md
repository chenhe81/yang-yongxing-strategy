---
name: yang-yongxing-strategy
description: 杨永兴短线战法 + SEPA策略 A股选股辅助工具。This skill should be used when the user asks about 杨永兴战法, 尾盘选股, 隔夜套利, T+1套利, 短线选股扫描, SEPA, 米勒维尼, 基本面筛选, or needs to scan/filter A-share stocks based on Yang Yongxing's rules or SEPA strategy. Also triggers when the user wants stock analysis for next-day trading, sell signal checks, combined scanning, or portfolio tracking.
---

# 杨永兴短线战法

## Overview

先杨永兴九步过滤股票（技术面筛选），再用SEPA策略验证基本面（财务+趋势），双重验证后再给出最终结果。核心逻辑：**先用杨永兴快速缩小范围（200→几十只），再用SEPA对候选股做精准验证**。提供联合扫描、单独扫描、卖出信号检查、持仓跟踪四大功能。

**扫描顺序**：
1. **第一步：杨永兴九步过滤**（全市场筛选，技术面为主）→ 候选股缩减到几十只
2. **第二步：SEPA策略验证**（对杨永兴候选股做基本面验证）→ 最终给出符合条件的标的

顺序不可颠倒。原因：SEPA查询全市场基本面数据太慢，杨永兴九步先过滤大幅减少候选股数量后再做SEPA验证，效率最高。

## 首次使用 - 环境安装

当用户首次使用本 Skill 时，执行以下安装步骤：

1. 确定 Skill 安装路径：
```bash
# Skill 安装在 ~/.codebuddy/skills/yang-yongxing-strategy/
SKILL_DIR="$HOME/.codebuddy/skills/yang-yongxing-strategy"
```

2. 创建 Python 虚拟环境并安装依赖：
```bash
cd "$SKILL_DIR/scripts"
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

3. 验证安装：
```bash
./venv/bin/python -c "import akshare; print(f'akshare {akshare.__version__} 安装成功')"
```

安装完成后，后续所有命令都在 `$SKILL_DIR/scripts` 目录下执行，使用 `./venv/bin/python` 运行。

## 扫描顺序（重要）

**先杨永兴战法 → 再SEPA**，不可颠倒。

原因：杨永兴九步法从全市场筛选（200+→几十只），大幅减少候选股数量；SEPA对全市场做基本面查询太慢，用杨永兴过滤后的几十只再做SEPA验证，效率最高。

## Workflow Decision Tree

```
用户触发场景
├── "扫描/选股/筛选股票" → 执行杨永兴九步过滤，再执行SEPA最终筛选（推荐顺序）
├── "联合扫描/双筛选/综合" → 执行杨永兴→SEPA联合扫描流程（推荐）
├── "短线/尾盘/杨永兴" → 仅执行杨永兴九步选股扫描流程
├── "SEPA/趋势/米勒维尼/基本面" → 仅执行SEPA策略选股扫描流程（输入为杨永兴候选股）
├── "卖出/卖出信号/该不该卖" → 执行卖出检查流程
├── "持仓/我的股票" → 查看持仓
├── "添加持仓/买入记录" → 记录持仓
├── "删除持仓/已卖出" → 移除持仓
├── "大盘/市场环境" → 分析大盘趋势
└── "战法/规则/杨永兴/SEPA" → 讲解战法知识
```

## 数据源

- A股实时行情：**腾讯财经接口**（`data_fetcher` 中的 `TencentDataSource`）
- 财务数据：腾讯财经 / 东方财富
- 不依赖 akshare（腾讯接口已够用，且速度更快）

## 核心交易规则

### 时间规则
- **买入时间**：14:30-14:50（尾盘30分钟）
- **卖出时间**：次日9:30-10:30（开盘1小时内）
- **持股时长**：严格≤2小时交易时间，绝不过夜

### 生死铁律
- 次日早盘必须清仓，除非缩量涨停或一字涨停
- 不要贪后续涨幅，"只赚属于我的那部分利润"
- 大盘放量大跌当日，直接空仓不操作

## 选股扫描流程

### 前置条件
- 确认当前为交易日且已过14:30
- 确认项目环境已就绪（akshare已安装）

### 执行步骤

1. 运行选股扫描脚本：
```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python run.py scan
```

如需快速扫描（跳过分时数据检查）：
```bash
./venv/bin/python run.py scan --skip-intraday
```

2. 解读扫描结果：
   - 查看大盘环境判断（趋势方向、是否放量大跌）
   - 查看九步过滤过程的淘汰情况
   - 关注最终候选股列表

3. 如果有候选股，根据三个买入时机给出建议：
   - **第一买点**：14:30左右股价创当日新高，大单拉升
   - **第二买点**：突破后回踩不破均价线，勾头向上
   - **第三买点**：突破短期前高

4. 用户决定买入后，记录持仓：
```bash
./venv/bin/python run.py add <代码> <名称> <买入价>
```

### 九步过滤法详解

执行扫描后，根据用户追问可详细解释每步逻辑（详见 `references/strategy-details.md`）：

| 步骤 | 维度 | 标准 | 逻辑 |
|------|------|------|------|
| 1 | 排除ST/非主板 | 只留主板票 | 减少风险 |
| 2 | 涨幅范围 | 3%-5% | 盈利空间充足但不追高 |
| 3 | 涨停基因 | 近20天有涨停 | 主力活跃，有人气 |
| 4 | 量比 | ≥1 | 有资金关注 |
| 5 | 流通市值 | 50-200亿 | 盘子适中易撬动 |
| 6 | 换手率 | 5%-10% | 健康换手，非出货 |
| 7 | 振幅 | ≤8% | 波动适中 |
| 8 | K线形态 | 上方无压力，无长上影线 | 上涨阻力小 |
| 9 | 分时走势 | 全天站均价线上方 | 买方主导，主力护盘 |

## SEPA策略选股扫描流程

### 前置条件
- 确认项目环境已就绪（akshare已安装）
- SEPA扫描主要使用财务数据，非交易时段也可运行

### 执行步骤

1. 运行SEPA策略选股扫描：
```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python run.py sepa-scan
```

跳过均线和量能检查（加快扫描速度，仅筛选基本面）：
```bash
./venv/bin/python run.py sepa-scan --skip-ma
```

2. 解读扫描结果：
   - 七步过滤过程的淘汰情况
   - 关注财务指标：营收增长、净利增长、ROE、3年CAGR
   - 技术指标：50日/150日均线、10日/120日均量

3. 结合杨永兴战法双重筛选：
   - SEPA候选股 + 杨永兴九步过滤 = 最高确定性标的
   - 先跑 `sepa-scan`，再用候选股代码跑 `scan`

### SEPA七步筛选法详解

| 步骤 | 维度 | 标准 | 逻辑 |
|------|------|------|------|
| 1 | 排除ST/次新股 | 上市>1年 | 减少风险，需历史验证 |
| 2 | 营收增长 | 同比>25% | 超级增长门槛 |
| 3 | 净利润增长 | 同比>30%，环比为正 | 利润加速释放 |
| 4 | 趋势确认 | 股价>MA50&MA150 | 中长期上升趋势 |
| 5 | 量能确认 | 10日均量>120日均量 | 机构资金入场 |
| 6 | ROE | >15% | 盈利效率高 |
| 7 | 3年CAGR | 净利润>20% | 业绩持续性强 |

### VCP形态（波动率收缩形态）

SEPA策略的核心买入信号：
- **特征**：价格波动从左到右逐渐收窄，成交量同步萎缩
- **买点**：价格从最后一个收缩区向上突破时
- **止损**：突破失败，价格回落到收缩区下沿
- **结合杨永兴**：在VCP突破当天尾盘确认买入

## SEPA+杨永兴联合扫描流程（推荐）

### 策略逻辑

先SEPA筛选基本面优质标的，再杨永兴寻找短线技术面买点，双重验证提高确定性：
- **SEPA通过** → 基本面优秀，业绩增长强劲，中长期上升趋势
- **杨永兴通过** → 短线技术面到位，资金活跃，买点确认
- **双战法同时通过** → 最高确定性标的

### 执行步骤

1. 运行联合扫描（推荐，双战法一体化）：
```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python run.py combined-scan
```

2. 快速模式（跳过均线检查+分时数据，最快）：
```bash
./venv/bin/python run.py combined-scan --skip-ma --skip-intraday
```

3. 放宽模式（杨永兴条件放宽，更多候选）：
```bash
./venv/bin/python run.py combined-scan --relax
```

4. 解读结果：
   - **🌟 双战法通过**：同时满足SEPA+杨永兴，最高确定性，尾盘择机买入
   - **✅ SEPA通过但杨永兴未通过**：基本面优秀但短线买点未到，加入自选等回调
   - **❌ 两者均未通过**：当日无机会，耐心等待

### 联合扫描参数说明

| 参数 | 作用 | 说明 |
|------|------|------|
| `--skip-ma` | 跳过均线检查 | SEPA步骤4/5跳过，仅做基本面筛选 |
| `-s, --skip-intraday` | 跳过分时数据 | 杨永兴步骤8跳过，加快速度 |
| `-r, --relax` | 放宽杨永兴条件 | 涨幅不限、市值30-500亿、换手2-15% |
| `-o, --openviking` | 启用OpenViking上下文管理 | 记忆积累+经验沉淀，需先启动openviking-server |

## OpenViking 上下文管理（可选增强）

### 功能说明

OpenViking 为选股 Skill 提供上下文管理能力，解决"无记忆、无经验、上下文浪费"三大痛点：

| 功能 | 说明 | 价值 |
|------|------|------|
| 自动记忆召回 | 每轮对话前自动检索相关历史 | 记住用户偏好和历史扫描 |
| 扫描结果同步 | 扫描完成后自动存储 | 历史可追溯，趋势可对比 |
| 用户偏好捕获 | 存储用户投资偏好 | 无需每次重复设置 |
| 操作经验积累 | 从历史操作中积累经验 | 提升选股准确率 |

### 一键初始化

```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python run.py openviking-init
```

此命令自动完成：安装openviking → 检查Ollama → 拉取嵌入模型 → 创建配置文件

### 手动启动步骤

```bash
# 1. 安装 Ollama（本地大模型运行环境）
brew install ollama
brew services start ollama

# 2. 拉取嵌入模型
ollama pull nomic-embed-text

# 3. 安装 OpenViking
pip install openviking

# 4. 创建配置文件
mkdir -p ~/.openviking
# 编辑 ~/.openviking/ov.conf 配置Ollama模型

# 5. 启动 OpenViking 服务
openviking-server

# 6. 导入策略知识
./venv/bin/python openviking_init_knowledge.py
```

### 使用方式

```bash
# 启用OpenViking的联合扫描
./venv/bin/python run.py combined-scan --openviking

# 查看OpenViking状态
./venv/bin/python run.py openviking-status
```

### 优雅降级

OpenViking 是**可选增强**，不启用时所有功能正常运行。适配层设计为：
- OpenViking 不可用 → 自动回退到本地文件存储
- 不影响核心选股逻辑
- 零侵入：核心扫描代码无需修改

## 卖出信号检查流程

### 执行步骤

1. 运行卖出信号检查（次日9:35后）：
```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python run.py sell-check
```

2. 根据检查结果给出明确操作建议：

| 开盘情况 | 卖出标准 | 紧急程度 |
|---------|---------|---------|
| 高开高走/平开高走/低开高走 | 破分时均价线或趋势线时卖 | 🟡 关注 |
| 平开平走/平开低走 | 破前低卖出 | 🟠 重要 |
| 高开低走/低开低走 | 破前低卖出 | 🔴 紧急 |
| 亏损达3% | 止损卖出 | 🔴 重要 |
| 亏损达5% | 强制止损 | ‼️ 极紧急 |

3. 用户确认卖出后，清除持仓记录：
```bash
./venv/bin/python run.py remove <代码>
```

## 持仓管理

```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"

# 查看当前持仓
./venv/bin/python run.py portfolio

# 添加持仓（买入后记录）
./venv/bin/python run.py add 000001 平安银行 15.50

# 移除持仓（卖出后清除）
./venv/bin/python run.py remove 000001

# 清空所有持仓
./venv/bin/python run.py clear
```

## 仓位管理原则

| 情况 | 仓位 |
|------|------|
| 看不懂 | 坚决空仓 |
| 半懂 | 分仓2-3只 |
| 看懂 | 重仓但≤50% |

- 单票仓位 ≤ 总资金20%
- 每日操作 ≤ 3笔
- 单次目标收益1%-3%，复利积累

## 战法深层心法

当用户问及战法背后的逻辑时，参考 `references/strategy-details.md` 进行讲解：

1. **核心思路**：趋势投机 + 事件驱动
2. **三大要诀**：看准大市 > 控制仓位 > 操盘技巧
3. **判断大市**：自下而上，从龙头股看板块，从板块看大盘
4. **操作精髓**：等待、发现、跟随——长时间持币，短时间持股
5. **提前量思维**：考虑对手在想什么，将要做什么，早他一步
6. **短线也看基本面**：从公告、券商研报中掘金

## 大盘环境判断

当用户问大盘时，运行：
```bash
cd "$HOME/.codebuddy/skills/yang-yongxing-strategy/scripts"
./venv/bin/python -c "
from data_fetcher import get_market_trend, get_market_status
import json
trend = get_market_trend()
status = get_market_status()
print(json.dumps({**trend, **status}, ensure_ascii=False, default=str, indent=2))
"
```

根据结果判断：
- trend=up + 非放量大跌 → 可操作，仓位根据趋势强度调整
- trend=down 或 is_crash=True → 空仓观望

## Important Notes

- ⚠️ **免责声明**：本工具仅供学习研究，不构成任何投资建议。股市有风险，投资需谨慎。
- 战法依赖盘中数据，非交易日运行可能获取不到实时行情
- 分时数据获取较慢，如候选股不多可用完整扫描；候选股多时建议 `--skip-intraday` 先快速筛选
- SEPA策略的财务数据获取较慢（需逐只查询），建议先用 `--skip-ma` 仅做基本面筛选
- 量化时代很多超短线已被程序化交易取代，战法有效性需持续验证
- SEPA策略数据来源参考社区Skill：china-stock-analysis (sugarforever/01coder-agent-skills)
