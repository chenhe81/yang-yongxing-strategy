"""
杨永兴短线战法 - 卖出信号检查
根据次日开盘情况判断卖出时机：
- 高开高走 / 平开高走 / 低开高走 → 破分时均价线或趋势线时卖出
- 平开平走 / 平开低走 → 破前低卖出
- 高开低走 / 低开低走 → 破前低卖出
- 止损线：亏损3%-5%强制离场
"""

import logging
import datetime
import json
import os
import data_fetcher as df_api
from config import PORTFOLIO_FILE, STOP_LOSS, FORCE_STOP_LOSS

logger = logging.getLogger(__name__)


def load_portfolio():
    """加载持仓"""
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_portfolio(data):
    """保存持仓"""
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def classify_open(current_price, pre_close):
    """
    分类开盘情况
    返回: "high_open" / "flat_open" / "low_open"
    """
    if pre_close <= 0:
        return "flat_open"
    pct = (current_price - pre_close) / pre_close * 100
    if pct > 0.5:
        return "high_open"
    elif pct < -0.5:
        return "low_open"
    else:
        return "flat_open"


def check_sell_signals():
    """
    检查所有持仓的卖出信号
    返回: list of dict，每个包含股票信息和卖出建议
    """
    portfolio = load_portfolio()
    if not portfolio:
        return {"signals": [], "message": "当前无持仓"}

    signals = []

    for position in portfolio:
        code = position.get("code", "")
        name = position.get("name", "")
        buy_price = position.get("buy_price", 0)
        buy_date = position.get("buy_date", "")

        if not code:
            continue

        signal = {
            "code": code,
            "name": name,
            "buy_price": buy_price,
            "buy_date": buy_date,
            "action": "hold",
            "reason": "",
            "urgency": "normal",  # normal / urgent / critical
        }

        # 获取实时行情
        try:
            all_quotes = df_api.get_realtime_quotes()
            stock_row = all_quotes[all_quotes["code"] == code]

            if stock_row.empty:
                signal["action"] = "unknown"
                signal["reason"] = "无法获取实时行情"
                signals.append(signal)
                continue

            row = stock_row.iloc[0]
            current_price = row.get("price", 0)
            pre_close = row.get("pre_close", 0)
            change_pct = row.get("change_pct", 0)

            signal["current_price"] = current_price
            signal["change_pct"] = change_pct
            signal["pre_close"] = pre_close

            # 计算盈亏
            if buy_price > 0:
                profit_pct = (current_price - buy_price) / buy_price * 100
                signal["profit_pct"] = round(profit_pct, 2)

                # ============ 强制止损 ============
                if profit_pct <= -FORCE_STOP_LOSS:
                    signal["action"] = "sell"
                    signal["reason"] = f"亏损{abs(profit_pct):.1f}%，超过强制止损线{FORCE_STOP_LOSS}%"
                    signal["urgency"] = "critical"
                    signals.append(signal)
                    continue

                if profit_pct <= -STOP_LOSS:
                    signal["action"] = "sell"
                    signal["reason"] = f"亏损{abs(profit_pct):.1f}%，触发止损线{STOP_LOSS}%"
                    signal["urgency"] = "urgent"
                    signals.append(signal)
                    continue

            # ============ 根据开盘情况判断 ============
            open_type = classify_open(current_price, pre_close)
            signal["open_type"] = open_type

            # 获取分时数据
            intraday = df_api.get_intraday_data(code)
            avg_price = intraday.get("avg_price")
            above_avg = intraday.get("above_avg")

            # 获取日K找前低
            kline = df_api.get_stock_kline(code, days=5)
            prev_low = kline["low"].min() if not kline.empty and "low" in kline.columns else None

            # 判断逻辑
            if open_type == "high_open":
                # 高开：关注是否破均价线
                if avg_price and current_price < avg_price:
                    signal["action"] = "sell"
                    signal["reason"] = f"高开但已跌破均价线({avg_price:.2f})，建议卖出"
                    signal["urgency"] = "urgent"
                else:
                    signal["action"] = "hold"
                    signal["reason"] = f"高开高走中，关注均价线({avg_price:.2f})支撑"

            elif open_type == "flat_open":
                # 平开：关注前低支撑
                if prev_low and current_price < prev_low:
                    signal["action"] = "sell"
                    signal["reason"] = f"平开且跌破前低({prev_low:.2f})，建议卖出"
                    signal["urgency"] = "urgent"
                elif above_avg is False:
                    signal["action"] = "sell"
                    signal["reason"] = "平开且运行在均价线下方，建议卖出"
                    signal["urgency"] = "normal"
                else:
                    signal["action"] = "watch"
                    signal["reason"] = "平开，关注前低和均价线支撑"

            elif open_type == "low_open":
                # 低开：最危险
                if prev_low and current_price < prev_low:
                    signal["action"] = "sell"
                    signal["reason"] = f"低开且跌破前低({prev_low:.2f})，必须卖出！"
                    signal["urgency"] = "critical"
                elif above_avg is False:
                    signal["action"] = "sell"
                    signal["reason"] = "低开且运行在均价线下方，建议卖出"
                    signal["urgency"] = "urgent"
                else:
                    signal["action"] = "watch"
                    signal["reason"] = "低开但尚未破位，密切关注"

        except Exception as e:
            signal["action"] = "error"
            signal["reason"] = f"检查异常: {e}"

        signals.append(signal)

    return {
        "signals": signals,
        "check_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(signals),
        "sell_count": len([s for s in signals if s["action"] == "sell"]),
    }
