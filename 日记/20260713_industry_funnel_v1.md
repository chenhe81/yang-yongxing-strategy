<!--
  版本: v1
  生成日期: 20260713
  修改内容: industry-funnel 行业漏斗筛选集成到凤雏
  前序版本: 无
-->

# industry-funnel 行业漏斗筛选集成

## 改动文件

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/tools/industry_funnel.py` | 新增 494 行 | 基于 ai-berkshire industry-funnel 框架的量化实现 |
| `fengchu_auto_trader.py` | 修改 ~50 行 | 集成行业漏斗加速逻辑 |

## industry_funnel.py 核心能力

1. **获取东方财富行业板块列表** — 带 7 天缓存
2. **多维度评分**:
   - 动量 (30%) — 近 5 日涨幅均值
   - 质量 (30%) — quality_screen 通过率
   - 活跃度 (15%) — 成交量 vs 均量比
   - 覆盖度 (10%) — 股票池中该行业占比
   - 集中度 (15%) — 龙头 ROE 集中度
3. **输出**:
   - `data/industry_funnel.json` — 供凤雏读取
   - `data/industry_funnel_report.md` — 可读报告

## 凤雏集成（fengchu_auto_trader.py）

### 新增函数: `load_industry_boost()`
- 位置: 第 224 行，在 `load_defensive_pool()` 后
- 读取 `data/industry_funnel.json`，返回 `{股票代码: 行业名称}` 字典
- 文件不存在或解析失败时返回空字典，不崩

### `_check_buys_mean_reversion()` 改动
- 新增参数 `industry_boost: dict = None`
- **加速阈值**: 来自行业漏斗前 N 的股票，zone_pct 门槛放宽 +0.10（上限 0.50）
- **加速加分**: score_bonus += 15（超过热点的 +10）

### `scan_once()` 改动
- 每次扫描加载行业漏斗数据
- 打印加速列表: "🏭 行业漏斗: 15 只股票来自 5 个优质行业"
- 将 `industry_boost` 传入 `check_buys()`

### 逻辑流程

```
行业漏斗 (收盘后 16:10) → data/industry_funnel.json
                                      ↓
凤雏轮询 → load_industry_boost()
              ↓
        zone_pct 检查：
          普通股: zone_pct ≤ zone_threshold
          行业加速股: zone_pct ≤ zone_threshold + 0.10
```

## 部署

| 步骤 | 状态 |
|------|------|
| industry_funnel.py → 凤雏 | ✅ scp 完成 |
| fengchu_auto_trader.py → 凤雏 | ✅ scp 完成 |
| crontab 16:10 收盘后运行 | ✅ 已添加 |
| MD5 一致性确认 | ✅ fc386198f2725aa8d0dae564c6ed98a9 |

## 注意事项

- 行业板块 API（17.push2.eastmoney.com）在凌晨可能不可达，不影响凤雏正常运行
- 首次运行需等待收盘后 16:10 触发，或手动在交易日盘中运行
- 若行业漏斗未运行（JSON 不存在），系统保持原行为，无加速
