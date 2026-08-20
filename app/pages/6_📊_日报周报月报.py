"""日报周报月报 —— JD 标签「日报周报月报」+ 职责 1 的 KPI 流程管理。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import (                                                    # noqa: E402
    data_source_widget, fmt_money, fmt_num, setup_page, sidebar_settings,
)
from core.quality import run_quality_check                                   # noqa: E402
from core.report import (                                                    # noqa: E402
    PERIOD_LABEL, build_report, report_to_excel, report_to_markdown,
)

setup_page("日报 · 周报 · 月报", "📊")
S = sidebar_settings()

st.markdown(
    "上传投放数据，选好周期和 KPI，一键出报告。"
    "**输出包含自动生成的分析结论**——那部分是初稿，"
    "你的价值在于把它改写成结合业务实际的判断。"
)

df = data_source_widget("placement", "rpt", "投放数据")
if df is None:
    st.stop()

st.divider()

# =============================================================================
st.subheader("① 报告设置")
# =============================================================================

c1, c2, c3 = st.columns(3)
period = c1.radio("报告周期", ["daily", "weekly", "monthly"],
                  format_func=lambda x: PERIOD_LABEL[x], horizontal=True, index=1)

max_date = pd.to_datetime(df["date"], errors="coerce").max()
min_date = pd.to_datetime(df["date"], errors="coerce").min()
as_of = c2.date_input(
    "截止日期", value=max_date.date() if pd.notna(max_date) else date.today(),
    min_value=min_date.date() if pd.notna(min_date) else None,
    max_value=max_date.date() if pd.notna(max_date) else None,
    help="报告以这一天为基准。日报=当天，周报=所在周，月报=所在月。",
)
run_qc = c3.checkbox("同时跑数据质检", value=True,
                     help="强烈建议勾上。质检结果会作为附录 sheet 附在报告里。")

# --- KPI 目标 ---
with st.expander("🎯 设置 KPI 目标（不填就只出现状，不做达成判定）", expanded=True):
    st.caption(
        "填客户/公司下达的目标值。**成本类指标（CPRP/CPM）是越低越好**，"
        "工具会自动反着算完成率，不用你操心。"
    )
    k1, k2, k3, k4 = st.columns(4)
    t_grp = k1.number_input("GRP 目标", 0.0, 1e6, 0.0, 10.0, help="0 = 不考核")
    t_cost = k2.number_input("花费目标（万元）", 0.0, 1e6, 0.0, 10.0, help="0 = 不考核")
    t_cprp = k3.number_input("CPRP 目标（元/点）", 0.0, 1e6, 0.0, 500.0,
                             help="0 = 不考核。实际 CPRP 低于目标才算达成。")
    t_reach = k4.number_input("曝光目标（万人次）", 0.0, 1e9, 0.0, 100.0, help="0 = 不考核")

targets = {}
if t_grp > 0:
    targets["GRP"] = t_grp
if t_cost > 0:
    targets["花费(元)"] = t_cost * 10000
if t_cprp > 0:
    targets["CPRP(元/点)"] = t_cprp
if t_reach > 0:
    targets["曝光(人次)"] = t_reach * 10000

st.divider()

if not st.button("📝 生成报告", type="primary", width="stretch"):
    st.info("配置好之后点上面的按钮。")
    st.stop()

# =============================================================================
with st.spinner("正在生成…"):
    rep = build_report(df, period, as_of, targets or None, S["universe_wan"])
    qdf = pd.DataFrame()
    if run_qc:
        qrep = run_quality_check(df, "placement")
        qdf = qrep.to_dataframe()

if rep["row_count"] == 0:
    st.error(
        f"**{rep['cur_label']} 这个区间没有数据。**\n\n"
        f"数据实际覆盖 {min_date:%Y-%m-%d} ~ {max_date:%Y-%m-%d}，请换一个截止日期。"
    )
    st.stop()

# --- 质检拦截 ---
if run_qc and not qrep.passed:
    st.error(
        f"🚨 **数据质检未通过：{qrep.error_count} 项错误。**　"
        f"报告仍然生成了，但**请先修正错误再对外交付**。"
        f"错误明细见下方「数据质检」标签，或去「🔍 数据质量检查」页看完整清单。"
    )
elif run_qc and qrep.warning_count > 0:
    st.warning(f"⚠️ 数据质检有 {qrep.warning_count} 项警告，交付前请逐条确认。")
elif run_qc:
    st.success("✅ 数据质检通过。")

st.divider()

# =============================================================================
st.subheader(f"{rep['period_label']}　{rep['cur_label']}")
st.caption(f"对比区间：{rep['prev_label']}　|　本期记录数：{rep['row_count']:,}　|　"
           f"人群口径：{S['universe_name']}　|　有效频次门槛：{S['effective_n']}+")
# =============================================================================

# --- 核心指标卡 ---
cm = rep["cur_metrics"]
cmp_df = rep["comparison"]

def _delta(key: str):
    if cmp_df.empty:
        return None
    row = cmp_df[cmp_df["指标"] == key]
    if row.empty or pd.isna(row["变化率(%)"].iloc[0]):
        return None
    return f"{row['变化率(%)'].iloc[0]:+.1f}%"

cols = st.columns(5)
metric_cards = [
    ("花费(元)", "花费", fmt_money, "normal"),
    ("GRP", "GRP", lambda v: fmt_num(v, 1), "normal"),
    ("CPRP(元/点)", "CPRP", lambda v: fmt_num(v, 0), "inverse"),
    ("曝光(人次)", "曝光", fmt_money, "normal"),
    ("投放频道数", "频道数", lambda v: f"{int(v)}", "off"),
]
for col, (key, label, formatter, dcolor) in zip(cols, metric_cards):
    if key in cm:
        col.metric(label, formatter(cm[key]), delta=_delta(key), delta_color=dcolor)

st.caption("💡 CPRP 的箭头方向已经反过来了：**下降 = 效率改善 = 好事**。")

tabs = ["📋 核心指标", "🎯 KPI 达成", "📐 维度拆解", "💬 分析结论", "📄 报告预览"]
if run_qc:
    tabs.append("🔍 数据质检")
T = st.tabs(tabs)

# =============================================================================
with T[0]:
# =============================================================================
    if cmp_df.empty:
        st.info("没有上期数据可对比。")
        st.dataframe(pd.DataFrame([cm]).T.rename(columns={0: "本期"}),
                     width="stretch")
    else:
        show = cmp_df.copy()
        for c in ("本期", "上期", "变化"):
            show[c] = show[c].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "—")
        show["变化率(%)"] = cmp_df["变化率(%)"].map(
            lambda x: f"{x:+.1f}%" if pd.notna(x) else "—")
        st.dataframe(show, width="stretch", hide_index=True)

# =============================================================================
with T[1]:
# =============================================================================
    if rep["kpi"].empty:
        st.info("没有设置 KPI 目标。回到上面「设置 KPI 目标」填写后重新生成。")
    else:
        k = rep["kpi"]
        show = k.copy()
        show["目标"] = k["目标"].map(lambda x: f"{x:,.0f}")
        show["实际"] = k["实际"].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "—")
        show["完成率(%)"] = k["完成率(%)"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        st.dataframe(show, width="stretch", hide_index=True)

        valid = k[k["完成率(%)"].notna()]
        if not valid.empty:
            fig = px.bar(valid, x="KPI", y="完成率(%)", color="判定",
                         color_discrete_map={"✅ 达标": "#2A9D8F", "🟡 基本达标": "#E9C46A",
                                             "🟠 预警": "#F4A261", "🔴 未达标": "#E76F51"},
                         title="KPI 完成率")
            fig.add_hline(y=100, line_dash="dash", line_color="gray",
                          annotation_text="100% 达标线")
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig, width="stretch")

        risky = k[k["判定"].isin(["🔴 未达标", "🟠 预警"])]
        if not risky.empty:
            st.error(
                "**⚠️ 以下 KPI 存在风险，报告里必须主动说明原因和补救措施：**\n\n" +
                "\n".join(
                    f"- **{r['KPI']}**：完成率 {r['完成率(%)']:.0f}%，{r['进度评价']}"
                    for _, r in risky.iterrows()
                )
            )
            st.caption(
                "💡 **KPI 没达成不可怕，可怕的是客户先发现。** "
                "主动报出来 + 给出原因 + 给出补救方案，反而是加分项。"
            )

# =============================================================================
with T[2]:
# =============================================================================
    if not rep["breakdowns"]:
        st.info("没有可拆解的维度。")
    else:
        dim_names = {"channel": "频道", "daypart": "时段", "program": "节目",
                     "creative": "素材", "region": "区域"}
        dim = st.selectbox("拆解维度", list(rep["breakdowns"].keys()),
                           format_func=lambda d: dim_names.get(d, d))
        tbl = rep["breakdowns"][dim]

        g1, g2 = st.columns([2, 3])
        with g1:
            if "花费(元)" in tbl.columns:
                top = tbl.head(10)
                fig = px.bar(top, x="花费(元)", y=dim, orientation="h",
                             title=f"花费 TOP10（按{dim_names.get(dim, dim)}）",
                             color="花费(元)", color_continuous_scale="Blues")
                fig.update_layout(height=400, yaxis=dict(autorange="reversed"),
                                  coloraxis_showscale=False,
                                  margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(fig, width="stretch")
        with g2:
            if "CPRP(元/点)" in tbl.columns and tbl["CPRP(元/点)"].notna().any():
                eff = tbl[tbl["CPRP(元/点)"].notna() & (tbl["CPRP(元/点)"] > 0)].head(12)
                fig2 = px.scatter(
                    eff, x="花费(元)", y="CPRP(元/点)", size="GRP" if "GRP" in eff.columns else None,
                    text=dim, title="效率象限：花费 vs CPRP（越靠左下越理想）",
                )
                if len(eff) > 1:
                    fig2.add_hline(y=eff["CPRP(元/点)"].median(), line_dash="dot",
                                   line_color="gray", annotation_text="CPRP 中位数")
                fig2.update_traces(textposition="top center")
                fig2.update_layout(height=400, margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(fig2, width="stretch")
                st.caption(
                    "**右上角的要重点关注**：花钱多、效率还差。"
                    "这些资源要么是有战略必要（比如覆盖互补），要么就该砍。"
                )

        show = tbl.copy()
        for c in show.select_dtypes("number").columns:
            if "花费" in c or "曝光" in c:
                show[c] = show[c].map(fmt_money)
            elif "%" in c:
                show[c] = show[c].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            else:
                show[c] = show[c].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "—")
        st.dataframe(show, width="stretch", hide_index=True)

# =============================================================================
with T[3]:
# =============================================================================
    st.markdown("**自动生成的分析结论**")
    st.caption(
        "⚠️ 这是**初稿不是终稿**。工具只能看到数据，看不到业务背景（客户临时停投、"
        "竞品动作、节假日、媒体资源变动）。**照抄发出去迟早出事**——"
        "请逐条判断，改写成结合业务实际的表述。"
    )
    text = "\n".join(f"{i}. {s}" for i, s in enumerate(rep["insights"], 1))
    st.text_area("结论（可编辑后复制）", text, height=300, key="insight_edit")

    st.divider()
    st.markdown("**把结论写好的三个套路**")
    st.markdown("""
| 套路 | 结构 | 示例 |
|---|---|---|
| **现象 + 归因** | 数据变化 → 为什么 | CPRP 上升 12%，主因是黄金档资源占比从 35% 提至 52%，该时段单点成本本身较高 |
| **对比 + 判断** | 跟谁比 → 好还是差 | 净到达率 42%，低于同类客户 48% 的行业均值，主要受频道集中度过高影响 |
| **问题 + 方案** | 发现什么 → 怎么办 | 3+ 有效到达仅 18%，建议将 CCTV-3 的 80 万转投湖南卫视，预计可提升至 24% |

**最忌讳的写法**：「本期投放正常，各项指标平稳」——这句话等于什么都没说。
    """)

# =============================================================================
with T[4]:
# =============================================================================
    md = report_to_markdown(rep)
    st.markdown(md)
    st.divider()
    d1, d2 = st.columns(2)
    with d1:
        xlsx = report_to_excel(rep, qdf if run_qc else None)
        fname = f"{rep['period_label']}_{rep['cur_label'].replace('/', '')}.xlsx"
        st.download_button("⬇️ 下载 Excel 报告（多 sheet）", xlsx, file_name=fname,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch", type="primary")
    with d2:
        st.download_button("⬇️ 下载 Markdown（贴邮件/飞书用）", md.encode("utf-8"),
                           file_name=f"{rep['period_label']}_{rep['cur_label'].replace('/', '')}.md",
                           width="stretch")

# =============================================================================
if run_qc:
    with T[5]:
        st.markdown(f"**{qrep.summary_text()}**")
        if qdf.empty:
            st.success("没有发现问题。")
        else:
            st.dataframe(qdf, width="stretch", hide_index=True)
