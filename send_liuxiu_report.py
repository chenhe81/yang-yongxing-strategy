#!/usr/bin/env python3
"""
凤雏 — 发送刘秀市场日报

交易日 15:30 运行，获取刘秀的市场分析数据 + 本地雷达评分 + 组合状态，生成日报邮件。
内容直接写入邮件正文（不转发文件），发送至配置邮箱。

升级内容（2026-07-09）：
  1. 引入本地 calculate_radar_score()，提供详细维度拆解
  2. 引入本地 portfolio.json，展示组合概况
  3. 增强分析文本：策略推理 + 仓位解释 + 评分映射说明
  4. 重新设计 HTML 结构：雷达拆解 → 指数/板块 → 组合概况 → 策略逻辑 → 行情分析
"""
import json
import os
import smtplib
import subprocess
import sys
import yaml
from datetime import datetime
from email.mime.text import MIMEText

BASE = os.path.dirname(os.path.abspath(__file__))
EMAIL_CONFIG = os.path.join(BASE, "config", "email_config.yaml")
LIUXIU_MARKET_URL = "http://10.26.0.5:18001/api/codex/market-status"
LIUXIU_SCORE_URL = "http://10.26.0.5:18001/api/score/latest"
CACHE_DIR = os.path.join(BASE, "data", "computing_analysis")

# ── 本地数据源 ──

LOCAL_RADAR_AVAILABLE = False
try:
    sys.path.insert(0, BASE)
    from src.market_radar import calculate_radar_score
    LOCAL_RADAR_AVAILABLE = True
except ImportError:
    pass

PORTFOLIO_PATH = os.path.join(BASE, "data", "trades", "portfolio.json")


def load_local_radar() -> dict:
    """调用本地雷达评分，返回详细维度数据"""
    if not LOCAL_RADAR_AVAILABLE:
        return {}
    try:
        radar = calculate_radar_score()
        if radar and radar.get("score") is not None:
            return radar
    except Exception as e:
        print(f"  ⚠️ 本地雷达评分失败: {e}")
    return {}


def load_local_portfolio() -> dict:
    """读取本地组合状态"""
    if not os.path.exists(PORTFOLIO_PATH):
        return {}
    try:
        return json.load(open(PORTFOLIO_PATH, encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 读取组合数据失败: {e}")
    return {}

def pull_computing_results() -> None:
    """拉取算力中心最新分析结果到本地缓存"""
    ssh_key = os.path.expanduser("~/.ssh/id_bt")
    server = "arcvideo@183.131.24.109"
    port = 3100

    modules = {
        "hmm":   "/home/arcvideo/hmm_analysis/output/latest.json",
        "garch": "/home/arcvideo/garch_analysis/output/latest.json",
        "pca":   "/home/arcvideo/pca_analysis/output/latest.json",
        "neural":"/home/arcvideo/neural_analysis/output/latest.json",
        "macro": "/home/arcvideo/macro_analysis/output/latest.json",
    }

    for mod, remote_path in modules.items():
        cache_dir = os.path.join(BASE, "data", "computing_analysis", mod)
        os.makedirs(cache_dir, exist_ok=True)
        local_path = os.path.join(cache_dir, "latest.json")

        try:
            subprocess.run(
                ["scp", "-i", ssh_key, "-P", str(port),
                 "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
                 f"{server}:{remote_path}", local_path],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass


def load_computing_analysis() -> dict:
    """读取本地缓存的算力分析结果"""
    results = {}
    for mod in ("hmm", "garch", "pca", "neural", "macro"):
        path = os.path.join(BASE, "data", "computing_analysis", mod, "latest.json")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                with open(path, encoding="utf-8") as f:
                    results[mod] = json.load(f)
            except Exception:
                results[mod] = None
        else:
            results[mod] = None
    return results





def format_computing_analysis(comp: dict) -> str:
    """生成算力分析的 HTML 行"""
    rows = ""

    def _cell(label: str, value: str, detail: str = "") -> str:
        cell = '<tr>'
        cell += '<td style="padding:4px 8px;color:#888;width:80px">' + str(label) + '</td>'
        cell += '<td style="padding:4px 8px;font-weight:600">' + str(value) + '</td>'
        cell += '<td style="padding:4px 8px;color:#999;font-size:12px">' + str(detail) + '</td>'
        cell += '</tr>'
        return cell

    h = comp.get("hmm")
    if h:
        state = h.get("current_state_label", "?")
        conf = h.get("confidence", 0)
        score = h.get("hmm_score", "?")
        rows += _cell("HMM 市场状态", state, f"置信度{conf:.0%}  分={score}/40")
    else:
        rows += _cell("HMM 市场状态", "—", "暂无数据")

    g = comp.get("garch")
    if g:
        vol = g.get("pred_annual_vol_pct", "?")
        score = g.get("garch_score", "?")
        rows += _cell("GARCH 波动率", f"年化{vol}%", f"分={score}/25")
    else:
        rows += _cell("GARCH 波动率", "—", "暂无数据")

    p = comp.get("pca")
    if p:
        w = p.get("pca_weights_dict", {})
        ev = p.get("first_component_var_ratio", 0)
        parts = " / ".join(f"{k}={v:.0%}" for k, v in w.items())
        rows += _cell("PCA 因子权重", f"解释方差{ev:.0%}", f"权重: {parts}")
    else:
        rows += _cell("PCA 因子权重", "—", "暂无数据")

    n = comp.get("neural")
    if n:
        label = n.get("neural_score_label", "?")
        sig = n.get("signal", 0)
        sig_cn = "看多" if sig == 1 else "看空" if sig == -1 else "中性"
        conf = n.get("confidence", 0)
        rows += _cell("神经信号", f"{sig_cn}({label})", f"置信度{conf:.0%}")
    else:
        rows += _cell("神经信号", "—", "暂无数据")

    m = comp.get("macro")
    if m:
        ma = m.get("analysis", {})
        risk = ma.get("risk_level", "?")
        pos = ma.get("position_ratio", "?")
        rows += _cell("宏观分析", f"风险等级{risk}", f"建议仓位{pos}")
    else:
        rows += _cell("宏观分析", "—", "暂无数据")

    return rows


def format_portfolio_text(pf: dict) -> list:
    """从 portfolio.json 生成组合描述的段落列表"""
    lines = []
    pos_list = pf.get("positions") or []
    capital = pf.get("capital", 0)
    initial = pf.get("initial_capital", capital)
    realized = pf.get("realized_pnl", 0)
    total_trades = pf.get("total_trades", 0)

    total_asset = capital + sum(p.get("market_value", 0) for p in pos_list)
    pnl_pct = ((total_asset - initial) / initial * 100) if initial > 0 else 0

    lines.append(f"持仓 {len(pos_list)} 只，现金 {capital:,.0f} 元，总资产 {total_asset:,.0f} 元。")

    if pnl_pct >= 0:
        lines.append(f"累计盈亏：{pnl_pct:+.2f}%（已实现 {realized:+,.0f} 元），累计交易 {total_trades} 笔。")
    else:
        lines.append(f"累计盈亏：{pnl_pct:+.2f}%（已实现 {realized:+,.0f} 元），累计交易 {total_trades} 笔。")

    if pos_list:
        winners = [p for p in pos_list if (p.get("profit_pct") or 0) > 0]
        losers = [p for p in pos_list if (p.get("profit_pct") or 0) < 0]
        if winners:
            best = max(winners, key=lambda x: x.get("profit_pct", 0))
            lines.append(f"持仓中 {best.get('name','?')}({best.get('code','?')}) 表现最好（{best.get('profit_pct',0):+.2f}%），"
                         f"浮盈 {best.get('profit',0):+,.0f} 元。")
        if losers:
            worst = min(losers, key=lambda x: x.get("profit_pct", 0))
            lines.append(f"持仓中 {worst.get('name','?')}({worst.get('code','?')}) 表现最差（{worst.get('profit_pct',0):+.2f}%），"
                         f"浮亏 {worst.get('profit',0):+,.0f} 元。")
    else:
        lines.append("当前无持仓，全部资金为现金状态。")

    return lines


# ── 邮件配置 ──

def load_email_config() -> dict:
    cfg = {}
    if os.path.exists(EMAIL_CONFIG):
        with open(EMAIL_CONFIG) as f:
            cfg = yaml.safe_load(f) or {}
    return cfg


def send_email(config: dict, subject: str, html_body: str) -> bool:
    to_list = [a.strip() for a in config.get("to_addrs", "").split(",") if a.strip()]
    if not to_list or not config.get("smtp_server"):
        print("  ❌ SMTP 未配置，跳过发送")
        return False

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    from_addr = config.get("from_addr") or config.get("smtp_user", "")
    msg["From"] = f"凤雏 <{from_addr}>"
    msg["To"] = ", ".join(to_list)

    try:
        if config.get("use_ssl", True):
            server = smtplib.SMTP_SSL(config["smtp_server"], int(config.get("smtp_port", 465)), timeout=30)
        else:
            server = smtplib.SMTP(config["smtp_server"], int(config.get("smtp_port", 465)), timeout=30)
            server.starttls()
        server.login(config["smtp_user"], config["smtp_pass"])
        server.sendmail(from_addr, to_list, msg.as_string())
        server.quit()
        print(f"  ✅ 邮件已发送至: {', '.join(to_list)}")
        return True
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")
        return False


# ── 数据获取 ──

def fetch_market_status() -> dict:
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "15", LIUXIU_MARKET_URL],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:
        print(f"  ⚠️ 市场状态 API 调用失败: {e}")
    return {}


def fetch_enhanced_score() -> dict:
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "15", LIUXIU_SCORE_URL],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:
        print(f"  ⚠️ 评分 API 调用失败: {e}")
    return {}


# ── 程序化生成分析（无需 LLM） ──

def generate_analysis(market_data: dict, score_data: dict,
                      local_radar: dict, portfolio: dict) -> str:
    """从结构化数据生成市场分析文本
    Args:
        market_data: 刘秀 API 返回的行情数据
        score_data: 刘秀 API 返回的评分数据
        local_radar: 本地 calculate_radar_score() 返回的详细评分
        portfolio: 本地 portfolio.json 组合状态
    """
    lines = []

    mood_map = {"bullish": "偏多", "mild_up": "温和上涨", "sideways": "震荡",
                "mild_down": "温和下跌", "bearish": "偏空"}
    mood = market_data.get("mood", "")
    mood_cn = mood_map.get(mood, mood)

    indices = market_data.get("indices") or []
    if indices:
        up = sum(1 for i in indices if (i.get("pct") or 0) > 0)
        down = sum(1 for i in indices if (i.get("pct") or 0) < 0)
        best = max(indices, key=lambda x: x.get("pct") or 0)
        worst = min(indices, key=lambda x: x.get("pct") or 0)
        lines.append(
            f"今日A股市场整体{mood_cn}。{up}涨{down}跌，"
            f"{worst.get('name','?')}跌幅最大（{worst.get('pct',0):+.2f}%），"
            f"{best.get('name','?')}相对抗跌（{best.get('pct',0):+.2f}%）。"
        )

    avg_vr = sum((i.get("volume_ratio") or 0) for i in indices) / max(len(indices), 1)
    if avg_vr < 0.8:
        lines.append(f"成交量萎缩（平均量比{avg_vr:.2f}），市场观望情绪浓厚。")
    elif avg_vr > 1.2:
        lines.append(f"成交量放大（平均量比{avg_vr:.2f}），市场交投活跃。")
    else:
        lines.append(f"成交量温和（平均量比{avg_vr:.2f}），市场运行平稳。")

    top_sectors = market_data.get("top_sectors") or []
    if top_sectors:
        top_names = "、".join(
            s.get("name", "?") for s in top_sectors[:3] if (s.get("pct") or 0) > 0
        )
        if top_names:
            lines.append(f"领涨板块：{top_names}。")

    # ── 策略推理 ──
    radar = local_radar if local_radar else {}
    score = radar.get("score") or market_data.get("enhanced_score")
    strategy_raw = radar.get("strategy") or market_data.get("strategy_signal", "")
    strategy_cn = radar.get("strategy_cn", "")

    if strategy_cn:
        lines.append(f"策略映射：「{strategy_cn}」")
        if score:
            if score >= 70:
                lines.append(f"评分{score:.0f}/100（动量区），均线多头排列且趋势明确，以追踪趋势为主。")
            elif score >= 40:
                lines.append(f"评分{score:.0f}/100（均值回归区），市场多空拉锯，以高抛低吸为主。")
            else:
                lines.append(f"评分{score:.0f}/100（空仓区），市场风险偏高，以持币观望为主。")

    # ── 仓位解释 ──
    if portfolio:
        pos_list = portfolio.get("positions") or []
        position_ratio = radar.get("position_ratio")
        if position_ratio is not None:
            lines.append(f"建议仓位比例{position_ratio:.0%}（基于波动率校准）。")
        if not pos_list:
            lines.append("当前无持仓信号，凤雏按规则保持空仓。")
        elif len(pos_list) <= 3:
            lines.append(f"当前持有{len(pos_list)}只标的，仓位较轻，以试探性布局为主。")
        else:
            lines.append(f"当前持有{len(pos_list)}只标的，仓位分散。")

    return "\n\n".join(lines) if lines else "今日市场数据暂不可用。"


def _html_bar(ratio: float, color: str) -> str:
    """返回一段内联 SVG 条形（用于 HTML 维度可视化）"""
    pct = min(100, max(0, round(ratio * 100)))
    return (f'<div style="background:#eee;border-radius:4px;height:14px;width:100%;">'
            f'<div style="background:{color};width:{pct}%;height:14px;border-radius:4px;'
            f'transition:width 0.5s;"></div></div>')


# ── HTML 组装 ──

def build_html(market_data: dict, score_data: dict, analysis: str,
               local_radar: dict, portfolio: dict,
               computing_analysis: dict = None) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    # ── 指数行 ──
    idx_rows = ""
    for i in (market_data.get("indices") or [])[:6]:
        name = i.get("name", "?")
        price = i.get("price", "")
        pct = i.get("pct") or 0
        vr = i.get("volume_ratio") or 0
        color = "#4CAF50" if pct >= 0 else "#f44336"
        idx_rows += f"<tr><td>{name}</td><td>{price}</td><td style='color:{color};font-weight:600'>{pct:+.2f}%</td><td>{vr:.2f}</td></tr>"

    # ── 板块行 ──
    sec_rows = ""
    for s in (market_data.get("top_sectors") or [])[:7]:
        pct = s.get("pct") or 0
        color = "#4CAF50" if pct >= 0 else "#f44336"
        sec_rows += f"<tr><td>{s.get('name','?')}</td><td style='color:{color};font-weight:600'>{pct:+.2f}%</td></tr>"

    # ── 评分：优先本地雷达（更精确），其次刘秀 API ──
    mood = market_data.get("mood", "—")
    raw_score = market_data.get("enhanced_score")
    local_score = local_radar.get("score") if local_radar else None
    score_val = local_score if local_score is not None else (raw_score if raw_score is not None else "—")
    raw_strategy = market_data.get("strategy_signal")
    local_strategy = local_radar.get("strategy_cn") if local_radar else None
    strategy = local_strategy if local_strategy else (raw_strategy if raw_strategy else "—")

    # ── 本地雷达维度 ──
    dims_def = [
        ("趋势状态", "trend", 40, "#2196F3"),
        ("波动率", "volatility", 25, "#FF9800"),
        ("量价健康", "volume_health", 20, "#4CAF50"),
        ("市场情绪", "sentiment", 15, "#9C27B0"),
    ]
    radar_dims = local_radar.get("dimensions") or {}
    score_total = local_radar.get("score", score_val)

    dims_rows = ""
    for dname, dkey, dmax, dcolor in dims_def:
        dd = radar_dims.get(dkey, {})
        dscore = dd.get("score", 0) if isinstance(dd, dict) else 0
        dlabel = dd.get("label", "") if isinstance(dd, dict) else ""
        ratio = dscore / dmax if dmax > 0 else 0
        bar = _html_bar(ratio, dcolor)
        dscore_display = f"{dscore:.0f}" if isinstance(dscore, float) else str(dscore)
        dims_rows += (
            f"<tr>"
            f"<td style='padding:7px 8px;font-weight:600'>{dname}</td>"
            f"<td style='padding:7px 8px;text-align:center;font-size:18px;font-weight:700;color:{dcolor}'>{dscore_display}</td>"
            f"<td style='padding:7px 8px;text-align:center;color:#888;font-size:12px'>/ {dmax}</td>"
            f"<td style='padding:7px 8px;width:40%'>{bar}</td>"
            f"<td style='padding:7px 8px;color:#666;font-size:12px'>{dlabel}</td>"
            f"</tr>"
        )

    # 总分行
    score_float = score_val if isinstance(score_val, (int, float)) else 50
    total_color = "#f44336" if score_float < 40 else ("#FF9800" if score_float < 70 else "#4CAF50")
    total_bar = _html_bar(score_float / 100, total_color)

    strategy_hint = ""
    if isinstance(score_float, (int, float)):
        if score_float >= 70:
            strategy_hint = "动量趋势策略 · 趋势明确"
        elif score_float >= 40:
            strategy_hint = "均值回归策略 · 震荡操作"
        else:
            strategy_hint = "空仓观望 · 防御为主"

    # ── 组合概况 ──
    pf = portfolio if portfolio else {}
    pos_list = pf.get("positions") or []
    capital = pf.get("capital", 0)
    initial = pf.get("initial_capital", capital)
    realized = pf.get("realized_pnl", 0)

    total_asset = capital + sum(p.get("market_value", 0) for p in pos_list)
    pnl_pct = ((total_asset - initial) / initial * 100) if initial > 0 else 0
    pnl_color = "#4CAF50" if pnl_pct >= 0 else "#f44336"

    pos_rows = ""
    for p in pos_list:
        p_name = p.get("name", p.get("code", "?"))
        p_code = p.get("code", "")
        p_qty = p.get("quantity", 0)
        p_cost = p.get("cost", 0)
        p_price = p.get("current_price", 0)
        p_pct = p.get("profit_pct", 0)
        p_mv = p.get("market_value", 0)
        p_color = "#4CAF50" if p_pct >= 0 else "#f44336"
        pos_rows += (
            f"<tr>"
            f"<td style='padding:5px 6px'>{p_name}<span style='color:#aaa;font-size:11px'> {p_code}</span></td>"
            f"<td style='padding:5px 6px;text-align:right'>{p_qty}</td>"
            f"<td style='padding:5px 6px;text-align:right'>{p_cost:.2f}</td>"
            f"<td style='padding:5px 6px;text-align:right'>{p_price:.2f}</td>"
            f"<td style='padding:5px 6px;text-align:right;color:{p_color}'>{p_pct:+.2f}%</td>"
            f"<td style='padding:5px 6px;text-align:right'>{p_mv:,.0f}</td>"
            f"</tr>"
        )

    # ── 段落化分析 ──
    
    # ── 算力分析行 ──
    comp_rows = ""
    if computing_analysis:
        ca = computing_analysis
        comp_rows = format_computing_analysis(ca)

    paragraphs = "".join(
        f"<p style='margin:6px 0'>{p.strip()}</p>" for p in analysis.split("\n\n") if p.strip()
    )

    # ── 完整的 HTML ──
    html = f"""<html>
<body style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:680px;margin:0 auto;padding:20px;background:#f4f5f7">

<div style="background:#fff;border-radius:8px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.1)">

<div style="text-align:center;border-bottom:1px solid #eee;padding-bottom:16px;margin-bottom:20px">
<h1 style="font-size:24px;margin:0;color:#1a1a2e">📊 市场日报</h1>
<p style="color:#888;font-size:13px;margin:4px 0 0">{today} ｜ 刘秀分析 · 凤雏代发</p></div>

<table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:13px" cellspacing="0" cellpadding="0">
<tr>
<td style="background:#e8f5e9;padding:10px 12px;text-align:center;border-radius:6px;width:33%">
<div style="color:#666;font-size:11px;margin-bottom:2px">市场情绪</div>
<div style="font-weight:bold;font-size:18px">{mood}</div></td>
<td style="background:#e3f2fd;padding:10px 12px;text-align:center;border-radius:6px;width:33%">
<div style="color:#666;font-size:11px;margin-bottom:2px">雷达评分</div>
<div style="font-weight:bold;font-size:18px">{score_val}/100</div></td>
<td style="background:#fff3e0;padding:10px 12px;text-align:center;border-radius:6px;width:33%">
<div style="color:#666;font-size:11px;margin-bottom:2px">策略信号</div>
<div style="font-weight:bold;font-size:18px">{strategy}</div></td>
</tr></table>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">🎯 雷达评分拆解</h3>
<div style="background:#f8f9fa;padding:12px;border-radius:6px;margin-bottom:16px">
<p style="margin:0 0 6px;font-size:13px;color:#555">
总评 {score_val}/100 · {strategy_hint}</p>
<table style="width:100%;border-collapse:collapse;font-size:13px" cellspacing="0" cellpadding="0">
<tr style="background:#eee;font-size:12px;color:#666">
<th style="padding:6px 8px;text-align:left;font-weight:600">维度</th>
<th style="padding:6px 8px;text-align:center;font-weight:600">得分</th>
<th style="padding:6px 8px;text-align:center;font-weight:600">满分</th>
<th style="padding:6px 8px;text-align:left;font-weight:600">分布</th>
<th style="padding:6px 8px;text-align:left;font-weight:600">状态</th></tr>
{dims_rows}
<tr style="border-top:2px solid #ddd">
<td style="padding:8px 8px;font-weight:700">综合评分</td>
<td style="padding:8px 8px;text-align:center;font-size:20px;font-weight:700;color:{total_color}">{score_float:.0f}</td>
<td style="padding:8px 8px;text-align:center;color:#888;font-size:12px">/ 100</td>
<td style="padding:8px 8px">{total_bar}</td>
<td style="padding:8px 8px;color:{total_color};font-size:12px;font-weight:600">{strategy_hint}</td></tr>
</table></div>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">📈 指数表现</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px" cellspacing="0" cellpadding="0">
<tr style="background:#f5f5f5"><th style="padding:7px 8px;text-align:left;color:#555;font-weight:600">指数</th>
<th style="padding:7px 8px;text-align:right;color:#555;font-weight:600">点位</th>
<th style="padding:7px 8px;text-align:right;color:#555;font-weight:600">涨跌幅</th>
<th style="padding:7px 8px;text-align:right;color:#555;font-weight:600">量比</th></tr>
{idx_rows}</table>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">🏆 领涨板块</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px" cellspacing="0" cellpadding="0">
<tr style="background:#f5f5f5"><th style="padding:7px 8px;text-align:left;color:#555;font-weight:600">板块</th>
<th style="padding:7px 8px;text-align:right;color:#555;font-weight:600">涨幅</th></tr>
{sec_rows}</table>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">📋 组合概况</h3>
<div style="background:#f8f9fa;padding:12px;border-radius:6px;margin-bottom:16px">
<table style="width:100%;font-size:13px;margin-bottom:8px" cellspacing="0" cellpadding="0">
<tr><td style="padding:4px 8px;color:#888">持仓数量</td>
<td style="padding:4px 8px;font-weight:700">{len(pos_list)} 只</td>
<td style="padding:4px 8px;color:#888">可用现金</td>
<td style="padding:4px 8px;font-weight:700">{capital:,.0f}</td></tr>
<tr><td style="padding:4px 8px;color:#888">总资产</td>
<td style="padding:4px 8px;font-weight:700">{total_asset:,.0f}</td>
<td style="padding:4px 8px;color:#888">累计盈亏</td>
<td style="padding:4px 8px;font-weight:700;color:{pnl_color}">{pnl_pct:+.2f}%</td></tr>
<tr><td style="padding:4px 8px;color:#888">已实现盈亏</td>
<td style="padding:4px 8px;font-weight:700;color:{'#4CAF50' if realized>=0 else '#f44336'}">{realized:+,.0f}</td>
<td style="padding:4px 8px;color:#888">累计交易</td>
<td style="padding:4px 8px;font-weight:700">{pf.get('total_trades',0)} 笔</td></tr>
</table>
{"".join(f'''
<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:8px" cellspacing="0" cellpadding="0">
<tr style="background:#f0f0f0"><th style="padding:5px 6px;text-align:left">标的</th>
<th style="padding:5px 6px;text-align:right">数量</th>
<th style="padding:5px 6px;text-align:right">成本</th>
<th style="padding:5px 6px;text-align:right">现价</th>
<th style="padding:5px 6px;text-align:right">盈亏</th>
<th style="padding:5px 6px;text-align:right">市值</th></tr>
{pos_rows}</table>''' for _ in [1]) if pos_rows else
"<p style='color:#888;font-size:13px;margin:4px 0 0'>当前无持仓，全部资金为现金状态。</p>"}
</div>


<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">🧮 算力分析</h3>
<div style="background:#f0f4f8;padding:12px;border-radius:6px;margin-bottom:16px">
<p style="margin:0 0 6px;font-size:12px;color:#888">算力中心 (RTX 5880) 自动分析结果 · 交易日 09:00~15:10 更新</p>
<table style="width:100%;font-size:13px;border-collapse:collapse" cellspacing="0" cellpadding="0">
{comp_rows}</table></div>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">💡 策略逻辑</h3>
<div style="background:#fff8e1;padding:14px;border-radius:6px;margin-bottom:16px;line-height:1.8;font-size:13px;color:#444">
<p style="margin:0 0 6px"><strong>评分-策略映射：</strong></p>
<p style="margin:2px 0">• 70-100 分 → 动量趋势策略（趋势明确，追踪为主）</p>
<p style="margin:2px 0">• 40-69 分 → 均值回归策略（多空拉锯，高抛低吸）</p>
<p style="margin:2px 0">• 0-39 分 → 空仓观望（风险偏高，持币为主）</p>
<hr style="border:none;border-top:1px solid #eee;margin:8px 0">
<p style="margin:2px 0"><strong>当前判断：</strong></p>
<p style="margin:2px 0">今日评分 {score_val}/100，处于
{"动量趋势区间" if isinstance(score_val,(int,float)) and score_val >= 70 else 
 "均值回归区间" if isinstance(score_val,(int,float)) and score_val >= 40 else 
 "空仓观望区间"}。</p>
<p style="margin:2px 0">{"趋势维度占主导，建议跟随市场方向操作。" if isinstance(score_val,(int,float)) and score_val >= 70 else "市场方向不明确，注意控制仓位风险。" if isinstance(score_val,(int,float)) and score_val < 40 else "市场处于平衡状态，适合区间操作。"}</p>
{"" if not local_radar.get("position_ratio") else f'''
<hr style="border:none;border-top:1px solid #eee;margin:8px 0">
<p style="margin:2px 0"><strong>仓位建议：</strong></p>
<p style="margin:2px 0">建议持仓比例 {local_radar["position_ratio"]:.0%}，基于当前波动率水平校准。波动率越低可适当增仓，越高则减仓。</p>'''}
</div>

<h3 style="color:#1a1a2e;font-size:15px;margin:16px 0 10px">📝 行情分析</h3>
<div style="background:#f0f4f8;padding:16px;border-radius:6px;line-height:1.9;font-size:14px;color:#333">
{paragraphs}</div>

<p style="color:#aaa;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:12px;text-align:center">
凤雏自动发送 ｜ 数据来源：刘秀市场雷达 + 本地评分<br>投资有风险，入市需谨慎</p>

</div></body></html>"""
    return html


# ── 主流程 ──

def main():
    now = datetime.now()
    print(f"📋 刘秀市场日报 — {now.strftime('%Y-%m-%d %H:%M')}")

    print("  ⟳ 获取本地雷达评分...")
    local_radar = load_local_radar()
    if local_radar:
        print(f"  ✅ 本地评分={local_radar.get('score','?')}/100  "
              f"策略={local_radar.get('strategy_cn','?')}")
    else:
        print("  ⚠️ 本地雷达不可用，将使用刘秀 API 数据")

    print("  ⟳ 读取组合状态...")
    portfolio = load_local_portfolio()
    if portfolio:
        pos_count = len(portfolio.get("positions") or [])
        print(f"  ✅ 持仓{pos_count}只  资金={portfolio.get('capital',0):,.0f}")
    else:
        print("  ⚠️ 未读取到组合数据")

    print("  ⟳ 获取刘秀市场数据与评分...")
    market_data = fetch_market_status()
    score_data = fetch_enhanced_score()

    if market_data:
        cached = market_data.get("cached", False)
        print(f"  ✅ 情绪={market_data.get('mood','?')}  评分={market_data.get('enhanced_score','?')}/100  "
              f"策略={market_data.get('strategy_signal','?')}  {'(缓存)' if cached else '(实时)'}")
    else:
        print("  ⚠️ 未获取到市场数据")

    print("  ⟳ 生成分析文本...")
    analysis = generate_analysis(market_data, score_data, local_radar, portfolio)
    print(f"  ✅ 分析完成（{len(analysis)}字符）")

    print("  ⟳ 拉取算力中心分析结果...")
    pull_computing_results()
    computing_analysis = load_computing_analysis()
    ok_count = sum(1 for v in computing_analysis.values() if v is not None)
    print(f"  ✅ 算力分析: {ok_count}/5 模块就绪")

    html = build_html(market_data, score_data, analysis, local_radar, portfolio, computing_analysis)
    subject = f"[凤雏] 刘秀市场日报 — {now.strftime('%Y-%m-%d')}"

    config = load_email_config()
    send_email(config, subject, html)

    log_dir = os.path.join(BASE, "logs", "liuxiu_reports")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"report_{now.strftime('%Y%m%d_%H%M')}.html")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ 日志已保存: {log_path}")
    print(f"  ℹ️ 打开日志文件预览效果: open '{log_path}'")


if __name__ == "__main__":
    main()
