"""
杨永兴战法 + SEPA策略 联合扫描引擎
先杨永兴九步技术面筛选，再用SEPA基本面验证（顺序不可颠倒）

流程：
  第一阶段 - 杨永兴九步技术面筛选（快速缩小范围）：
    0. 大盘环境判断（放量大跌则空仓）
    1. 排除ST/非主板（只留主板票）
    2. 今日涨幅 1%-5%（盈利空间充足但不追高）
    3. 近20天有涨停记录（主力活跃，有人气）
    4. 量比 ≥ 1.2（有资金关注）
    5. 流通市值 50-200亿（盘子适中易撬动）
    6. 换手率 5%-10%（健康换手，非出货）
    7. 振幅 ≤ 8%（波动适中）
    8. K线上方无压力（无长上影线）
    9. 分时站均价线上方（买方主导，主力护盘）

  第二阶段 - SEPA基本面验证（对杨永兴候选股做精准财务验证，共9步）：
    1. 剔除ST和上市不满1年的次新股
    2. 营收同比增长 > 25%（超级增长门槛）
    3. 净利润同比增长 > 30%，且近2-3季度逐季提升（EPS加速）
    4. ROE > 17%（盈利效率高，SEPA原文优秀标准）
    5. 近3年净利润CAGR > 20%（业绩持续性强）
    6. 股价在50日/150日均线之上（中长期上升趋势）
    7. 近10日均量 > 120日均量（机构资金入场）
    8. 股价接近52周前期高点（>85%，同花顺创新高数据）
    9. VCP紧凑收盘（10日振幅<8% + 5日收盘价稳定，VCP代理指标）

  数据源：A股实时行情使用腾讯财经接口
"""

import logging
import datetime
import time
import math
import pandas as pd
import numpy as np
from config import (
    SEPA_REVENUE_GROWTH_MIN, SEPA_PROFIT_GROWTH_MIN, SEPA_ROE_MIN,
    SEPA_PROFIT_CAGR_MIN, SEPA_LISTING_MIN_DAYS, SEPA_MA_SHORT, SEPA_MA_LONG,
    SEPA_VOL_SHORT, SEPA_VOL_LONG,
    RISE_MIN, RISE_MAX, MARKET_CAP_MIN, MARKET_CAP_MAX,
    TURNOVER_MIN, TURNOVER_MAX, VOLUME_RATIO_MIN, AMPLITUDE_MAX,
    LIMIT_UP_DAYS,
)
from sepa_filter import SEPAFilter
from scanner import Scanner, is_st_stock
import data_fetcher as df_api
from openviking_adapter import OpenVikingAdapter

logger = logging.getLogger(__name__)


class CombinedScanner:
    """SEPA + 杨永兴 联合扫描引擎（集成OpenViking上下文管理）"""

    def __init__(self, openviking: OpenVikingAdapter = None):
        self.filter_log = []
        self.sepa_filter = SEPAFilter()
        self.scanner = Scanner()
        self.ov = openviking or OpenVikingAdapter()

    def log_filter(self, phase, step, action, count_before, count_after, reason=""):
        self.filter_log.append({
            "phase": phase,
            "step": step,
            "action": action,
            "count_before": count_before,
            "count_after": count_after,
            "filtered": count_before - count_after,
            "reason": reason,
        })

    def scan(self, skip_intraday=False, skip_ma_check=False, relax_yang=False):
        """
        执行杨永兴+SEPA联合扫描（顺序：杨永兴先 → SEPA后）

        参数:
          skip_intraday: 跳过杨永兴分时数据检查（加快速度）
          skip_ma_check: 跳过SEPA均线和量能检查（加快速度）
          relax_yang: 放宽杨永兴条件（涨幅不限、市值/换手率放宽）

        返回: {
            yang_candidates: list,      # 杨永兴技术面通过的候选股
            final_candidates: list,    # 双战法同时通过的最终候选
            filter_log: list,           # 完整筛选日志
            market: dict,               # 大盘环境
            scan_time: str,
            strategy: str,
        }
        """
        self.filter_log = []
        yang_candidates = []

        # ============ 第一阶段：杨永兴九步技术面筛选（快速缩小范围）============
        logger.info("=" * 60)
        logger.info("第一阶段：杨永兴九步技术面筛选")
        logger.info("=" * 60)

        yang_result = self.scanner.scan(skip_intraday=skip_intraday)
        yang_candidates = yang_result.get("candidates", [])
        yang_codes = set(c["code"] for c in yang_candidates)

        for log in self.scanner.filter_log:
            self.filter_log.append({
                "phase": "杨永兴",
                "step": log.get("step"),
                "action": log.get("action"),
                "count_before": log.get("count_before", 0),
                "count_after": log.get("count_after", 0),
                "filtered": log.get("filtered", 0),
                "reason": log.get("reason", ""),
            })

        logger.info(f"杨永兴筛选完成: {len(yang_candidates)} 只候选股")

        if not yang_candidates:
            logger.warning("杨永兴无候选股，联合扫描结束")
            return self._build_result([], [], {}, {}, "杨永兴筛选无候选股")

        # ============ 大盘环境判断（放量大跌则直接结束）============
        market_status = df_api.get_market_status()
        market_trend = df_api.get_market_trend()

        if market_status.get("is_crash"):
            logger.warning("大盘放量大跌，按杨永兴战法应空仓！")
            return self._build_result([], yang_candidates, market_trend, market_status, "大盘放量大跌，空仓")

        # ============ 第二阶段：SEPA基本面验证（对杨永兴候选股做精准验证）============
        logger.info("=" * 60)
        logger.info("第二阶段：SEPA基本面验证（9步筛选：1剔除ST次新 + 2营收>25% + 3EPS加速+净利>30% + 4ROE>17% + 5三年CAGR>20% + 6均线 + 7放量 + 8接近52周高点 + 9VCP紧凑收盘）")
        logger.info("=" * 60)

        # SEPA只对杨永兴候选股进行财务验证
        sepa_result = self.sepa_filter.scan(
            target_codes=list(yang_codes),
            skip_ma_check=skip_ma_check,
        )

        for log in self.sepa_filter.filter_log:
            self.filter_log.append({
                "phase": "SEPA",
                "step": log.get("step"),
                "action": log.get("action"),
                "count_before": log.get("count_before", 0),
                "count_after": log.get("count_after", 0),
                "filtered": log.get("filtered", 0),
            })

        sepa_candidates = sepa_result.get("candidates", [])
        logger.info(f"SEPA验证完成: {len(sepa_candidates)} 只候选股通过")

        # 最终结果：杨永兴 + SEPA 同时通过
        final_codes = set(c["code"] for c in sepa_candidates)
        final_candidates = [c for c in yang_candidates if c["code"] in final_codes]

        # 补充SEPA财务数据到最终候选
        financial_cache = self.sepa_filter._financial_cache
        for c in final_candidates:
            fin = financial_cache.get(c["code"], {})
            c["revenue_growth_yoy"] = fin.get("revenue_growth_yoy")
            c["profit_growth_yoy"] = fin.get("profit_growth_yoy")
            c["roe"] = fin.get("roe")

        logger.info(f"双战法同时通过: {len(final_candidates)} 只")

        result = self._build_result(
            final_candidates, yang_candidates, market_trend, market_status
        )

        # ============ OpenViking 上下文同步 ============
        if self.ov.available:
            self.ov.sync_scan_result(result)
            logger.info("📋 扫描结果已同步到OpenViking上下文数据库")

        return result

    def _filter_kline_pressure(self, stocks):
        """K线形态过滤：高位长上影线剔除"""
        result_codes = []
        for _, row in stocks.iterrows():
            code = row["code"]
            try:
                kline = df_api.get_stock_kline(code, days=20)
                if kline.empty or len(kline) < 5:
                    result_codes.append(code)
                    continue
                recent = kline.head(5)
                has_long_shadow = False
                for _, krow in recent.iterrows():
                    if pd.notna(krow.get("high")) and pd.notna(krow.get("close")):
                        upper_shadow = (krow["high"] - krow["close"]) / krow["close"]
                        if upper_shadow > 0.03:
                            has_long_shadow = True
                            break
                if not has_long_shadow:
                    result_codes.append(code)
            except Exception:
                result_codes.append(code)
            time.sleep(0.2)
        return stocks[stocks["code"].isin(result_codes)].copy()

    def _filter_intraday(self, stocks):
        """分时数据过滤：全天站均价线上方"""
        result_codes = []
        for _, row in stocks.iterrows():
            code = row["code"]
            try:
                intraday = df_api.get_intraday_data(code)
                if intraday.get("above_avg") is True or intraday.get("above_avg") is None:
                    result_codes.append(code)
            except Exception:
                result_codes.append(code)
        return stocks[stocks["code"].isin(result_codes)].copy()

    def _log_remaining_steps(self, start_step):
        """记录未执行的步骤"""
        step_names = {
            2: f"近{LIMIT_UP_DAYS}天有涨停", 3: f"量比≥{VOLUME_RATIO_MIN}",
            4: f"流通市值{MARKET_CAP_MIN}-{MARKET_CAP_MAX}亿",
            5: f"换手率{TURNOVER_MIN}-{TURNOVER_MAX}%", 6: f"振幅≤{AMPLITUDE_MAX}%",
            7: "K线上方无压力", 8: "分时站均价线上方",
        }
        for step in range(start_step, 9):
            self.log_filter("杨永兴", step, f"{step_names.get(step, '')}（前置淘汰）", 0, 0)

    def _build_candidates(self, stocks, financial_cache):
        """构建候选股列表（含SEPA基本面+杨永兴技术面数据）"""
        candidates = []
        for _, row in stocks.iterrows():
            code = str(row.get("code", ""))
            financial = financial_cache.get(code, {})

            def _float(val):
                try:
                    v = float(val)
                    return v if not (math.isnan(v) or math.isinf(v)) else None
                except:
                    return None

            candidate = {
                "code": code,
                "name": str(row.get("name", "")),
                "price": _float(row.get("price")),
                "change_pct": _float(row.get("change_pct")),
                # SEPA基本面
                "revenue_growth_yoy": financial.get("revenue_growth_yoy"),
                "profit_growth_yoy": financial.get("profit_growth_yoy"),
                "roe": financial.get("roe"),
                # 杨永兴技术面
                "volume_ratio": _float(row.get("volume_ratio")),
                "turnover_rate": _float(row.get("turnover_rate")),
                "circ_mv_billion": _float(row.get("circ_mv_billion")),
                "amplitude": _float(row.get("amplitude")),
                "pe": _float(row.get("pe")),
            }
            candidates.append(candidate)
        return candidates

    def _build_result(self, final_candidates, yang_candidates,
                      market=None, market_status=None, warning=""):
        """构建最终返回结果"""
        return {
            "yang_candidates": yang_candidates,
            "final_candidates": final_candidates,
            "filter_log": self.filter_log,
            "market": market or {},
            "market_status": market_status or {},
            "scan_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_final": len(final_candidates),
            "total_yang": len(yang_candidates),
            "strategy": "杨永兴+SEPA",
            "warning": warning or "",
        }