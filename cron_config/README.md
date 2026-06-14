# 定时任务配置说明

采用**混合架构**：系统 cron 跑数据，OpenClaw cron 做汇报。

## 部署顺序

```
第1步：凤雏（10.26.0.7）→ 系统 cron
第2步：仲达（10.26.0.5）→ 系统 cron
第3步：孔明（本机）      → 系统 cron（需 ssh-copy-id）
第4步：OpenClaw（本机）  → openclaw cron add
```

## 快速部署

```bash
# 查看所有设备配置
bash scripts/setup_cron.sh

# 查看单个设备
bash scripts/setup_cron.sh fengchu
bash scripts/setup_cron.sh zhongda
bash scripts/setup_cron.sh kongming
bash scripts/setup_cron.sh openclaw
```

## 三设备系统 cron

### 凤雏（10.26.0.7）— 杨永兴隔夜套利
```cron
35 09 * * 1-5 cd ~/股票市场扫描规则 && python3 run_morning_sell.py >> logs/morning_sell.log
00 14 * * 1-5 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy fengchu >> logs/fengchu.log
```

### 仲达（10.26.0.5）— SEPA 基本面周筛
```cron
30 08 * * 1-5 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy zhongda --incremental >> logs/zhongda_daily.log
00 21 * * 0 cd ~/股票市场扫描规则 && python3 run_scan.py --strategy zhongda >> logs/zhongda_weekly.log
```

### 孔明（本机）— 数据聚合
```cron
30 15 * * 1-5 cd /path/to/project && scp chenhe@10.26.0.7:~/.../*.json output/fengchu/candidates/
35 15 * * 1-5 cd /path/to/project && scp chenhe@10.26.0.7:~/.../*.json data/trades/
00 16 * * 1-5 cd /path/to/project && python3 run_scan.py --compare
00 22 * * 0 cd /path/to/project && python3 run_scan.py --merge-pools
```

## OpenClaw 汇报层

### 凤雏早盘复盘（交易日 10:00）
```bash
openclaw cron add \
  --name "凤雏早盘复盘" \
  --cron "0 10 * * 1-5" \
  --session isolated \
  --message "读取 output/fengchu/trades/ 下最新交易记录，生成早盘卖出复盘报告" \
  --announce --channel feishu --to "user:me"
```

### 凤雏收盘复盘（交易日 15:30）
```bash
openclaw cron add \
  --name "凤雏收盘复盘" \
  --cron "30 15 * * 1-5" \
  --session isolated \
  --message "读取 output/fengchu/candidates/ 和 trades/ 下最新文件，生成收盘复盘报告" \
  --announce --channel feishu --to "user:me"
```

### 双策略周报（周日 22:30）
```bash
openclaw cron add \
  --name "双策略周报" \
  --cron "30 22 * * 0" \
  --session isolated \
  --message "读取 reports/comparison/ 下对比报告，生成周报" \
  --announce --channel feishu --to "user:me"
```
