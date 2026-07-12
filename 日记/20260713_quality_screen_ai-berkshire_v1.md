<!--
  版本: v1
  生成日期: 20260713
  修改内容: quality_screen.py 补齐 ai-berkshire SKILL.md 遗漏项：REIT/周期性/数据窗口/输出格式
  前序版本: 无
-->

# quality_screen.py ai-berkshire 补齐 v1

## 时间
2026-07-13 02:00~02:30 CST

## 修改文件

`src/factors/quality_screen.py` (381→561 行)

## 改动内容

### 1. 新增函数

| 函数 | 行号 | 用途 |
|------|------|------|
| `_classify_stock()` | 85~129 | 行业分类：REIT（代码前缀）/ 周期性（ROE波动率+名称关键词）/ 正常 |
| `_format_quality_summary()` | 131~192 | 生成格式化汇总文本，含状态标记、指标明细、豁免/边界说明 |
| `_get_cycle_head()` | 194~198 | 周期性行业返回 999（全量），正常行业返回 default |

### 2. 新增逻辑（check_quality 内）

**行业分类 + 数据窗口**（L253~262）
- 调用 `_classify_stock()` 获取行业分类
- 金融行业覆盖为 `financial` 分类
- 计算数据窗口年限，不足5年标注警告

**`head(N)` 全周期化**（8处）
- ROE L285 / 豁免A毛利率 L293 / FCF L316 / INTCOV L340
- 毛利率 L359 / OCF/NI L368 / OCF/NI L391 / 净利率 L412
- 全部改为 `_get_cycle_head(classification, N)`
- `head(1)`, `head(2)` 保留（豁免A/B 近2年判断）

**边界检测**（L487~514）
- 数据窗口不足
- 阈值附近指标：ROE 7-9%/毛利率 13-17%/净利率 4-6%
- ROE 波动率极端高（>2.0x）

**输出字段扩充**
- `exemptions`, `sector_type`, `sector_note`
- `data_window_years`, `data_window_note`
- `boundary_notes`, `formatted_summary`

### 3. 不变逻辑
- `_is_financial()` 双因素交叉验证不变
- 豁免 A/B/C 判定条件不变
- "fail-open" API 异常处理不变
- 缓存机制不变

## 与 SKILL.md 对比

| SKILL.md 要求 | 状态 | 实现方式 |
|---------------|------|----------|
| REIT 特殊处理 | ✅ | 代码 180xxx/508xxx 检测，ROE含重估备注 |
| 周期性行业全周期 | ✅ | ROE波动率>1.5x + 名称关键词，head(999)全量 |
| 数据"不足"标注 | ✅ | <5年标注"数据窗口不足" |
| 输出格式化 | ✅ | `formatted_summary` 含通过/豁免/边界明细 |
| 金融行业 | ✅ 已有 | 不变 |
| 7指标+3豁免 | ✅ 已有 | 不变 |

## 部署
- 本地 Mac: 已合并到 quality_screen.py
- 凤雏 10.26.0.7: 待 scp 推送
- 算力中心: 不相关（quality_screen 只在凤雏跑）
