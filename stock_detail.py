#!/usr/bin/env python3
"""个股周期可视化 — 展示单只国资股的历史谷峰、当前价、买卖点

用法:
  python3 stock_detail.py 600519            # 展示贵州茅台周期详情
  python3 stock_detail.py 000001 --top 5    # 展示平安银行+前5名候选
  python3 stock_detail.py --scan            # 扫描所有候选股
  python3 stock_detail.py --output-html     # 输出HTML可视化
"""
import argparse
import json
import logging
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_klines(code: str, days: int = 120) -> list:
    """从腾讯接口获取历史K线

    返回格式: [{"date":"2025-11-05","close":15.20,"high":15.50,"low":14.80,"volume":152000}, ...]
    """
    c6 = str(code).zfill(6)
    prefix = "sh" if c6.startswith(("6", "9")) else "sz"
    sym = f"{prefix}{c6}"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=kline&code={sym}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
        # 去掉 JSONP 包装
        if "=" in raw:
            raw = raw.split("=", 1)[1]
        if raw.endswith(";"):
            raw = raw[:-1]
        data = json.loads(raw)
    except Exception as e:
        logger.debug(f"腾讯K线接口失败: {e}, 尝试备用接口")

        # 备用：从本地数据库读
        try:
            sys.path.insert(0, BASE_DIR)
            from src.database import get_db

            db = get_db()
            df = db.get_klines(c6, days=days)
            if df.empty:
                return []
            result = []
            for _, r in df.iterrows():
                d = r["date"]
                ds = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                result.append({
                    "date": ds,
                    "close": float(r["close"]),
                    "high": float(r.get("high", r["close"])),
                    "low": float(r.get("low", r["close"])),
                    "volume": float(r.get("volume", 0)),
                    "amount": float(r.get("amount", 0)),
                })
            return result
        except Exception as e2:
            logger.debug(f"本地数据库也失败: {e2}")
            return []

    # 从腾讯响应解析
    klines = []
    try:
        qt_data = data.get("data", {})
        stock = qt_data.get(sym, {})
        # 日线在 qt 或 data 字段下
        for key in ("qt", "data"):
            day_data = stock.get(key, {}).get(sym, [])
            if day_data:
                for item in day_data:
                    if isinstance(item, list) and len(item) >= 6:
                        klines.append({
                            "date": item[0],
                            "close": float(item[2]),
                            "high": float(item[3]),
                            "low": float(item[4]),
                            "volume": float(item[5]) if len(item) > 5 else 0,
                        })
                break
    except Exception:
        pass

    return klines


def get_stock_name(code: str) -> str:
    """获取股票名称"""
    c6 = str(code).zfill(6)
    prefix = "sh" if c6.startswith(("6", "9")) else "sz"
    sym = f"{prefix}{c6}"
    url = f"http://qt.gtimg.cn/q={sym}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        raw = resp.read().decode("gbk")
        parts = raw.split("~")
        if len(parts) > 1:
            return parts[1]
    except Exception:
        pass
    return code


def analyze_stock(code: str, klines: list, cycle_stats: list = None) -> dict:
    """分析单只股票的谷峰和当前状态"""
    if not klines:
        return {"code": code, "error": "无K线数据"}

    closes = [k["close"] for k in klines]

    # 找周期谷峰（简单滑动窗口）
    n = len(closes)
    peaks, troughs = [], []
    window = 10  # 局部窗口

    for i in range(window, n - window):
        if closes[i] == max(closes[max(0, i - window):min(n, i + window + 1)]):
            peaks.append({"index": i, "date": klines[i]["date"], "price": closes[i]})
        if closes[i] == min(closes[max(0, i - window):min(n, i + window + 1)]):
            troughs.append({"index": i, "date": klines[i]["date"], "price": closes[i]})

    # 去重：剔除太近的峰/谷
    def dedup(points, min_gap=5):
        if not points:
            return []
        result = [points[0]]
        for p in points[1:]:
            if p["index"] - result[-1]["index"] >= min_gap:
                result.append(p)
        return result

    peaks = dedup(peaks)
    troughs = dedup(troughs)

    # 计算平均谷峰
    avg_peak = sum(p["price"] for p in peaks) / len(peaks) if peaks else 0
    avg_trough = sum(t["price"] for t in troughs) / len(troughs) if troughs else 0
    range_pct = (avg_peak - avg_trough) / avg_trough * 100 if avg_trough > 0 else 0

    # 找周期对
    cycles = []
    for p in peaks:
        # 找到这个峰前后最近的谷
        before = [t for t in troughs if t["index"] < p["index"]]
        after = [t for t in troughs if t["index"] > p["index"]]
        trough_before = before[-1] if before else None
        trough_after = after[0] if after else None
        if trough_before:
            days = p["index"] - trough_before["index"]
            ret = (p["price"] - trough_before["price"]) / trough_before["price"] * 100
            cycles.append({"trough_date": trough_before["date"],
                          "peak_date": p["date"],
                          "trough_price": trough_before["price"],
                          "peak_price": p["price"],
                          "days": days,
                          "return_pct": round(ret, 1)})

    # 当前价 vs 谷峰
    current_price = closes[-1] if closes else 0
    near_trough_ratio = current_price / avg_trough if avg_trough > 0 else 999
    near_peak_ratio = current_price / avg_peak if avg_peak > 0 else 999
    upside = (avg_peak - current_price) / current_price * 100 if current_price > 0 else 0

    # 从 cycle_stats 获取额外信息
    cycle_win_rate = 0
    n_cycles_from_stats = 0
    if cycle_stats:
        for s in cycle_stats:
            if s["code"] == code:
                cycle_win_rate = s.get("cycle_win_rate", 0)
                n_cycles_from_stats = s.get("n_cycles", 0)
                break

    today = datetime.now().strftime("%Y-%m-%d")

    return {
        "code": code,
        "name": klines[0].get("name", code),
        "current_price": round(current_price, 2),
        "avg_peak": round(avg_peak, 2),
        "avg_trough": round(avg_trough, 2),
        "range_pct": round(range_pct, 1),
        "near_trough_ratio": round(near_trough_ratio, 3),
        "near_peak_ratio": round(near_peak_ratio, 3),
        "upside_pct": round(upside, 1),
        "n_cycles": len(cycles),
        "cycle_win_rate": cycle_win_rate,
        "n_cycles_from_stats": n_cycles_from_stats,
        "avg_cycle_days": round(sum(c["days"] for c in cycles) / len(cycles), 1) if cycles else 0,
        "avg_return": round(sum(c["return_pct"] for c in cycles) / len(cycles), 1) if cycles else 0,
        "data_range": f"{klines[0]['date']} ~ {klines[-1]['date']}",
        "data_points": n,
        "analysis_date": today,
    }


def print_stock_detail(result: dict, klines: list = None):
    """打印个股详情"""
    if "error" in result:
        print(f"\n❌ {result['code']}: {result['error']}")
        return

    print(f"\n{'='*60}")
    print(f"  {result['name']} ({result['code']})")
    print(f"  分析日期: {result['analysis_date']}")
    print(f"  数据范围: {result.get('data_range', 'N/A')} ({result['data_points']}点)")
    print(f"{'='*60}")
    print(f"  当前价:    {result['current_price']:.2f}")
    print(f"  平均谷底:  {result['avg_trough']:.2f}")
    print(f"  平均峰顶:  {result['avg_peak']:.2f}")
    print(f"  振幅:      {result['range_pct']:.1f}%")
    print(f"  距谷底:    {result['near_trough_ratio']:.3f}x")
    print(f"  距峰顶:    {result['near_peak_ratio']:.3f}x")
    print(f"  上升空间:  {result['upside_pct']:+.1f}%")
    print(f"  周期数:    {result['n_cycles']}个")
    print(f"  平均周期:  {result['avg_cycle_days']:.0f}天")
    print(f"  平均收益:  {result['avg_return']:+.1f}%")
    print(f"  周期胜率:  {result['cycle_win_rate']:.0f}%")

    # 买卖建议
    if result["near_trough_ratio"] <= 1.05:
        at = "🟢" if result["near_trough_ratio"] <= 1.02 else "🟡"
        print(f"\n  {at} 买入信号: 距谷底仅{result['near_trough_ratio']:.2f}x, 空间+{result['upside_pct']:.1f}%")
    elif result["near_peak_ratio"] >= 0.95:
        print(f"\n  🔴 卖出信号: 接近峰顶, 距峰顶{result['near_peak_ratio']:.3f}x")
    else:
        print(f"\n  ⚪ 观望: 谷底{result['near_trough_ratio']:.2f}x, 峰顶{result['near_peak_ratio']:.2f}x")

    if klines:
        # 最近的几根K线
        print(f"\n  最近K线 (尾{min(5, len(klines))}条):")
        print(f"  {'日期':12s} {'收盘':>8s} {'最高':>8s} {'最低':>8s}")
        print("  " + "-" * 38)
        for k in klines[-5:]:
            print(f"  {k['date']:12s} {k['close']:>8.2f} {k['high']:>8.2f} {k['low']:>8.2f}")


def scan_candidates(top: int = 10, threshold: float = 1.10, min_range: float = 5.0):
    """扫描所有国资股，列出候选"""
    stats = json.load(open(os.path.join(BASE_DIR, "data", "stock_cycle_stats.json")))
    logger.info(f"周期数据: {len(stats)}只")

    # 获取行情
    symbols, code_map = [], {}
    for s in stats:
        c6 = str(s["code"]).zfill(6)
        prefix = "sh" if c6.startswith(("6", "9")) else "sz"
        sym = f"{prefix}{c6}"
        symbols.append(sym)
        code_map[sym] = s["code"]

    prices = {}
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
                prices[code] = float(parts[3] or 0)
        except Exception:
            pass

    logger.info(f"行情: {len(prices)}/{len(stats)}只")

    candidates = []
    for s in stats:
        if s["n_cycles"] < 3 or s["avg_trough"] <= 0 or s["range_pct"] < min_range:
            continue
        code = s["code"]
        price = prices.get(code)
        if not price or price <= 0:
            continue
        ratio = price / s["avg_trough"]
        if ratio <= threshold:
            upside = (s["avg_peak"] - price) / price * 100
            candidates.append({
                "code": code,
                "name": code,
                "price": price,
                "trough": s["avg_trough"],
                "peak": s["avg_peak"],
                "trough_ratio": round(ratio, 3),
                "range_pct": s["range_pct"],
                "upside_pct": round(upside, 1),
                "cycle_days": s["avg_cycle_days"],
                "win_rate": s["cycle_win_rate"],
            })

    candidates.sort(key=lambda x: (x["trough_ratio"], -x["upside_pct"]))

    print(f"\n{'='*55}")
    print(f"  国资股谷底候选扫描 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  阈值: 当前价 <= 谷底 x {threshold}")
    print(f"  候选: {len(candidates)}只")
    print(f"{'='*55}")
    if not candidates:
        print("  今日无符合条件的股票")
        return candidates

    print(f"  {'代码':8s} {'现价':>8s} {'谷底':>8s} {'峰顶':>8s} {'距谷':>6s} {'空间':>7s} {'胜率':>5s}")
    print("  " + "-" * 48)
    for c in candidates[:top]:
        icon = "🟢" if c["trough_ratio"] <= 1.02 else ("🟡" if c["trough_ratio"] <= 1.05 else "⚪")
        print(f"  {icon} {c['code']:8s} {c['price']:>8.2f} {c['trough']:>8.2f} "
              f"{c['peak']:>8.2f} {c['trough_ratio']:>6.2f} {c['upside_pct']:>+6.1f}% {c['win_rate']:>4.0f}%")

    return candidates


def generate_html(code: str, result: dict, klines: list) -> str:
    """生成HTML可视化"""
    if not klines or "error" in result:
        return f"<html><body><h2>{code} 无数据</h2></body></html>"

    # 构建价格数据
    dates = json.dumps([k["date"] for k in klines])
    closes = json.dumps([k["close"] for k in klines])

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{result['name']} ({result['code']}) 周期分析</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 1000px; margin: 20px auto; padding: 0 20px; background: #f5f5f5; }}
  .card {{ background: white; border-radius: 12px; padding: 24px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }}
  .stat-item {{ text-align: center; padding: 12px; background: #f8f9fa; border-radius: 8px; }}
  .stat-label {{ font-size: 12px; color: #666; }}
  .stat-value {{ font-size: 20px; font-weight: bold; }}
  #chart {{ width: 100%; height: 500px; }}
  h2 {{ margin-top: 0; }}
  .buy {{ color: #e74c3c; }}
  .sell {{ color: #27ae60; }}
  .neutral {{ color: #f39c12; }}
</style>
</head>
<body>
<div class="card">
  <h2>{result['name']} <span style="font-weight:normal;color:#666;">({result['code']})</span></h2>
  <p>分析日期: {result.get('analysis_date', '')} | 数据范围: {result.get('data_range', '')} ({result['data_points']}条)</p>
  <div class="stats">
    <div class="stat-item"><div class="stat-label">当前价</div><div class="stat-value">{result['current_price']:.2f}</div></div>
    <div class="stat-item"><div class="stat-label">平均谷底</div><div class="stat-value">{result['avg_trough']:.2f}</div></div>
    <div class="stat-item"><div class="stat-label">平均峰顶</div><div class="stat-value" style="color:#27ae60;">{result['avg_peak']:.2f}</div></div>
    <div class="stat-item"><div class="stat-label">振幅</div><div class="stat-value">{result['range_pct']:.1f}%</div></div>
    <div class="stat-item"><div class="stat-label">距谷底</div><div class="stat-value">{'🟢' if result['near_trough_ratio'] <= 1.02 else '🟡' if result['near_trough_ratio'] <= 1.05 else '⚪'} {result['near_trough_ratio']:.2f}x</div></div>
    <div class="stat-item"><div class="stat-label">上升空间</div><div class="stat-value" style="color:{'#e74c3c' if result['upside_pct'] > 0 else '#666'};">{result['upside_pct']:+.1f}%</div></div>
    <div class="stat-item"><div class="stat-label">周期数</div><div class="stat-value">{result['n_cycles']}</div></div>
    <div class="stat-item"><div class="stat-label">平均周期</div><div class="stat-value">{result['avg_cycle_days']:.0f}天</div></div>
    <div class="stat-item"><div class="stat-label">平均收益</div><div class="stat-value" style="color:#e74c3c;">{result['avg_return']:+.1f}%</div></div>
    <div class="stat-item"><div class="stat-label">周期胜率</div><div class="stat-value">{result['cycle_win_rate']:.0f}%</div></div>
  </div>
</div>
<div class="card">
  <div id="chart"></div>
</div>
<script>
  var chart = echarts.init(document.getElementById('chart'));
  var dates = {dates};
  var closes = {closes};
  var peaks = [];
  var troughs = [];

  // 找局部峰谷
  var windowSize = 10;
  for (var i = windowSize; i < closes.length - windowSize; i++) {{
    var maxVal = Math.max(...closes.slice(i - windowSize, i + windowSize + 1));
    var minVal = Math.min(...closes.slice(i - windowSize, i + windowSize + 1));
    if (closes[i] === maxVal) {{
      peaks.push({{"name": "峰", "coord": [dates[i], closes[i]]}});
    }}
    if (closes[i] === minVal) {{
      troughs.push({{"name": "谷", "coord": [dates[i], closes[i]]}});
    }}
  }}

  // 合并峰谷标注（去重）
  var markPoints = [];
  var seen = new Set();
  for (var p of peaks) {{
    var key = p.coord[0] + '_' + p.coord[1];
    if (!seen.has(key)) {{
      markPoints.push({{"name": "峰顶", "coord": p.coord, "itemStyle": {{"color": "#e74c3c"}}, "symbol": "pin", "symbolSize": 40}});
      seen.add(key);
    }}
  }}
  for (var t of troughs) {{
    var key = t.coord[0] + '_' + t.coord[1];
    if (!seen.has(key)) {{
      markPoints.push({{"name": "谷底", "coord": t.coord, "itemStyle": {{"color": "#3498db"}}, "symbol": "pin", "symbolSize": 40}});
      seen.add(key);
    }}
  }}

  var avgTrough = {result['avg_trough']:.2f};
  var avgPeak = {result['avg_peak']:.2f};

  chart.setOption({{
    title: {{ text: '{result['name']} 价格走势', left: 'center' }},
    tooltip: {{ trigger: 'axis' }},
    xAxis: {{ type: 'category', data: dates, axisLabel: {{ rotate: 45, fontSize: 10 }} }},
    yAxis: {{ type: 'value', scale: true }},
    series: [{{
      type: 'line',
      data: closes,
      smooth: true,
      lineStyle: {{ width: 2, color: '#2c3e50' }},
      areaStyle: {{ color: 'rgba(44,62,80,0.08)' }},
      markPoint: {{ data: markPoints }},
      markLine: {{
        silent: true,
        data: [
          {{ yAxis: avgTrough, label: {{ formatter: '谷底均价 {c}', color: '#3498db' }}, lineStyle: {{ color: '#3498db', type: 'dashed', width: 1.5 }} }},
          {{ yAxis: avgPeak, label: {{ formatter: '峰顶均价 {c}', color: '#e74c3c' }}, lineStyle: {{ color: '#e74c3c', type: 'dashed', width: 1.5 }} }}
        ]
      }}
    }}]
  }});
</script>
</body>
</html>"""
    return html


def get_code_name(code: str) -> str:
    """获取股票名称"""
    c6 = str(code).zfill(6)
    prefix = "sh" if c6.startswith(("6", "9")) else "sz"
    sym = f"{prefix}{c6}"
    url = f"http://qt.gtimg.cn/q={sym}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5)
        raw = resp.read().decode("gbk")
        parts = raw.split("~")
        if len(parts) > 1:
            return parts[1]
    except Exception:
        pass
    return code


def main():
    parser = argparse.ArgumentParser(description="国资股周期可视化")
    parser.add_argument("code", nargs="?", help="股票代码，如 600519")
    parser.add_argument("--scan", action="store_true", help="扫描所有候选股")
    parser.add_argument("--output-html", action="store_true", help="输出HTML可视化")
    parser.add_argument("--top", type=int, default=10, help="扫描显示数量")
    parser.add_argument("--threshold", type=float, default=1.10, help="谷底阈值")
    parser.add_argument("--min-range", type=float, default=5.0, help="最小振幅")
    args = parser.parse_args()

    if args.scan:
        scan_candidates(top=args.top, threshold=args.threshold, min_range=args.min_range)
        return

    if not args.code:
        # 默认展示最优候选
        scan_candidates(top=1, threshold=args.threshold, min_range=args.min_range)
        print("\n提示: 用 python3 stock_detail.py <股票代码> 查看个股详情")
        return

    code = str(args.code).zfill(6)
    stats = json.load(open(os.path.join(BASE_DIR, "data", "stock_cycle_stats.json")))
    name = get_code_name(code)

    klines = fetch_klines(code, days=120)
    if not klines:
        logger.warning(f"无法获取 {code} K线数据，从本地数据库补充")
        try:
            sys.path.insert(0, BASE_DIR)
            from src.database import get_db
            db = get_db()
            df = db.get_klines(code, days=120)
            if not df.empty:
                for _, r in df.iterrows():
                    d = r["date"]
                    ds = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    klines.append({
                        "date": ds,
                        "close": float(r["close"]),
                        "high": float(r.get("high", r["close"])),
                        "low": float(r.get("low", r["close"])),
                        "volume": float(r.get("volume", 0)),
                    })
        except Exception as e:
            logger.error(f"数据库读取失败: {e}")

    if klines:
        for k in klines:
            k["name"] = name
    result = analyze_stock(code, klines, cycle_stats=stats)
    result["name"] = name

    print_stock_detail(result, klines)

    if args.output_html:
        html = generate_html(code, result, klines)
        out_path = os.path.join(BASE_DIR, "output", f"stock_{code}_{datetime.now().strftime('%Y%m%d')}.html")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"HTML已保存: {out_path}")


if __name__ == "__main__":
    main()
