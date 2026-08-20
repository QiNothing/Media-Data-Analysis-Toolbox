"""排期方案对比 —— JD 第 3 条：能支持报告解读以及策略建议等服务。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import (                                                    # noqa: E402
    download_df, fmt_money, fmt_num, fmt_pct, setup_page, sidebar_settings,
)
from core.config import benchmark_table                                      # noqa: E402
from core.metrics import evaluate_plan                                       # noqa: E402

setup_page("排期方案对比", "🎯")
S = sidebar_settings()

st.markdown(
    "手工搭 2~4 套排期方案，横向比一比。"
    "**这是给客户做提案时的核心页**——把取舍摊开讲，让对方在明白代价的前提下做选择，"
    "而不是你替他拍板。"
)

bt = benchmark_table()
if bt.empty:
    st.error("频道基准表为空。")
    st.stop()

# =============================================================================
st.subheader("① 搭建方案")
# =============================================================================

n_plans = st.slider("方案数量", 2, 4, 2)
default_names = ["方案A：广覆盖", "方案B：高频次", "方案C：均衡", "方案D：低成本"]

if "plan_data" not in st.session_state:
    st.session_state["plan_data"] = {}

plans: dict[str, pd.DataFrame] = {}
cols = st.columns(n_plans)

for i in range(n_plans):
    with cols[i]:
        name = st.text_input(f"方案 {i+1} 名称", default_names[i], key=f"pname_{i}")
        st.caption("填每个频道的预算（万元），不投的填 0")

        init = pd.DataFrame({
            "频道": bt["channel"],
            "预算(万元)": [0.0] * len(bt),
        })
        # 给个不同的默认值，方便直接看到对比效果
        if i == 0:
            init.loc[:5, "预算(万元)"] = [200.0, 150.0, 150.0, 150.0, 200.0, 150.0][:min(6, len(bt))]
        elif i == 1:
            init.loc[:2, "预算(万元)"] = [500.0, 400.0, 100.0][:min(3, len(bt))]
        elif i == 2:
            init.loc[:3, "预算(万元)"] = [300.0, 250.0, 250.0, 200.0][:min(4, len(bt))]

        edited = st.data_editor(
            init, width="stretch", hide_index=True, key=f"pedit_{i}",
            height=340,
            column_config={
                "频道": st.column_config.TextColumn(disabled=True),
                "预算(万元)": st.column_config.NumberColumn(format="%.0f", min_value=0.0),
            },
        )
        total = float(edited["预算(万元)"].sum())
        st.metric("方案总预算", fmt_money(total * 10000))

        merged = edited.merge(bt, left_on="频道", right_on="channel", how="left")
        merged["cost"] = merged["预算(万元)"] * 10000
        plans[name] = merged[merged["cost"] > 0][
            ["channel", "cost", "cprp", "max_reach", "rho"]
        ].reset_index(drop=True)

valid_plans = {k: v for k, v in plans.items() if not v.empty}
if not valid_plans:
    st.warning("至少给一个方案分配预算。")
    st.stop()

st.divider()

# =============================================================================
st.subheader("② 方案对比")
# =============================================================================

results = {}
rows = []
for name, alloc in valid_plans.items():
    res = evaluate_plan(alloc, S["universe_wan"], S["effective_n"], S["cross_media_method"])
    results[name] = res
    rows.append({
        "方案": name,
        "总预算(元)": res.total_cost,
        "总GRP": res.total_grp,
        "CPRP(元/点)": res.cprp,
        "净到达率(%)": res.net_reach,
        "平均频次": res.avg_frequency,
        f"{S['effective_n']}+有效到达(%)": res.effective_reach,
        "曝光(人次)": res.impressions,
        "CPM(元/千人次)": res.cpm,
        "频道数": len(alloc),
    })

comp = pd.DataFrame(rows)

show = comp.copy()
show["总预算(元)"] = comp["总预算(元)"].map(fmt_money)
show["曝光(人次)"] = comp["曝光(人次)"].map(fmt_money)
show["总GRP"] = comp["总GRP"].map(lambda x: f"{x:,.1f}")
show["CPRP(元/点)"] = comp["CPRP(元/点)"].map(lambda x: f"{x:,.0f}")
show["CPM(元/千人次)"] = comp["CPM(元/千人次)"].map(lambda x: f"{x:.2f}")
show["净到达率(%)"] = comp["净到达率(%)"].map(lambda x: f"{x:.2f}%")
show[f"{S['effective_n']}+有效到达(%)"] = comp[f"{S['effective_n']}+有效到达(%)"].map(lambda x: f"{x:.2f}%")
show["平均频次"] = comp["平均频次"].map(lambda x: f"{x:.2f}")

st.dataframe(show, width="stretch", hide_index=True)

# --- 各项最优标注 ---
st.markdown("**各维度最优方案**")
w1, w2, w3, w4 = st.columns(4)
try:
    w1.metric("GRP 最高", comp.loc[comp["总GRP"].idxmax(), "方案"],
              f"{comp['总GRP'].max():,.0f} 点")
    w2.metric("CPRP 最低", comp.loc[comp["CPRP(元/点)"].idxmin(), "方案"],
              f"{comp['CPRP(元/点)'].min():,.0f} 元/点")
    w3.metric("到达率最高", comp.loc[comp["净到达率(%)"].idxmax(), "方案"],
              f"{comp['净到达率(%)'].max():.1f}%")
    ercol = f"{S['effective_n']}+有效到达(%)"
    w4.metric("有效到达最高", comp.loc[comp[ercol].idxmax(), "方案"],
              f"{comp[ercol].max():.1f}%")
except (ValueError, KeyError):
    pass

st.caption(
    "⚠️ **注意各方案的预算是否可比。** 如果预算不同，比绝对值没有意义，"
    "要看下面的『每万元效率』标签。"
)

st.divider()

t1, t2, t3, t4 = st.tabs(["📊 雷达图", "💹 每万元效率", "🔬 频道结构", "📝 提案话术"])

# =============================================================================
with t1:
# =============================================================================
    st.caption("五个维度归一化到 0~100 分（每个维度以最优方案为 100 分）。面积越大越好。")
    dims = ["总GRP", "净到达率(%)", f"{S['effective_n']}+有效到达(%)", "平均频次"]
    dims = [d for d in dims if d in comp.columns]

    fig = go.Figure()
    for _, row in comp.iterrows():
        vals = []
        for d in dims:
            col_max = comp[d].max()
            vals.append(row[d] / col_max * 100 if col_max > 0 else 0)
        # 成本效率维度：CPRP 越低越好，反向归一化
        cprp_min = comp["CPRP(元/点)"].min()
        vals.append(cprp_min / row["CPRP(元/点)"] * 100 if row["CPRP(元/点)"] > 0 else 0)

        labels = dims + ["成本效率"]
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=labels + [labels[0]],
            fill="toself", name=row["方案"], opacity=0.5,
        ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        height=520, margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.12),
    )
    st.plotly_chart(fig, width="stretch")

# =============================================================================
with t2:
# =============================================================================
    st.caption("预算不同的方案之间，只有看单位预算的产出才公平。")
    eff = comp.copy()
    eff["每万元GRP"] = eff["总GRP"] / (eff["总预算(元)"] / 10000)
    eff["每万元净到达(pt)"] = eff["净到达率(%)"] / (eff["总预算(元)"] / 10000)
    eff["每万元有效到达(pt)"] = eff[f"{S['effective_n']}+有效到达(%)"] / (eff["总预算(元)"] / 10000)

    e_show = eff[["方案", "总预算(元)", "每万元GRP", "每万元净到达(pt)", "每万元有效到达(pt)"]].copy()
    e_show["总预算(元)"] = eff["总预算(元)"].map(fmt_money)
    for c in ("每万元GRP", "每万元净到达(pt)", "每万元有效到达(pt)"):
        e_show[c] = eff[c].map(lambda x: f"{x:.4f}")
    st.dataframe(e_show, width="stretch", hide_index=True)

    fig2 = go.Figure()
    for c, color in (("每万元GRP", "#2E86AB"), ("每万元净到达(pt)", "#A23B72"),
                     ("每万元有效到达(pt)", "#F18F01")):
        fig2.add_trace(go.Bar(name=c, x=eff["方案"], y=eff[c], marker_color=color))
    fig2.update_layout(barmode="group", height=380, title="单位预算产出对比",
                       margin=dict(l=10, r=10, t=50, b=10),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig2, width="stretch")

# =============================================================================
with t3:
# =============================================================================
    all_ch = sorted({c for a in valid_plans.values() for c in a["channel"]})
    matrix = pd.DataFrame({"频道": all_ch})
    for name, alloc in valid_plans.items():
        m = dict(zip(alloc["channel"], alloc["cost"]))
        total = sum(m.values()) or 1
        matrix[name] = [m.get(c, 0) / total * 100 for c in all_ch]

    fig3 = go.Figure()
    for name in valid_plans:
        fig3.add_trace(go.Bar(name=name, x=matrix["频道"], y=matrix[name]))
    fig3.update_layout(barmode="group", height=420, title="各方案的频道预算占比 (%)",
                       yaxis_title="占比 (%)", margin=dict(l=10, r=10, t=50, b=10),
                       legend=dict(orientation="h", yanchor="bottom", y=1.02))
    st.plotly_chart(fig3, width="stretch")

    st.dataframe(
        matrix.assign(**{n: matrix[n].map(lambda x: f"{x:.1f}%") for n in valid_plans}),
        width="stretch", hide_index=True,
    )
    download_df(comp, "排期方案对比.xlsx", key="dl_plan")

# =============================================================================
with t4:
# =============================================================================
    st.markdown("**提案话术生成 —— 照着这个结构讲**")

    if len(comp) >= 2:
        best_reach = comp.loc[comp["净到达率(%)"].idxmax()]
        ercol = f"{S['effective_n']}+有效到达(%)"
        best_er = comp.loc[comp[ercol].idxmax()]
        best_cprp = comp.loc[comp["CPRP(元/点)"].idxmin()]

        script = f"""### 方案汇报话术（可直接改写使用）

**开场 —— 先说清楚在比什么**

> 我们准备了 {len(comp)} 套方案，预算分别是
> {'、'.join(f"{r['方案']} {r['总预算(元)']/10000:,.0f}万" for _, r in comp.iterrows())}。
> 三套方案的差异不在花多少钱，而在于**把钱花在广度还是深度上**。

**核心取舍 —— 这是整个汇报最重要的一段**

> - **{best_reach['方案']}** 的净到达率最高，为 {best_reach['净到达率(%)']:.1f}%，
>   意味着能覆盖到最多的目标人群，但平均频次只有 {best_reach['平均频次']:.1f} 次，
>   {S['effective_n']}+ 有效到达 {best_reach[ercol]:.1f}%。
>   **适合新品上市、需要快速建立广泛认知的场景。**
>
> - **{best_er['方案']}** 的 {S['effective_n']}+ 有效到达最高，为 {best_er[ercol]:.1f}%，
>   平均频次 {best_er['平均频次']:.1f} 次，能更有效地建立品牌记忆，
>   代价是净到达率 {best_er['净到达率(%)']:.1f}%，覆盖面较窄。
>   **适合品牌建设期、需要加深已有认知的场景。**
>
> - **{best_cprp['方案']}** 的 CPRP 最低（{best_cprp['CPRP(元/点)']:,.0f} 元/点），
>   单位成本效率最优。如果 KPI 直接考核 GRP，这套最划算，
>   但要注意它的净到达率是 {best_cprp['净到达率(%)']:.1f}%。

**结论 —— 给建议但不替客户决策**

> 三套方案没有绝对优劣，取决于本次投放的核心目标：
> - 目标是**拉新** → 建议 {best_reach['方案']}
> - 目标是**加深记忆/促转化** → 建议 {best_er['方案']}
> - KPI 直接考核 **GRP/收视点** → 建议 {best_cprp['方案']}
>
> 我个人倾向 __（填你的判断和理由）__，请您定夺。

**必须主动说明的口径**

> 以上测算基于 __（CSM/勾正）__ 数据，人群口径 {S['universe_name']}，
> 跨媒体到达率采用 {S['cross_media_method']} 方法去重，
> 属于规划阶段的估算，实际结果以投后监播数据为准。
"""
        st.markdown(script)
        st.download_button("⬇️ 下载话术", script.encode("utf-8"),
                           file_name="方案汇报话术.md", key="dl_script")

        st.divider()
        st.info("""
**汇报时的三个细节，做到了显得很专业**

1. **主动说口径和局限。** 不说，客户追问时你就是被动的；主动说，你就是严谨的。
2. **给建议，但把决策权交回去。** 「我倾向 A，理由是…，请您定夺」
   比「就选 A」更容易被接受，也把风险摆回了正确的位置。
3. **准备好『如果预算变了怎么办』。** 客户十有八九会问「砍 20% 会怎样」，
   提前用「💰 预算分配优化」页算好，当场就能答。
        """)
    else:
        st.info("至少两个方案才能生成对比话术。")
