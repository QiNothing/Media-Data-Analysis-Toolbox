"""预算分配优化 —— JD 第 4 条：对如何最佳分配广告预算/资源提出建议。"""

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
    download_df, fmt_money, fmt_num, fmt_pct, setup_page, sidebar_settings,
)
from core.budget import (                                                   # noqa: E402
    OBJECTIVE_LABELS, Constraint, compare_scenarios, marginal_analysis, optimize_budget,
)
from core.config import benchmark_table, is_calibrated                      # noqa: E402
from core.metrics import evaluate_plan                                      # noqa: E402

setup_page("预算分配优化", "💰")
S = sidebar_settings()

st.markdown(
    "**这一页是这份工作里最能体现专业度的地方。** "
    "客户问『预算怎么分』，凭感觉答『多给央视』谁都会说；"
    "能拿出边际测算说『每万元在 A 换 0.019pt 到达率、在 B 只换 0.012pt』，才是分析师。"
)

# =============================================================================
st.subheader("① 候选频道与基准")
# =============================================================================

bt = benchmark_table()
if bt.empty:
    st.error("频道基准表为空，请检查 config/benchmarks.yaml")
    st.stop()

st.caption(
    "下表是可选频道池。**CPRP 和覆盖天花板直接决定优化结果**，"
    "所以接入真实数据后第一件事就是用公司真实数据替换这些值——可以在这张表里直接改（临时生效），"
    "长期请改 `config/benchmarks.yaml`。"
)

picked = st.multiselect(
    "参与优化的频道", bt["channel"].tolist(),
    default=bt["channel"].tolist()[:8],
    help="选太少会限制到达率上限，选太多计算变慢。建议 5~10 个。",
)
if not picked:
    st.warning("至少选一个频道。")
    st.stop()

pool = bt[bt["channel"].isin(picked)].reset_index(drop=True)

edited = st.data_editor(
    pool.rename(columns={
        "channel": "频道", "channel_type": "类型", "cprp": "CPRP(元/点)",
        "avg_rating": "平均收视率(%)", "max_reach": "覆盖天花板(%)", "rho": "重复系数ρ",
    }),
    width="stretch", hide_index=True, key="pool_edit",
    column_config={
        "CPRP(元/点)": st.column_config.NumberColumn(format="%.0f", min_value=1,
                                                    help="每收视点成本，越低越划算"),
        "覆盖天花板(%)": st.column_config.NumberColumn(format="%.1f", min_value=1, max_value=100,
                                                     help="这个媒体最多能碰到多少人"),
        "重复系数ρ": st.column_config.NumberColumn(format="%.2f", min_value=0.0, max_value=0.6,
                                                 help="观众忠诚度，越大到达率涨得越慢"),
        "类型": st.column_config.TextColumn(disabled=True),
    },
)

chans = edited.rename(columns={
    "频道": "channel", "CPRP(元/点)": "cprp",
    "覆盖天花板(%)": "max_reach", "重复系数ρ": "rho",
})[["channel", "cprp", "max_reach", "rho"]]

if not is_calibrated():
    st.caption("⚠️ 上面的数字是占位基准。改成真实值后，优化结果才有对外汇报的价值。")

st.divider()

# =============================================================================
st.subheader("② 预算与目标")
# =============================================================================

c1, c2 = st.columns([1, 2])
with c1:
    budget_wan = st.number_input("总预算（万元）", 10.0, 500000.0, 1000.0, 50.0)
    budget = budget_wan * 10000

with c2:
    objective = st.radio(
        "优化目标", list(OBJECTIVE_LABELS.keys()),
        format_func=lambda k: OBJECTIVE_LABELS[k], horizontal=False,
    )

OBJ_EXPLAIN = {
    "max_reach": "把每一块钱投到边际到达率增量最大的地方。结果通常会**分散到多个频道**，"
                 "因为单个频道有覆盖天花板。适合新品上市、品牌拉新。",
    "max_grp": "全部砸给 CPRP 最低的频道。GRP 数字最好看，但**到达率会很差**——"
               "钱都在重复触达同一批人。只有当客户 KPI 就是考核 GRP 时才这么做，"
               "而且你有义务提示到达率的代价。",
    "max_effective_reach": "在 3+ 有效到达上做优化。会倾向于**适度集中**以堆高频次，"
                           "在覆盖和记忆度之间取平衡。适合品牌建设期。",
}
st.info(f"**{OBJECTIVE_LABELS[objective]}**　{OBJ_EXPLAIN[objective]}")

# --- 约束 ---
with st.expander("🔒 添加约束（客户指定、媒体返点、资源锁定）"):
    st.caption(
        "真实工作里预算很少能自由分配：客户会说『央视必须投』，"
        "媒体返点政策会要求『年框量不能低于 X』。在这里设置。"
    )
    cons_df = st.data_editor(
        pd.DataFrame({
            "频道": chans["channel"],
            "最低占比(%)": [0.0] * len(chans),
            "最高占比(%)": [100.0] * len(chans),
            "锁定金额(万元)": [None] * len(chans),
        }),
        width="stretch", hide_index=True, key="cons_edit",
        column_config={
            "频道": st.column_config.TextColumn(disabled=True),
            "最低占比(%)": st.column_config.NumberColumn(format="%.1f", min_value=0.0, max_value=100.0),
            "最高占比(%)": st.column_config.NumberColumn(format="%.1f", min_value=0.0, max_value=100.0),
            "锁定金额(万元)": st.column_config.NumberColumn(
                format="%.0f", min_value=0.0,
                help="填了这个就完全按这个金额，忽略上下限"),
        },
    )

constraints = []
for _, r in cons_df.iterrows():
    lock = r["锁定金额(万元)"]
    has_lock = pd.notna(lock) and lock is not None
    if has_lock:
        constraints.append(Constraint(r["频道"], locked_amount=float(lock) * 10000))
    elif r["最低占比(%)"] > 0 or r["最高占比(%)"] < 100:
        constraints.append(Constraint(r["频道"],
                                      min_pct=float(r["最低占比(%)"]) / 100,
                                      max_pct=float(r["最高占比(%)"]) / 100))

if constraints:
    st.caption(f"已设置 {len(constraints)} 条约束")

st.divider()

if not st.button("🚀 开始优化", type="primary", width="stretch"):
    st.info("配置好预算和目标后，点上面的按钮。")
    st.stop()

# =============================================================================
try:
    with st.spinner("正在计算最优分配…"):
        opt = optimize_budget(
            chans, budget, objective, constraints,
            steps=150, effective_n=S["effective_n"],
            cross_media_method=S["cross_media_method"],
        )
except ValueError as e:
    st.error(f"❌ 优化失败：{e}")
    st.stop()

alloc = opt["allocation"]
res = evaluate_plan(
    alloc[["channel", "cost", "cprp", "max_reach", "rho"]],
    S["universe_wan"], S["effective_n"], S["cross_media_method"],
)

for w in opt["warnings"]:
    st.warning(w)

st.subheader("③ 优化结果")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("总 GRP", fmt_num(res.total_grp, 1))
m2.metric("CPRP", fmt_num(res.cprp, 0), help="元/收视点")
m3.metric("净到达率", fmt_pct(res.net_reach))
m4.metric("平均频次", fmt_num(res.avg_frequency, 2))
m5.metric(f"{S['effective_n']}+ 有效到达", fmt_pct(res.effective_reach))

g1, g2 = st.columns([2, 3])

with g1:
    fig_pie = px.pie(alloc, names="channel", values="cost", hole=0.45,
                     title="预算分配结构")
    fig_pie.update_traces(textposition="inside", textinfo="label+percent")
    fig_pie.update_layout(height=380, showlegend=False, margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_pie, width="stretch")

with g2:
    show = alloc[["channel", "cost", "预算占比(%)", "grp", "reach(%)", "cprp"]].copy()
    show.columns = ["频道", "分配预算", "占比(%)", "GRP", "单媒体到达率(%)", "CPRP"]
    st.dataframe(
        show.assign(**{
            "分配预算": show["分配预算"].map(fmt_money),
            "占比(%)": show["占比(%)"].map(lambda x: f"{x:.1f}%"),
            "GRP": show["GRP"].map(lambda x: f"{x:.1f}"),
            "单媒体到达率(%)": show["单媒体到达率(%)"].map(lambda x: f"{x:.2f}%"),
            "CPRP": show["CPRP"].map(lambda x: f"{x:,.0f}"),
        }),
        width="stretch", hide_index=True, height=360,
    )

st.caption(
    f"⚠️ 注意：各频道「单媒体到达率」加起来是 {alloc['reach(%)'].sum():.1f}%，"
    f"但去重后的净到达率只有 {res.net_reach:.1f}%。**汇报时一定要用净到达率。**"
)

download_df(alloc, f"预算分配方案_{budget_wan:.0f}万.xlsx", "⬇️ 下载分配方案", key="dl_alloc")

st.divider()

# =============================================================================
t1, t2, t3 = st.tabs(["📈 边际收益曲线", "⚖️ 三方案对比", "➕ 追加预算怎么加"])
# =============================================================================

with t1:
    st.markdown("**预算投入 → 效果产出 响应曲线**")
    curve = opt["curve"]
    if not curve.empty:
        ylabel = {"max_reach": "净到达率 (%)", "max_grp": "总 GRP",
                  "max_effective_reach": f"{S['effective_n']}+ 有效到达 (%)"}[objective]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=curve["已分配预算"] / 10000, y=curve["目标值"],
            mode="lines", line=dict(color="#2E86AB", width=3), name=ylabel,
        ))
        fig.update_layout(
            xaxis_title="已投入预算（万元）", yaxis_title=ylabel,
            height=420, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
        )
        st.plotly_chart(fig, width="stretch")

        # 找拐点：边际收益跌到峰值 30% 以下的位置
        if len(curve) > 10 and objective != "max_grp":
            d = curve["目标值"].diff().fillna(0)
            peak = d.max()
            knee_idx = d[d < peak * 0.3].index
            if len(knee_idx) > 0:
                knee = curve.loc[knee_idx[0]]
                st.warning(
                    f"💡 **边际效益拐点约在 {knee['已分配预算']/10000:,.0f} 万元处**"
                    f"（此时{ylabel} {knee['目标值']:.1f}）。\n\n"
                    f"超过这个点之后，每追加一万元带来的效果提升不到峰值的 30%。"
                    f"如果预算有弹性，**这个数字就是你跟客户谈『投多少最划算』的依据**——"
                    f"再往上投不是没效果，而是性价比明显下降。"
                )
        st.caption(
            "这条曲线的形状就是**边际收益递减**。"
            "它是你回答『为什么不能无限加预算』最直观的一张图。"
        )

with t2:
    st.markdown("**同样的预算，三种目标分别能拿到什么**")
    st.caption("这张表是给客户/老板做决策用的核心页——把取舍摊开讲，让对方选。")
    with st.spinner("正在计算三种方案…"):
        cmp_df = compare_scenarios(
            chans, budget, constraints, S["universe_wan"],
            S["effective_n"], S["cross_media_method"], steps=100,
        )
    show = cmp_df.copy()
    for c in show.select_dtypes("number").columns:
        if "CPRP" in c or "CPM" in c:
            show[c] = show[c].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
        elif "%" in c:
            show[c] = show[c].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
        else:
            show[c] = show[c].map(lambda x: f"{x:,.1f}" if pd.notna(x) else "—")
    st.dataframe(show, width="stretch", hide_index=True)

    if len(cmp_df) == 3 and "净到达率(%)" in cmp_df.columns:
        try:
            r_reach = cmp_df.iloc[0]
            r_grp = cmp_df.iloc[1]
            st.info(f"""
**怎么读这张表（拿去汇报可以直接用）**

同样 {budget_wan:,.0f} 万元预算：

- 若追求**广度**（最大化到达率）：能碰到 **{r_reach['净到达率(%)']:.1f}%** 的目标人群，
  但 GRP 只有 {r_reach['总GRP']:.0f} 点。
- 若追求**GRP 数字**：GRP 可达 **{r_grp['总GRP']:.0f} 点**（高 {(r_grp['总GRP']/r_reach['总GRP']-1)*100:.0f}%），
  但净到达率掉到 {r_grp['净到达率(%)']:.1f}%（少 {r_reach['净到达率(%)']-r_grp['净到达率(%)']:.1f} 个百分点）。

**这就是媒介策划的核心取舍**：钱一定的情况下，铺得广就砸得浅，砸得深就铺得窄。
往哪边偏，取决于这波投放的营销目标是拉新还是转化、是打认知还是促购买。
            """)
        except (KeyError, IndexError, ZeroDivisionError):
            pass

with t3:
    st.markdown("**客户临时追加预算，应该加到哪个频道**")
    st.caption("这是日常最高频的一个问题。不要凭感觉，算边际。")

    inc_wan = st.number_input("追加金额（万元）", 1.0, 10000.0, 100.0, 10.0, key="inc")
    current = dict(zip(alloc["channel"], alloc["cost"]))

    marg = marginal_analysis(chans, current, inc_wan * 10000,
                             S["effective_n"], S["cross_media_method"])

    col_reach = f"加{inc_wan:.0f}万后 净到达率增量(pt)"
    col_er = f"{S['effective_n']}+有效到达增量(pt)"

    fig_m = px.bar(marg, x="频道", y=col_reach, color=col_reach,
                   color_continuous_scale="Blues",
                   title=f"追加 {inc_wan:.0f} 万元，各频道的净到达率增量")
    fig_m.update_layout(height=380, showlegend=False, coloraxis_showscale=False,
                        margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_m, width="stretch")

    show_m = marg.copy()
    show_m["当前预算"] = show_m["当前预算"].map(fmt_money)
    for c in (col_reach, col_er, "每万元换到达率(pt/万元)"):
        show_m[c] = show_m[c].map(lambda x: f"{x:+.3f}")
    show_m["GRP增量"] = show_m["GRP增量"].map(lambda x: f"{x:+.1f}")
    st.dataframe(show_m, width="stretch", hide_index=True)

    if not marg.empty:
        best = marg.iloc[0]
        worst = marg.iloc[-1]
        best_er = marg.sort_values(col_er, ascending=False).iloc[0]
        st.success(f"""
**建议（可以直接说给老板听）**

追加 {inc_wan:.0f} 万元：

- **若目标是扩大覆盖**：加到 **{best['频道']}**，净到达率 +{best[col_reach]:.2f}pt，
  每万元换 {best['每万元换到达率(pt/万元)']:.4f}pt。
  相比最差的 {worst['频道']}（+{worst[col_reach]:.2f}pt），效率高
  {(best[col_reach]/worst[col_reach] if worst[col_reach] > 0 else 999):.1f} 倍。
- **若目标是加深记忆**：加到 **{best_er['频道']}**，{S['effective_n']}+ 有效到达 +{best_er[col_er]:.2f}pt。

先确认追加预算的目的是拉新还是加深，再定投哪个。
        """)

st.divider()
with st.expander("📖 优化器是怎么算的（被问起来要答得上）"):
    st.markdown(f"""
**算法：贪心边际分配**

把总预算切成 150 份，每次把一份钱放到「能带来最大目标增量」的频道，重复 150 次。

**为什么这样是最优的？**

因为到达率对预算是**凹函数**（边际递减）。凹函数的贪心逐份分配，
等价于经济学里的**边际效用相等条件**——最优解一定满足「每个频道最后一块钱的边际收益相等」，
贪心过程会自然收敛到这个状态。对 GRP 目标（线性函数），贪心同样最优。

**到达率模型**

```
Reach = MaxReach × (1 - exp(-k × GRP / MaxReach))，其中 k = 1 - ρ
```

- GRP = 0 时到达率 = 0
- GRP → ∞ 时到达率 → MaxReach（永远不超天花板）
- ρ 越大（观众越忠诚、重复越多），到达率涨得越慢

**跨媒体去重**：{S['cross_media_method']}（Sainsbury 公式：A + B − A×B/100）

**⚠️ 这个模型的局限，你必须知道**

1. 它是**业界通用的近似方法**，跟 CSM/尼尔森官方软件的测算会有差异
2. Sainsbury 假设各媒体受众独立，实际正相关，所以净到达会**略微高估**
3. 模型不考虑：排期节奏（集中投 vs 铺开投）、素材损耗、季节性、竞品干扰
4. **CPRP 用的是平均值**，实际采买中不同时段/资源包的 CPRP 差异很大

**所以正确的用法是**：用它做方案的**相对比较**和**结构判断**，
不要把绝对数字当成承诺给客户。对外的到达率数字，以官方数据源测算为准。
    """)
