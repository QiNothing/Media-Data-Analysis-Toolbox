"""
日报 / 周报 / 月报 自动生成
============================
对应 JD 标签「日报周报月报」和第 1 条「根据事先制定的 kpi 和指标对常规项目进行流程管理」。

核心思路：报告不是把数字堆出来，而是回答三个问题——
  1. 现在什么情况？（核心指标）
  2. 跟目标比怎么样？（KPI 达成 + 进度对比）
  3. 所以要做什么？（自动生成的洞察与行动建议）

第 3 点是最值钱的。这个模块会自动生成中文结论句，你在此基础上改，
比对着空白 PPT 发呆快得多。

输出：多 sheet 的 Excel（含格式），以及可直接粘贴的 Markdown 摘要。
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .config import load_benchmarks
from .metrics import cpm, cprp, impressions_from_grp

PERIOD_LABEL = {"daily": "日报", "weekly": "周报", "monthly": "月报"}


# =============================================================================
# 期间切分
# =============================================================================

def slice_period(
    df: pd.DataFrame,
    period: str,
    as_of: date | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    """把数据切成【本期】和【上期】。

    返回 (本期df, 上期df, 本期标签, 上期标签)

    daily   : 本期=as_of当天，       上期=前一天
    weekly  : 本期=as_of所在自然周，  上期=上一周
    monthly : 本期=as_of所在自然月，  上期=上一月
    """
    if "date" not in df.columns:
        raise ValueError("数据需要 date 列")

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"])
    if work.empty:
        return work, work, "", ""

    ref = pd.Timestamp(as_of) if as_of else work["date"].max().normalize()

    if period == "daily":
        cur_start = cur_end = ref.normalize()
        prev_start = prev_end = cur_start - timedelta(days=1)
        cur_label = f"{cur_start:%Y-%m-%d}"
        prev_label = f"{prev_start:%Y-%m-%d}"
    elif period == "weekly":
        cur_start = (ref - timedelta(days=ref.weekday())).normalize()
        cur_end = cur_start + timedelta(days=6)
        prev_start = cur_start - timedelta(days=7)
        prev_end = cur_start - timedelta(days=1)
        cur_label = f"{cur_start:%m/%d}~{cur_end:%m/%d}"
        prev_label = f"{prev_start:%m/%d}~{prev_end:%m/%d}"
    else:  # monthly
        cur_start = ref.replace(day=1).normalize()
        cur_end = (cur_start + pd.offsets.MonthEnd(1)).normalize()
        prev_start = (cur_start - pd.offsets.MonthBegin(1)).normalize()
        prev_end = (cur_start - timedelta(days=1)).normalize()
        cur_label = f"{cur_start:%Y-%m}"
        prev_label = f"{prev_start:%Y-%m}"

    cur = work[(work["date"] >= cur_start) & (work["date"] <= cur_end)]
    prev = work[(work["date"] >= prev_start) & (work["date"] <= prev_end)]
    return cur, prev, cur_label, prev_label


# =============================================================================
# 核心指标汇总
# =============================================================================

def core_metrics(df: pd.DataFrame, universe_wan: float | None = None) -> dict:
    """算一期数据的核心指标。缺哪个字段就跳过哪个指标，不报错。"""
    if df.empty:
        return {}

    bm = load_benchmarks()
    if universe_wan is None:
        key = bm.get("default_universe", "全国4+")
        universe_wan = float(bm.get("universe", {}).get(key, 130000))

    m: dict = {}
    if "cost" in df.columns:
        m["花费(元)"] = float(df["cost"].sum())
    if "spots" in df.columns:
        m["播出次数"] = float(df["spots"].sum())
    elif "cost" in df.columns:
        m["播出次数"] = float(len(df))

    # GRP：优先用原始列，没有就用 收视率×次数 现算
    if "grp" in df.columns and df["grp"].notna().any():
        m["GRP"] = float(df["grp"].sum())
    elif {"rating", "spots"}.issubset(df.columns):
        m["GRP"] = float((df["rating"] * df["spots"]).sum())

    if "GRP" in m and m["GRP"] > 0:
        if "花费(元)" in m:
            m["CPRP(元/点)"] = cprp(m["花费(元)"], m["GRP"])
        m["曝光(人次)"] = impressions_from_grp(m["GRP"], universe_wan)

    if "impressions" in df.columns and df["impressions"].notna().any():
        m["曝光(人次)"] = float(df["impressions"].sum())

    if "曝光(人次)" in m and "花费(元)" in m:
        m["CPM(元/千人次)"] = cpm(m["花费(元)"], m["曝光(人次)"])

    if "channel" in df.columns:
        m["投放频道数"] = int(df["channel"].nunique())
    if "duration" in df.columns and "spots" in df.columns:
        m["总时长(秒)"] = float((df["duration"] * df["spots"]).sum())

    return m


def compare_metrics(cur: dict, prev: dict) -> pd.DataFrame:
    """本期 vs 上期对比表，自动算变化率并打箭头。

    对成本类指标（CPRP/CPM），下降是好事，箭头方向要反过来——
    这个细节做对了，汇报时不会闹笑话。
    """
    cost_metrics = {"CPRP(元/点)", "CPM(元/千人次)"}
    rows = []
    for k in cur:
        c = cur.get(k)
        p = prev.get(k)
        if p in (None, 0) or (isinstance(p, float) and np.isnan(p)):
            chg, chg_pct, arrow = None, None, "—"
        else:
            chg = c - p
            chg_pct = chg / p * 100
            improving = (chg < 0) if k in cost_metrics else (chg > 0)
            if abs(chg_pct) < 0.5:
                arrow = "→ 持平"
            else:
                arrow = "↑ 向好" if improving else "↓ 转差"
                if k in cost_metrics:
                    arrow = ("↓ 向好" if chg < 0 else "↑ 转差")
        rows.append({
            "指标": k, "本期": c, "上期": p,
            "变化": chg,
            "变化率(%)": chg_pct,
            "评价": arrow,
        })
    return pd.DataFrame(rows)


# =============================================================================
# KPI 达成
# =============================================================================

def kpi_achievement(actual: dict, targets: dict, progress_pct: float | None = None) -> pd.DataFrame:
    """KPI 达成情况。

    参数
    ----
    actual   : 实际值 dict，来自 core_metrics
    targets  : 目标值 dict，key 要和 actual 对得上，如 {"GRP": 1200, "花费(元)": 5000000}
    progress_pct : 时间进度（%）。比如月报在 20 号出，时间进度 = 20/31 = 64.5%。
                   有这个数才能判断"进度是快了还是慢了"——只看完成率会误判。
    """
    grading = load_benchmarks().get("kpi_grading", {})
    cost_metrics = {"CPRP(元/点)", "CPM(元/千人次)"}

    rows = []
    for k, target in targets.items():
        if target in (None, 0):
            continue
        act = actual.get(k)
        if act is None:
            rows.append({"KPI": k, "目标": target, "实际": None, "完成率(%)": None,
                         "判定": "无数据", "进度评价": "-"})
            continue

        # 成本类指标：实际低于目标才是达成，完成率反着算
        rate = (target / act if k in cost_metrics and act else act / target) * 100

        if rate >= grading.get("达标", 1.0) * 100:
            verdict = "✅ 达标"
        elif rate >= grading.get("基本达标", 0.95) * 100:
            verdict = "🟡 基本达标"
        elif rate >= grading.get("预警", 0.85) * 100:
            verdict = "🟠 预警"
        else:
            verdict = "🔴 未达标"

        if progress_pct is None:
            pace = "-"
        else:
            gap = rate - progress_pct
            if gap > 5:
                pace = f"超前 {gap:.0f}pt"
            elif gap < -5:
                pace = f"滞后 {abs(gap):.0f}pt"
            else:
                pace = "符合进度"

        rows.append({"KPI": k, "目标": target, "实际": act,
                     "完成率(%)": rate, "判定": verdict, "进度评价": pace})
    return pd.DataFrame(rows)


# =============================================================================
# 维度拆解
# =============================================================================

def breakdown(df: pd.DataFrame, by: str, universe_wan: float | None = None) -> pd.DataFrame:
    """按某个维度（频道/时段/节目/素材）拆解核心指标，并排序。"""
    if by not in df.columns or df.empty:
        return pd.DataFrame()

    rows = []
    for key, grp in df.groupby(by, dropna=True):
        m = core_metrics(grp, universe_wan)
        m[by] = key
        rows.append(m)
    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    cols = [by] + [c for c in out.columns if c != by]
    out = out[cols]

    sort_col = "花费(元)" if "花费(元)" in out.columns else out.columns[1]
    out = out.sort_values(sort_col, ascending=False).reset_index(drop=True)

    if "花费(元)" in out.columns:
        total = out["花费(元)"].sum()
        out.insert(2, "花费占比(%)", out["花费(元)"] / total * 100 if total else 0)
    return out


# =============================================================================
# 自动洞察（这是最值钱的部分）
# =============================================================================

def auto_insights(
    cur: pd.DataFrame,
    prev: pd.DataFrame,
    cur_m: dict,
    prev_m: dict,
    kpi_df: pd.DataFrame | None = None,
    universe_wan: float | None = None,
) -> list[str]:
    """自动生成中文洞察句，可直接粘进报告。

    每句话都遵循"现象 + 幅度 + 归因/建议"的结构，
    这也是媒介报告里客户最认可的表达方式。
    """
    lines: list[str] = []
    if not cur_m:
        return ["本期无投放数据。"]

    # --- 总量 ---
    if "花费(元)" in cur_m:
        s = f"本期投放花费 {cur_m['花费(元)']:,.0f} 元"
        if "GRP" in cur_m:
            s += f"，产出 GRP {cur_m['GRP']:,.1f} 点"
        if "CPRP(元/点)" in cur_m:
            s += f"，CPRP {cur_m['CPRP(元/点)']:,.0f} 元/点"
        lines.append(s + "。")

    # --- 环比 ---
    if prev_m:
        cmp_df = compare_metrics(cur_m, prev_m)
        for key, good_dir in (("GRP", "up"), ("CPRP(元/点)", "down")):
            r = cmp_df[cmp_df["指标"] == key]
            if r.empty or pd.isna(r["变化率(%)"].iloc[0]):
                continue
            pct = float(r["变化率(%)"].iloc[0])
            if abs(pct) < 3:
                continue
            word = "上升" if pct > 0 else "下降"
            if key == "CPRP(元/点)":
                judge = "投放效率改善" if pct < 0 else "投放效率下滑，需核查是否收视不及预期或折扣变差"
            else:
                judge = "投放强度加大" if pct > 0 else "投放强度收缩"
            lines.append(f"{key} 环比{word} {abs(pct):.1f}%，{judge}。")

    # --- 频道效率 ---
    if "channel" in cur.columns:
        ch = breakdown(cur, "channel", universe_wan)
        if not ch.empty and "CPRP(元/点)" in ch.columns:
            valid = ch[ch["CPRP(元/点)"].notna() & (ch["CPRP(元/点)"] > 0)]
            if len(valid) >= 2:
                best = valid.nsmallest(1, "CPRP(元/点)").iloc[0]
                worst = valid.nlargest(1, "CPRP(元/点)").iloc[0]
                lines.append(
                    f"效率最优频道为 {best['channel']}（CPRP {best['CPRP(元/点)']:,.0f} 元/点），"
                    f"最差为 {worst['channel']}（CPRP {worst['CPRP(元/点)']:,.0f} 元/点），"
                    f"相差 {worst['CPRP(元/点)']/best['CPRP(元/点)']:.1f} 倍。"
                )
                if worst["CPRP(元/点)"] / best["CPRP(元/点)"] > 2:
                    lines.append(
                        f"建议：{worst['channel']} 单点成本显著偏高，"
                        f"如无覆盖互补的必要，可考虑将部分预算调整至 {best['channel']} 等高效资源。"
                    )
            # 集中度
            if "花费占比(%)" in ch.columns and len(ch) >= 3:
                top1 = float(ch["花费占比(%)"].iloc[0])
                if top1 > 50:
                    lines.append(
                        f"预算高度集中于 {ch['channel'].iloc[0]}（占 {top1:.0f}%），"
                        f"到达率上限受该频道覆盖能力约束，建议评估增补媒体以扩大净到达。"
                    )
                elif len(ch) > 8 and top1 < 20:
                    lines.append(
                        f"预算分散在 {len(ch)} 个频道（最高单频道仅 {top1:.0f}%），"
                        f"存在频次不足风险，建议向头部资源集中以保证有效到达。"
                    )

    # --- 时段 ---
    if "daypart" in cur.columns:
        dp = breakdown(cur, "daypart", universe_wan)
        if not dp.empty and "花费占比(%)" in dp.columns:
            lines.append(
                "时段结构：" + "、".join(
                    f"{row['daypart']} {row['花费占比(%)']:.0f}%"
                    for _, row in dp.head(4).iterrows()
                ) + "。"
            )

    # --- KPI ---
    if kpi_df is not None and not kpi_df.empty:
        risky = kpi_df[kpi_df["判定"].isin(["🔴 未达标", "🟠 预警"])]
        if risky.empty:
            lines.append("全部 KPI 达成情况正常。")
        else:
            for _, r in risky.iterrows():
                rate = r["完成率(%)"]
                lines.append(
                    f"⚠️ {r['KPI']} 完成率仅 {rate:.0f}%（目标 {r['目标']:,.0f}，"
                    f"实际 {r['实际']:,.0f}），{r['进度评价']}，需在剩余周期内补量或调整资源。"
                )

    return lines


# =============================================================================
# 导出
# =============================================================================

def build_report(
    df: pd.DataFrame,
    period: str = "weekly",
    as_of: date | None = None,
    targets: dict | None = None,
    universe_wan: float | None = None,
    dimensions: list[str] | None = None,
) -> dict:
    """生成一份完整报告的所有内容（不落盘，返回 dict）。"""
    cur, prev, cur_label, prev_label = slice_period(df, period, as_of)
    cur_m = core_metrics(cur, universe_wan)
    prev_m = core_metrics(prev, universe_wan)

    # 时间进度：月报才有意义
    progress = None
    if period == "monthly" and not cur.empty:
        ref = pd.Timestamp(as_of) if as_of else cur["date"].max()
        days_in_month = ref.days_in_month
        progress = ref.day / days_in_month * 100

    kpi_df = kpi_achievement(cur_m, targets, progress) if targets else pd.DataFrame()

    dims = dimensions or [d for d in ("channel", "daypart", "program", "creative", "region")
                          if d in cur.columns]
    breakdowns = {d: breakdown(cur, d, universe_wan) for d in dims}
    breakdowns = {k: v for k, v in breakdowns.items() if not v.empty}

    return {
        "period": period,
        "period_label": PERIOD_LABEL.get(period, period),
        "cur_label": cur_label,
        "prev_label": prev_label,
        "cur_metrics": cur_m,
        "prev_metrics": prev_m,
        "comparison": compare_metrics(cur_m, prev_m) if prev_m else pd.DataFrame(),
        "kpi": kpi_df,
        "breakdowns": breakdowns,
        "insights": auto_insights(cur, prev, cur_m, prev_m, kpi_df, universe_wan),
        "raw_current": cur,
        "row_count": len(cur),
    }


def report_to_markdown(rep: dict) -> str:
    """把报告转成 Markdown，可以直接粘进邮件、飞书、企微。"""
    L = []
    L.append(f"# 媒介投放{rep['period_label']}　{rep['cur_label']}")
    L.append("")
    L.append(f"> 数据区间：{rep['cur_label']}　|　对比区间：{rep['prev_label']}　"
             f"|　记录数：{rep['row_count']}")
    L.append("")

    L.append("## 一、核心指标")
    L.append("")
    if rep["cur_metrics"]:
        L.append("| 指标 | 本期 | 上期 | 变化率 | 评价 |")
        L.append("|---|---:|---:|---:|:---:|")
        cmp_df = rep["comparison"]
        for k, v in rep["cur_metrics"].items():
            prev_v = rep["prev_metrics"].get(k)
            row = cmp_df[cmp_df["指标"] == k] if not cmp_df.empty else pd.DataFrame()
            pct = row["变化率(%)"].iloc[0] if not row.empty else None
            ev = row["评价"].iloc[0] if not row.empty else "—"
            pct_s = f"{pct:+.1f}%" if pct is not None and not pd.isna(pct) else "—"
            prev_s = f"{prev_v:,.1f}" if isinstance(prev_v, (int, float)) and not pd.isna(prev_v) else "—"
            L.append(f"| {k} | {v:,.1f} | {prev_s} | {pct_s} | {ev} |")
    L.append("")

    if not rep["kpi"].empty:
        L.append("## 二、KPI 达成")
        L.append("")
        L.append("| KPI | 目标 | 实际 | 完成率 | 判定 | 进度 |")
        L.append("|---|---:|---:|---:|:---:|:---:|")
        for _, r in rep["kpi"].iterrows():
            act = f"{r['实际']:,.1f}" if pd.notna(r["实际"]) else "—"
            rate = f"{r['完成率(%)']:.0f}%" if pd.notna(r["完成率(%)"]) else "—"
            L.append(f"| {r['KPI']} | {r['目标']:,.0f} | {act} | {rate} | {r['判定']} | {r['进度评价']} |")
        L.append("")

    L.append("## 三、分析结论与建议")
    L.append("")
    for i, s in enumerate(rep["insights"], 1):
        L.append(f"{i}. {s}")
    L.append("")

    if rep["breakdowns"]:
        L.append("## 四、维度拆解")
        L.append("")
        dim_names = {"channel": "频道", "daypart": "时段", "program": "节目",
                     "creative": "素材", "region": "区域"}
        for dim, tbl in rep["breakdowns"].items():
            L.append(f"### 按{dim_names.get(dim, dim)}")
            L.append("")
            show = tbl.head(10).copy()
            for c in show.select_dtypes("number").columns:
                show[c] = show[c].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "—")
            L.append("| " + " | ".join(show.columns) + " |")
            L.append("|" + "---|" * len(show.columns))
            for _, r in show.iterrows():
                L.append("| " + " | ".join(str(v) for v in r.values) + " |")
            L.append("")

    L.append("---")
    L.append(f"*本报告由媒介分析工具箱自动生成于 {datetime.now():%Y-%m-%d %H:%M}，"
             f"结论部分请结合业务实际人工复核后发出。*")
    return "\n".join(L)


def report_to_excel(rep: dict, quality_df: pd.DataFrame | None = None) -> bytes:
    """导出多 sheet Excel（带基础格式），返回字节流供下载。"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        wb = xw.book
        fmt_title = wb.add_format({"bold": True, "font_size": 14, "bg_color": "#1F4E79",
                                   "font_color": "white", "align": "left", "valign": "vcenter"})
        fmt_head = wb.add_format({"bold": True, "bg_color": "#D9E2F3", "border": 1,
                                  "align": "center", "valign": "vcenter", "text_wrap": True})
        fmt_num = wb.add_format({"num_format": "#,##0.00", "border": 1})
        fmt_int = wb.add_format({"num_format": "#,##0", "border": 1})
        fmt_txt = wb.add_format({"border": 1, "valign": "top", "text_wrap": True})

        def write_df(name: str, df: pd.DataFrame, title: str = ""):
            if df is None or df.empty:
                return
            ws = wb.add_worksheet(name[:31])
            xw.sheets[name[:31]] = ws
            r0 = 0
            if title:
                ws.merge_range(0, 0, 0, max(len(df.columns) - 1, 1), title, fmt_title)
                ws.set_row(0, 24)
                r0 = 2
            for j, c in enumerate(df.columns):
                ws.write(r0, j, str(c), fmt_head)
                width = max(len(str(c)) * 2 + 4,
                            df[c].astype(str).str.len().max() * 1.2 if len(df) else 10)
                ws.set_column(j, j, min(float(width), 45))
            for i, (_, row) in enumerate(df.iterrows(), start=r0 + 1):
                for j, v in enumerate(row.values):
                    if isinstance(v, (int, np.integer)):
                        ws.write_number(i, j, float(v), fmt_int)
                    elif isinstance(v, (float, np.floating)) and pd.notna(v):
                        ws.write_number(i, j, float(v), fmt_num)
                    elif pd.isna(v):
                        ws.write_blank(i, j, None, fmt_txt)
                    else:
                        ws.write(i, j, str(v), fmt_txt)
            ws.freeze_panes(r0 + 1, 1)
            ws.autofilter(r0, 0, r0 + len(df), len(df.columns) - 1)

        title = f"媒介投放{rep['period_label']}　{rep['cur_label']}"

        # 摘要页
        summary = pd.DataFrame({
            "项目": ["报告类型", "数据区间", "对比区间", "记录数", "生成时间"],
            "内容": [rep["period_label"], rep["cur_label"], rep["prev_label"],
                     rep["row_count"], f"{datetime.now():%Y-%m-%d %H:%M}"],
        })
        write_df("00_摘要", summary, title)

        insight_df = pd.DataFrame({"序号": range(1, len(rep["insights"]) + 1),
                                   "分析结论与建议": rep["insights"]})
        write_df("01_结论建议", insight_df, "分析结论与行动建议（请人工复核后发出）")

        if not rep["comparison"].empty:
            write_df("02_核心指标", rep["comparison"], "核心指标环比")
        if not rep["kpi"].empty:
            write_df("03_KPI达成", rep["kpi"], "KPI 达成情况")

        dim_names = {"channel": "频道", "daypart": "时段", "program": "节目",
                     "creative": "素材", "region": "区域"}
        for i, (dim, tbl) in enumerate(rep["breakdowns"].items(), start=4):
            write_df(f"{i:02d}_按{dim_names.get(dim, dim)}", tbl, f"按{dim_names.get(dim, dim)}拆解")

        if quality_df is not None and not quality_df.empty:
            write_df("90_数据质检", quality_df, "数据质量检查结果")

        write_df("99_明细", rep["raw_current"].head(5000), "本期投放明细（最多5000行）")

    buf.seek(0)
    return buf.getvalue()
