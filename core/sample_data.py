"""
样例数据生成器
==============
在拿到真实数据之前，这个脚本按【电视/OTT 媒介行业通用结构】造一批假数据，
让可以立刻把所有功能点一遍、心里有底。

拿到真实数据后：
  - 如果表头不一样 → 改 config/field_mapping.yaml 的 aliases，不用改代码
  - 这些样例文件可以直接删掉

数据结构参考了 CSM/尼尔森监播表、ADQUEST 竞品导出表的常见字段。
数字量级是合理的，但都是【虚构的】，不代表任何真实媒体的报价或收视表现。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"

CHANNELS = [
    ("CCTV-1", 0.85, 42000), ("CCTV-3", 0.52, 30000), ("CCTV-5", 0.48, 33000),
    ("CCTV-6", 0.45, 26000), ("CCTV-8", 0.58, 28000),
    ("湖南卫视", 0.72, 38000), ("浙江卫视", 0.55, 32000), ("江苏卫视", 0.53, 31000),
    ("东方卫视", 0.42, 27000), ("北京卫视", 0.40, 25000),
    ("安徽卫视", 0.28, 18000), ("山东卫视", 0.26, 17000),
    ("OTT开机屏", 0.35, 22000), ("OTT贴片", 0.30, 19000),
]

DAYPARTS = {
    "早间(06:00-09:00)": 0.35,
    "日间(09:00-18:00)": 0.55,
    "前黄金(18:00-19:00)": 0.85,
    "黄金(19:00-22:00)": 1.60,
    "晚间(22:00-24:00)": 0.80,
}

PROGRAMS = ["新闻联播前", "热播剧场", "综艺季播", "体育赛事", "生活服务", "电影剧场"]
CREATIVES = ["品牌TVC-15s", "品牌TVC-30s", "促销版-15s", "新品上市-30s"]
REGIONS = ["全国", "华东", "华北", "华南", "西南"]

COMPETITOR_BRANDS = [
    ("本品-悦享", 1.00), ("竞品A-康臻", 1.85), ("竞品B-优果", 1.35),
    ("竞品C-鲜活", 0.92), ("竞品D-晨光", 0.60), ("竞品E-每日", 0.45),
]


def make_placement(days: int = 61, seed: int = 42) -> pd.DataFrame:
    """造一份投放明细表（排期/监播表结构）。

    故意埋了一些【真实工作中常见的数据问题】，好让质检功能有东西可抓：
      - 3 条完全重复的记录（重复导出）
      - 2 条收视率写成 85 而不是 0.85（单位错误）
      - 2 条折扣写成 30 而不是 0.3
      - 1 条花费和刊例×折扣对不上（口径不一致）
      - 中间缺 2 天数据（漏导）
      - 1 条金额多打一个零（异常值）
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-06-01", periods=days, freq="D")
    # 制造断档：删掉两天
    dates = dates.delete([25, 26])

    rows = []
    for d in dates:
        # 每天投 6~14 条
        n = rng.integers(6, 15)
        for _ in range(n):
            ch, base_rating, base_cprp = CHANNELS[rng.integers(0, len(CHANNELS))]
            dp = list(DAYPARTS.keys())[rng.integers(0, len(DAYPARTS))]
            dp_mult = DAYPARTS[dp]

            # 周末收视上浮
            weekend = 1.15 if d.dayofweek >= 5 else 1.0
            rating = round(base_rating * dp_mult * weekend * rng.normal(1.0, 0.18), 3)
            rating = max(rating, 0.02)

            spots = int(rng.integers(1, 5))
            duration = int([15, 30, 15, 15, 30, 10][rng.integers(0, 6)])
            # 刊例价随时段和时长走
            rate_card = round(base_cprp * dp_mult * (duration / 15) * rng.normal(1.0, 0.08), -2)
            discount = round(float(rng.choice([0.15, 0.18, 0.20, 0.25, 0.30, 0.35])), 2)
            cost = round(rate_card * discount * spots, 2)

            rows.append({
                "日期": d,
                "频道": ch,
                "时段": dp,
                "节目": PROGRAMS[rng.integers(0, len(PROGRAMS))],
                "播出时间": f"{rng.integers(6, 24):02d}:{rng.integers(0, 60):02d}",
                "品牌": "本品-悦享",
                "产品": "悦享果汁",
                "素材": CREATIVES[rng.integers(0, len(CREATIVES))],
                "时长(秒)": duration,
                "播出次数": spots,
                "收视率(%)": rating,
                "GRP": round(rating * spots, 3),
                "刊例价": rate_card,
                "折扣": discount,
                "花费": cost,
                "区域": REGIONS[rng.integers(0, len(REGIONS))],
                "目标人群": "25-54岁",
            })

    df = pd.DataFrame(rows)

    # ---- 埋雷：单位错误（收视率写成百分数的100倍） ----
    for i in [10, 250]:
        if i < len(df):
            df.loc[i, "收视率(%)"] = df.loc[i, "收视率(%)"] * 100
            df.loc[i, "GRP"] = df.loc[i, "收视率(%)"] * df.loc[i, "播出次数"]

    # ---- 埋雷：折扣写成 30 而不是 0.3 ----
    for i in [55, 320]:
        if i < len(df):
            df.loc[i, "折扣"] = df.loc[i, "折扣"] * 100

    # ---- 埋雷：花费勾稽不上 ----
    if len(df) > 88:
        df.loc[88, "花费"] = round(df.loc[88, "花费"] * 1.42, 2)

    # ---- 埋雷：金额多打一个零 ----
    if len(df) > 160:
        df.loc[160, "花费"] = df.loc[160, "花费"] * 10

    # ---- 埋雷：完全重复的记录 ----
    dups = df.iloc[[30, 31, 32]].copy()
    df = pd.concat([df, dups], ignore_index=True).sort_values("日期").reset_index(drop=True)

    return df


def make_competitor(months: int = 6, seed: int = 7) -> pd.DataFrame:
    """造一份竞品监测表（ADQUEST 导出结构）。"""
    rng = np.random.default_rng(seed)
    months_idx = pd.date_range("2026-03-01", periods=months, freq="MS")

    rows = []
    for m in months_idx:
        for brand, scale in COMPETITOR_BRANDS:
            # 每个品牌在 4~9 个频道有投放
            n_ch = rng.integers(4, 10)
            picked = rng.choice(len(CHANNELS), size=n_ch, replace=False)
            for ci in picked:
                ch, base_rating, base_cprp = CHANNELS[ci]
                # 加一点时间趋势：竞品A在后期加码，本品持平
                trend = 1.0
                if brand == "竞品A-康臻":
                    trend = 1.0 + 0.09 * (m.month - months_idx[0].month)
                elif brand == "竞品B-优果":
                    trend = 1.0 - 0.04 * (m.month - months_idx[0].month)

                spend = float(rng.normal(1.0, 0.22) * scale * trend * base_cprp * rng.integers(8, 40))
                spend = max(spend, 50_000)
                grp = spend / (base_cprp * rng.normal(1.0, 0.12))
                rows.append({
                    "月份": m,
                    "品牌": brand,
                    "品类": "饮料/果汁",
                    "频道": ch,
                    "GRP": round(grp, 2),
                    "花费": round(spend, 0),
                    "播出次数": int(rng.integers(10, 120)),
                    "时长(秒)": int(rng.choice([15, 30])),
                })
    return pd.DataFrame(rows)


def make_benchmark() -> pd.DataFrame:
    """造一份频道基准表。"""
    from .config import benchmark_table
    df = benchmark_table()
    return df.rename(columns={
        "channel": "频道", "channel_type": "频道类型", "cprp": "CPRP",
        "avg_rating": "平均收视率(%)", "max_reach": "理论最大到达率(%)",
        "rho": "内部重复系数",
    })


def generate_all(out_dir: Path | None = None) -> dict[str, Path]:
    """生成全部样例文件，返回 {名称: 路径}。"""
    out = Path(out_dir) if out_dir else OUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    files = {}

    p1 = out / "样例_投放明细.xlsx"
    make_placement().to_excel(p1, index=False, sheet_name="投放明细")
    files["投放明细"] = p1

    p2 = out / "样例_竞品投放.xlsx"
    make_competitor().to_excel(p2, index=False, sheet_name="竞品投放")
    files["竞品投放"] = p2

    p3 = out / "样例_频道基准.xlsx"
    make_benchmark().to_excel(p3, index=False, sheet_name="频道基准")
    files["频道基准"] = p3

    return files


if __name__ == "__main__":
    created = generate_all()
    for name, path in created.items():
        print(f"✅ {name}: {path}")
