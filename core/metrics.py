"""
媒介指标计算内核
=================
这个文件是整个工具箱的数学地基。所有页面的计算都调用这里的函数。

核心概念速记（跟客户和媒体开会时高频出现）：
  GRP  = 毛评点 = Σ(每次播出的收视率) = 到达率 × 平均频次
  TRP  = 目标毛评点，同上但只算目标人群
  CPRP = 每个收视点的成本 = 总花费 / GRP        ← 电视媒介最核心的议价指标
  CPM  = 每千人次曝光成本 = 总花费 / 曝光量 × 1000
  到达率 Reach = 至少看到 1 次广告的人占目标人群的比例（去重）
  频次 Frequency = GRP / 到达率，平均每个被触达的人看了几次
  有效到达 nR+ = 至少看到 n 次的人的比例（n 通常取 3）

所有函数都是纯函数：输入数字，输出数字，不读文件不改全局状态，方便单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "grp_from_rating",
    "cprp",
    "cpm",
    "cpp_from_reach_freq",
    "impressions_from_grp",
    "frequency",
    "reach_from_grp",
    "grp_needed_for_reach",
    "effective_reach",
    "frequency_distribution",
    "combine_reach_sainsbury",
    "combine_reach_list",
    "net_cost",
    "discount_from_cost",
    "sov",
    "esov_growth_forecast",
    "PlanResult",
    "evaluate_plan",
]


# =============================================================================
# 一、基础换算：GRP / CPRP / CPM
# =============================================================================

def grp_from_rating(rating_pct: float | Sequence[float], spots: float | Sequence[float] = 1) -> float:
    """由收视率和播出次数算 GRP。

    GRP = Σ(单次收视率 × 该次播出数)

    参数
    ----
    rating_pct : 收视率，百分数形式（0.85 表示 0.85%，不是 85%）
    spots      : 播出次数

    例：在收视率 0.85% 的时段投 20 次 → GRP = 0.85 × 20 = 17
    """
    r = np.asarray(rating_pct, dtype=float)
    s = np.asarray(spots, dtype=float)
    return float(np.nansum(r * s))


def cprp(cost: float, grp: float) -> float:
    """CPRP = 每收视点成本 = 总花费 / GRP。

    这是电视投放最重要的一个数。跟媒体谈判、跟客户汇报效率，都是看它。
    CPRP 越低越划算。GRP 为 0 时返回 nan 而不是崩溃。
    """
    if grp is None or grp == 0 or (isinstance(grp, float) and math.isnan(grp)):
        return float("nan")
    return float(cost) / float(grp)


def cpm(cost: float, impressions: float) -> float:
    """CPM = 每千次曝光成本 = 花费 / 曝光量 × 1000。

    数字媒体和 OTT 常用 CPM，传统电视常用 CPRP。
    跨媒体比价时要统一换算到 CPM 才公平。
    """
    if not impressions:
        return float("nan")
    return float(cost) / float(impressions) * 1000.0


def cpp_from_reach_freq(cost: float, reach_pct: float, freq: float) -> float:
    """已知到达率和频次时反推 CPRP（因为 GRP = 到达率 × 频次）。"""
    return cprp(cost, reach_pct * freq)


def impressions_from_grp(grp: float, universe_wan: float) -> float:
    """由 GRP 换算绝对曝光人次。

    曝光人次 = GRP/100 × 人口基数

    参数
    ----
    grp          : 毛评点
    universe_wan : 目标人群基数，单位【万人】

    返回：曝光【人次】（已换算成个位数的人次，不是万人次）
    """
    return float(grp) / 100.0 * float(universe_wan) * 10_000.0


def frequency(grp: float, reach_pct: float) -> float:
    """平均频次 = GRP / 到达率。

    含义：被触达到的人，平均每人看了几次广告。
    经验判断：频次 < 2 说明投得太散记不住；频次 > 10 通常是浪费，该换频道扩人群了。
    """
    if not reach_pct:
        return float("nan")
    return float(grp) / float(reach_pct)


# =============================================================================
# 二、到达率模型（GRP → Reach 的转换曲线）
# =============================================================================
# 为什么需要模型：GRP 是可以无限叠加的（投两倍就是两倍 GRP），
# 但到达率不行——人口就那么多，投到后面全是在重复触达同一批人。
# 所以到达率是一条【向天花板收敛的凹曲线】，这叫"到达率递减"。
#
# 这里用工业界通用的 Beta-Binomial 简化式（Sainsbury / 负指数族）：
#     Reach = MaxReach × (1 - exp(-k × GRP / MaxReach))
# k 由内部重复系数 rho 决定：rho 越大（观众越忠诚），k 越小，曲线爬得越慢。
# =============================================================================

def _decay_k(rho: float) -> float:
    """把内部重复系数 rho 转成衰减系数 k。

    rho=0   → k=1.0  每次播出触达完全随机的人，到达率涨得最快
    rho=0.2 → k=0.8  行业常见值
    rho=0.5 → k=0.5  观众高度重叠，投再多也只覆盖固定那批人
    """
    rho = min(max(float(rho), 0.0), 0.95)
    return 1.0 - rho


def reach_from_grp(grp: float, max_reach_pct: float, rho: float = 0.20) -> float:
    """由 GRP 推算净到达率（1+ 到达率），单位 %。

    Reach = MaxReach × (1 - exp(-k × GRP / MaxReach))

    参数
    ----
    grp           : 毛评点
    max_reach_pct : 该媒体理论覆盖上限（%），例如 CCTV-1 约 62
    rho           : 内部重复系数，见 _decay_k

    性质检查（单测覆盖）：
      - GRP=0   → Reach=0
      - GRP→∞  → Reach→MaxReach（永远不会超过天花板）
      - 单调递增、凹（边际到达递减）
    """
    grp = max(float(grp), 0.0)
    mr = float(max_reach_pct)
    if mr <= 0 or grp == 0:
        return 0.0
    k = _decay_k(rho)
    return mr * (1.0 - math.exp(-k * grp / mr))


def grp_needed_for_reach(target_reach_pct: float, max_reach_pct: float, rho: float = 0.20) -> float:
    """reach_from_grp 的反函数：想达到某个到达率，需要投多少 GRP。

    这是排期时最常被问的问题："老板要 60% 到达率，我要买多少点？"
    如果目标到达率 >= 该媒体天花板，返回 inf（表示这个媒体单独做不到，必须加媒体）。
    """
    mr = float(max_reach_pct)
    tr = float(target_reach_pct)
    if tr <= 0:
        return 0.0
    if tr >= mr:
        return float("inf")
    k = _decay_k(rho)
    return -mr / k * math.log(1.0 - tr / mr)


def frequency_distribution(grp: float, reach_pct: float, max_n: int = 10) -> pd.DataFrame:
    """频次分布：算出"恰好看到 n 次"和"至少看到 n 次"各占多少人。

    用泊松分布近似（媒介行业标准做法之一）：
    在被触达的人群中，观看次数近似服从均值 = 平均频次 的泊松分布（截断掉 0 次）。

    返回一张表，列：频次n / 恰好n次占比(%) / n+到达率(%)
    这张表是做"有效到达率"论证时给客户看的核心材料。
    """
    if reach_pct <= 0 or grp <= 0:
        return pd.DataFrame({"频次n": [], "恰好n次占比(%)": [], "n+到达率(%)": []})

    f = frequency(grp, reach_pct)
    # 截断泊松：在"至少看过 1 次"的条件下，均值为 f
    # 求原始泊松参数 lam 使得 lam/(1-exp(-lam)) = f
    lam = _solve_truncated_poisson_lambda(f)

    rows = []
    cum_ge = reach_pct  # n=1 时的 n+ 到达率就是净到达率
    p_zero = math.exp(-lam)
    for n in range(1, max_n + 1):
        # 在总人口中，恰好看 n 次的比例
        p_n = (math.exp(-lam) * lam**n / math.factorial(n)) / (1 - p_zero) * reach_pct
        rows.append({"频次n": n, "恰好n次占比(%)": p_n, "n+到达率(%)": cum_ge})
        cum_ge = max(cum_ge - p_n, 0.0)
    return pd.DataFrame(rows)


def _solve_truncated_poisson_lambda(mean_freq: float, iters: int = 60) -> float:
    """解 lam / (1 - e^-lam) = mean_freq，二分法。

    mean_freq 必须 > 1（因为截断泊松的均值恒 > 1）。小于等于 1 时退化返回极小值。
    """
    if mean_freq <= 1.0000001:
        return 1e-6
    lo, hi = 1e-6, 200.0
    for _ in range(iters):
        mid = (lo + hi) / 2
        val = mid / (1 - math.exp(-mid))
        if val < mean_freq:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def effective_reach(grp: float, reach_pct: float, n: int = 3) -> float:
    """有效到达率 nR+ ：至少看到 n 次广告的人口占比（%）。

    为什么重要：只看过 1 次广告的人基本记不住，业内公认 3+ 才算"有效触达"。
    客户问"我这波投放到底有多少人真记住了"，答的就是这个数。
    """
    if n <= 1:
        return float(reach_pct)
    dist = frequency_distribution(grp, reach_pct, max_n=max(n, 10))
    row = dist[dist["频次n"] == n]
    if row.empty:
        return 0.0
    return float(row["n+到达率(%)"].iloc[0])


# =============================================================================
# 三、跨媒体到达率合并（多个频道叠加后，去重的总到达率）
# =============================================================================

def combine_reach_sainsbury(reach_a_pct: float, reach_b_pct: float) -> float:
    """Sainsbury 公式合并两个媒体的到达率（假设两者受众相互独立）。

    合并到达率 = A + B - A×B/100

    直觉：两个媒体各覆盖 50%，如果观众完全不重叠能覆盖 100%，
    但实际上会有 25% 的人两个都看到了，所以净覆盖是 75%。

    这是行业最常用的近似。它假设独立，实际会略微【高估】（真实受众总有正相关）。
    保守汇报时可以在结果上打 0.9~0.95 的折扣。
    """
    a, b = float(reach_a_pct), float(reach_b_pct)
    return a + b - a * b / 100.0


def combine_reach_list(reaches: Iterable[float], method: str = "sainsbury") -> float:
    """合并任意多个媒体的到达率。

    method:
      "sainsbury" —— 逐个用 Sainsbury 公式累积（默认，行业标准）
      "max"       —— 保守法，直接取最大值（相当于假设完全重叠，给出下限）
    """
    vals = [float(r) for r in reaches if r and not math.isnan(float(r))]
    if not vals:
        return 0.0
    if method == "max":
        return max(vals)
    total = 0.0
    for r in vals:
        total = combine_reach_sainsbury(total, r)
    return total


# =============================================================================
# 四、成本与折扣
# =============================================================================

def net_cost(rate_card: float, discount: float, spots: float = 1) -> float:
    """净花费 = 刊例价 × 折扣 × 次数。

    注意折扣的写法：0.3 表示 3 折。如果传进来 30，这里自动按 30% 处理（容错）。
    """
    d = float(discount)
    if d > 1.0:          # 容错：有人习惯填 30 表示 3折/30%
        d = d / 100.0
    return float(rate_card) * d * float(spots)


def discount_from_cost(cost: float, rate_card: float, spots: float = 1) -> float:
    """反算实际折扣 = 花费 / (刊例 × 次数)。

    对账时用：媒体报"给你 2 折"，用实际结算金额反推是不是真的 2 折。
    """
    denom = float(rate_card) * float(spots)
    if denom == 0:
        return float("nan")
    return float(cost) / denom


# =============================================================================
# 五、竞品声量
# =============================================================================

def sov(brand_value: float, market_total: float) -> float:
    """SOV 声量份额（%）= 本品投放量 / 市场总投放量。

    brand_value / market_total 可以是花费、GRP 或曝光量，但两者口径必须一致。
    """
    if not market_total:
        return float("nan")
    return float(brand_value) / float(market_total) * 100.0


def esov_growth_forecast(sov_pct: float, som_pct: float, growth_per_10pt: float = 0.5) -> dict:
    """ESOV 增长预测（Binet & Field 法则）。

    ESOV = SOV - SOM（声量份额 - 市场份额）
    经验规律：ESOV 每高出 10 个百分点，年市场份额约增长 0.5 个百分点。

    这是给客户论证"为什么要加预算"最好用的一把武器：
      SOV < SOM  → 声量赤字，份额会被侵蚀，必须加投
      SOV = SOM  → 只够维持现状
      SOV > SOM  → 有增长动能

    返回 dict，包含 esov / 预测份额增长 / 文字结论。
    """
    esov = float(sov_pct) - float(som_pct)
    growth = esov / 10.0 * float(growth_per_10pt)
    if esov < -2:
        verdict = "声量赤字：投放低于市场地位，份额有被竞品侵蚀的风险，建议增加预算"
    elif esov <= 2:
        verdict = "声量持平：仅能维持现有份额，无增长动能"
    else:
        verdict = "超额声量：具备份额增长动能，建议保持当前投放强度"
    return {
        "SOV(%)": float(sov_pct),
        "SOM(%)": float(som_pct),
        "ESOV(%)": esov,
        "预测年份额增长(pt)": growth,
        "结论": verdict,
    }


# =============================================================================
# 六、排期整体评估（把上面所有东西串起来）
# =============================================================================

@dataclass
class PlanResult:
    """一份排期方案的完整评估结果。"""
    total_cost: float = 0.0
    total_grp: float = 0.0
    cprp: float = float("nan")
    net_reach: float = 0.0
    avg_frequency: float = float("nan")
    effective_reach: float = 0.0
    effective_n: int = 3
    impressions: float = 0.0
    cpm: float = float("nan")
    per_channel: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_summary_dict(self) -> dict:
        return {
            "总预算(元)": self.total_cost,
            "总GRP": self.total_grp,
            "CPRP(元/点)": self.cprp,
            "净到达率(%)": self.net_reach,
            "平均频次": self.avg_frequency,
            f"{self.effective_n}+有效到达率(%)": self.effective_reach,
            "总曝光(人次)": self.impressions,
            "CPM(元/千人次)": self.cpm,
        }


def evaluate_plan(
    allocations: pd.DataFrame,
    universe_wan: float,
    effective_n: int = 3,
    cross_media_method: str = "sainsbury",
) -> PlanResult:
    """评估一份完整排期。

    参数
    ----
    allocations : DataFrame，必须包含列：
        channel      频道名
        cost         该频道预算
        cprp         该频道 CPRP
        max_reach    该频道到达率天花板(%)
        rho          该频道内部重复系数
    universe_wan : 目标人群基数（万人）
    effective_n  : 有效频次门槛，默认 3
    cross_media_method : 跨媒体合并方法

    返回 PlanResult，同时在 per_channel 里给出每个频道的分项指标。
    """
    df = allocations.copy()
    required = {"channel", "cost", "cprp", "max_reach", "rho"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"allocations 缺少必要列：{sorted(missing)}")

    df = df[df["cost"] > 0].copy()
    if df.empty:
        return PlanResult()

    # 每个频道：预算 → GRP → 单媒体到达率
    df["grp"] = df.apply(
        lambda r: r["cost"] / r["cprp"] if r["cprp"] > 0 else 0.0, axis=1
    )
    df["reach"] = df.apply(
        lambda r: reach_from_grp(r["grp"], r["max_reach"], r["rho"]), axis=1
    )
    df["frequency"] = df.apply(
        lambda r: frequency(r["grp"], r["reach"]) if r["reach"] > 0 else 0.0, axis=1
    )
    df["impressions"] = df["grp"].apply(lambda g: impressions_from_grp(g, universe_wan))

    total_cost = float(df["cost"].sum())
    total_grp = float(df["grp"].sum())
    net_reach = combine_reach_list(df["reach"].tolist(), method=cross_media_method)
    total_imps = float(df["impressions"].sum())

    return PlanResult(
        total_cost=total_cost,
        total_grp=total_grp,
        cprp=cprp(total_cost, total_grp),
        net_reach=net_reach,
        avg_frequency=frequency(total_grp, net_reach),
        effective_reach=effective_reach(total_grp, net_reach, n=effective_n),
        effective_n=effective_n,
        impressions=total_imps,
        cpm=cpm(total_cost, total_imps),
        per_channel=df.reset_index(drop=True),
    )
