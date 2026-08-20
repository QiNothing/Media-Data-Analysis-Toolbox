"""竞品声量分析 —— JD 第 4 条：深入了解客户的业务及其竞争对手。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import (                                                    # noqa: E402
    data_source_widget, download_df, fmt_money, fmt_pct, setup_page,
)
from core.competitor import (                                               # noqa: E402
    channel_overlap, competitive_summary, esov_analysis, sov_ranking, sov_trend,
)

setup_page("竞品声量分析", "⚔️")

st.markdown(
    "数据源通常是 **ADQUEST / CTR / 秒针** 的竞品监测导出。"
    "⚠️ 注意这类数据的花费一般是**刊例价**不是实际成交价，"
    "所以**只能看相对趋势和结构，不能当真金白银**——这一点汇报时要主动说明。"
)

df = data_source_widget("competitor", "comp", "竞品数据")
if df is None:
    st.stop()

st.divider()

# =============================================================================
st.subheader("① 分析设置")
# =============================================================================

brands = sorted(df["brand"].dropna().unique().tolist())
if not brands:
    st.error("数据里没有品牌信息。")
    st.stop()

c1, c2, c3 = st.columns(3)
my_brand = c1.selectbox("本品品牌", brands,
                        help="选你负责的那个品牌，要和数据里的写法一致")

metric_options = [m for m in ("spend", "grp") if m in df.columns]
if not metric_options:
    st.error("数据里既没有 花费 也没有 GRP，无法计算声量。")
    st.stop()
metric = c2.selectbox(
    "声量口径", metric_options,
    format_func=lambda x: {"spend": "按花费（刊例）", "grp": "按 GRP"}[x],
    help="按花费算受折扣和刊例定价影响大；按 GRP 算更接近真实曝光强度。"
         "两个都看一遍，如果结论不一致要在报告里说明。",
)

periods = []
if "date" in df.columns:
    periods = sorted(pd.to_datetime(df["date"], errors="coerce")
                     .dt.to_period("M").astype(str).dropna().unique().tolist())
period = c3.selectbox("统计期间", ["全部"] + periods) if periods else "全部"
period_arg = None if period == "全部" else period

st.divider()

t1, t2, t3, t4 = st.tabs(["🏆 声量排名", "📈 声量走势", "🎯 ESOV 诊断", "🗺️ 频道重合度"])

# =============================================================================
with t1:
# =============================================================================
    rank = sov_ranking(df, metric, period_arg)
    if rank.empty:
        st.warning("该期间没有数据。")
    else:
        g1, g2 = st.columns([3, 2])
        with g1:
            colors = ["#A23B72" if b == my_brand else "#8FB8DE" for b in rank["品牌"]]
            fig = go.Figure(go.Bar(
                x=rank["SOV(%)"], y=rank["品牌"], orientation="h",
                marker_color=colors,
                text=[f"{v:.1f}%" for v in rank["SOV(%)"]], textposition="outside",
            ))
            fig.update_layout(
                title=f"声量份额排名（{period}）",
                xaxis_title="SOV (%)", height=max(360, len(rank) * 45),
                yaxis=dict(autorange="reversed"), margin=dict(l=10, r=40, t=50, b=10),
            )
            st.plotly_chart(fig, width="stretch")

        with g2:
            show = rank.copy()
            show["投放量"] = show["投放量"].map(fmt_money)
            show["SOV(%)"] = show["SOV(%)"].map(lambda x: f"{x:.2f}%")
            show["累计SOV(%)"] = show["累计SOV(%)"].map(lambda x: f"{x:.1f}%")
            st.dataframe(show, width="stretch", hide_index=True,
                         height=max(360, len(rank) * 40))

        cr3 = rank["SOV(%)"].head(3).sum()
        cr5 = rank["SOV(%)"].head(5).sum()
        m1, m2, m3 = st.columns(3)
        m1.metric("市场品牌数", len(rank))
        m2.metric("CR3（前三集中度）", f"{cr3:.1f}%")
        m3.metric("CR5", f"{cr5:.1f}%")

        if cr3 > 60:
            st.warning(
                f"**市场集中度高（CR3 = {cr3:.0f}%）。** 头部品牌已形成声量壁垒，"
                "跟随式投放很难建立记忆优势。中小品牌建议走差异化路线："
                "聚焦细分人群、错位频道或错位时段，把有限预算在局部做到相对领先。"
            )
        elif cr3 < 35:
            st.info(
                f"**市场高度分散（CR3 = {cr3:.0f}%）。** 没有品牌形成压倒性声量，"
                "这种格局下集中投放更容易脱颖而出——把预算压在少数高效资源上，"
                "在特定频道/时段做到 SOV 第一。"
            )

        download_df(rank, f"竞品声量排名_{period}.xlsx", key="dl_rank")

# =============================================================================
with t2:
# =============================================================================
    if "date" not in df.columns:
        st.info("数据里没有日期列，无法看走势。")
    else:
        trend = sov_trend(df, metric)
        if trend.empty or len(trend) < 2:
            st.info("数据期间不足 2 个月，无法看走势。")
        else:
            pick = st.multiselect("显示品牌", trend.columns.tolist(),
                                  default=trend.columns.tolist()[:6], key="trend_brands")
            if pick:
                fig = go.Figure()
                for b in pick:
                    is_mine = b == my_brand
                    fig.add_trace(go.Scatter(
                        x=trend.index, y=trend[b], name=b, mode="lines+markers",
                        line=dict(width=4 if is_mine else 2,
                                  color="#A23B72" if is_mine else None),
                    ))
                fig.update_layout(
                    title="声量份额（SOV）逐月走势",
                    xaxis_title="月份", yaxis_title="SOV (%)",
                    height=440, hovermode="x unified",
                    margin=dict(l=10, r=10, t=50, b=10),
                )
                st.plotly_chart(fig, width="stretch")

                st.markdown("**环比变化**")
                delta = (trend.iloc[-1] - trend.iloc[-2]).sort_values(ascending=False)
                dd = pd.DataFrame({
                    "品牌": delta.index,
                    f"{trend.index[-2]} SOV(%)": trend.iloc[-2].values,
                    f"{trend.index[-1]} SOV(%)": trend.iloc[-1].values,
                    "环比(pt)": delta.values,
                })
                dd["动向"] = dd["环比(pt)"].map(
                    lambda x: "🔺 明显加码" if x > 3 else "↗ 小幅增加" if x > 1
                    else "🔻 明显收缩" if x < -3 else "↘ 小幅减少" if x < -1 else "→ 基本持平"
                )
                st.dataframe(
                    dd.assign(**{
                        f"{trend.index[-2]} SOV(%)": dd[f"{trend.index[-2]} SOV(%)"].map(lambda x: f"{x:.1f}%"),
                        f"{trend.index[-1]} SOV(%)": dd[f"{trend.index[-1]} SOV(%)"].map(lambda x: f"{x:.1f}%"),
                        "环比(pt)": dd["环比(pt)"].map(lambda x: f"{x:+.1f}"),
                    }),
                    width="stretch", hide_index=True,
                )
                st.caption(
                    "💡 **重点看『明显加码』的竞品。** 声量突然上升通常意味着新品上市、"
                    "大促备战或渠道冲量。及时发现能给客户预警，这是分析师主动价值的体现。"
                )
                st.dataframe(trend.style.format("{:.1f}"), width="stretch")

# =============================================================================
with t3:
# =============================================================================
    st.markdown("**ESOV 诊断 —— 论证『要不要加预算』最有力的工具**")
    st.caption(
        "ESOV = SOV（声量份额）− SOM（市场份额）。"
        "Binet & Field 基于数千个案例的研究发现：ESOV 每高出 10 个百分点，"
        "年市场份额约增长 0.5 个百分点。这是广告界被引用最多的增长法则之一。"
    )

    som = st.number_input(
        "本品市场份额 SOM (%)", 0.0, 100.0, 18.0, 0.5,
        help="⚠️ 这个数投放数据里没有，必须问客户要。"
             "可以来自尼尔森/凯度的零售监测，或客户内部的销售数据。",
    )

    try:
        e = esov_analysis(df, my_brand, som, metric)
    except ValueError as ex:
        st.error(str(ex))
        st.stop()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("SOV 声量份额", fmt_pct(e["SOV(%)"]))
    m2.metric("SOM 市场份额", fmt_pct(e["SOM(%)"]))
    m3.metric("ESOV", f"{e['ESOV(%)']:+.1f} pt",
              delta=f"{e['ESOV(%)']:+.1f}", delta_color="normal")
    m4.metric("预测年份额增长", f"{e['预测年份额增长(pt)']:+.2f} pt")

    if e["ESOV(%)"] < -2:
        st.error(f"🔴 **{e['结论']}**")
    elif e["ESOV(%)"] <= 2:
        st.warning(f"🟡 **{e['结论']}**")
    else:
        st.success(f"🟢 **{e['结论']}**")

    gap = e["预算缺口"]
    if gap > 0:
        st.info(
            f"**测算**：要让声量与市场地位匹配（SOV = SOM = {som}%），"
            f"本品投放量需达到 **{fmt_money(e['达到SOV=SOM所需投放量'])}**，"
            f"当前为 {fmt_money(e['本品投放量'])}，**缺口 {fmt_money(gap)}**。\n\n"
            f"⚠️ 注意：这是按刊例口径算的缺口，实际需要的净预算要按你的采买折扣换算。"
        )
    else:
        st.info(
            f"**测算**：本品当前投放量 {fmt_money(e['本品投放量'])}，"
            f"已高于 SOV = SOM 所需的 {fmt_money(e['达到SOV=SOM所需投放量'])}，"
            f"**超出 {fmt_money(-gap)}**。声量投入领先于市场地位，具备份额增长基础。"
        )

    # ESOV 可视化
    fig = go.Figure()
    fig.add_trace(go.Bar(x=["SOV 声量份额", "SOM 市场份额"],
                         y=[e["SOV(%)"], e["SOM(%)"]],
                         marker_color=["#A23B72", "#8FB8DE"],
                         text=[f"{e['SOV(%)']:.1f}%", f"{e['SOM(%)']:.1f}%"],
                         textposition="outside"))
    fig.update_layout(title="声量份额 vs 市场份额", yaxis_title="%",
                      height=340, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, width="stretch")

    with st.expander("📖 ESOV 怎么用在汇报里"):
        st.markdown(f"""
**场景一：客户想砍预算**

> 目前我们的 SOV 是 {e['SOV(%)']:.1f}%，市场份额 {som}%，ESOV {e['ESOV(%)']:+.1f}pt。
> 按 Binet & Field 的研究，ESOV 低于 0 时份额会被逐步侵蚀。
> 如果这次削减预算 X%，SOV 将降至约 Y%，ESOV 进一步恶化到 Z pt，
> 预计未来 12 个月份额面临约 W pt 的下行压力。

**场景二：客户问加预算的理由**

> 竞品A本季 SOV 提升 8.7pt，我们持平。
> 若维持当前投放，明年 SOV 差距将扩大到 20pt 以上。
> 建议追加预算，把 ESOV 拉回正值，为份额增长提供声量支撑。

**⚠️ 使用这个法则的三个前提，被追问时要答得上**

1. 它是**跨品类的统计规律**，不是精确预测公式。单个品牌的实际结果会偏离。
2. 前提是**创意质量不显著低于竞品**。声量再大，广告本身不行也没用。
3. 主要适用于**成熟品类的份额竞争**。全新品类、颠覆式创新不适用这个框架。

诚实地说出这三条限制，比把它当成铁律更专业。
        """)

# =============================================================================
with t4:
# =============================================================================
    if "channel" not in df.columns:
        st.info("数据里没有频道列，无法做重合度分析。")
    else:
        st.markdown("**本品 vs 竞品的频道结构对比 —— 找机会点用这张表**")
        ov = channel_overlap(df, my_brand, metric)
        if ov.empty:
            st.warning("没有可分析的频道数据。")
        else:
            fig = go.Figure()
            fig.add_trace(go.Bar(name="本品占比", x=ov["频道"], y=ov["本品占比(%)"],
                                 marker_color="#A23B72"))
            fig.add_trace(go.Bar(name="竞品占比", x=ov["频道"], y=ov["竞品占比(%)"],
                                 marker_color="#8FB8DE"))
            fig.update_layout(
                barmode="group", title="频道预算结构对比（各自占本方总投放的比例）",
                yaxis_title="占比 (%)", height=420,
                margin=dict(l=10, r=10, t=50, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, width="stretch")

            show = ov.copy()
            for c in ("本品投放量", "竞品投放量"):
                show[c] = show[c].map(fmt_money)
            for c in ("本品占比(%)", "竞品占比(%)", "本品该频道SOV(%)"):
                show[c] = show[c].map(lambda x: f"{x:.1f}%")
            show["占比差(pt)"] = ov["占比差(pt)"].map(lambda x: f"{x:+.1f}")
            st.dataframe(show, width="stretch", hide_index=True,
                         column_config={"策略提示": st.column_config.TextColumn(width="large")})

            # 机会点
            gaps = ov[ov["策略提示"].str.contains("缺位")]
            forts = ov[ov["策略提示"].str.contains("独占")]
            reds = ov[ov["策略提示"].str.contains("红海")]

            oc1, oc2, oc3 = st.columns(3)
            with oc1:
                st.markdown("**🔴 竞品重仓、本品缺位**")
                if gaps.empty:
                    st.caption("无")
                else:
                    for _, r in gaps.iterrows():
                        st.caption(f"• {r['频道']}（竞品占 {r['竞品占比(%)']:.1f}%）")
                    st.caption("→ 评估是否需要进入，或确认是否为主动放弃")
            with oc2:
                st.markdown("**🟢 本品独占阵地**")
                if forts.empty:
                    st.caption("无")
                else:
                    for _, r in forts.iterrows():
                        st.caption(f"• {r['频道']}（本品占 {r['本品占比(%)']:.1f}%）")
                    st.caption("→ 差异化优势，建议保持")
            with oc3:
                st.markdown("**🟡 红海频道**")
                if reds.empty:
                    st.caption("无")
                else:
                    for _, r in reds.iterrows():
                        st.caption(f"• {r['频道']}（本品SOV {r['本品该频道SOV(%)']:.0f}%）")
                    st.caption("→ 注意收视稀释与频次浪费")

            download_df(ov, "频道重合度分析.xlsx", key="dl_ov")

# =============================================================================
st.divider()
st.subheader("📝 自动生成的竞品分析结论")
st.caption("可以直接粘进周报/月报，但**请务必结合业务实际人工复核和改写**。")
# =============================================================================

lines = competitive_summary(df, my_brand, metric)
text = "\n".join(f"{i}. {s}" for i, s in enumerate(lines, 1))
st.text_area("结论（可复制）", text, height=220)
st.download_button("⬇️ 下载结论（txt）", text.encode("utf-8"),
                   file_name="竞品分析结论.txt", key="dl_summary")
