#!/usr/bin/env python3
"""模拟持仓跟踪 — 自动买入谷底候选股，跟踪浮盈，峰顶附近卖出

用法:
  python3 portfolio_tracker.py                      # 执行一次跟踪（检查+交易）
  python3 portfolio_tracker.py --status              # 仅显示持仓状态
  python3 portfolio_tracker.py --reset               # 清零重置
  python3 portfolio_tracker.py --seed-capital 50000  # 设置初始资金
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data", "trades")
PORTFOLIO_PATH = os.path.join(DATA_DIR, "portfolio_tracker.json")
TRADES_PATH = os.path.join(DATA_DIR, "portfolio_trades.json")

# 交易参数
DEFAULT_CAPITAL = 50000          # 初始资金
MAX_POSITIONS = 5                # 最大同时持仓数
POSITION_SIZE_PCT = 0.20         # 每只仓位占比（20%）
TROUGH_THRESHOLD = 1.05          # 买入：现价/谷底 <= 1.05
PEAK_SELL_THRESHOLD = 0.95       # 卖出：现价/峰顶 >= 0.95（到达峰顶95%）
STOP_LOSS_PCT = -0.05            # 止损：-5%
PROFIT_TARGET_PCT = 0.08         # 止盈：+8%
MIN_CYCLE_DAYS = 5               # 最小持仓天数后才检查卖出


# ── 行情获取 ──

def fetch_prices(codes):
    """从腾讯接口获取实时行情"""
    symbols, code_map = [], {}
    for c in codes:
        c6 = str(c).zfill(6)
        prefix = "sh" if c6.startswith(("6", "9")) else "sz"
        sym = f"{prefix}{c6}"
        symbols.append(sym)
        code_map[sym] = c6

    results = {}
    for i in range(0, len(symbols), 80):
        batch = symbols[i:i + 80]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode("gbk")
            for line in raw.split(";"):
                line = line.strip()
                if "=" not in line or "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 5:
                    continue
                sym = parts[0].split("=")[0].strip().removeprefix("v_")
                if sym not in code_map:
                    continue
                code = code_map[sym]
                price = float(parts[3] or 0)
                pre_close = float(parts[4] or 0)
                chg_pct = round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0
                results[code] = {
                    "name": parts[1],
                    "price": price,
                    "pct": chg_pct,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "code": code,
                }
        except Exception as e:
            logger.debug(f"行情获取失败(batch {i}): {e}")
        time.sleep(0.05)

    return results


# ── 持仓状态 ──

def load_portfolio():
    """加载持仓状态"""
    if not os.path.exists(PORTFOLIO_PATH):
        return {
            "strategy": "portfolio_tracker",
            "initial_capital": DEFAULT_CAPITAL,
            "cash": DEFAULT_CAPITAL,
            "positions": [],
            "total_buy_value": 0,
            "total_sell_value": 0,
            "realized_pnl": 0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def save_portfolio(pf):
    """保存持仓状态"""
    os.makedirs(DATA_DIR, exist_ok=True)
    pf["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PORTFOLIO_PATH, "w") as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)


def load_trades():
    """加载交易记录"""
    if not os.path.exists(TRADES_PATH):
        return []
    with open(TRADES_PATH, "r") as f:
        return json.load(f)


def save_trades(trades):
    """保存交易记录"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TRADES_PATH, "w") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


# ── 核心逻辑 ──

def run_tracker(seed_capital: float = None):
    """执行一次完整的持仓跟踪"""
    pf = load_portfolio()
    if seed_capital is not None:
        pf["initial_capital"] = seed_capital
        pf["cash"] = seed_capital
        logger.info(f"初始资金已设为: {seed_capital:.0f}")

    # 加载周期数据
    stats = json.load(open(os.path.join(BASE_DIR, "data", "stock_cycle_stats.json")))
    logger.info(f"周期数据: {len(stats)} 只")

    # 获取有效股票（有谷峰数据）
    valid = {s["code"]: s for s in stats
             if s["n_cycles"] >= 3 and s["avg_trough"] > 0 and s["avg_peak"] > s["avg_trough"]}
    logger.info(f"有效: {len(valid)} 只")

    # 获取当前行情
    prices = fetch_prices(list(valid.keys()))
    logger.info(f"行情: {len(prices)} 只")

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    is_trading = 9 <= now.hour < 15

    # ── 检查持仓卖出条件 ──
    trades = load_trades()
    positions = pf.get("positions", [])
    closed_positions = []

    for pos in list(positions):
        code = pos["code"]
        code_data = valid.get(code)
        p = prices.get(code)

        if not p or p["price"] <= 0:
            continue

        price = p["price"]
        buy_price = pos["buy_price"]
        pnl_pct = (price - buy_price) / buy_price
        hold_days = pos.get("hold_days", 0) + 1

        # 更新浮盈
        pos["current_price"] = price
        pos["pnl_pct"] = round(pnl_pct * 100, 2)
        pos["hold_days"] = hold_days

        sell_reason = None

        # 检查卖出条件
        if code_data:
            # 到达峰顶附近
            peak = code_data["avg_peak"]
            if price >= peak * PEAK_SELL_THRESHOLD and hold_days >= MIN_CYCLE_DAYS:
                sell_reason = f"接近峰顶({price:.2f}/{peak:.2f})"
            # 谷底买入后反弹超目标
            elif pnl_pct >= PROFIT_TARGET_PCT:
                sell_reason = f"止盈({pnl_pct*100:.1f}%)"
        # 止损
        if pnl_pct <= STOP_LOSS_PCT:
            sell_reason = f"止损({pnl_pct*100:.1f}%)"

        if sell_reason:
            # 执行卖出
            shares = pos["shares"]
            sell_value = shares * price
            pf["cash"] += sell_value
            pf["total_sell_value"] += sell_value
            pnl_amount = (price - buy_price) * shares
            pf["realized_pnl"] += pnl_amount

            trade_record = {
                "code": code,
                "name": pos.get("name", code),
                "action": "sell",
                "date": today,
                "price": price,
                "shares": shares,
                "pnl_amount": round(pnl_amount, 2),
                "pnl_pct": round(pnl_pct * 100, 2),
                "hold_days": hold_days,
                "reason": sell_reason,
            }
            trades.append(trade_record)
            closed_positions.append(pos)
            logger.info(f"卖出 {code}({pos.get('name','')}): {sell_reason}")

    # 移除已平仓
    for cp in closed_positions:
        positions.remove(cp)

    # ── 检查买入条件 ──
    if is_trading and len(positions) < MAX_POSITIONS:
        # 按距谷底距离排序
        candidates = []
        for code, s in valid.items():
            if code in [p["code"] for p in positions]:
                continue
            p = prices.get(code)
            if not p or p["price"] <= 0:
                continue
            ratio = p["price"] / s["avg_trough"]
            if ratio <= TROUGH_THRESHOLD:
                upside = (s["avg_peak"] - p["price"]) / p["price"] * 100
                candidates.append({
                    "code": code,
                    "name": p["name"],
                    "price": p["price"],
                    "trough_ratio": ratio,
                    "upside_pct": round(upside, 1),
                })

        candidates.sort(key=lambda x: x["trough_ratio"])

        # 逐只买入
        for cand in candidates:
            if len(positions) >= MAX_POSITIONS:
                break

            code = cand["code"]
            price = cand["price"]
            # 计算买入股数
            alloc = pf["cash"] * POSITION_SIZE_PCT
            shares = int(alloc / price / 100) * 100
            if shares < 100:
                continue

            cost = shares * price
            if cost > pf["cash"] * 0.95:  # 留5%余量
                continue

            pf["cash"] -= cost
            pf["total_buy_value"] += cost
            pos = {
                "code": code,
                "name": cand["name"],
                "buy_date": today,
                "buy_price": price,
                "shares": shares,
                "cost": round(cost, 2),
                "current_price": price,
                "pnl_pct": 0.0,
                "hold_days": 0,
            }
            positions.append(pos)

            trade_record = {
                "code": code,
                "name": cand["name"],
                "action": "buy",
                "date": today,
                "price": price,
                "shares": shares,
                "cost": round(cost, 2),
                "reason": f"谷底买入(ratio={cand['trough_ratio']:.2f},空间+{cand['upside_pct']:.1f}%)",
            }
            trades.append(trade_record)
            logger.info(f"买入 {code}({cand['name']}): {price:.2f}x{shares}股={cost:.0f}元")

    pf["positions"] = positions
    save_portfolio(pf)
    save_trades(trades)

    # ── 输出状态 ──
    pos_value = sum(p["shares"] * p.get("current_price", p["buy_price"]) for p in positions)
    total = pf["cash"] + pos_value
    total_return = (total / pf["initial_capital"] - 1) * 100
    win_trades = [t for t in trades if t.get("action") == "sell" and t.get("pnl_amount", 0) > 0]
    loss_trades = [t for t in trades if t.get("action") == "sell" and t.get("pnl_amount", 0) <= 0]

    print(f"\n{'='*55}")
    print(f"  持仓跟踪 — {today} ({'交易中' if is_trading else '已收盘'})")
    print(f"{'='*55}")
    print(f"  初始资金: {pf['initial_capital']:.0f}")
    print(f"  现金余额: {pf['cash']:.2f}")
    print(f"  持仓市值: {pos_value:.2f}")
    print(f"  总资产:   {total:.2f}")
    print(f"  总收益:   {total_return:+.2f}%")
    print(f"  已实现盈亏: {pf['realized_pnl']:+.2f}")
    print(
        f"  累计交易: {len([t for t in trades if t['action']=='sell'])}笔完成"
        f" ({len(win_trades)}胜/{len(loss_trades)}负)"
    )

    if positions:
        print(f"\n  {'代码':8s} {'名称':10s} {'买入价':>8s} {'现价':>8s} {'浮盈':>7s} {'持仓':>4s}")
        print("  " + "-" * 45)
        for p in sorted(positions, key=lambda x: x["pnl_pct"]):
            icon = "🔴" if p["pnl_pct"] < -3 else ("🟡" if p["pnl_pct"] < 0 else "🟢")
            print(f"  {icon} {p['code']:8s} {p['name']:10s} {p['buy_price']:>8.2f} "
                  f"{p['current_price']:>8.2f} {p['pnl_pct']:>+6.1f}% {p['hold_days']:>3d}d")

    return pf


def show_status():
    """仅显示持仓状态"""
    pf = load_portfolio()
    positions = pf.get("positions", [])
    trades = load_trades()
    pos_value = sum(p["shares"] * p.get("current_price", p["buy_price"]) for p in positions)
    total = pf["cash"] + pos_value
    total_return = (total / pf["initial_capital"] - 1) * 100
    win_trades = [t for t in trades if t.get("action") == "sell" and t.get("pnl_amount", 0) > 0]
    loss_trades = [t for t in trades if t.get("action") == "sell" and t.get("pnl_amount", 0) <= 0]

    print(f"\n{'='*55}")
    print(f"  持仓状态")
    print(f"{'='*55}")
    print(f"  初始资金: {pf['initial_capital']:.0f}")
    print(f"  现金余额: {pf['cash']:.2f}")
    print(f"  持仓市值: {pos_value:.2f}")
    print(f"  总资产:   {total:.2f}")
    print(f"  总收益:   {total_return:+.2f}%")
    print(f"  已实现盈亏: {pf['realized_pnl']:+.2f}")
    print(
        f"  累计交易: {len([t for t in trades if t['action']=='sell'])}笔完成"
        f" ({len(win_trades)}胜/{len(loss_trades)}负)"
    )

    if positions:
        print(f"\n  {'代码':8s} {'名称':10s} {'买入价':>8s} {'现价':>8s} {'浮盈':>7s} {'持仓':>4s}")
        print("  " + "-" * 45)
        for p in sorted(positions, key=lambda x: x["pnl_pct"]):
            icon = "🔴" if p["pnl_pct"] < -3 else ("🟡" if p["pnl_pct"] < 0 else "🟢")
            print(f"  {icon} {p['code']:8s} {p['name']:10s} {p['buy_price']:>8.2f} "
                  f"{p['current_price']:>8.2f} {p['pnl_pct']:>+6.1f}% {p['hold_days']:>3d}d")

    return pf


def reset():
    """重置持仓"""
    pf = {
        "strategy": "portfolio_tracker",
        "initial_capital": DEFAULT_CAPITAL,
        "cash": DEFAULT_CAPITAL,
        "positions": [],
        "total_buy_value": 0,
        "total_sell_value": 0,
        "realized_pnl": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_portfolio(pf)
    if os.path.exists(TRADES_PATH):
        os.remove(TRADES_PATH)
    logger.info("持仓已重置")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟持仓跟踪")
    parser.add_argument("--status", action="store_true", help="仅显示持仓状态")
    parser.add_argument("--reset", action="store_true", help="清零重置")
    parser.add_argument("--seed-capital", type=float, default=None, help="设置初始资金")
    args = parser.parse_args()

    if args.reset:
        reset()
    elif args.status:
        show_status()
    else:
        run_tracker(seed_capital=args.seed_capital)
