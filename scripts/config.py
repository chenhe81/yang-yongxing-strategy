"""
杨永兴短线战法 - 配置参数
"""

# ============ 选股过滤参数 ============

# 涨幅范围（尾盘涨幅榜起始）
# 杨永兴原文：下午一点半查看涨幅排行榜，范围从1%以上开始
RISE_MIN = 1.0  # %
RISE_MAX = 5.0  # %

# 流通市值范围（亿元）
MARKET_CAP_MIN = 50.0
MARKET_CAP_MAX = 200.0

# 换手率范围
TURNOVER_MIN = 5.0  # %
TURNOVER_MAX = 10.0  # %

# 量比最低要求
# 杨永兴原文：量比≥1.2，最好1-5倍
VOLUME_RATIO_MIN = 1.2

# 振幅上限（超过则风险偏高）
AMPLITUDE_MAX = 8.0  # %

# 近N天有涨停记录
LIMIT_UP_DAYS = 20

# 只选主板（排除科创板688、北交所8/4、创业板300）
MAIN_BOARD_ONLY = True

# ============ 大盘环境参数 ============

# 上证指数代码
SH_INDEX_CODE = "000001"

# 大盘5日均线趋势判断：近N日均线方向
TREND_DAYS = 5

# ============ 卖出规则参数 ============

# 止损线（亏损%）
STOP_LOSS = 3.0

# 止损线2（亏损%强制）
FORCE_STOP_LOSS = 5.0

# ============ SEPA策略参数（米勒维尼《股票魔法师》） ============

# 最近季度营收同比增长率最低要求（%）
SEPA_REVENUE_GROWTH_MIN = 25.0

# 最近季度净利润同比增长率最低要求（%）
SEPA_PROFIT_GROWTH_MIN = 30.0

# ROE最低要求（%）
# SEPA原文：>17%（年化/TTM口径）
# A股实战：akshare同花顺年报ROE，10%已是优质公司门槛
SEPA_ROE_MIN = 10.0

# 近3年净利润复合增长率最低要求（%）
SEPA_PROFIT_CAGR_MIN = 20.0

# 上市最少天数（排除次新股）
SEPA_LISTING_MIN_DAYS = 365

# 均线参数
SEPA_MA_SHORT = 50    # 短期均线（日）
SEPA_MA_LONG = 150    # 长期均线（日）

# 量能参数
SEPA_VOL_SHORT = 10   # 短期均量（日）
SEPA_VOL_LONG = 120   # 长期均量（日）

# ============ 仓位管理参数 ============

# 单票最大仓位占比
MAX_POSITION_RATIO = 0.20

# 每日最大操作笔数
MAX_TRADES_PER_DAY = 3

# ============ OpenViking 上下文管理参数 ============

import os

# 是否启用 OpenViking 上下文管理（记忆、经验积累）
# 设为 true 后需要先启动 openviking-server
OPENVIKING_ENABLED = os.environ.get("OPENVIKING_ENABLED", "false").lower() == "true"

# OpenViking 服务地址
OPENVIKING_URL = os.environ.get("OPENVIKING_URL", "http://localhost:1933")

# 请求超时（秒）
OPENVIKING_TIMEOUT = int(os.environ.get("OPENVIKING_TIMEOUT", "5"))

# 自动召回记忆数（每轮对话最多注入N条相关记忆）
OPENVIKING_RECALL_LIMIT = int(os.environ.get("OPENVIKING_RECALL_LIMIT", "6"))

# 本地降级存储目录（OpenViking不可用时自动使用）
OPENVIKING_LOCAL_DIR = os.environ.get("OPENVIKING_LOCAL_DIR", "")

# ============ 路径配置（自动检测） ============

import os

# 基于脚本所在目录自动检测，无需硬编码
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = SCRIPTS_DIR
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
