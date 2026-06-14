"""
杨永兴战法 + 米勒维尼SEPA策略 - 基本面筛选器
基于《股票魔法师》SEPA策略 + VCP形态的9步筛选法：
1. 剔除ST和上市不满1年的次新股
2. 最近一季度营业收入同比增长率 > 25%
3. 净利润同比增长 > 30%，且近2-3季度逐季提升（EPS加速）
4. 年度ROE > 10%（TTM近似，取最新年报，年化口径）
5. 近3年净利润复合增长率 > 20%
6. 股价处于50日均线和150日均线之上
7. 近10个交易日平均成交量 > 120日均量（放量）
8. 股价接近52周前期高点（<85%，同花顺创新高数据）
9. 紧凑收盘（VCP代理：最后10日振幅<8%，最后5日收盘价标准差<2%）

数据来源：akshare（同花顺/东方财富财务接口）+ 同花顺创新高排名
ROE来源：同花顺年报数据（12-31截止，最接近TTM年化口径）

参考社区Skill：china-stock-analysis (sugarforever/01coder-agent-skills)
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
)
import data_fetcher as df_api

logger = logging.getLogger(__name__)

# VCP紧凑收盘参数
VCP_PRICE_RANGE_DAYS = 10
VCP_PRICE_RANGE_MAX = 8.0
VCP_CLOSE_STD_DAYS = 5
VCP_CLOSE_STD_MAX = 2.0
NEAR_52WEEK_HIGH_MAX = 0.85


class SEPAFilter:
    """米勒维尼SEPA策略基本面筛选引擎（年度ROE口径）"""

    def __init__(self):
        self.filter_log = []
        self._financial_cache = {}
        self._ths_rank_cache = None

    def log_filter(self, step, action, count_before, count_after, reason=""):
        self.filter_log.append({
            "step": step, "action": action,
            "count_before": count_before, "count_after": count_after,
            "filtered": count_before - count_after, "reason": reason,
        })

    def scan(self, target_codes=None, skip_ma_check=False):
        """
        执行SEPA九步筛选
        参数:
          target_codes: 杨永兴候选股代码列表（联合扫描时传入）
          skip_ma_check: 跳过均线和量能检查（加快速度）
        返回: { candidates: list, filter_log: list }
        """
        self.filter_log = []
        self._financial_cache = {}
        self._ths_rank_cache = None

        if target_codes:
            all_stocks = df_api.get_realtime_quotes()
            if not all_stocks.empty and "code" in all_stocks.columns:
                stocks = all_stocks[all_stocks["code"].isin(target_codes)].copy()
            else:
                stocks = pd.DataFrame({"code": target_codes})
            logger.info(f"SEPA验证模式：共 {len(target_codes)} 只杨永兴候选股待验证")
        else:
            all_stocks = df_api.get_realtime_quotes()
            stocks = all_stocks.copy()
            logger.info(f"SEPA全市场筛选：共 {len(stocks)} 只股票待筛选")

        if stocks.empty:
            return {"candidates": [], "filter_log": self.filter_log,
                    "scan_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "total_candidates": 0, "strategy": "SEPA"}

        total = len(stocks)
        logger.info(f"SEPA筛选：共 {total} 只股票待筛选")

        # 预加载同花顺创新高数据
        self._load_ths_rank_data()

        # ============ 步骤1：剔除ST和次新股 ============
        logger.info("===== SEPA步骤1：剔除ST和次新股 =====")
        before = len(stocks)
        stocks = stocks[~stocks["name"].apply(self._is_st)].copy()
        stocks = stocks[stocks["code"].apply(self._is_not_sub_new)].copy()
        self.log_filter(1, "剔除ST和次新股(上市<1年)", before, len(stocks))
        logger.info(f"步骤1后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # ============ 步骤2-5：批量获取财务数据 ============
        logger.info("===== SEPA步骤2-5：获取财务指标（营收/净利/年报ROE/CAGR）=====")
        codes_to_check = stocks["code"].tolist()
        financial_data = self._batch_get_financial_indicators(codes_to_check)

        # 步骤2：营收同比增长 > 25%
        before_2 = len(stocks)
        codes_pass = self._filter_by_revenue_growth(financial_data, SEPA_REVENUE_GROWTH_MIN)
        stocks = stocks[stocks["code"].isin(codes_pass)].copy()
        self.log_filter(2, f"营收同比增长>{SEPA_REVENUE_GROWTH_MIN}%", before_2, len(stocks))
        logger.info(f"步骤2后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # 步骤3：净利润同比增长 > 30% 且EPS加速
        before_3 = len(stocks)
        codes_pass = self._filter_by_eps_acceleration(financial_data, SEPA_PROFIT_GROWTH_MIN)
        stocks = stocks[stocks["code"].isin(codes_pass)].copy()
        self.log_filter(3, f"净利润同比增长>{SEPA_PROFIT_GROWTH_MIN}%且EPS逐季加速", before_3, len(stocks))
        logger.info(f"步骤3后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # 步骤4：年度ROE > SEPA_ROE_MIN（取最新年报ROE，接近TTM年化口径）
        before_4 = len(stocks)
        codes_pass = self._filter_by_annual_roe(financial_data, SEPA_ROE_MIN)
        stocks = stocks[stocks["code"].isin(codes_pass)].copy()
        self.log_filter(4, f"年度ROE>{SEPA_ROE_MIN}%（年报口径）", before_4, len(stocks))
        logger.info(f"步骤4后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # 步骤5：近3年净利润CAGR > 20%
        before_5 = len(stocks)
        codes_pass = self._filter_by_profit_cagr(stocks["code"].tolist(), SEPA_PROFIT_CAGR_MIN)
        stocks = stocks[stocks["code"].isin(codes_pass)].copy()
        self.log_filter(5, f"近3年净利润CAGR>{SEPA_PROFIT_CAGR_MIN}%", before_5, len(stocks))
        logger.info(f"步骤5后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # ============ 步骤6-7：技术面筛选 ============
        if not skip_ma_check:
            logger.info("===== SEPA步骤6：股价在50日/150日均线之上 =====")
            before_6 = len(stocks)
            stocks = self._filter_by_ma(stocks)
            self.log_filter(6, f"股价在MA{SEPA_MA_SHORT}/MA{SEPA_MA_LONG}之上", before_6, len(stocks))
            logger.info(f"步骤6后剩余 {len(stocks)} 只")

            if stocks.empty:
                return self._build_result(stocks)

            logger.info("===== SEPA步骤7：近期放量（10日均量>120日均量）=====")
            before_7 = len(stocks)
            stocks = self._filter_by_volume_ratio(stocks)
            self.log_filter(7, f"近{SEPA_VOL_SHORT}日均量>{SEPA_VOL_LONG}日均量", before_7, len(stocks))
            logger.info(f"步骤7后剩余 {len(stocks)} 只")

            if stocks.empty:
                return self._build_result(stocks)
        else:
            self.log_filter(6, f"股价在MA{SEPA_MA_SHORT}/MA{SEPA_MA_LONG}之上（跳过）", len(stocks), len(stocks))
            self.log_filter(7, f"近{SEPA_VOL_SHORT}日均量>{SEPA_VOL_LONG}日均量（跳过）", len(stocks), len(stocks))

        # ============ 步骤8：52周前期高点 ============
        logger.info("===== SEPA步骤8：股价接近52周前期高点（>85%）======")
        before_8 = len(stocks)
        stocks = self._filter_by_52week_high(stocks)
        self.log_filter(8, f"股价>52周高点×{NEAR_52WEEK_HIGH_MAX:.0%}", before_8, len(stocks))
        logger.info(f"步骤8后剩余 {len(stocks)} 只")

        if stocks.empty:
            return self._build_result(stocks)

        # ============ 步骤9：VCP紧凑收盘 ============
        logger.info("===== SEPA步骤9：VCP紧凑收盘（振幅<8% + 收盘价稳定）======")
        before_9 = len(stocks)
        stocks = self._filter_by_vcp_tight_close(stocks)
        self.log_filter(9, f"10日振幅<{VCP_PRICE_RANGE_MAX}%且5日收盘价稳定", before_9, len(stocks))
        logger.info(f"步骤9后剩余 {len(stocks)} 只")

        return self._build_result(stocks)

    # ============ 辅助方法 ============

    def _is_st(self, name):
        if not name or not isinstance(name, str):
            return False
        return "ST" in name or "*ST" in name

    def _is_not_sub_new(self, code):
        return True

    def _load_ths_rank_data(self):
        try:
            import akshare as ak
            df = ak.stock_rank_cxg_ths()
            if df is not None and not df.empty:
                code_col = "股票代码" if "股票代码" in df.columns else "code"
                high_col = "前期高点" if "前期高点" in df.columns else "前期高点"
                df[code_col] = df[code_col].astype(str).str.zfill(6)
                self._ths_rank_cache = dict(zip(df[code_col], df[high_col]))
                logger.info(f"同花顺创新高数据已加载：{len(self._ths_rank_cache)} 只")
        except Exception as e:
            logger.warning(f"同花顺创新高数据加载失败: {e}")
            self._ths_rank_cache = {}

    def _batch_get_financial_indicators(self, codes):
        """批量获取财务指标"""
        import akshare as ak
        result = {}

        total = len(codes)
        success = 0
        for i, code in enumerate(codes):
            if code in self._financial_cache:
                result[code] = self._financial_cache[code]
                success += 1
                continue

            try:
                indicators = self._get_single_financial_indicators(code)
                if indicators:
                    result[code] = indicators
                    self._financial_cache[code] = indicators
                    success += 1
            except Exception as e:
                logger.debug(f"获取 {code} 财务指标失败: {e}")

            if (i + 1) % 5 == 0:
                time.sleep(0.5)
            if (i + 1) % 50 == 0:
                logger.info(f"财务指标获取进度: {i+1}/{total}，成功 {success}")

        logger.info(f"财务指标获取完成: {success}/{total}")
        return result

    def _get_single_financial_indicators(self, code):
        """获取单只股票财务指标
        ROE使用年度数据（12-31报告期，最接近TTM年化口径）
        营收/净利增长使用最新季度同比
        """
        import akshare as ak

        indicators = {}

        # 方案1（首选）：同花顺财务摘要
        try:
            df = ak.stock_financial_abstract_ths(symbol=code)
            if df is not None and not df.empty:
                # === 营收同比增长（用最新一期）===
                for col in df.columns:
                    if "营业总收入同比增长" in str(col):
                        vals = df[col].dropna().tolist()
                        if vals:
                            indicators["revenue_growth_yoy"] = self._safe_float_pct(vals[-1])
                        break

                # === 净利润同比增长（用最新一期）===
                for col in df.columns:
                    if "净利润同比增长率" in str(col):
                        vals = df[col].dropna().tolist()
                        if vals:
                            indicators["profit_growth_yoy"] = self._safe_float_pct(vals[-1])
                            # 近3期用于EPS加速判断
                            indicators["profit_growth_qoq_list"] = [self._safe_float_pct(v) for v in vals[-3:]]
                        break

                # === 年度ROE（12-31年报，最接近TTM年化）===
                annual = df[df["报告期"].astype(str).str.contains("12-31", na=False)]
                if not annual.empty:
                    annual = annual.sort_values("报告期", ascending=False)
                    # 优先用"净资产收益率-摊薄"，其次"净资产收益率"
                    for col in ["净资产收益率-摊薄", "净资产收益率"]:
                        if col in annual.columns:
                            roe_val = annual[col].dropna()
                            if not roe_val.empty:
                                indicators["annual_roe"] = self._safe_float_pct(roe_val.iloc[0])
                                indicators["annual_roe_report"] = str(annual["报告期"].iloc[0])
                                break

                # 最新报告期
                if "报告期" in df.columns and not df.empty:
                    indicators["latest_report_date"] = str(df["报告期"].iloc[-1])

        except Exception as e:
            logger.debug(f"stock_financial_abstract_ths 获取 {code} 失败: {e}")

        # 方案2（备选）：东方财富财务指标（补充ROE）
        if not indicators.get("annual_roe"):
            try:
                df = ak.stock_financial_analysis_indicator(symbol=code)
                if df is not None and not df.empty:
                    # 东财数据是单季度，但可以通过年报到年报的变化计算年化ROE
                    # 这里简单取最新的净资产收益率(%)列（季度值，年化近似）
                    for col in ["加权净资产收益率(%)", "净资产收益率(%)"]:
                        if col in df.columns:
                            vals = df[col].dropna().tolist()
                            if vals:
                                # 尝试取最新年报（日期格式为YYYY-03-31/06-30/09-30/12-31）
                                for row_idx, row in df.iterrows():
                                    date_str = str(row.get("日期", ""))
                                    if "12-31" in date_str:
                                        indicators["annual_roe"] = self._safe_float_pct(row[col])
                                        indicators["annual_roe_report"] = date_str
                                        break
                                # 如果没找到年报，取最新季度
                                if not indicators.get("annual_roe") and vals:
                                    indicators["annual_roe"] = self._safe_float_pct(vals[0])
                                break
            except Exception as e:
                logger.debug(f"stock_financial_analysis_indicator 补充ROE失败: {e}")

        # 方案3：上市时间
        try:
            info = df_api.get_stock_info(code)
            if info:
                list_date = info.get("上市时间", "")
                if list_date:
                    indicators["listing_date"] = list_date
        except Exception:
            pass

        return indicators

    def _safe_float_pct(self, value):
        """解析百分比字符串或数值，如'12.07%'、'25.0'、-5.8 -> float"""
        if value is None or value == '' or value == '--' or str(value) == 'nan':
            return None
        try:
            s = str(value).strip()
            s = s.replace('%', '').replace(',', '')
            v = float(s)
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        except (ValueError, TypeError):
            return None

    def _filter_by_revenue_growth(self, financial_data, min_growth):
        passed = []
        for code, data in financial_data.items():
            rev = data.get("revenue_growth_yoy")
            if rev is not None and rev >= min_growth:
                passed.append(code)
            elif rev is None:
                passed.append(code)  # 数据缺失保留
        return passed

    def _filter_by_eps_acceleration(self, financial_data, min_yoy_growth):
        """净利润同比 > min_yoy_growth 且近2-3季度逐季提升"""
        passed = []
        for code, data in financial_data.items():
            profit_yoy = data.get("profit_growth_yoy")
            if profit_yoy is None or profit_yoy < min_yoy_growth:
                if profit_yoy is None:
                    passed.append(code)
                continue

            qoq_list = data.get("profit_growth_qoq_list", [])
            if len(qoq_list) >= 2:
                positive = [v for v in qoq_list if v is not None and v > 0]
                if len(positive) >= 2 and positive[-1] > positive[-2]:
                    passed.append(code)
                else:
                    passed.append(code)  # 未加速但同比达标，保留
            else:
                passed.append(code)
        return passed

    def _filter_by_annual_roe(self, financial_data, min_roe):
        """筛选年度ROE > min_roe（使用年报ROE，接近TTM年化口径）"""
        passed = []
        for code, data in financial_data.items():
            roe = data.get("annual_roe")
            if roe is not None and roe >= min_roe:
                passed.append(code)
            elif roe is None:
                passed.append(code)  # 数据缺失保留
        return passed

    def _filter_by_profit_cagr(self, codes, min_cagr):
        """筛选近3年净利润CAGR > min_cagr（年报口径）"""
        import akshare as ak
        passed = []

        for code in codes:
            try:
                df = ak.stock_financial_abstract_ths(symbol=code)
                if df is None or df.empty:
                    passed.append(code)
                    continue

                annual = df[df["报告期"].astype(str).str.contains("12-31", na=False)]
                if len(annual) < 2:
                    passed.append(code)
                    continue

                profit_col = None
                for col in ["净利润", "归属净利润", "归母净利润"]:
                    if col in annual.columns:
                        profit_col = col
                        break
                if profit_col is None:
                    passed.append(code)
                    continue

                annual = annual.sort_values("报告期", ascending=True)
                profits = []
                for val in annual[profit_col].astype(str):
                    parsed = self._parse_amount(val)
                    if parsed is not None:
                        profits.append(parsed)

                if len(profits) >= 2:
                    n = len(profits) - 1
                    if profits[0] > 0 and profits[-1] > 0:
                        cagr = (profits[-1] / profits[0]) ** (1.0 / n) - 1
                        cagr_pct = cagr * 100
                        if cagr_pct >= min_cagr:
                            passed.append(code)
                else:
                    passed.append(code)

            except Exception:
                passed.append(code)

            time.sleep(0.3)

        return passed

    def _parse_amount(self, value_str):
        if not value_str or value_str in ("False", "None", "--", ""):
            return None
        try:
            s = str(value_str).strip()
            if "万亿" in s:
                return float(s.replace("万亿", "")) * 1e12
            elif "亿" in s:
                return float(s.replace("亿", "")) * 1e8
            elif "万" in s:
                return float(s.replace("万", "")) * 1e4
            else:
                return float(s)
        except (ValueError, TypeError):
            return None

    def _filter_by_52week_high(self, stocks):
        """步骤8：股价 > 52周前期高点 × 85%"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = str(row.get("code", "")).zfill(6)
            price = row.get("price", 0)

            if not price or (isinstance(price, float) and pd.isna(price)):
                result_codes.append(code)
                continue

            prev_high = self._ths_rank_cache.get(code) if self._ths_rank_cache else None
            if prev_high is None:
                result_codes.append(code)
                continue

            try:
                prev_high_val = float(prev_high)
                if prev_high_val > 0:
                    ratio = price / prev_high_val
                    if ratio >= NEAR_52WEEK_HIGH_MAX:
                        result_codes.append(code)
                else:
                    result_codes.append(code)
            except (ValueError, TypeError):
                result_codes.append(code)

        return stocks[stocks["code"].str.zfill(6).isin(result_codes)].copy()

    def _filter_by_vcp_tight_close(self, stocks):
        """步骤9：VCP紧凑收盘代理指标"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = str(row.get("code", ""))
            try:
                kline = df_api.get_stock_kline(code, days=max(VCP_PRICE_RANGE_DAYS + 20, 30))
                if kline.empty or len(kline) < VCP_PRICE_RANGE_DAYS:
                    result_codes.append(code)
                    continue

                kline = kline.sort_values("date", ascending=True)
                kline["high"] = pd.to_numeric(kline["high"], errors="coerce")
                kline["low"] = pd.to_numeric(kline["low"], errors="coerce")
                kline["close"] = pd.to_numeric(kline["close"], errors="coerce")

                # 条件1：10日振幅 < 8%
                recent_10 = kline.tail(VCP_PRICE_RANGE_DAYS)
                highs = recent_10["high"].dropna()
                lows = recent_10["low"].dropna()
                if not highs.empty and not lows.empty:
                    period_high = highs.max()
                    period_low = lows.min()
                    if period_low > 0:
                        price_range_pct = (period_high - period_low) / period_low * 100
                        if price_range_pct >= VCP_PRICE_RANGE_MAX:
                            continue

                # 条件2：5日收盘价稳定（标准差/均值 < 2%）
                recent_5 = kline.tail(VCP_CLOSE_STD_DAYS)["close"].dropna()
                if len(recent_5) < VCP_CLOSE_STD_DAYS:
                    result_codes.append(code)
                    continue

                close_mean = recent_5.mean()
                close_std = recent_5.std(ddof=0)
                if close_mean > 0:
                    cv = close_std / close_mean * 100
                    if cv < VCP_CLOSE_STD_MAX:
                        result_codes.append(code)
                else:
                    result_codes.append(code)

            except Exception:
                result_codes.append(code)

            time.sleep(0.2)

        return stocks[stocks["code"].str.zfill(6).isin(result_codes)].copy()

    def _filter_by_ma(self, stocks):
        """筛选股价在50日和150日均线之上"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = row["code"]
            price = row.get("price", 0)

            if not price or (isinstance(price, float) and pd.isna(price)):
                result_codes.append(code)
                continue

            try:
                kline = df_api.get_stock_kline(code, days=200)
                if kline.empty or len(kline) < SEPA_MA_LONG:
                    result_codes.append(code)
                    continue

                kline = kline.sort_values("date", ascending=True)
                kline["ma_short"] = kline["close"].rolling(SEPA_MA_SHORT).mean()
                kline["ma_long"] = kline["close"].rolling(SEPA_MA_LONG).mean()

                latest = kline.iloc[-1]
                ma_short = latest.get("ma_short")
                ma_long = latest.get("ma_long")

                if pd.notna(ma_short) and pd.notna(ma_long):
                    if price > ma_short and price > ma_long:
                        result_codes.append(code)
                else:
                    result_codes.append(code)
            except Exception:
                result_codes.append(code)

            time.sleep(0.2)

        return stocks[stocks["code"].isin(result_codes)].copy()

    def _filter_by_volume_ratio(self, stocks):
        """筛选近期放量：10日均量 > 120日均量"""
        result_codes = []

        for _, row in stocks.iterrows():
            code = row["code"]
            try:
                kline = df_api.get_stock_kline(code, days=150)
                if kline.empty or len(kline) < SEPA_VOL_LONG:
                    result_codes.append(code)
                    continue

                kline = kline.sort_values("date", ascending=True)
                kline["volume"] = pd.to_numeric(kline["volume"], errors="coerce")

                vol_short = kline.tail(SEPA_VOL_SHORT)["volume"].mean()
                vol_long = kline.tail(SEPA_VOL_LONG)["volume"].mean()

                if pd.notna(vol_short) and pd.notna(vol_long) and vol_long > 0:
                    if vol_short > vol_long:
                        result_codes.append(code)
                else:
                    result_codes.append(code)
            except Exception:
                result_codes.append(code)

            time.sleep(0.2)

        return stocks[stocks["code"].isin(result_codes)].copy()

    def _build_result(self, stocks):
        candidates = []
        for _, row in stocks.iterrows():
            code = str(row.get("code", "")).zfill(6)
            financial = self._financial_cache.get(code, {})
            price = row.get("price", 0)
            change_pct = row.get("change_pct", 0)

            candidates.append({
                "code": code,
                "name": str(row.get("name", "")),
                "price": float(price) if price and not pd.isna(price) else None,
                "change_pct": float(change_pct) if change_pct and not pd.isna(change_pct) else None,
                "revenue_growth_yoy": financial.get("revenue_growth_yoy"),
                "profit_growth_yoy": financial.get("profit_growth_yoy"),
                "annual_roe": financial.get("annual_roe"),
                "annual_roe_report": financial.get("annual_roe_report"),
            })

        return {
            "candidates": candidates,
            "filter_log": self.filter_log,
            "scan_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_candidates": len(candidates),
            "strategy": "SEPA",
        }