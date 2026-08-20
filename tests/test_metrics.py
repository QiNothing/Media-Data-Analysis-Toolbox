"""
媒介数学正确性测试
==================
这些测试保证工具箱算出来的数不会错——因为你要拿这些数去跟客户汇报。

跑法：在 打工工具 目录下执行
    python -m tests.test_metrics
或
    python tests/test_metrics.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from core.budget import Constraint, compare_scenarios, marginal_analysis, optimize_budget
from core.metrics import (
    combine_reach_list,
    combine_reach_sainsbury,
    cpm,
    cprp,
    discount_from_cost,
    effective_reach,
    esov_growth_forecast,
    evaluate_plan,
    frequency,
    frequency_distribution,
    grp_from_rating,
    grp_needed_for_reach,
    impressions_from_grp,
    net_cost,
    reach_from_grp,
    sov,
)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(b))


# =============================================================================
print("\n【1】基础换算")
# =============================================================================

check("GRP = 收视率 × 次数", approx(grp_from_rating(0.85, 20), 17.0))
check("GRP 支持数组求和", approx(grp_from_rating([1.0, 2.0, 3.0], [1, 2, 3]), 14.0))
check("CPRP = 花费 / GRP", approx(cprp(1_000_000, 25), 40_000))
check("CPRP 除零返回 nan", math.isnan(cprp(100, 0)))
check("CPM = 花费/曝光×1000", approx(cpm(50_000, 2_000_000), 25.0))
check("GRP→曝光人次", approx(impressions_from_grp(100, 13000), 130_000_000),
      "GRP100 × 1.3亿人 = 1.3亿人次")
check("频次 = GRP / 到达率", approx(frequency(180, 60), 3.0))

# =============================================================================
print("\n【2】到达率模型的数学性质")
# =============================================================================

check("GRP=0 时到达率=0", reach_from_grp(0, 60, 0.2) == 0.0)

r_small = reach_from_grp(10, 60, 0.2)
r_mid = reach_from_grp(100, 60, 0.2)
r_big = reach_from_grp(1000, 60, 0.2)
r_huge = reach_from_grp(100_000, 60, 0.2)

check("到达率单调递增", r_small < r_mid < r_big)
check("到达率不超过天花板", r_huge <= 60.0 + 1e-9, f"得到 {r_huge}")
check("GRP 极大时收敛到天花板", approx(r_huge, 60.0, 1e-4), f"得到 {r_huge:.6f}")

# 凹性：等量增加 GRP，到达率增量应递减
d1 = reach_from_grp(50, 60, 0.2) - reach_from_grp(0, 60, 0.2)
d2 = reach_from_grp(100, 60, 0.2) - reach_from_grp(50, 60, 0.2)
d3 = reach_from_grp(150, 60, 0.2) - reach_from_grp(100, 60, 0.2)
check("边际到达递减（凹函数）", d1 > d2 > d3, f"增量 {d1:.2f} > {d2:.2f} > {d3:.2f}")

# rho 越大，到达率涨得越慢
check("rho 越大到达率越低",
      reach_from_grp(100, 60, 0.05) > reach_from_grp(100, 60, 0.20) > reach_from_grp(100, 60, 0.45))

# 反函数
for target in (10.0, 30.0, 50.0, 58.0):
    g = grp_needed_for_reach(target, 60, 0.2)
    back = reach_from_grp(g, 60, 0.2)
    check(f"反函数自洽（目标到达率 {target}%）", approx(back, target, 1e-6),
          f"需 GRP {g:.1f} → 回算到达率 {back:.6f}")

check("目标到达率≥天花板返回 inf", math.isinf(grp_needed_for_reach(60, 60, 0.2)))
check("目标到达率超天花板返回 inf", math.isinf(grp_needed_for_reach(70, 60, 0.2)))

# =============================================================================
print("\n【3】跨媒体到达率合并")
# =============================================================================

check("Sainsbury: 50%+50% = 75%", approx(combine_reach_sainsbury(50, 50), 75.0))
check("Sainsbury: 与 0 合并不变", approx(combine_reach_sainsbury(40, 0), 40.0))
check("Sainsbury: 与 100 合并为 100", approx(combine_reach_sainsbury(40, 100), 100.0))
check("Sainsbury 交换律", approx(combine_reach_sainsbury(30, 70), combine_reach_sainsbury(70, 30)))

multi = combine_reach_list([50, 50, 50])
check("三媒体合并 = 87.5%", approx(multi, 87.5), f"得到 {multi}")
check("合并结果不超过 100", combine_reach_list([90, 90, 90, 90]) <= 100.0)
check("合并结果 ≥ 单项最大", combine_reach_list([30, 55, 20]) >= 55.0)
check("max 方法取最大值", approx(combine_reach_list([30, 55, 20], method="max"), 55.0))
check("空列表返回 0", combine_reach_list([]) == 0.0)

# 结合律：合并顺序不影响结果
a = combine_reach_list([20, 40, 60])
b = combine_reach_list([60, 20, 40])
check("合并顺序无关", approx(a, b), f"{a:.6f} vs {b:.6f}")

# =============================================================================
print("\n【4】频次分布与有效到达")
# =============================================================================

dist = frequency_distribution(grp=180, reach_pct=60, max_n=10)
check("频次分布非空", not dist.empty)
check("1+ 到达率 = 净到达率", approx(float(dist.loc[0, "n+到达率(%)"]), 60.0, 1e-6))
check("n+ 到达率单调递减", dist["n+到达率(%)"].is_monotonic_decreasing)
check("各频次占比非负", (dist["恰好n次占比(%)"] >= -1e-9).all())

er1 = effective_reach(180, 60, n=1)
er3 = effective_reach(180, 60, n=3)
er5 = effective_reach(180, 60, n=5)
check("1+ 有效到达 = 净到达率", approx(er1, 60.0))
check("有效到达随 n 递减", er1 > er3 > er5, f"1+={er1:.1f} 3+={er3:.1f} 5+={er5:.1f}")
check("3+ 有效到达 ≤ 净到达率", er3 <= 60.0)
check("有效到达非负", er5 >= 0)

# 频次越高，3+ 有效到达占净到达比例越高
low_f = effective_reach(120, 60, 3) / 60      # 频次 2
high_f = effective_reach(360, 60, 3) / 60     # 频次 6
check("频次越高 3+占比越高", high_f > low_f, f"频次2时 {low_f:.2%}，频次6时 {high_f:.2%}")

# =============================================================================
print("\n【5】成本与折扣")
# =============================================================================

check("净花费 = 刊例×折扣×次数", approx(net_cost(100_000, 0.3, 2), 60_000))
check("折扣容错（传30当30%）", approx(net_cost(100_000, 30, 1), 30_000))
check("反算折扣", approx(discount_from_cost(60_000, 100_000, 2), 0.3))
check("反算折扣除零返回 nan", math.isnan(discount_from_cost(100, 0)))

# =============================================================================
print("\n【6】竞品 SOV / ESOV")
# =============================================================================

check("SOV 计算", approx(sov(250, 1000), 25.0))
check("SOV 除零返回 nan", math.isnan(sov(100, 0)))

e = esov_growth_forecast(30, 20)
check("ESOV = SOV - SOM", approx(e["ESOV(%)"], 10.0))
check("ESOV 增长预测", approx(e["预测年份额增长(pt)"], 0.5), f"得到 {e['预测年份额增长(pt)']}")
check("正 ESOV 给增长结论", "增长动能" in e["结论"])
check("负 ESOV 给赤字警告", "赤字" in esov_growth_forecast(10, 25)["结论"])
check("ESOV 持平给维持结论", "持平" in esov_growth_forecast(20, 20)["结论"])

# =============================================================================
print("\n【7】排期评估")
# =============================================================================

plan = pd.DataFrame({
    "channel": ["CCTV-1", "湖南卫视", "浙江卫视"],
    "cost": [2_000_000, 1_500_000, 1_000_000],
    "cprp": [42000, 38000, 32000],
    "max_reach": [62, 52, 47],
    "rho": [0.16, 0.22, 0.22],
})
res = evaluate_plan(plan, universe_wan=13000)

expected_grp = 2_000_000/42000 + 1_500_000/38000 + 1_000_000/32000
check("总花费正确", approx(res.total_cost, 4_500_000))
check("总GRP正确", approx(res.total_grp, expected_grp, 1e-9), f"{res.total_grp:.4f}")
check("CPRP 自洽", approx(res.cprp, 4_500_000 / expected_grp))
check("净到达率 ≤ 100", res.net_reach <= 100)
check("净到达率 > 最大单频道", res.net_reach > max(
    reach_from_grp(2_000_000/42000, 62, 0.16),
    reach_from_grp(1_500_000/38000, 52, 0.22),
    reach_from_grp(1_000_000/32000, 47, 0.22),
))
check("平均频次 = GRP/到达率", approx(res.avg_frequency, res.total_grp / res.net_reach))
check("3+有效到达 ≤ 净到达率", res.effective_reach <= res.net_reach)
check("每频道明细行数正确", len(res.per_channel) == 3)

try:
    evaluate_plan(pd.DataFrame({"channel": ["A"], "cost": [1]}), 13000)
    check("缺必要列时抛异常", False, "没有抛异常")
except ValueError:
    check("缺必要列时抛异常", True)

check("空排期返回零结果", evaluate_plan(
    pd.DataFrame({"channel": [], "cost": [], "cprp": [], "max_reach": [], "rho": []}),
    13000).total_cost == 0)

# =============================================================================
print("\n【8】预算优化器")
# =============================================================================

chans = pd.DataFrame({
    "channel": ["CCTV-1", "湖南卫视", "浙江卫视", "安徽卫视", "OTT开机屏"],
    "cprp": [42000, 38000, 32000, 18000, 22000],
    "max_reach": [62, 52, 47, 32, 55],
    "rho": [0.16, 0.22, 0.22, 0.26, 0.18],
})
BUDGET = 10_000_000

opt_reach = optimize_budget(chans, BUDGET, "max_reach", steps=60)
check("预算全部分配完", approx(float(opt_reach["allocation"]["cost"].sum()), BUDGET, 1e-3),
      f"分配 {opt_reach['allocation']['cost'].sum():,.0f}")
check("到达率优化会分散到多个频道", len(opt_reach["allocation"]) >= 3,
      f"用了 {len(opt_reach['allocation'])} 个频道")
check("响应曲线单调递增", opt_reach["curve"]["目标值"].is_monotonic_increasing)

opt_grp = optimize_budget(chans, BUDGET, "max_grp", steps=60)
top_grp_ch = opt_grp["allocation"].iloc[0]["channel"]
check("GRP优化集中到最低CPRP频道", top_grp_ch == "安徽卫视", f"实际是 {top_grp_ch}")
check("GRP优化的GRP ≥ 到达率优化的GRP",
      opt_grp["result"].total_grp >= opt_reach["result"].total_grp - 1e-6,
      f"{opt_grp['result'].total_grp:.1f} vs {opt_reach['result'].total_grp:.1f}")
check("到达率优化的净到达 ≥ GRP优化的净到达",
      opt_reach["result"].net_reach >= opt_grp["result"].net_reach - 1e-6,
      f"{opt_reach['result'].net_reach:.2f} vs {opt_grp['result'].net_reach:.2f}")

# 约束
cons = [Constraint("CCTV-1", min_pct=0.30), Constraint("安徽卫视", max_pct=0.10)]
opt_c = optimize_budget(chans, BUDGET, "max_reach", constraints=cons, steps=60)
alloc_map = dict(zip(opt_c["allocation"]["channel"], opt_c["allocation"]["cost"]))
check("最低占比约束生效", alloc_map.get("CCTV-1", 0) >= BUDGET * 0.30 - 1,
      f"CCTV-1 分到 {alloc_map.get('CCTV-1', 0):,.0f}")
check("最高占比约束生效", alloc_map.get("安徽卫视", 0) <= BUDGET * 0.10 + 1,
      f"安徽卫视 分到 {alloc_map.get('安徽卫视', 0):,.0f}")

# 锁定金额
opt_l = optimize_budget(chans, BUDGET, "max_reach",
                        constraints=[Constraint("CCTV-1", locked_amount=3_000_000)], steps=40)
locked = dict(zip(opt_l["allocation"]["channel"], opt_l["allocation"]["cost"]))
check("锁定金额精确生效", approx(locked.get("CCTV-1", 0), 3_000_000, 1e-6),
      f"实际 {locked.get('CCTV-1', 0):,.0f}")

# 无解检测
try:
    optimize_budget(chans, 1_000_000,
                    constraints=[Constraint(c, min_pct=0.5) for c in chans["channel"][:3]])
    check("约束无解时抛异常", False, "没有抛异常")
except ValueError as ex:
    check("约束无解时抛异常", "无解" in str(ex))

# 约束优化的目标值不会优于无约束
check("约束不会让结果更优",
      opt_c["result"].net_reach <= opt_reach["result"].net_reach + 1e-6,
      f"约束后 {opt_c['result'].net_reach:.3f} vs 自由 {opt_reach['result'].net_reach:.3f}")

# 预算越多到达率越高
small = optimize_budget(chans, 2_000_000, "max_reach", steps=40)
large = optimize_budget(chans, 20_000_000, "max_reach", steps=40)
check("预算越大净到达越高",
      large["result"].net_reach > small["result"].net_reach,
      f"200万 {small['result'].net_reach:.1f}% → 2000万 {large['result'].net_reach:.1f}%")

# 三方案对比
cmp_df = compare_scenarios(chans, BUDGET, steps=40)
check("三方案对比表生成", len(cmp_df) == 3)
check("对比表无错误列", "错误" not in cmp_df.columns,
      str(cmp_df.get("错误", pd.Series()).tolist()))

# 边际分析
marg = marginal_analysis(chans, {"CCTV-1": 3_000_000, "湖南卫视": 2_000_000}, increment=1_000_000)
check("边际分析覆盖全部频道", len(marg) == len(chans))
check("边际到达增量非负", (marg["加100万后 净到达率增量(pt)"] >= -1e-9).all())
check("边际分析按增量降序", marg["加100万后 净到达率增量(pt)"].is_monotonic_decreasing)

# =============================================================================
print("\n【9】边界与异常输入")
# =============================================================================

check("到达率天花板为0时返回0", reach_from_grp(100, 0, 0.2) == 0.0)
check("负GRP按0处理", reach_from_grp(-50, 60, 0.2) == 0.0)
check("rho=0 时到达率最高", reach_from_grp(100, 60, 0) > reach_from_grp(100, 60, 0.5))
check("rho 超界被夹紧", reach_from_grp(100, 60, 5.0) >= 0)
check("频次为0到达率时返回nan", math.isnan(frequency(100, 0)))
check("空频次分布不崩", frequency_distribution(0, 0).empty)

try:
    optimize_budget(chans, -100)
    check("负预算抛异常", False)
except ValueError:
    check("负预算抛异常", True)

try:
    optimize_budget(pd.DataFrame({"channel": ["A"], "cprp": [0], "max_reach": [50], "rho": [0.2]}), 1e6)
    check("全零CPRP抛异常", False)
except ValueError:
    check("全零CPRP抛异常", True)


# =============================================================================
print("\n" + "=" * 62)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("\n失败清单：")
    for name, detail in FAIL:
        print(f"  ❌ {name}  {detail}")
    sys.exit(1)
print("✅ 全部通过 —— 媒介数学计算可信")
print("=" * 62)
