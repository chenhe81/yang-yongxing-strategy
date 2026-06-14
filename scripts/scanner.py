"""
杨永兴短线战法 - 核心筛选引擎
九步过滤法：
0. 大盘环境判断（放量大跌则空仓）
1. 排除ST/非主板（只留主板票）
2. 今日涨幅 1%-5%（盈利空间充足但不追高）
3. 近20天有涨停记录（主力活跃，有人气）
4. 量比 ≥ 1.2（有资金关注）
5. 流通市值 50-200亿（盘子适中易撬动）
6. 换手率 5%-10%（健康换手，非出货）
7. 振幅 ≤ 8%（波动适中）
8. K线上方无压力（无长上影线）
9. 分时全天站均价线上方（买方主导，主力护盘）
"""

import logging
import datetime
import pandas as pd
from config import (
    RISE_MIN, RISE_MAX, MARKET_CAP_MIN, MARKET_CAP_MAX,
    TURNOVER_MIN, TURNOVER_MAX, VOLUME_RATIO_MIN, AMPLITUDE_MAX,
    LIMIT_UP_DAYS, MAIN_BOARD_ONLY, STOP_LOSS, FORCE_STOP_LOSS,
)
import data_fetcher as df_api

logger = logging.getLogger(__name__)


def is_main_board(code):
    """判断是否为主板股票"""
    if not MAIN_BOARD_ONLY:
        return True
    # 排除: 科创板688, 北交所8/4开头, 创业板300
    if code.startswith("688"):  # 科创板
        return False
    if code.startswith(("8", "4")):  # 北交所
        return False
    if code.startswith("300"):  # 创业板
        return False
    # 排除ST
    return True


def is_st_stock(name):
    """判断是否为ST股票"""
    if not name:
        return False
    return "ST" in name or "*ST" in name


class Scanner:
    """杨永兴九步过滤选股引擎"""

    def __init__(self):
        self.filter_log = []  # 记录每步过滤情况
        self.limit_up_cache = {}  # 涨停记录缓存

    def log_filter(self, step, action, count_before, count_after, reason=""):
        self.filter_log.append({
            "step": step,
            "action": action,
            "count_before": count_before,
            "count_after": count_after,
            "filtered": count_before - count_after,
            "reason": reason,
        })

    def scan(self, skip_intraday=False):
        """
        执行完整九步筛选
        参数 skip_intraday: 跳过分时数据检查（分时数据获取慢，可先跑前8步）
        返回: { candidates: list, market: dict, filter_log: list }
        """
        self.filter_log = []

        # ============ 步骤0：大盘环境判断 ============
        logger.info("===== 步骤0：大盘环境判断 =====")
        market_status = df_api.get_market_status()
        market_trend = df_api.get_market_trend()

        if market_status.get("is_crash"):
            logger.warning("⚠️ 大盘放量大跌，今日不操作！")
            return {
                "candidates": [],
                "market": {**market_status, **market_trend},
                "filter_log": self.filter_log,
                "warning": "大盘放量大跌，按规则应空仓",
            }

        # ============ 步骤1：获取全市场行情 ============
        logger.info("===== 步骤1：获取全市场实时行情 =====")
        all_stocks = df_api.get_realtime_quotes()
        if all_stocks.empty:
            logger.error("无法获取行情数据")
            return {"candidates": [], "market": market_trend, "filter_log": self.filter_log}

        total = len(all_stocks)
        logger.info(f"全市场共 {total} 只股票")

        # 排除非主板（ST排除留给SEPA步骤1，这里只过滤板块）
        all_stocks["is_main"] = all_stocks["code"].apply(is_main_board)
        stocks = all_stocks[all_stocks["is_main"]].copy()
        self.log_filter(1, "排除非主板（科创板/北交所/创业板）", total, len(stocks))

        # ============ 步骤2：涨幅范围 3%-5% ============
        logger.info("===== 步骤2：涨幅范围 3%-5% =====")
        before = len(stocks)
        stocks = stocks[
            (stocks["change_pct"] >= RISE_MIN) & (stocks["change_pct"] <= RISE_MAX)
        ].copy()
        self.log_filter(2, f"涨幅{RISE_MIN}%-{RISE_MAX}%", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤3：近20天有涨停记录 ============
        logger.info("===== 步骤3：涨停基因筛选 =====")
        before = len(stocks)

        # 获取涨停历史（只检查当前候选股，提高效率）
        candidate_codes = stocks["code"].tolist() if "code" in stocks.columns else []
        self.limit_up_cache = df_api.get_limit_up_history(days=LIMIT_UP_DAYS, target_codes=candidate_codes)
        limit_up_codes = set()
        for codes in self.limit_up_cache.values():
            limit_up_codes.update(codes)

        # 也加上今日涨停
        today_limit = df_api.get_limit_up_today()
        limit_up_codes.update(today_limit)

        stocks = stocks[stocks["code"].isin(limit_up_codes)].copy()
        self.log_filter(3, f"近{LIMIT_UP_DAYS}天有涨停", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤4：量比 ≥ 1 ============
        logger.info("===== 步骤4：量比筛选 =====")
        before = len(stocks)
        if "volume_ratio" in stocks.columns and stocks["volume_ratio"].notna().any():
            # 有量比数据时正常过滤，NaN的保留
            mask = (stocks["volume_ratio"] >= VOLUME_RATIO_MIN) | stocks["volume_ratio"].isna()
            stocks = stocks[mask].copy()
            self.log_filter(4, f"量比≥{VOLUME_RATIO_MIN}（含NaN保留）", before, len(stocks))
        else:
            self.log_filter(4, "量比数据缺失，跳过", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤5：流通市值 50-200亿 ============
        logger.info("===== 步骤5：流通市值筛选 =====")
        before = len(stocks)
        if "circ_mv_billion" in stocks.columns and stocks["circ_mv_billion"].notna().any():
            mask = (
                (stocks["circ_mv_billion"] >= MARKET_CAP_MIN) &
                (stocks["circ_mv_billion"] <= MARKET_CAP_MAX)
            ) | stocks["circ_mv_billion"].isna()
            stocks = stocks[mask].copy()
        self.log_filter(5, f"流通市值{MARKET_CAP_MIN}-{MARKET_CAP_MAX}亿", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤6：换手率 5%-10% ============
        logger.info("===== 步骤6：换手率筛选 =====")
        before = len(stocks)
        if "turnover_rate" in stocks.columns and stocks["turnover_rate"].notna().any():
            mask = (
                (stocks["turnover_rate"] >= TURNOVER_MIN) &
                (stocks["turnover_rate"] <= TURNOVER_MAX)
            ) | stocks["turnover_rate"].isna()
            stocks = stocks[mask].copy()
            self.log_filter(6, f"换手率{TURNOVER_MIN}-{TURNOVER_MAX}%（含NaN保留）", before, len(stocks))
        else:
            self.log_filter(6, "换手率数据缺失，跳过", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤7：成交量稳定放大筛选 ============
        logger.info("===== 步骤7：成交量稳定放大筛选 =====")
        before = len(stocks)
        # 杨永兴原文：把成交量忽高忽低的删掉，只留下成交量温和放大的
        # 当前实现：振幅过滤（振幅过大=波动风险高），成交量稳定性需历史数据暂用振幅替代
        if "amplitude" in stocks.columns:
            stocks = stocks[stocks["amplitude"] <= AMPLITUDE_MAX].copy()
            self.log_filter(7, f"成交量温和放大（振幅≤{AMPLITUDE_MAX}%）", before, len(stocks))
        else:
            self.log_filter(7, "振幅数据缺失，跳过", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤8：K线形态上方无压力 ============
        logger.info("===== 步骤8：K线形态筛选 =====")
        before = len(stocks)
        stocks = self._filter_kline_pressure(stocks)
        self.log_filter(8, "K线上方无压力", before, len(stocks))
        logger.info(f"剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks, market_trend)

        # ============ 步骤9：分时站均价线上方 ============
        if not skip_intraday:
            logger.info("===== 步骤9：分时均价线筛选 =====")
            before = len(stocks)
            stocks = self._filter_intraday(stocks)
            self.log_filter(9, "分时站均价线上方", before, len(stocks))
            logger.info(f"剩余 {len(stocks)} 只")

        return self._build_result(stocks, market_trend)

    def _filter_kline_pressure(self, stocks):
        """K线形态过滤：高位长上影线或短期支撑不明显的剔除"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = row["code"]
            try:
                kline = df_api.get_stock_kline(code, days=20)
                if kline.empty or len(kline) < 5:
                    result_codes.append(code)
                    continue

                # 检查近5日是否有长上影线（最高价远高于收盘价）
                recent = kline.head(5)
                has_long_shadow = False
                for _, krow in recent.iterrows():
                    if pd.notna(krow.get("high")) and pd.notna(krow.get("close")):
                        upper_shadow = (krow["high"] - krow["close"]) / krow["close"]
                        if upper_shadow > 0.03:  # 上影线超过3%
                            has_long_shadow = True
                            break

                if not has_long_shadow:
                    result_codes.append(code)

            except Exception:
                # 获取K线失败的暂时保留
                result_codes.append(code)

        return stocks[stocks["code"].isin(result_codes)].copy()

    def _filter_intraday(self, stocks):
        """分时数据过滤：全天站均价线上方"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = row["code"]
            try:
                intraday = df_api.get_intraday_data(code)
                # 只保留明确站均价线上方的
                if intraday.get("above_avg") is True:
                    result_codes.append(code)
                elif intraday.get("above_avg") is None:
                    # 数据缺失时保留，但标注
                    result_codes.append(code)
                # above_avg=False 的剔除
            except Exception:
                result_codes.append(code)

        return stocks[stocks["code"].isin(result_codes)].copy()

    def _build_result(self, stocks, market_info):
        """构建结果"""
        candidates = []
        for _, row in stocks.iterrows():
            candidate = {
                "code": str(row.get("code", "")),
                "name": str(row.get("name", "")),
                "price": float(row.get("price", 0) or 0),
                "change_pct": float(row.get("change_pct", 0) or 0),
                "volume_ratio": float(row.get("volume_ratio", 0) or 0),
                "turnover_rate": float(row.get("turnover_rate", 0) or 0),
                "circ_mv_billion": float(row.get("circ_mv_billion", 0) or 0),
                "amplitude": float(row.get("amplitude", 0) or 0),
                "amount": float(row.get("amount", 0) or 0),
            }
            candidates.append(candidate)

        return {
            "candidates": candidates,
            "market": market_info,
            "filter_log": self.filter_log,
            "scan_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_candidates": len(candidates),
        }
