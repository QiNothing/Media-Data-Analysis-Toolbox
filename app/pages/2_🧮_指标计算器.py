"""指标计算器 —— 手动输入几个数，立刻看到结果，用来建立数感。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import fmt_money, fmt_num, fmt_pct, setup_page, sidebar_settings   # noqa: E402
from core.config import benchmark_table, get_channel_benchmark                      # noqa: E402
from core.metrics import (                                                          # noqa: E402
    combine_reach_list,
    cpm,
    cprp,
    discount_from_cost,
    effective_reach,
    frequency,
    frequency_distribution,
    grp_from_rating,
    grp_needed_for_reach,
    impressions_from_grp,
    net_cost,
    reach_from_grp,
)

setup_page("指标计算器", "🧮")
S = sidebar_settings()

st.caption(
    "每个计算器下面都写了公式和解读。**建议先在这里把几个数字来回拨一拨**，"
    "感受一下 GRP、到达率、频次之间是怎么互相牵制的——这个数感比记公式重要得多。"
)

t1, t2, t3, t4, t5 = st.tabs(
    ["📐 GRP · CPRP · CPM", "📡 到达率 · 频次", "🎯 反算：要多少 GRP", "💵 刊例 · 折扣", "🔀 跨媒体合并"]
)

# =============================================================================
with t1:
# =============================================================================
    st.subheader("投放量与成本效率")

    mode = st.radio("已知条件", ["收视率 + 播出次数", "直接填 GRP"],
                    horizontal=True, key="t1_mode")

    c1, c2, c3 = st.columns(3)
    if mode == "收视率 + 播出次数":
        rating = c1.number_input("单次收视率 (%)", 0.0, 30.0, 0.85, 0.01, format="%.3f",
                                 help="注意是百分数：0.85 表示 0.85%")
        spots = c2.number_input("播出次数", 1, 100000, 20, 1)
        grp = grp_from_rating(rating, spots)
        c3.metric("GRP", fmt_num(grp, 2))
        st.caption(f"计算过程：GRP = {rating} × {spots} = **{grp:.2f}**")
    else:
        grp = c1.number_input("GRP", 0.0, 100000.0, 17.0, 0.1)
        rating = spots = None
        c2.write("")
        c3.write("")

    cost = st.number_input("总花费（元）", 0.0, 1e10, 700_000.0, 10_000.0, format="%.0f")

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    val_cprp = cprp(cost, grp)
    imps = impressions_from_grp(grp, S["universe_wan"])
    val_cpm = cpm(cost, imps)

    m1.metric("GRP", fmt_num(grp, 2))
    m2.metric("CPRP（元/点）", fmt_num(val_cprp, 0),
              help="每买一个收视点花多少钱。电视议价核心指标，越低越好。")
    m3.metric("曝光人次", fmt_money(imps).replace("万", "万人次").replace("亿", "亿人次"),
              help=f"按 {S['universe_name']}（{S['universe_wan']:,.0f}万人）换算")
    m4.metric("CPM（元/千人次）", fmt_num(val_cpm, 2),
              help="跨媒体比价用这个")

    with st.expander("📖 怎么读这几个数"):
        st.markdown(f"""
- **GRP {grp:.2f}** —— 相当于把广告在 {S['universe_name']} 面前平均露了 **{grp/100:.2f} 遍**。
- **CPRP {val_cprp:,.0f} 元/点** —— 这个数要跟三个东西比才有意义：
  1. 跟**计划值**比（预算测算时定的目标 CPRP）
  2. 跟**上期**比（效率是变好还是变差）
  3. 跟**同频道基准**比（是不是买贵了）
- **曝光 {fmt_money(imps)}人次** —— 注意是**人次不是人数**，同一个人看 3 次算 3 人次。
- **CPM {val_cpm:.2f} 元/千人次** —— 只有换算成 CPM，才能把电视和 OTT、信息流放在一起比。
        """)

    st.divider()
    st.markdown("**对照频道基准，看看这个价格买得值不值**")
    bt = benchmark_table()
    if not bt.empty and grp > 0:
        pick = st.selectbox("对照频道", bt["channel"].tolist(), key="t1_bench")
        bench = get_channel_benchmark(pick)
        bc1, bc2, bc3 = st.columns(3)
        bc1.metric("基准 CPRP", fmt_num(bench["cprp"], 0))
        bc2.metric("你的 CPRP", fmt_num(val_cprp, 0),
                   delta=f"{(val_cprp - bench['cprp'])/bench['cprp']*100:+.1f}%",
                   delta_color="inverse")
        verdict = ("✅ 优于基准" if val_cprp < bench["cprp"] * 0.95
                   else "⚠️ 高于基准" if val_cprp > bench["cprp"] * 1.05 else "➖ 基本持平")
        bc3.metric("判定", verdict)
        st.caption(f"基准来源：{bench['source']}")

# =============================================================================
with t2:
# =============================================================================
    st.subheader("到达率与频次")
    st.caption(
        "这一页回答的是：**投这么多 GRP，到底能碰到多少人、每人看几遍、多少人真记住了。**"
    )

    c1, c2, c3 = st.columns(3)
    grp2 = c1.number_input("GRP", 0.0, 5000.0, 180.0, 10.0, key="t2_grp")

    bt = benchmark_table()
    use_bench = c2.checkbox("从频道基准取参数", value=True, key="t2_usebench")
    if use_bench and not bt.empty:
        ch = c2.selectbox("频道", bt["channel"].tolist(), key="t2_ch")
        b = get_channel_benchmark(ch)
        max_reach, rho = float(b["max_reach"]), float(b["rho"])
        c3.metric("覆盖天花板", fmt_pct(max_reach))
        c3.caption(f"内部重复系数 ρ = {rho}")
    else:
        max_reach = c2.number_input("理论最大到达率 (%)", 1.0, 100.0, 60.0, 1.0, key="t2_mr",
                                    help="这个媒体最多能碰到多少人，到达率的天花板")
        rho = c3.slider("内部重复系数 ρ", 0.0, 0.6, 0.20, 0.01, key="t2_rho",
                        help="观众忠诚度。越大表示每次播出触达的越是同一批人，到达率涨得越慢。"
                             "央视约 0.16，一线卫视 0.22，地面频道 0.32。")

    r = reach_from_grp(grp2, max_reach, rho)
    f = frequency(grp2, r) if r > 0 else 0.0
    er = effective_reach(grp2, r, S["effective_n"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("净到达率 (1+)", fmt_pct(r), help="至少看到 1 次的人口占比（已去重）")
    m2.metric("平均频次", fmt_num(f, 2), help="被碰到的人平均每人看了几遍")
    m3.metric(f"{S['effective_n']}+ 有效到达", fmt_pct(er),
              help=f"至少看到 {S['effective_n']} 次的人口占比 —— 真正记住广告的人")
    m4.metric("触达人数", fmt_money(r / 100 * S["universe_wan"] * 10000).replace("万", "万人").replace("亿", "亿人"))

    # --- 频次诊断 ---
    if f > 0:
        if f < 2:
            st.warning(
                f"⚠️ **平均频次仅 {f:.1f} 次，偏低。** 观众看一两次基本记不住广告。"
                f"当前 {S['effective_n']}+ 有效到达只有 {er:.1f}%，"
                f"占净到达率的 {er/r*100:.0f}%。建议提高单媒体投放强度，或缩减媒体数量集中投放。"
            )
        elif f > 10:
            st.warning(
                f"⚠️ **平均频次高达 {f:.1f} 次，存在明显浪费。** "
                f"净到达率 {r:.1f}% 已接近该媒体天花板 {max_reach}%，"
                f"再加预算主要是在重复轰炸同一批人。建议增补覆盖互补的媒体来扩大净到达。"
            )
        else:
            st.success(
                f"✅ **平均频次 {f:.1f} 次，处于合理区间（3~8）。** "
                f"{S['effective_n']}+ 有效到达 {er:.1f}%，占净到达率的 {er/r*100:.0f}%。"
            )

    st.divider()

    # --- 响应曲线 ---
    gc1, gc2 = st.columns([3, 2])
    with gc1:
        st.markdown("**GRP → 到达率 响应曲线**")
        xs = list(range(0, int(max(grp2 * 2.5, 300)) + 1, 5))
        ys = [reach_from_grp(x, max_reach, rho) for x in xs]
        ys_eff = [effective_reach(x, reach_from_grp(x, max_reach, rho), S["effective_n"]) for x in xs]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=xs, y=ys, name="净到达率 (1+)",
                                 line=dict(color="#2E86AB", width=3)))
        fig.add_trace(go.Scatter(x=xs, y=ys_eff, name=f"有效到达 ({S['effective_n']}+)",
                                 line=dict(color="#A23B72", width=2, dash="dot")))
        fig.add_hline(y=max_reach, line_dash="dash", line_color="gray",
                      annotation_text=f"覆盖天花板 {max_reach}%")
        fig.add_vline(x=grp2, line_dash="dot", line_color="#F18F01",
                      annotation_text=f"当前 GRP {grp2:.0f}")
        fig.update_layout(
            xaxis_title="GRP（毛评点）", yaxis_title="到达率 (%)",
            height=380, hovermode="x unified",
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "曲线越往后越平，这就是**边际到达递减**。"
            "同样加 100 个 GRP，在曲线前段能涨很多到达率，在后段几乎不涨——"
            "这时候就该换媒体而不是加预算了。"
        )

    with gc2:
        st.markdown("**频次分布**")
        dist = frequency_distribution(grp2, r, max_n=10)
        if not dist.empty:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=dist["频次n"], y=dist["恰好n次占比(%)"],
                                  name="恰好n次", marker_color="#8FB8DE"))
            fig2.add_trace(go.Scatter(x=dist["频次n"], y=dist["n+到达率(%)"],
                                      name="n+ 累计到达", yaxis="y2",
                                      line=dict(color="#A23B72", width=2)))
            fig2.update_layout(
                xaxis_title="观看次数", yaxis_title="人口占比 (%)",
                yaxis2=dict(title="n+到达率(%)", overlaying="y", side="right"),
                height=380, margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig2, width="stretch")
            st.caption(f"柱子 = 看了恰好 n 次的人；线 = 至少看 n 次的累计人数。")

    with st.expander("📋 频次分布明细表"):
        if not dist.empty:
            show = dist.copy()
            show["恰好n次占比(%)"] = show["恰好n次占比(%)"].map(lambda x: f"{x:.2f}%")
            show["n+到达率(%)"] = show["n+到达率(%)"].map(lambda x: f"{x:.2f}%")
            st.dataframe(show, width="stretch", hide_index=True)
            st.caption(
                "**这张表是跟客户论证有效到达时最有力的材料。**"
                "比如客户说『我投了 200 个点为什么没效果』，"
                "你可以指着这张表说『其中 X% 的人只看了 1 次，真正达到 3 次以上的只有 Y%』。"
            )

# =============================================================================
with t3:
# =============================================================================
    st.subheader("反算：想达到某个目标，需要投多少")
    st.caption("这是排期测算时最常被问的问题：『老板要 60% 到达率，我该买多少 GRP、准备多少预算？』")

    c1, c2, c3 = st.columns(3)
    target = c1.number_input("目标净到达率 (%)", 1.0, 99.0, 50.0, 1.0, key="t3_target")

    bt = benchmark_table()
    use_b = c2.checkbox("从基准取参数", value=True, key="t3_usebench")
    if use_b and not bt.empty:
        ch3 = c2.selectbox("频道", bt["channel"].tolist(), key="t3_ch")
        b3 = get_channel_benchmark(ch3)
        mr3, rho3, cprp3 = float(b3["max_reach"]), float(b3["rho"]), float(b3["cprp"])
        c3.metric("该频道天花板", fmt_pct(mr3))
        c3.caption(f"CPRP {cprp3:,.0f} 元/点")
    else:
        mr3 = c2.number_input("最大到达率 (%)", 1.0, 100.0, 60.0, 1.0, key="t3_mr")
        rho3 = c3.slider("ρ", 0.0, 0.6, 0.20, 0.01, key="t3_rho")
        cprp3 = st.number_input("CPRP（元/点）", 1000.0, 200000.0, 35000.0, 1000.0, key="t3_cprp")

    need_grp = grp_needed_for_reach(target, mr3, rho3)

    if need_grp == float("inf"):
        st.error(
            f"❌ **单靠这个媒体做不到。** 该频道理论覆盖上限只有 {mr3}%，"
            f"低于你的目标 {target}%。\n\n"
            f"**这不是投更多钱能解决的问题**——就算投无限预算，到达率也只会无限逼近 {mr3}%。\n\n"
            f"解决办法：增加覆盖互补的媒体。去「🔀 跨媒体合并」标签看两个媒体加起来能到多少。"
        )
    else:
        need_cost = need_grp * cprp3
        r_check = reach_from_grp(need_grp, mr3, rho3)
        f_check = frequency(need_grp, r_check)
        er_check = effective_reach(need_grp, r_check, S["effective_n"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("需要 GRP", fmt_num(need_grp, 1))
        m2.metric("需要预算", fmt_money(need_cost))
        m3.metric("届时平均频次", fmt_num(f_check, 2))
        m4.metric(f"届时 {S['effective_n']}+ 有效到达", fmt_pct(er_check))

        st.success(
            f"要在 **{ch3 if use_b else '该媒体'}** 上做到 **{target}%** 的净到达率，"
            f"需投放 **{need_grp:.0f} 个 GRP**，按 CPRP {cprp3:,.0f} 元/点计算，"
            f"预算约 **{fmt_money(need_cost)}**。"
        )

        # 敏感性：目标每提高 5pt，成本涨多少
        st.markdown("**成本敏感性 —— 目标提高一点，代价涨多少**")
        rows = []
        for t in [target - 10, target - 5, target, target + 5, target + 10]:
            if t <= 0 or t >= mr3:
                continue
            g = grp_needed_for_reach(t, mr3, rho3)
            rows.append({
                "目标到达率(%)": t, "需要GRP": g, "需要预算(元)": g * cprp3,
                "较当前目标": "—" if t == target else f"{(g*cprp3 - need_cost)/need_cost*100:+.0f}%",
            })
        sens = pd.DataFrame(rows)
        show = sens.copy()
        show["需要GRP"] = show["需要GRP"].map(lambda x: f"{x:,.0f}")
        show["需要预算(元)"] = show["需要预算(元)"].map(fmt_money)
        show["目标到达率(%)"] = show["目标到达率(%)"].map(lambda x: f"{x:.0f}%")
        st.dataframe(show, width="stretch", hide_index=True)
        st.caption(
            "**注意成本是非线性上涨的。** 到达率目标越接近天花板，每提高 1 个点的代价越高。"
            "跟客户谈目标时，这张表能帮你解释『为什么从 55% 提到 60% 要多花那么多钱』。"
        )

# =============================================================================
with t4:
# =============================================================================
    st.subheader("刊例价与折扣")
    st.caption("对账、议价时用。折扣一律用小数：0.3 = 3折 = 打三折。")

    cc1, cc2 = st.columns(2)

    with cc1:
        st.markdown("**正算：算净花费**")
        rc = st.number_input("刊例价（元/次）", 0.0, 1e8, 100_000.0, 1000.0, key="t4_rc")
        dc = st.number_input("折扣", 0.01, 1.0, 0.25, 0.01, format="%.3f", key="t4_dc",
                             help="0.25 = 2.5折")
        sp = st.number_input("播出次数", 1, 10000, 10, 1, key="t4_sp")
        nc = net_cost(rc, dc, sp)
        st.metric("净花费", fmt_money(nc))
        st.caption(f"{rc:,.0f} × {dc} × {sp} = **{nc:,.0f} 元**（相当于打 {dc*10:.1f} 折）")

    with cc2:
        st.markdown("**反算：媒体说的折扣是真的吗**")
        actual = st.number_input("实际结算金额（元）", 0.0, 1e10, 250_000.0, 1000.0, key="t4_act")
        rc2 = st.number_input("刊例价（元/次）", 0.0, 1e8, 100_000.0, 1000.0, key="t4_rc2")
        sp2 = st.number_input("播出次数", 1, 10000, 10, 1, key="t4_sp2")
        d_real = discount_from_cost(actual, rc2, sp2)
        st.metric("实际折扣", f"{d_real:.4f}" if pd.notna(d_real) else "—",
                  help=f"相当于 {d_real*10:.2f} 折" if pd.notna(d_real) else "")
        if pd.notna(d_real):
            if d_real > 1:
                st.error(f"⚠️ 实际折扣 {d_real:.2f} > 1，说明结算金额高于刊例价。"
                         f"核对是否含制作费、代理费或附加资源。")
            else:
                st.caption(f"实际相当于打 **{d_real*10:.2f} 折**")

    st.divider()
    st.markdown("**折扣对照表**")
    st.dataframe(pd.DataFrame({
        "折扣（小数）": [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50],
        "口语说法": ["1.5折", "2折", "2.5折", "3折", "3.5折", "4折", "5折"],
        "10万刊例对应净价": [f"{0.15*1e5:,.0f}", f"{0.2*1e5:,.0f}", f"{0.25*1e5:,.0f}",
                          f"{0.3*1e5:,.0f}", f"{0.35*1e5:,.0f}", f"{0.4*1e5:,.0f}", f"{0.5*1e5:,.0f}"],
    }), width="stretch", hide_index=True)
    st.info(
        "💡 **谈折扣的时候记住**：折扣只是手段，**CPRP 才是目的**。"
        "媒体给你 1.5 折听起来很划算，但如果它的刊例价本身虚高、收视又差，"
        "换算出来的 CPRP 可能比 3 折的优质资源还贵。**永远回到 CPRP 比。**"
    )

# =============================================================================
with t5:
# =============================================================================
    st.subheader("跨媒体到达率合并")
    st.caption(
        "回答『A 台 + B 台一起投，去重后总共能碰到多少人』。"
        "单个媒体做不到的到达率目标，靠组合媒体来实现。"
    )

    n_media = st.slider("媒体数量", 2, 8, 3, key="t5_n")
    bt = benchmark_table()
    ch_options = bt["channel"].tolist() if not bt.empty else []

    rows = []
    cols = st.columns(min(n_media, 4))
    for i in range(n_media):
        with cols[i % len(cols)]:
            st.markdown(f"**媒体 {i+1}**")
            if ch_options:
                ch = st.selectbox("频道", ch_options,
                                  index=min(i, len(ch_options) - 1), key=f"t5_ch{i}")
                b = get_channel_benchmark(ch)
                mr, rho_i, cprp_i = float(b["max_reach"]), float(b["rho"]), float(b["cprp"])
            else:
                ch = f"媒体{i+1}"
                mr, rho_i, cprp_i = 50.0, 0.2, 30000.0
            g = st.number_input("GRP", 0.0, 2000.0, float(60 - i * 10), 5.0, key=f"t5_g{i}")
            r_i = reach_from_grp(g, mr, rho_i)
            st.caption(f"到达率 {r_i:.1f}%　成本 {fmt_money(g * cprp_i)}")
            rows.append({"媒体": ch, "GRP": g, "到达率(%)": r_i,
                         "花费(元)": g * cprp_i, "天花板(%)": mr})

    df5 = pd.DataFrame(rows)
    total_grp = float(df5["GRP"].sum())
    total_cost = float(df5["花费(元)"].sum())
    net_sain = combine_reach_list(df5["到达率(%)"].tolist(), "sainsbury")
    net_max = combine_reach_list(df5["到达率(%)"].tolist(), "max")
    sum_naive = float(df5["到达率(%)"].sum())

    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总 GRP", fmt_num(total_grp, 1))
    m2.metric("净到达率（去重后）", fmt_pct(net_sain),
              help="Sainsbury 公式，行业标准方法")
    m3.metric("平均频次", fmt_num(frequency(total_grp, net_sain), 2))
    m4.metric("总花费", fmt_money(total_cost))

    st.warning(
        f"**⚠️ 千万别把各媒体到达率直接相加。** "
        f"简单相加是 **{sum_naive:.1f}%**，但去重后的真实净到达只有 **{net_sain:.1f}%**，"
        f"虚高了 **{sum_naive - net_sain:.1f} 个百分点**。"
        f"这是新人汇报时最容易犯的错误之一。"
    )

    st.dataframe(
        df5.assign(**{
            "花费(元)": df5["花费(元)"].map(fmt_money),
            "到达率(%)": df5["到达率(%)"].map(lambda x: f"{x:.2f}%"),
            "天花板(%)": df5["天花板(%)"].map(lambda x: f"{x:.0f}%"),
            "GRP": df5["GRP"].map(lambda x: f"{x:.1f}"),
        }),
        width="stretch", hide_index=True,
    )

    with st.expander("📖 两种合并方法的区别，以及该用哪个"):
        st.markdown(f"""
| 方法 | 结果 | 假设 | 什么时候用 |
|---|---:|---|---|
| **Sainsbury（默认）** | {net_sain:.2f}% | 各媒体受众相互**独立** | 行业标准，对外汇报用这个 |
| **保守法（取最大）** | {net_max:.2f}% | 各媒体受众**完全重叠** | 给出下限，做最坏打算时用 |
| ~~简单相加~~ | ~~{sum_naive:.2f}%~~ | **没有任何假设，是错的** | ❌ 永远不要用 |

**Sainsbury 公式**：合并到达 = A + B − A×B/100

**它的局限**：假设独立，但现实中各媒体受众总是正相关的（爱看电视的人到处都看），
所以 Sainsbury 会**略微高估**真实净到达。

**实务建议**：对外汇报用 Sainsbury 并注明方法；
如果要保守一点，可以在结果上乘 0.9~0.95 的系数，并说明这是保守估计。
若公司有 CSM/尼尔森的官方跨媒体去重工具，以官方结果为准。
        """)
