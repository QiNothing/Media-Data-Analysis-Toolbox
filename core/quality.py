"""
数据质量检查引擎
================
对应 JD 第 2 条："负责数据质量检查，对最终交付数据报告质量负责"。
这是这份工作里【风险最高】的一项——报告发出去数字错了，锅是你的。

设计原则：
  1. 每条规则独立、可解释。检查结果必须能直接说清"哪一行、哪一列、错在哪、
     应该是多少"，而不是只丢一句"数据有问题"。
  2. 分三个等级：
     ❌ 错误(error)   —— 数据一定有问题，报告不能发
     ⚠️ 警告(warning) —— 可疑，需要人工确认
     ℹ️ 提示(info)    —— 供参考，不一定是问题
  3. 检查器返回结构化 DataFrame，方便导出成"质检报告"附在交付物后面。

规则清单见文件底部 RULE_CATALOG。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd

from .config import load_benchmarks

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SEVERITY_LABEL = {"error": "❌ 错误", "warning": "⚠️ 警告", "info": "ℹ️ 提示"}


@dataclass
class Issue:
    """一条质检发现。"""
    rule: str            # 规则名
    severity: str        # error / warning / info
    column: str          # 涉及哪一列
    row_index: Any       # 涉及哪一行（原表行号，从 1 开始，对应 Excel 行号 +1）
    detail: str          # 人话描述：错在哪
    suggestion: str      # 怎么改
    value: Any = None    # 当前值


class QualityReport:
    """质检结果容器。"""

    def __init__(self, issues: list[Issue], row_count: int, checked_rules: list[str]):
        self.issues = issues
        self.row_count = row_count
        self.checked_rules = checked_rules

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")

    @property
    def passed(self) -> bool:
        """没有 error 才算通过。有 warning 可以发但要说明。"""
        return self.error_count == 0

    def to_dataframe(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame(columns=["等级", "规则", "列", "行号", "当前值", "问题", "处理建议"])
        rows = []
        for i in sorted(self.issues, key=lambda x: (SEVERITY_ORDER[x.severity], x.rule)):
            d = asdict(i)
            rows.append({
                "等级": SEVERITY_LABEL[d["severity"]],
                "规则": d["rule"],
                "列": d["column"],
                "行号": d["row_index"],
                "当前值": d["value"],
                "问题": d["detail"],
                "处理建议": d["suggestion"],
            })
        return pd.DataFrame(rows)

    def summary_text(self) -> str:
        """一句话结论，可以直接粘进交付邮件。"""
        if self.passed and self.warning_count == 0:
            return f"✅ 质检通过：{self.row_count} 行数据，{len(self.checked_rules)} 项规则全部通过，可以交付。"
        if self.passed:
            return (
                f"⚠️ 有条件通过：{self.row_count} 行数据，0 项错误、{self.warning_count} 项警告。"
                f"建议逐条确认警告后再交付。"
            )
        return (
            f"❌ 质检未通过：{self.row_count} 行数据，发现 {self.error_count} 项错误、"
            f"{self.warning_count} 项警告。修正错误前不要交付。"
        )


# =============================================================================
# 单条规则实现
# =============================================================================

def _excel_row(idx: int) -> int:
    """DataFrame 行索引 → Excel 里的行号（+2：一行表头，Excel 从 1 开始）。"""
    return int(idx) + 2


def check_missing_required(df: pd.DataFrame, required_cols: list[str]) -> list[Issue]:
    """必填字段为空 —— 最基础也最常见的问题。"""
    issues = []
    for col in required_cols:
        if col not in df.columns:
            issues.append(Issue(
                "必填字段缺失", "error", col, "-",
                f"整张表没有「{col}」这一列", "检查数据源导出设置，或在字段映射配置里补充该列的别名",
            ))
            continue
        na_idx = df.index[df[col].isna()]
        for idx in na_idx[:50]:                     # 最多列 50 条，避免刷屏
            issues.append(Issue(
                "必填字段为空", "error", col, _excel_row(idx),
                f"「{col}」为空值", "补齐该行数据，或确认该行是否应该删除", None,
            ))
        if len(na_idx) > 50:
            issues.append(Issue(
                "必填字段为空", "error", col, "…",
                f"「{col}」共 {len(na_idx)} 行为空（仅列出前 50 条）", "批量核查数据源",
            ))
    return issues


def check_duplicates(df: pd.DataFrame, key_cols: list[str]) -> list[Issue]:
    """重复记录 —— 排期表最容易出的错：同一条广告被导了两遍，花费直接翻倍。"""
    cols = [c for c in key_cols if c in df.columns]
    if len(cols) < 2:
        return []
    dup_mask = df.duplicated(subset=cols, keep=False)
    if not dup_mask.any():
        return []
    issues = []
    dup_groups = df[dup_mask].groupby(cols, dropna=False)
    for key, grp in list(dup_groups)[:30]:
        rows = "、".join(str(_excel_row(i)) for i in grp.index[:10])
        issues.append(Issue(
            "疑似重复记录", "error", "+".join(cols), rows,
            f"以下行在 {'/'.join(cols)} 上完全相同（{len(grp)} 条）：{key}",
            "确认是否重复导出。若确为多次播出，请补充「播出时间」等区分字段",
        ))
    return issues


def check_value_range(df: pd.DataFrame) -> list[Issue]:
    """数值合理性 —— 抓单位搞错、小数点错位这类事故。"""
    bm = load_benchmarks().get("quality", {})
    issues = []

    # 收视率：>15% 基本不可能，常见错误是把 0.85% 写成 85
    if "rating" in df.columns:
        cap = float(bm.get("rating_max", 15.0))
        bad = df.index[df["rating"] > cap]
        for idx in bad[:30]:
            v = df.at[idx, "rating"]
            issues.append(Issue(
                "收视率超出合理范围", "error", "rating", _excel_row(idx),
                f"收视率 {v} 超过 {cap}%，几乎可以确定是单位错误",
                f"如果原意是 {v/100:.2f}%，说明源数据用了小数形式，需整列除以 100", v,
            ))
        neg = df.index[df["rating"] < 0]
        for idx in neg[:20]:
            issues.append(Issue(
                "收视率为负", "error", "rating", _excel_row(idx),
                "收视率不可能为负数", "核对数据源", df.at[idx, "rating"],
            ))

    # 折扣：必须在 (0, 1]
    if "discount" in df.columns:
        dmin = float(bm.get("discount_min", 0.01))
        dmax = float(bm.get("discount_max", 1.0))
        bad = df.index[(df["discount"] > dmax) & df["discount"].notna()]
        for idx in bad[:30]:
            v = df.at[idx, "discount"]
            hint = f"若原意是 {v/100:.2f}（{v/10:.1f}折），需整列除以 100" if v <= 100 else "数值异常，请核对"
            issues.append(Issue(
                "折扣大于1", "error", "discount", _excel_row(idx),
                f"折扣 {v} > 1，折扣应为小数形式（0.3 = 3折）", hint, v,
            ))
        low = df.index[(df["discount"] < dmin) & (df["discount"] > 0)]
        for idx in low[:20]:
            issues.append(Issue(
                "折扣异常低", "warning", "discount", _excel_row(idx),
                f"折扣 {df.at[idx, 'discount']} 低于 {dmin}（不到 {dmin*10:.1f} 折）",
                "确认是否为特殊资源置换或数据错误", df.at[idx, "discount"],
            ))

    # 花费、次数：不能为负
    for col, label in (("cost", "花费"), ("spots", "播出次数"), ("grp", "GRP"),
                       ("impressions", "曝光量"), ("rate_card", "刊例价")):
        if col in df.columns:
            neg = df.index[df[col] < 0]
            for idx in neg[:20]:
                issues.append(Issue(
                    f"{label}为负", "error", col, _excel_row(idx),
                    f"{label} = {df.at[idx, col]}，不应为负数",
                    "确认是否为冲红/退款记录，若是请单独标记", df.at[idx, col],
                ))

    # 到达率：0~100
    if "reach" in df.columns:
        bad = df.index[(df["reach"] > 100) | (df["reach"] < 0)]
        for idx in bad[:20]:
            issues.append(Issue(
                "到达率超出0-100", "error", "reach", _excel_row(idx),
                f"到达率 {df.at[idx, 'reach']} 不在 0~100 区间",
                "到达率是百分数，最大 100", df.at[idx, "reach"],
            ))

    # 广告时长：非常规秒数
    if "duration" in df.columns:
        valid = set(bm.get("duration_valid", [5, 10, 15, 20, 30, 45, 60]))
        odd = df.index[df["duration"].notna() & ~df["duration"].isin(valid)]
        odd_vals = df.loc[odd, "duration"].value_counts()
        for v, cnt in list(odd_vals.items())[:10]:
            issues.append(Issue(
                "非常规广告时长", "info", "duration", "-",
                f"出现 {cnt} 条时长为 {v} 秒的记录，不在常见时长 {sorted(valid)} 中",
                "确认是否为定制时长或数据录入错误", v,
            ))

    return issues


def check_cost_consistency(df: pd.DataFrame) -> list[Issue]:
    """勾稽关系：花费 ≈ 刊例价 × 折扣 × 次数。

    这是对账的核心检查。媒体给的结算单和排期表对不上，一般就是这里出问题。
    """
    need = {"cost", "rate_card", "discount"}
    if not need.issubset(df.columns):
        return []
    tol = float(load_benchmarks().get("quality", {}).get("cost_consistency_tol", 0.02))

    spots = df["spots"] if "spots" in df.columns else pd.Series(1.0, index=df.index)
    disc = df["discount"].where(df["discount"] <= 1, df["discount"] / 100)   # 容错
    expected = df["rate_card"] * disc * spots.fillna(1)

    valid = expected.notna() & df["cost"].notna() & (expected > 0)
    rel_diff = ((df["cost"] - expected) / expected).abs()
    bad = df.index[valid & (rel_diff > tol)]

    issues = []
    for idx in bad[:40]:
        issues.append(Issue(
            "花费与刊例×折扣不符", "error", "cost", _excel_row(idx),
            f"实际花费 {df.at[idx, 'cost']:,.0f}，按刊例×折扣×次数应为 "
            f"{expected.at[idx]:,.0f}，偏差 {rel_diff.at[idx]*100:.1f}%",
            "核对刊例价版本、折扣口径（是否含代理费/税）或是否有附加资源",
            df.at[idx, "cost"],
        ))
    if len(bad) > 40:
        issues.append(Issue(
            "花费与刊例×折扣不符", "error", "cost", "…",
            f"共 {len(bad)} 行不符（仅列出前 40 条）",
            "偏差行数过多，通常是整列口径不一致，先确认口径再逐行核",
        ))
    return issues


def check_grp_consistency(df: pd.DataFrame) -> list[Issue]:
    """勾稽关系：GRP ≈ 收视率 × 播出次数。"""
    need = {"grp", "rating", "spots"}
    if not need.issubset(df.columns):
        return []
    tol = float(load_benchmarks().get("quality", {}).get("grp_consistency_tol", 0.05))
    expected = df["rating"] * df["spots"]
    valid = expected.notna() & df["grp"].notna() & (expected > 0)
    rel_diff = ((df["grp"] - expected) / expected).abs()
    bad = df.index[valid & (rel_diff > tol)]

    issues = []
    for idx in bad[:40]:
        issues.append(Issue(
            "GRP与收视率×次数不符", "error", "grp", _excel_row(idx),
            f"GRP {df.at[idx, 'grp']:.2f}，按收视率×次数应为 {expected.at[idx]:.2f}，"
            f"偏差 {rel_diff.at[idx]*100:.1f}%",
            "确认 GRP 是否为目标人群口径（TRP），两者不能混用",
            df.at[idx, "grp"],
        ))
    return issues


def check_outliers(df: pd.DataFrame, cols: list[str] | None = None) -> list[Issue]:
    """统计异常值（Z-score）—— 抓那种"多打了一个零"的录入事故。"""
    z_thresh = float(load_benchmarks().get("quality", {}).get("outlier_z", 3.0))
    numeric = cols or [c for c in ("cost", "grp", "rating", "impressions", "rate_card")
                       if c in df.columns]
    issues = []
    for col in numeric:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) < 10 or s.std(ddof=0) == 0:
            continue
        z = (s - s.mean()) / s.std(ddof=0)
        for idx in z.index[z.abs() > z_thresh][:15]:
            issues.append(Issue(
                "统计异常值", "warning", col, _excel_row(idx),
                f"{col} = {df.at[idx, col]:,.2f}，偏离均值 {abs(z.at[idx]):.1f} 个标准差"
                f"（均值 {s.mean():,.2f}）",
                "确认是否为大单/特殊资源，或小数点/零的位数错误", df.at[idx, col],
            ))
    return issues


def check_date_continuity(df: pd.DataFrame) -> list[Issue]:
    """日期连续性 —— 排期中间断档，通常意味着漏导数据。"""
    if "date" not in df.columns:
        return []
    dates = pd.to_datetime(df["date"], errors="coerce").dropna()
    if dates.empty:
        return []
    uniq = pd.Series(sorted(dates.dt.normalize().unique()))
    if len(uniq) < 2:
        return []
    full = pd.date_range(uniq.iloc[0], uniq.iloc[-1], freq="D")
    missing = sorted(set(full) - set(uniq))
    issues = []
    if missing:
        preview = "、".join(d.strftime("%m-%d") for d in missing[:15])
        more = f"…等 {len(missing)} 天" if len(missing) > 15 else ""
        issues.append(Issue(
            "日期断档", "warning", "date", "-",
            f"投放区间 {uniq.iloc[0]:%Y-%m-%d} ~ {uniq.iloc[-1]:%Y-%m-%d} 内，"
            f"以下日期没有任何记录：{preview}{more}",
            "确认是排期本身就停投，还是数据漏导",
        ))
    # 未来日期
    today = pd.Timestamp.now().normalize()
    future = dates[dates > today]
    if len(future) > 0:
        issues.append(Issue(
            "存在未来日期", "info", "date", "-",
            f"有 {len(future)} 条记录日期晚于今天（最晚 {future.max():%Y-%m-%d}）",
            "如果是排期计划表属正常；如果是投后监播数据，说明日期有误",
        ))
    return issues


def check_mom_jump(df: pd.DataFrame, value_col: str = "cost") -> list[Issue]:
    """环比波动 —— 逐日花费突然翻倍/腰斩，值得看一眼。"""
    if "date" not in df.columns or value_col not in df.columns:
        return []
    thresh = float(load_benchmarks().get("quality", {}).get("mom_jump_pct", 0.5))
    daily = (
        df.assign(_d=pd.to_datetime(df["date"], errors="coerce"))
        .dropna(subset=["_d"])
        .groupby(df.assign(_d=pd.to_datetime(df["date"], errors="coerce"))["_d"].dt.date)[value_col]
        .sum()
        .sort_index()
    )
    if len(daily) < 3:
        return []
    pct = daily.pct_change()
    issues = []
    for d, p in pct.items():
        if pd.notna(p) and abs(p) > thresh:
            issues.append(Issue(
                "日环比大幅波动", "info", value_col, str(d),
                f"{d} 的{value_col}为 {daily[d]:,.0f}，较前一日变化 {p*100:+.0f}%",
                "确认是否为大促/停投等正常业务波动",
            ))
    return issues[:20]


def check_channel_coverage(df: pd.DataFrame) -> list[Issue]:
    """频道是否都在基准表里 —— 不在的话后续算 CPRP 只能用兜底均值。"""
    if "channel" not in df.columns:
        return []
    from .config import load_benchmarks as _lb
    known = set(_lb().get("channels", {}).keys())
    actual = {c for c in df["channel"].dropna().unique() if str(c).strip()}
    unknown = sorted(actual - known)
    if not unknown:
        return []
    return [Issue(
        "频道不在基准表", "warning", "channel", "-",
        f"以下频道没有基准数据，计算 CPRP/到达率时会用全表均值兜底：{'、'.join(unknown[:20])}",
        "在 config/benchmarks.yaml 的 channels 里补充这些频道的 CPRP 与收视基准",
    )]


# =============================================================================
# 主入口
# =============================================================================

def run_quality_check(
    df: pd.DataFrame,
    section: str = "placement",
    enabled_rules: set[str] | None = None,
) -> QualityReport:
    """跑全套质检。

    参数
    ----
    df       : 已经过字段映射（列名是标准字段名）的表
    section  : "placement" / "competitor"
    enabled_rules : 只跑指定规则；None = 全跑

    返回 QualityReport
    """
    from .config import load_field_mapping

    spec = load_field_mapping().get(section, {})
    required = [k for k, v in spec.items() if isinstance(v, dict) and v.get("required")]

    all_rules: dict[str, Any] = {
        "必填字段": lambda d: check_missing_required(d, required),
        "重复记录": lambda d: check_duplicates(d, ["date", "channel", "program", "spot_time", "creative"]),
        "数值范围": check_value_range,
        "花费勾稽": check_cost_consistency,
        "GRP勾稽": check_grp_consistency,
        "异常值": check_outliers,
        "日期连续性": check_date_continuity,
        "环比波动": lambda d: check_mom_jump(d, "cost"),
        "频道覆盖": check_channel_coverage,
    }

    rules = {k: v for k, v in all_rules.items()
             if enabled_rules is None or k in enabled_rules}

    issues: list[Issue] = []
    for name, fn in rules.items():
        try:
            issues.extend(fn(df))
        except Exception as e:                      # noqa: BLE001 —— 单条规则挂了不影响其他规则
            issues.append(Issue(
                name, "warning", "-", "-",
                f"规则「{name}」执行失败：{e}", "这通常是数据格式问题，请检查该规则涉及的列",
            ))

    return QualityReport(issues, len(df), list(rules.keys()))


# =============================================================================
# 规则说明书 —— 页面上展示，也是你跟同事解释"我都查了什么"的依据
# =============================================================================

RULE_CATALOG = pd.DataFrame([
    {"规则": "必填字段", "查什么": "日期/频道/花费等关键列是否缺列或有空值", "等级": "❌ 错误",
     "为什么重要": "缺关键字段的行无法参与任何汇总，会导致合计数对不上"},
    {"规则": "重复记录", "查什么": "同日期+频道+节目+时间+素材的完全重复行", "等级": "❌ 错误",
     "为什么重要": "重复导出会让花费和GRP直接翻倍，是最容易发生的重大事故"},
    {"规则": "数值范围", "查什么": "收视率>15%、折扣>1、金额为负、到达率>100 等", "等级": "❌ 错误",
     "为什么重要": "抓单位错误和小数点错位，例如把 0.85% 写成 85"},
    {"规则": "花费勾稽", "查什么": "花费 是否等于 刊例价×折扣×次数", "等级": "❌ 错误",
     "为什么重要": "对账核心。不符通常是折扣口径不一致（含不含代理费/税）"},
    {"规则": "GRP勾稽", "查什么": "GRP 是否等于 收视率×播出次数", "等级": "❌ 错误",
     "为什么重要": "不符往往是 GRP 与 TRP 混用（全人群 vs 目标人群口径）"},
    {"规则": "异常值", "查什么": "Z-score 超过 3 的极端数值", "等级": "⚠️ 警告",
     "为什么重要": "抓'多打一个零'这类录入事故，也可能是真实大单，需人工判断"},
    {"规则": "日期连续性", "查什么": "投放区间内有没有整天没数据、有没有未来日期", "等级": "⚠️ 警告",
     "为什么重要": "断档往往是漏导数据，会低估总投放量"},
    {"规则": "环比波动", "查什么": "逐日花费环比变化超过 50%", "等级": "ℹ️ 提示",
     "为什么重要": "帮你在汇报前先知道哪天有异动，免得被客户问住"},
    {"规则": "频道覆盖", "查什么": "数据里的频道是否都有基准 CPRP", "等级": "⚠️ 警告",
     "为什么重要": "没有基准的频道只能用均值兜底，测算精度会下降"},
])
