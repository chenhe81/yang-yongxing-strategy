<!--
  版本: v1
  生成日期: 20260712
  修改内容: 神经网络信号 (Neural Signals) 从凤雏本地迁移到算力中心 183.131.24.109
  前序版本: 无
-->

# 神经网络信号迁移 — 算力中心 (183.131.24.109)

## 背景

`neural_signals.py` 原为框架预留存根（`detect()` 始终返回 0），从未实际使用。核心逻辑需 GPU 训练 MLP 预测市场方向，符合迁移到算力中心（RTX 5880 48GB）的条件。

## 迁移方案

算力中心 GPU 训练 + 凤雏 SSH 读取

### 架构变化

```
[之前] 凤雏本地: neural_signals.py (空存根, 始终返回 0)

[之后] 算力中心: neural_worker.py (交易日 09:10, GPU MLP 训练)
         ↓ JSON
       凤雏: _fetch_neural_status() → SSH 读取
```

### 文件清单

| 文件 | 位置 | 说明 |
|------|------|------|
| `macro_analysis/neural_worker.py` | 算力中心(cron) + git | 神经网络 Worker |
| `fengchu_auto_trader.py` | 凤雏(runtime) + git | 新增 `_fetch_neural_status()` |
| `src/tools/neural_signals.py` | 凤雏(runtime) + git | 新增 `fetch_remote_neural_status()` |

### 详细变更

#### neural_worker.py (算力中心)
- 路径: `/home/arcvideo/neural_analysis/neural_worker.py`
- 依赖: `torch` (已预装 CUDA 13.0) + `akshare numpy pandas`
- 输出: `/home/arcvideo/neural_analysis/output/latest.json`
- 数据: 上证指数日线 (akshare, 8679行, 1990-12-19~至今)
- 模型: 4维特征 (动量/波动率/价格位置/成交量) → 小型 MLP → 次日方向预测
- 设备: **CUDA** (NVIDIA RTX 5880 Ada Generation, 48GB VRAM)
- 训练: 8658 样本全部 GPU 训练，约 3 秒完成
- 当前输出: **中性** (neural_score=14/40, 上涨概率 47.96%, 验证准确率 52.71%)
- cron: `10 09 * * 1-5` CST (交易日 09:10，位于 HMM 和 GARCH 之后)

#### fengchu_auto_trader.py (凤雏)
- 新增 `_fetch_neural_status()`: 与 HMM/GARCH/PCA 相同的 SSH 缓存模式
- 缓存机制同原有模式：`_NEURAL_CACHE/_NEURAL_CACHE_DATE/_NEURAL_TRIED_TODAY`

#### neural_signals.py (凤雏)
- 模块 docstring 更新，标注迁移信息
- 新增 `fetch_remote_neural_status()` 模块级函数，用于独立 SSH 读取
- 原 `NeuralSignalDetector` 类保留向后兼容

### 算力中心完整 cron 任务表

```
时间   任务         数据源
──────────────────────────────────
09:00  HMM         上证指数
09:05  GARCH       上证指数
09:10  Neural      上证指数 (GPU)
09:40  PCA         凤雏股票池
15:10  Macro       多源宏观数据
```

### 部署状态

| 位置 | 文件 | 状态 |
|------|------|------|
| 算力中心 183.131.24.109 | neural_worker.py | ✅ 已部署 + 测试通过 + cron 配置 |
| 凤雏 10.26.0.7 | fengchu_auto_trader.py | ✅ 已更新 |
| 本地 Mac | src/tools/neural_signals.py | ✅ 已更新 |
| 本地 Mac | git (待提交) | ⏳ |
| 本地 Mac | 日记 | ✅ 本文件 |

### 验证结果

```
设备:        NVIDIA RTX 5880 Ada Generation (CUDA)
训练样本:    8658 (正:4542 负:4116)
Epochs:      100
上涨概率:    47.96%
信号:        中性 (score=14/40)
验证准确率:  52.71%
运行耗时:    ~3 秒
```
