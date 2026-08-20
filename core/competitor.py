"""
竞品与市场分析
==============
对应 JD 第 4 条："深入了解客户的业务及其竞争对手，能通过媒体投放数据的研究
对如何最佳分配广告预算/资源提出建议"。

核心产出三样东西：
  1. SOV 声量份额榜 —— 谁在市场上喊得最响
  2. ESOV 分析      —— 我的声量配不配得上我的市场份额（论证加预算的武器）
  3. 频道重合度分析 —— 竞品都在哪些频道扎堆，我该跟还是该躲
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_benchmarks
from .metrics import esov_growth_forecast, sov


def sov_ranking(
    df: pd.DataFrame,
    metric: str = "spend",
    period: str | None = None,
    top_n: int = 20,
) -> pd.DataFrame:
    """按品牌汇总，算 SOV 排名。

    参数
    ----
    df     : 竞品表，需含 brand 列 和 metric 列
    metric : 用哪个指标算份额，"spend"（花费）或 "grp"
    period : 可选，形如 "2026-07"，只算这个月

    返回：品牌 / 投放量 / SOV(%) / 排名 / 环比（若数据跨期）
    """
    if "brand" not in df.columns or metric not in df.columns:
        raise ValueError(f"竞品表需要 brand 列和 {metric} 列")

    work = df.copy()
    if period and "date" in work.columns:
        work["_p"] = pd.to_datetime(work["date"], errors="coerce").dt.to_period("M").astype(str)
        work = work[work["_p"] == period]

    if work.empty:
        return pd.DataFrame(columns=["品牌", "投放量", "SOV(%)", "排名"])

    agg = work.groupby("brand", dropna=True)[metric].sum().sort_values(ascending=False)
    total = float(agg.sum())
    out = pd.DataFrame({
        "品牌": agg.index,
        "投放量": agg.values,
        "SOV(%)": [sov(v, total) for v in agg.values],
    })
    out["排名"] = range(1, len(out) + 1)
    out["累计SOV(%)"] = out["SOV(%)"].cumsum()
    return out.head(top_n).reset_index(drop=True)


def sov_trend(df: pd.DataFrame, metric: str = "spend", brands: list[str] | None = None) -> pd.DataFrame:
    """SOV 逐月走势 —— 看竞品是在加码还是在收缩。

    返回宽表：行是月份，列是品牌，值是 SOV(%)。
    """
    if "date" not in df.columns:
        raise ValueError("需要 date 列才能算走势")
    work = df.copy()
    work["月份"] = pd.to_datetime(work["date"], errors="coerce").dt.to_period("M").astype(str)
    work = work.dropna(subset=["月份"])

    pivot = work.pivot_table(index="月份", columns="brand", values=metric,
                             aggfunc="sum", fill_value=0)
    if pivot.empty:
        return pivot
    share = pivot.div(pivot.sum(axis=1).replace(0, np.nan), axis=0) * 100
    if brands:
        keep = [b for b in brands if b in share.columns]
        share = share[keep] if keep else share
    return share.round(2)


def esov_analysis(
    df: pd.DataFrame,
    my_brand: str,
    market_share_pct: float,
    metric: str = "spend",
) -> dict:
    """本品 ESOV 分析。

    参数
    ----
    my_brand         : 本品品牌名（要和数据里一致）
    market_share_pct : 本品的市场份额 SOM（%），这个数要问客户要，投放数据里没有
    """
    rank = sov_ranking(df, metric=metric, top_n=999)
    row = rank[rank["品牌"] == my_brand]
    if row.empty:
        raise ValueError(f"竞品数据里没有找到品牌「{my_brand}」，现有品牌：{list(rank['品牌'][:10])}")

    my_sov = float(row["SOV(%)"].iloc[0])
    growth_cfg = load_benchmarks().get("esov", {})
    result = esov_growth_forecast(
        my_sov, market_share_pct,
        growth_per_10pt=float(growth_cfg.get("growth_per_10pt_esov", 0.5)),
    )
    result["本品排名"] = int(row["排名"].iloc[0])
    result["市场品牌数"] = len(rank)
    result["本品投放量"] = float(row["投放量"].iloc[0])
    result["市场总投放量"] = float(rank["投放量"].sum())

    # 要追上"声量=份额"需要补多少预算
    total = result["市场总投放量"]
    need_spend = market_share_pct / 100 * total
    result["达到SOV=SOM所需投放量"] = need_spend
    result["预算缺口"] = need_spend - result["本品投放量"]
    return result


def channel_overlap(
    df: pd.DataFrame,
    my_brand: str,
    metric: str = "spend",
    top_channels: int = 15,
) -> pd.DataFrame:
    """频道重合度：本品 vs 竞品在各频道的投放结构对比。

    这张表能直接支撑两类建议：
      - 竞品扎堆、我没投的频道 → "对手在这块吃独食，我们要不要跟"
      - 我重仓、竞品没投的频道 → "这是我们的差异化阵地，可以继续加码"
      - 大家都在挤的频道       → "红海，注意频次浪费和收视稀释"
    """
    if "channel" not in df.columns:
        raise ValueError("竞品表需要 channel 列")

    work = df.dropna(subset=["channel"]).copy()
    mine = work[work["brand"] == my_brand]
    others = work[work["brand"] != my_brand]

    my_ch = mine.groupby("channel")[metric].sum()
    ot_ch = others.groupby("channel")[metric].sum()
    all_ch = sorted(set(my_ch.index) | set(ot_ch.index))

    my_total = float(my_ch.sum()) or 1.0
    ot_total = float(ot_ch.sum()) or 1.0

    rows = []
    for ch in all_ch:
        m = float(my_ch.get(ch, 0.0))
        o = float(ot_ch.get(ch, 0.0))
        m_share = m / my_total * 100
        o_share = o / ot_total * 100
        gap = m_share - o_share

        if m_share < 1 and o_share > 8:
            verdict = "🔴 竞品重仓 / 本品缺位 —— 评估是否需要进入"
        elif m_share > 8 and o_share < 1:
            verdict = "🟢 本品独占阵地 —— 差异化优势，可继续持有"
        elif m_share > 5 and o_share > 5:
            verdict = "🟡 红海频道 —— 注意收视稀释与频次浪费"
        elif gap > 5:
            verdict = "🟢 本品偏重"
        elif gap < -5:
            verdict = "🔴 竞品偏重"
        else:
            verdict = "⚪ 结构接近"

        rows.append({
            "频道": ch,
            "本品投放量": m, "本品占比(%)": m_share,
            "竞品投放量": o, "竞品占比(%)": o_share,
            "占比差(pt)": gap,
            "本品该频道SOV(%)": sov(m, m + o) if (m + o) > 0 else 0.0,
            "策略提示": verdict,
        })

    out = pd.DataFrame(rows)
    out["_rank"] = out[["本品投放量", "竞品投放量"]].max(axis=1)
    return (out.sort_values("_rank", ascending=False)
            .drop(columns="_rank").head(top_channels).reset_index(drop=True))


def competitive_summary(df: pd.DataFrame, my_brand: str, metric: str = "spend") -> list[str]:
    """自动生成竞品分析要点，可以直接粘进周报/月报。

    返回一串中文结论句子。这是"报告解读"能力的直接体现——
    数据摆出来谁都会，能一句话说清"所以呢"才是分析师的价值。
    """
    lines: list[str] = []
    rank = sov_ranking(df, metric=metric, top_n=999)
    if rank.empty:
        return ["竞品数据为空，无法分析。"]

    metric_label = "花费" if metric == "spend" else metric.upper()
    total = rank["投放量"].sum()
    lines.append(f"本期市场共 {len(rank)} 个品牌投放，总{metric_label} {total:,.0f}。")

    top3 = rank.head(3)
    lines.append(
        "市场 TOP3：" + "、".join(
            f"{row['品牌']}（SOV {row['SOV(%)']:.1f}%）"
            for _, row in top3.iterrows()
        ) + f"，合计占据 {top3['SOV(%)'].sum():.1f}% 的市场声量。"
    )

    cr3 = top3["SOV(%)"].sum()
    if cr3 > 60:
        lines.append(f"市场集中度高（CR3 = {cr3:.0f}%），头部品牌形成声量壁垒，中小品牌需靠差异化频道或时段切入。")
    elif cr3 < 35:
        lines.append(f"市场高度分散（CR3 = {cr3:.0f}%），声量竞争充分，集中投放更容易建立相对优势。")

    mine = rank[rank["品牌"] == my_brand]
    if not mine.empty:
        r = mine.iloc[0]
        lines.append(f"本品「{my_brand}」SOV {r['SOV(%)']:.1f}%，排名第 {int(r['排名'])} / {len(rank)}。")
        leader = rank.iloc[0]
        if leader["品牌"] != my_brand:
            ratio = leader["SOV(%)"] / r["SOV(%)"] if r["SOV(%)"] > 0 else float("inf")
            lines.append(
                f"领先者「{leader['品牌']}」声量为本品的 {ratio:.1f} 倍，"
                f"差距 {leader['SOV(%)'] - r['SOV(%)']:.1f} 个百分点。"
            )

    # 走势
    if "date" in df.columns:
        try:
            trend = sov_trend(df, metric=metric)
            if len(trend) >= 2 and my_brand in trend.columns:
                delta = float(trend[my_brand].iloc[-1] - trend[my_brand].iloc[-2])
                direction = "上升" if delta > 0 else "下降"
                lines.append(f"本品 SOV 环比{direction} {abs(delta):.1f} 个百分点（{trend.index[-2]} → {trend.index[-1]}）。")
                # 谁在加码
                deltas = (trend.iloc[-1] - trend.iloc[-2]).sort_values(ascending=False)
                risers = [f"{b}(+{v:.1f}pt)" for b, v in deltas.items() if v > 1 and b != my_brand][:3]
                if risers:
                    lines.append("本期明显加码的竞品：" + "、".join(risers) + "，需关注其排期动向。")
        except Exception:                            # noqa: BLE001 —— 走势算不出来不影响主结论
            pass

    return lines
