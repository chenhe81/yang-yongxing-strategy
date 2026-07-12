#!/usr/bin/env python3
"""
基本面质量筛选模块 — 七指标去劣（东方财富 akshare，年报数据）

指标：
  ① 10年平均ROE ≥ 8%（豁免A：毛利率>30% + OCF为正 + 上市不足10年）
  ② 5年累计FCF > 0
  ③ 利息覆盖倍数 ≥ 2
  ④ 5年平均毛利率 ≥ 15%（豁免C：ROE>20% + OCF/NI>1.0，同时豁免⑥）
  ⑤ 5年平均OCF/净利润 ≥ 0.7
  ⑥ 10年平均净利率 ≥ 5%（豁免B：近来毛利率>30% + 净利率≥5%）
  ⑦ 5年股本稀释 ≤ 20%

  金融行业（银行/保险等）：自动检测，7项标记为 N/A 自动通过
  API 获取失败：fail-open，跳过筛选（不阻塞交易）

用法：
  from src.factors.quality_screen import check_quality
  result = check_quality("600519", "贵州茅台")
  if not result["pass"]:
      print(f"筛除: {result['fails']}")
"""
import time
import concurrent.futures
import akshare as ak
import pandas as pd
import numpy as np


# ── 内存缓存（同一次运行不重复请求） ──
_quality_cache = {}
# ── 行业分类相关 ──
_classification_cache = {}
_CYCLICAL_KEYWORDS = ["钢", "铁", "煤", "有色", "化工", "石化", "航运", "采矿",
                       "水泥", "玻璃", "造纸", "养殖", "猪肉", "航空", "石油",
                       "化纤", "化肥", "农药", "钢铁", "重工", "船舶", "机械"]




# ── 超时包装（防止 akshare 内部 requests 无 timeout 永远卡死） ──
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_AK_TIMEOUT = 20


def _ak_call(func, timeout=_AK_TIMEOUT):
    future = _executor.submit(func)
    return future.result(timeout=timeout)




def _derive_mkt(code: str) -> str:
    """根据股票代码推导市场后缀"""
    return "SH" if code.startswith("6") else "SZ"


def _is_financial(ind: pd.DataFrame) -> bool:
    """检测是否为金融行业（基于毛利率+净利率值）

    银行/保险公司不按常规口径计算销售毛利率：
      - XSMLL 列全部缺失（不披露）→ 金融
      - XSMLL < 1% 但 XSJLL 净利率 > 5% → 金融（低毛利+高净利=银行业务结构）
      - XSMLL < 1% 且 XSJLL ≤ 5% → 困境公司（非金融，正常执行筛选）
    """
    if ind is None or ind.empty:
        return False
    if "XSMLL" in ind.columns:
        vals = ind["XSMLL"].dropna().head(5)
        if len(vals) == 0:
            # XSMLL 全部缺失 → 金融行业（银行/保险不披露毛利率）
            return True
        if vals.mean() < 1:
            # 毛利率极低——可能是金融行业，也可能是经营困境
            if "XSJLL" in ind.columns:
                nm_vals = ind["XSJLL"].dropna().head(5)
                if len(nm_vals) > 0 and nm_vals.mean() > 5:
                    return True  # 毛利率低但净利率>5% → 金融行业
            # 有毛利率数据但净利率也低或无净利率数据 → 困境公司
            return False
    return False



def _classify_stock(code: str, name: str, ann: pd.DataFrame) -> dict:
    """对股票进行行业分类，缓存结果

    Returns:
        {"type": "normal"|"financial"|"reit"|"cyclical",
         "note": str,
         "roe_volatility": float}
    """
    cache_key = f"{code}|{name}"
    if cache_key in _classification_cache:
        return _classification_cache[cache_key]

    result = {"type": "normal", "note": "", "roe_volatility": 0.0}

    # 1. REIT 检测：中国公募REITs 代码 180xxx(SZ) / 508xxx(SH)
    if (code.startswith("180") and len(code) == 6) or (code.startswith("508") and len(code) == 6):
        result["type"] = "reit"
        result["note"] = "公募REITs，ROE含物业重估损益，需关注核心营运利润ROE"
        _classification_cache[cache_key] = result
        return result

    # 2. ROE 波动率检测（周期性行业特征：ROE大幅波动）
    if "ROEJQ" in ann.columns:
        roe_vals = ann["ROEJQ"].dropna()
        if len(roe_vals) >= 6:
            mean_roe = abs(roe_vals.mean())
            std_roe = roe_vals.std()
            if mean_roe > 1:
                vol = std_roe / mean_roe
                result["roe_volatility"] = round(vol, 2)
                if vol > 1.5:
                    result["type"] = "cyclical"
                    result["note"] = f"ROE波动率{vol:.1f}x均值，疑似周期性行业"

    # 3. 名称关键词辅助检测
    if result["type"] == "normal" and name:
        for kw in _CYCLICAL_KEYWORDS:
            if kw in name:
                result["type"] = "cyclical"
                result["note"] = f'疑似周期性行业（名称含"{kw}"）'
                break

    _classification_cache[cache_key] = result
    return result


def _format_quality_summary(code: str, name: str, r: dict) -> str:
    """生成格式化的质量筛选汇总文本"""
    lines = []
    display = f"{name}({code})" if name else code

    if r["pass"]:
        if r.get("sector_type") == "financial":
            tag = "🟡 金融豁免"
        elif r.get("exemptions"):
            tag = f"🟢 豁免通过({','.join(r['exemptions'])})"
        else:
            tag = "✅ 通过"
    else:
        tag = "❌ 排除"

    lines.append(f"# {tag} {display}")

    meta_parts = []
    if r.get("sector_type") and r["sector_type"] != "normal":
        meta_parts.append(f"行业类型: {r['sector_type']}")
    if r.get("sector_note"):
        meta_parts.append(r["sector_note"])
    if r.get("data_window_years"):
        meta_parts.append(f"数据窗口: {r['data_window_years']}年")
    if r.get("data_window_note"):
        meta_parts.append(f"⚠️ {r['data_window_note']}")
    if meta_parts:
        lines.append(f"  {' | '.join(meta_parts)}")

    label_map = {"ROE": "①ROE", "FCF": "②FCF", "INTCOV": "③利息覆盖",
                 "GM": "④毛利率", "OCF_NI": "⑤OCF/NI",
                 "NM": "⑥净利率", "DILUTION": "⑦稀释"}
    scores = r.get("scores", {})
    parts = []
    for key, label in label_map.items():
        val = scores.get(key)
        if val is None or val == "":
            parts.append(f"{label}:—")
        elif val == "N/A":
            parts.append(f"{label}:N/A")
        elif isinstance(val, (int, float)):
            if key == "FCF":
                parts.append(f"{label}:{val:.1f}亿")
            elif key == "INTCOV":
                parts.append(f"{label}:{val:.1f}x")
            elif key == "DILUTION":
                parts.append(f"{label}:{val:+.1f}%")
            else:
                parts.append(f"{label}:{val:.1f}%")
    lines.append(f"  {' | '.join(parts)}")

    fails = r.get("fails", [])
    if fails:
        lines.append(f"  未通过: {'; '.join(fails)}")

    boundaries = r.get("boundary_notes", [])
    if boundaries:
        for b in boundaries:
            lines.append(f"  ⚠️ 边界: {b}")

    return "\\n".join(lines)


def _get_cycle_head(classification: dict, default: int = 10) -> int:
    """周期性行业返回大值以覆盖全周期，正常行业返回 default"""
    if classification['type'] == 'cyclical':
        return 999
    return default


def check_quality(code: str, name: str = "", mkt: str = None) -> dict:
    """基本面七指标质量筛选

    Args:
        code: 股票代码，如 "600519"
        name: 股票名称（仅用于日志显示）
        mkt: 市场后缀 "SH"/"SZ"，为 None 时自动推导

    Returns:
        {"pass": bool, "fails": list[str], "scores": dict, "note": str}
        通过返回 {"pass": True, "fails": [], "scores": {...}}
        失败返回 {"pass": False, "fails": ["①...", "②..."], "scores": {...}}
        API错误返回 {"pass": True, "fails": [], "scores": {}, "note": "数据获取失败，跳过筛选"}
    """
    # 缓存命中
    if code in _quality_cache:
        return _quality_cache[code]

    if mkt is None:
        mkt = _derive_mkt(code)

    display = f"{name}({code})" if name else code

    # ── 1. 获取财务指标数据 ──
    symbol = f"{code}.{mkt}"
    try:
        df = _ak_call(lambda: ak.stock_financial_analysis_indicator_em(symbol=symbol))
        if df is None or df.empty:
            result = {"pass": True, "fails": [], "scores": {}, "note": f"{display} 财务数据为空，跳过筛选"}
            _quality_cache[code] = result
            return result
    except Exception as e:
        result = {"pass": True, "fails": [], "scores": {}, "note": f"{display} 数据获取失败: {e}"}
        _quality_cache[code] = result
        return result

    time.sleep(0.15)

    # 解析日期，筛选年报
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    ann = df[df["REPORT_TYPE"] == "年报"].copy()
    if len(ann) < 3:
        ann = df.copy()  # 年报不足则用全量
    ann = ann.sort_values("REPORT_DATE", ascending=False)

    # 计算年报数据年限（用于豁免A：上市不足10年判定）
    earliest_date = ann["REPORT_DATE"].min()
    years_available = (pd.Timestamp.now() - earliest_date).days / 365.25

    # ── 2. 金融行业检测 ──
    is_financial = _is_financial(ann)

    # ── 2.1 行业分类 + 数据窗口 ──
    classification = _classify_stock(code, name, ann)
    if is_financial:
        classification = {"type": "financial", "note": "金融行业", "roe_volatility": 0.0}
    data_window_years = round(years_available, 1) if years_available > 0 else 0
    data_window_note = ""
    if 0 < years_available < 5:
        data_window_note = f"数据窗口不足（仅{data_window_years}年），指标可靠性降低"


    # ── 3. 获取现金流量表（非金融行业需要） ──
    cf = None
    if not is_financial:
        try:
            cf_symbol = f"{mkt}{code}"
            cf_df = _ak_call(lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=cf_symbol))
            if cf_df is not None and not cf_df.empty:
                cf = cf_df[cf_df["REPORT_TYPE"] == "年报"].sort_values("REPORT_DATE", ascending=False)
        except Exception:
            cf = None
        time.sleep(0.15)

    # ── 4. 逐项打分 ──
    scores = {}
    fails = []
    exemptions = []

    # ① ROE（10年平均）— 列: ROEJQ
    if is_financial:
        scores["ROE"] = "N/A"
        status1 = "N/A"
    elif "ROEJQ" in ann.columns:
        vals = ann["ROEJQ"].dropna().head(_get_cycle_head(classification, 10))
        if len(vals) > 0:
            roe_val = vals.mean()
            scores["ROE"] = round(roe_val, 2)
            if roe_val >= 8:
                status1 = "PASS"
            else:
                # 豁免A：毛利率>30% + OCF为正
                gm_avg = ann["XSMLL"].dropna().head(_get_cycle_head(classification, 5)).mean() if "XSMLL" in ann.columns else 0
                ocf_pos = False
                if cf is not None and "NETCASH_OPERATE" in cf.columns:
                    ocf_val = cf["NETCASH_OPERATE"].dropna().head(1)
                    ocf_pos = (ocf_val.iloc[0] > 0) if len(ocf_val) > 0 else False
                if gm_avg > 30 and ocf_pos and years_available < 10 and not is_financial:
                    exemptions.append("A")
                    status1 = "PASS(E)"
                else:
                    status1 = "FAIL"
                    fails.append(f"①ROE={roe_val:.1f}%<8%")
        else:
            scores["ROE"] = None
            status1 = "SKIP"
    else:
        scores["ROE"] = None
        status1 = "SKIP"

    # ② FCF（5年累计）
    if is_financial:
        scores["FCF"] = "N/A"
        status2 = "N/A"
    elif cf is not None and len(cf) > 0:
        cf_5yr = cf.head(_get_cycle_head(classification, 5))
        fcf_vals = []
        for _, row in cf_5yr.iterrows():
            op_cf = float(row.get("NETCASH_OPERATE", 0) or 0)
            capex = float(row.get("CONSTRUCT_LONG_ASSET", 0) or 0)
            fcf_vals.append(op_cf - abs(capex))
        fcf_total = sum(fcf_vals)
        scores["FCF"] = round(fcf_total / 1e8, 2)
        if fcf_total > 0:
            status2 = "PASS"
        else:
            status2 = "FAIL"
            fails.append(f"②5年FCF={fcf_total/1e8:.1f}亿≤0")
    else:
        scores["FCF"] = None
        status2 = "SKIP"

    # ③ 利息覆盖倍数
    if is_financial:
        scores["INTCOV"] = "N/A"
        status3 = "N/A"
    elif "INTEREST_COVERAGE_RATIO" in ann.columns:
        vals = ann["INTEREST_COVERAGE_RATIO"].dropna()
        if len(vals) > 0:
            ic_val = vals.head(_get_cycle_head(classification, 3)).mean()
            scores["INTCOV"] = round(ic_val, 2)
            if ic_val >= 2:
                status3 = "PASS"
            else:
                status3 = "FAIL"
                fails.append(f"③利息覆盖={ic_val:.1f}x<2")
        else:
            scores["INTCOV"] = None
            status3 = "SKIP"
    else:
        scores["INTCOV"] = None
        status3 = "SKIP"

    # ④ 毛利率（5年平均）— 列: XSMLL
    if is_financial:
        scores["GM"] = "N/A"
        status4 = "N/A"
    elif "XSMLL" in ann.columns:
        vals = ann["XSMLL"].dropna().head(_get_cycle_head(classification, 5))
        if len(vals) > 0:
            gm_val = vals.mean()
            scores["GM"] = round(gm_val, 2)
            if gm_val >= 15:
                status4 = "PASS"
            else:
                roe_val = scores.get("ROE", 0)
                if isinstance(roe_val, (int, float)) and roe_val > 0:
                    ocf_ni_vals = ann["NCO_NETPROFIT"].dropna().head(_get_cycle_head(classification, 5)) if "NCO_NETPROFIT" in ann.columns else []
                    avg_ocf_ni = ocf_ni_vals.mean() if len(ocf_ni_vals) > 0 else 0
                    if roe_val > 20 and avg_ocf_ni > 1.0:
                        exemptions.append("C")
                        status4 = "PASS(E)"
                    else:
                        status4 = "FAIL"
                        fails.append(f"④毛利率={gm_val:.1f}%<15%")
                else:
                    status4 = "FAIL"
                    fails.append(f"④毛利率={gm_val:.1f}%<15%")
        else:
            scores["GM"] = None
            status4 = "SKIP"
    else:
        scores["GM"] = None
        status4 = "SKIP"

    # ⑤ OCF/净利润（5年平均）— 列: NCO_NETPROFIT
    if is_financial:
        scores["OCF_NI"] = "N/A"
        status5 = "N/A"
    elif "NCO_NETPROFIT" in ann.columns:
        vals = ann["NCO_NETPROFIT"].dropna().head(_get_cycle_head(classification, 5))
        if len(vals) > 0:
            ocf_ni_val = vals.mean()
            scores["OCF_NI"] = round(ocf_ni_val, 2)
            if ocf_ni_val >= 0.7:
                status5 = "PASS"
            else:
                status5 = "FAIL"
                fails.append(f"⑤OCF/NI={ocf_ni_val:.2f}<0.7")
        else:
            scores["OCF_NI"] = None
            status5 = "SKIP"
    else:
        scores["OCF_NI"] = None
        status5 = "SKIP"

    # ⑥ 净利率（10年平均）— 列: XSJLL
    if is_financial:
        scores["NM"] = "N/A"
        status6 = "N/A"
    elif "XSJLL" in ann.columns:
        vals = ann["XSJLL"].dropna().head(_get_cycle_head(classification, 10))
        if len(vals) > 0:
            nm_val = vals.mean()
            scores["NM"] = round(nm_val, 2)
            if nm_val >= 5:
                status6 = "PASS"
            else:
                # 豁免B：近来毛利率>30% + 近来净利率≥5%
                gm_recent = ann["XSMLL"].dropna().head(2).mean() if "XSMLL" in ann.columns else 0
                nm_recent = ann["XSJLL"].dropna().head(2).mean() if "XSJLL" in ann.columns else 0
                if gm_recent > 30 and nm_recent >= 5:
                    exemptions.append("B")
                    status6 = "PASS(E)"
                elif "C" in exemptions:
                    status6 = "PASS(E)"
                else:
                    status6 = "FAIL"
                    fails.append(f"⑥净利率={nm_val:.1f}%<5%")
        else:
            scores["NM"] = None
            status6 = "SKIP"
    else:
        scores["NM"] = None
        status6 = "SKIP"

    # ⑦ 5年股本稀释
    if is_financial:
        scores["DILUTION"] = "N/A"
        status7 = "N/A"
    else:
        try:
            abstract = _ak_call(lambda: ak.stock_financial_abstract(symbol=code))
            ni_row = abstract[abstract["指标"] == "归母净利润"]
            eps_row = abstract[abstract["指标"] == "基本每股收益"]
            if not ni_row.empty and not eps_row.empty:
                ni_data = ni_row.iloc[0]
                eps_data = eps_row.iloc[0]
                date_cols = sorted(
                    [c for c in abstract.columns if c not in ("选项", "指标") and len(str(c)) == 8],
                    reverse=True,
                )
                annual_dates = [c for c in date_cols if c.endswith("1231")]
                if len(annual_dates) >= 5:
                    latest = annual_dates[0]
                    prev = None
                    target_year = int(latest[:4]) - 5
                    for c in annual_dates:
                        if int(c[:4]) == target_year:
                            prev = c
                            break
                    if not prev and len(annual_dates) > 1:
                        prev = annual_dates[-1]
                    if prev and prev != latest:
                        curr_ni = float(ni_data[latest])
                        curr_eps = float(eps_data[latest])
                        prev_ni = float(ni_data[prev])
                        prev_eps = float(eps_data[prev])
                        if curr_eps > 0 and prev_eps > 0:
                            curr_shares = curr_ni / curr_eps
                            prev_shares = prev_ni / prev_eps
                            if prev_shares > 0:
                                dil = (curr_shares - prev_shares) / prev_shares * 100
                                scores["DILUTION"] = round(dil, 2)
                                if dil <= 20:
                                    status7 = "PASS"
                                else:
                                    status7 = "FAIL"
                                    fails.append(f"⑦股本稀释={dil:+.1f}%>20%")
        except Exception as _e:
            print(f"  ⚠️ {display} 股本稀释计算失败: {_e}", flush=True)
        if "DILUTION" not in scores or scores["DILUTION"] is None:
            scores["DILUTION"] = None
            status7 = "SKIP"
        time.sleep(0.15)

    boundary_notes = []

    # 数据窗口注明
    if data_window_note:
        boundary_notes.append(data_window_note)

    # 边界检测：ROE 在阈值附近（7-9%）
    roe_val = scores.get("ROE")
    if isinstance(roe_val, (int, float)) and 7 <= roe_val <= 9:
        boundary_notes.append(f"ROE={roe_val:.1f}%在阈值（8%）附近")

    # 边界检测：毛利率在阈值附近（13-17%）
    gm_val = scores.get("GM")
    if isinstance(gm_val, (int, float)) and 13 <= gm_val <= 17:
        boundary_notes.append(f"毛利率={gm_val:.1f}%在阈值（15%）附近")

    # 边界检测：净利率在阈值附近（4-6%）
    nm_val = scores.get("NM")
    if isinstance(nm_val, (int, float)) and 4 <= nm_val <= 6:
        boundary_notes.append(f"净利率={nm_val:.1f}%在阈值（5%）附近")

    # 边界检测：ROE 波动率极端高
    if classification.get("roe_volatility", 0) > 2.0:
        boundary_notes.append(
            f"ROE波动率极高（{classification['roe_volatility']:.1f}x），"
            f"虽已使用全周期数据，但阈值对周期股可能不适用"
        )

    # ── 5. 汇总 ──
    note_parts = []
    if is_financial:
        note_parts.append("金融行业")
    if exemptions:
        note_parts.append(f"豁免{','.join(exemptions)}")
    note = " | ".join(note_parts) if note_parts else ""

    # 豁免A（Costco模式）: 高毛利+OCF为正的次新股
    # 覆盖全部检查项——这类公司上市不足10年，传统质量指标不适用
    if "A" in exemptions:
        fails.clear()
        result_pass = True
    else:
        result_pass = len(fails) == 0

    result = {
        "pass": result_pass,
        "fails": fails,
        "scores": scores,
        "note": note,
        "exemptions": exemptions,
        "sector_type": classification["type"],
        "sector_note": classification["note"],
        "data_window_years": data_window_years,
        "data_window_note": data_window_note,
        "boundary_notes": boundary_notes,
        "formatted_summary": _format_quality_summary(code, name, {
            "pass": result_pass,
            "fails": fails,
            "scores": scores,
            "note": note,
            "exemptions": exemptions,
            "sector_type": classification["type"],
            "sector_note": classification["note"],
            "data_window_years": data_window_years,
            "data_window_note": data_window_note,
            "boundary_notes": boundary_notes,
        }),
    }
    _quality_cache[code] = result
    return result


def clear_cache():
    """清除质量筛选缓存（用于测试）"""
    _quality_cache.clear()
