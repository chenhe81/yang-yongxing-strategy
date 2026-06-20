#!/usr/bin/env python3
"""实时监测：哪些国资股接近历史谷底，适合买入"""
import argparse, json, logging, os, sys, urllib.request, csv, time
from datetime import datetime
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def fetch_prices(codes):
    symbols, code_map = [], {}
    for c in codes:
        c6 = str(c).zfill(6)
        prefix = "sh" if c6.startswith(("6","9")) else "sz"
        sym = f"{prefix}{c6}"
        symbols.append(sym)
        code_map[sym] = c6
    results = {}
    for i in range(0, len(symbols), 80):
        batch = symbols[i:i+80]
        url = f"http://qt.gtimg.cn/q={','.join(batch)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode("gbk")
            for line in raw.split(";"):
                line = line.strip()
                if "=" not in line or "~" not in line: continue
                parts = line.split("~")
                if len(parts) < 5: continue
                sym = parts[0].split("=")[0].strip().removeprefix("v_")
                if sym not in code_map: continue
                code = code_map[sym]
                price = float(parts[3] or 0)
                pre_close = float(parts[4] or 0)
                chg_pct = round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0
                results[code] = {
                    "name": parts[1], "price": price, "pct": chg_pct,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "code": code,
                }
        except Exception as e:
            pass
        time.sleep(0.05)
    return results

def main():
    parser = argparse.ArgumentParser(description="实时监测国资股谷底买入机会")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--threshold", type=float, default=1.10,
                        help="当前价/谷价 <= 比例 (默认1.10=10)")
    parser.add_argument("--min-range", type=float, default=5.0,
                        help="最小谷峰幅度 (默认5)")
    parser.add_argument("--csv", action="store_true")
    args = parser.parse_args()

    stats = json.load(open(os.path.join(BASE_DIR, "data", "stock_cycle_stats.json")))
    logger.info(f"周期数据: {len(stats)}只")

    valid = [s for s in stats if s["n_cycles"] >= 3 and s["avg_cycle_days"] > 0
             and s["avg_trough"] > 0 and s["range_pct"] >= args.min_range]
    logger.info(f"有效: {len(valid)}只")
    codes = [s["code"] for s in valid]

    prices = fetch_prices(codes)
    logger.info(f"行情: {len(prices)}只")

    candidates = []
    for s in valid:
        p = prices.get(s["code"])
        if not p or p["price"] <= 0: continue
        ratio = p["price"] / s["avg_trough"]
        if ratio <= args.threshold:
            upside = (s["avg_peak"] - p["price"]) / p["price"] * 100
            candidates.append({
                "code": s["code"], "name": p["name"],
                "price": p["price"], "pct": p["pct"],
                "trough": s["avg_trough"], "peak": s["avg_peak"],
                "trough_ratio": round(ratio, 3),
                "range_pct": s["range_pct"],
                "upside_pct": round(upside, 1),
                "cycle_days": s["avg_cycle_days"],
                "win_rate": s["cycle_win_rate"],
            })

    candidates.sort(key=lambda x: (x["trough_ratio"], -x["upside_pct"]))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    mkt = "交易中" if 9 <= datetime.now().hour < 15 else "已收盘"

    print(f"\n{'='*65}")
    print(f"  国资股谷底扫描 — {now_str} ({mkt})")
    print(f"  阈值: 当前价 <= 谷底 x {args.threshold}")
    print(f"  范围: {len(prices)}/{len(codes)}只\n")

    if not candidates:
        print("  今日无符合条件股票")
        return

    print(f"  候选: {len(candidates)}只 (前{min(args.top, len(candidates))}):")
    print(f"  {'代码':8s} {'名称':10s} {'现价':>8s} {'涨跌':>7s} {'谷底':>8s} {'峰顶':>8s} {'距谷':>6s} {'空间':>7s} {'周期':>4s}")
    print("  " + "-" * 65)

    for c in candidates[:args.top]:
        icon = "🟢" if c["trough_ratio"] <= 1.02 else ("🟡" if c["trough_ratio"] <= 1.05 else "⚪")
        print(f"  {icon} {c['code']:8s} {c['name']:10s} {c['price']:>8.2f} {c['pct']:>+7.2f}% {c['trough']:>8.2f} {c['peak']:>8.2f} {c['trough_ratio']:>6.2f} {c['upside_pct']:>+6.1f}% {c['cycle_days']:>3d}d")

    top = candidates[0]
    print(f"\n  最优: {top['name']}({top['code']}) 现价{top['price']:.2f} 空间+{top['upside_pct']:.1f}%")

    if args.csv:
        path = os.path.join(BASE_DIR, "output", f"monitor_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["code","name","price","pct","trough","peak","trough_ratio","upside_pct","cycle_days","win_rate"])
            w.writeheader(); w.writerows(candidates)
        logger.info(f"CSV: {path}")

if __name__ == "__main__":
    main()
