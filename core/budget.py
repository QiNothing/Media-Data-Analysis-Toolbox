"""
预算分配优化器
==============
这是 JD 第 4 条"通过媒体投放数据的研究对如何最佳分配广告预算/资源提出建议"的核心工具。

三种分配模式，对应三种真实业务场景：

  1. 最大化净到达率（max_reach）
     场景：新品上市，要让尽可能多的人知道有这个东西。
     做法：贪心地把每一块钱投到"边际到达率增量最大"的频道。
     因为到达率是凹函数（边际递减），贪心解就是全局最优。

  2. 最大化 GRP（max_grp）
     场景：客户 KPI 直接考核 GRP/收视点数。
     做法：全部砸给 CPRP 最低的频道。数学上就这么简单。
     但工具会同时提示这样做的到达率代价——这正是你能给出的"专业建议"。

  3. 最大化有效到达（max_effective_reach）
     场景：需要建立品牌记忆，只触达一次没用。
     做法：在 3+ 到达率上做贪心，会自动倾向于把钱集中在少数频道以堆高频次。

约束支持：每个频道设最小/最大预算占比（真实工作里客户和媒体返点都会有硬性要求）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
import pandas as pd

from .metrics import (
    combine_reach_list,
    cprp as calc_cprp,
    effective_reach,
    evaluate_plan,
    frequency,
    reach_from_grp,
)

Objective = Literal["max_reach", "max_grp", "max_effective_reach"]

OBJECTIVE_LABELS = {
    "max_reach": "最大化净到达率（拉新/上市）",
    "max_grp": "最大化GRP总量（考核收视点）",
    "max_effective_reach": "最大化3+有效到达（建立记忆）",
}


@dataclass
class Constraint:
    """单个频道的预算约束。min_pct / max_pct 是占总预算的比例，0~1。"""
    channel: str
    min_pct: float = 0.0
    max_pct: float = 1.0
    locked_amount: float | None = None   # 直接锁死金额（客户指定"央视必须投200万"）


def _objective_value(
    alloc: np.ndarray,
    channels: pd.DataFrame,
    objective: Objective,
    effective_n: int,
    cross_media_method: str,
) -> float:
    """给定一组分配金额，算出目标函数值。"""
    grps = np.where(channels["cprp"].values > 0, alloc / channels["cprp"].values, 0.0)

    if objective == "max_grp":
        return float(grps.sum())

    reaches = [
        reach_from_grp(g, mr, rho)
        for g, mr, rho in zip(grps, channels["max_reach"].values, channels["rho"].values)
    ]
    net = combine_reach_list(reaches, method=cross_media_method)

    if objective == "max_reach":
        return net

    # max_effective_reach
    total_grp = float(grps.sum())
    return effective_reach(total_grp, net, n=effective_n)


def optimize_budget(
    channels: pd.DataFrame,
    total_budget: float,
    objective: Objective = "max_reach",
    constraints: list[Constraint] | None = None,
    steps: int = 200,
    effective_n: int = 3,
    cross_media_method: str = "sainsbury",
) -> dict:
    """贪心边际分配优化器。

    参数
    ----
    channels : DataFrame，需含列 channel / cprp / max_reach / rho
    total_budget : 总预算（元）
    objective : 见 Objective
    constraints : 频道约束列表
    steps : 把预算切成多少份逐份分配。份数越多结果越精细但越慢。
            200 份对绝大多数场景足够（每份 = 总预算的 0.5%）。
    effective_n : 有效频次门槛

    返回 dict：
      allocation   : DataFrame，每频道分到多少钱、产出多少 GRP/到达率
      result       : PlanResult，整体评估
      curve        : DataFrame，预算-到达率响应曲线（画边际收益图用）
      objective    : 用的哪个目标
      warnings     : 提示信息

    算法说明
    --------
    因为到达率对预算是【凹函数】（每多投一块钱带来的到达率增量单调递减），
    贪心逐份分配等价于拉格朗日边际相等条件，能取到全局最优。
    对 max_grp 目标（线性函数）贪心同样最优。
    """
    df = channels.copy().reset_index(drop=True)
    for col in ("channel", "cprp", "max_reach", "rho"):
        if col not in df.columns:
            raise ValueError(f"channels 缺少列：{col}")

    df = df[df["cprp"] > 0].reset_index(drop=True)
    warnings: list[str] = []
    if df.empty:
        raise ValueError("没有可用频道（CPRP 必须 > 0）")
    if total_budget <= 0:
        raise ValueError("总预算必须 > 0")

    n = len(df)
    cons_map = {c.channel: c for c in (constraints or [])}

    # ---- 处理硬性约束 ----
    lower = np.zeros(n)
    upper = np.full(n, float(total_budget))
    for i, ch in enumerate(df["channel"]):
        c = cons_map.get(ch)
        if c is None:
            continue
        if c.locked_amount is not None:
            lower[i] = upper[i] = float(c.locked_amount)
        else:
            lower[i] = float(c.min_pct) * total_budget
            upper[i] = float(c.max_pct) * total_budget

    if lower.sum() > total_budget + 1e-6:
        raise ValueError(
            f"约束下限之和 {lower.sum():,.0f} 元 超过总预算 {total_budget:,.0f} 元，无解。"
            "请降低某些频道的最低投放要求。"
        )
    if upper.sum() < total_budget - 1e-6:
        warnings.append(
            f"约束上限之和 {upper.sum():,.0f} 元 小于总预算 {total_budget:,.0f} 元，"
            f"有 {total_budget - upper.sum():,.0f} 元无法分配（已保留为未分配预算）。"
        )

    # ---- 先满足下限 ----
    alloc = lower.copy()
    remaining = total_budget - alloc.sum()
    chunk = remaining / steps if steps > 0 else remaining

    curve_rows = []
    if chunk > 0:
        base_val = _objective_value(alloc, df, objective, effective_n, cross_media_method)
        curve_rows.append({"已分配预算": float(alloc.sum()), "目标值": base_val})

        for _ in range(steps):
            best_i, best_gain = -1, -np.inf
            cur_val = _objective_value(alloc, df, objective, effective_n, cross_media_method)

            for i in range(n):
                if alloc[i] + chunk > upper[i] + 1e-9:
                    continue                       # 会超上限，跳过
                trial = alloc.copy()
                trial[i] += chunk
                gain = _objective_value(trial, df, objective, effective_n, cross_media_method) - cur_val
                if gain > best_gain:
                    best_gain, best_i = gain, i

            if best_i < 0:
                break                              # 所有频道都到上限了
            alloc[best_i] += chunk
            curve_rows.append({
                "已分配预算": float(alloc.sum()),
                "目标值": cur_val + best_gain,
            })

    # ---- 组装结果 ----
    out = df.copy()
    out["cost"] = alloc
    result = evaluate_plan(
        out[["channel", "cost", "cprp", "max_reach", "rho"]],
        universe_wan=_universe_placeholder(),
        effective_n=effective_n,
        cross_media_method=cross_media_method,
    )

    alloc_df = out[out["cost"] > 0].copy()
    alloc_df["grp"] = alloc_df["cost"] / alloc_df["cprp"]
    alloc_df["reach(%)"] = alloc_df.apply(
        lambda r: reach_from_grp(r["grp"], r["max_reach"], r["rho"]), axis=1
    )
    alloc_df["预算占比(%)"] = alloc_df["cost"] / total_budget * 100
    alloc_df["边际CPRP"] = alloc_df["cprp"]
    alloc_df = alloc_df.sort_values("cost", ascending=False).reset_index(drop=True)

    unallocated = total_budget - float(alloc.sum())
    if unallocated > 1:
        warnings.append(f"有 {unallocated:,.0f} 元未能分配（受上限约束）")

    return {
        "allocation": alloc_df,
        "result": result,
        "curve": pd.DataFrame(curve_rows),
        "objective": objective,
        "objective_label": OBJECTIVE_LABELS[objective],
        "warnings": warnings,
        "unallocated": unallocated,
    }


def _universe_placeholder() -> float:
    """优化器内部只关心相对大小，人口基数在这里不影响最优解，取配置默认值。"""
    from .config import load_benchmarks
    bm = load_benchmarks()
    key = bm.get("default_universe", "全国4+")
    return float(bm.get("universe", {}).get(key, 130000))


def compare_scenarios(
    channels: pd.DataFrame,
    total_budget: float,
    constraints: list[Constraint] | None = None,
    universe_wan: float | None = None,
    effective_n: int = 3,
    cross_media_method: str = "sainsbury",
    steps: int = 120,
) -> pd.DataFrame:
    """三种目标各跑一遍，横向对比。

    这张对比表就是给客户/老板汇报时的核心页：
    "如果你要广度选方案A，要收视点选方案B，要记忆度选方案C，代价分别是……"
    """
    uni = universe_wan if universe_wan is not None else _universe_placeholder()
    rows = []
    for obj in ("max_reach", "max_grp", "max_effective_reach"):
        try:
            opt = optimize_budget(
                channels, total_budget, objective=obj, constraints=constraints,
                steps=steps, effective_n=effective_n,
                cross_media_method=cross_media_method,
            )
            alloc = opt["allocation"][["channel", "cost", "cprp", "max_reach", "rho"]]
            res = evaluate_plan(alloc, uni, effective_n, cross_media_method)
            top = opt["allocation"].head(3)
            rows.append({
                "方案": OBJECTIVE_LABELS[obj],
                "总GRP": res.total_grp,
                "CPRP(元/点)": res.cprp,
                "净到达率(%)": res.net_reach,
                "平均频次": res.avg_frequency,
                f"{effective_n}+有效到达(%)": res.effective_reach,
                "CPM(元/千人次)": res.cpm,
                "频道数": len(opt["allocation"]),
                "TOP3频道": "、".join(
                    f"{row['channel']}({row['预算占比(%)']:.0f}%)"
                    for _, row in top.iterrows()
                ) if not top.empty else "",
            })
        except Exception as e:                      # noqa: BLE001 —— 单个方案失败不该拖垮整张对比表
            rows.append({"方案": OBJECTIVE_LABELS[obj], "总GRP": float("nan"), "错误": str(e)})
    return pd.DataFrame(rows)


def marginal_analysis(
    channels: pd.DataFrame,
    current_allocation: dict[str, float],
    increment: float = 100_000,
    effective_n: int = 3,
    cross_media_method: str = "sainsbury",
) -> pd.DataFrame:
    """边际分析：在现有排期基础上，"再加 X 万应该加到哪个频道"。

    这是日常工作中最高频的一个问题——客户临时追加预算，你要马上给出建议。
    返回每个频道的边际到达率增量、边际 GRP、边际成本效率，按增量排序。
    """
    df = channels.copy().reset_index(drop=True)
    base = np.array([float(current_allocation.get(ch, 0.0)) for ch in df["channel"]])

    base_reach = _objective_value(base, df, "max_reach", effective_n, cross_media_method)
    base_grp = _objective_value(base, df, "max_grp", effective_n, cross_media_method)
    base_er = _objective_value(base, df, "max_effective_reach", effective_n, cross_media_method)

    rows = []
    for i, ch in enumerate(df["channel"]):
        trial = base.copy()
        trial[i] += increment
        d_reach = _objective_value(trial, df, "max_reach", effective_n, cross_media_method) - base_reach
        d_grp = _objective_value(trial, df, "max_grp", effective_n, cross_media_method) - base_grp
        d_er = _objective_value(trial, df, "max_effective_reach", effective_n, cross_media_method) - base_er
        rows.append({
            "频道": ch,
            "当前预算": base[i],
            f"加{increment/10000:.0f}万后 净到达率增量(pt)": d_reach,
            "GRP增量": d_grp,
            f"{effective_n}+有效到达增量(pt)": d_er,
            "每万元换到达率(pt/万元)": d_reach / (increment / 10000) if increment else 0,
        })
    return (
        pd.DataFrame(rows)
        .sort_values(f"加{increment/10000:.0f}万后 净到达率增量(pt)", ascending=False)
        .reset_index(drop=True)
    )
