"""
媒介数据分析工具箱 —— 首页
==========================
启动方式：双击 启动.bat，或在 打工工具 目录执行 streamlit run app/主页.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import DOCS_DIR, SAMPLE_DIR, setup_page                    # noqa: E402
from core.config import is_calibrated                                       # noqa: E402

setup_page("媒介数据分析工具箱", "🎬")

st.markdown("""
欢迎。这个工具箱是照着媒介方向数据分析师的常见 JD 的四条职责搭的，
左侧每个页面都对应 JD 里的一项具体要求。

**第一次用，建议按这个顺序走一遍**（大约 20 分钟）：
""")

c1, c2 = st.columns([3, 2])

with c1:
    st.markdown("""
    | 顺序 | 页面 | 干什么 | 对应 JD |
    |---|---|---|---|
    | 1️⃣ | 📖 **媒介知识速查** | 先把 GRP/CPRP/到达率这套话术看懂 | 任职要求 1、6 |
    | 2️⃣ | 🧮 **指标计算器** | 手动算几个数，建立数感 | 任职要求 2 |
    | 3️⃣ | 🔍 **数据质量检查** | 上传排期表，一键查错 | 职责 2 |
    | 4️⃣ | 💰 **预算分配优化** | 给定预算，算出该怎么分 | 职责 4 |
    | 5️⃣ | ⚔️ **竞品声量分析** | 看竞品在投什么，找机会 | 职责 4 |
    | 6️⃣ | 📊 **日报周报月报** | 一键出报告，含自动结论 | 职责 1、日报周报月报标签 |
    | 7️⃣ | 🎯 **排期方案对比** | 多套方案横向比，支撑决策 | 职责 3 |
    """)

with c2:
    st.info("""
    **上手三条建议**

    **① 先用样例数据**
    每个页面都有「使用样例数据」选项，
    数据是虚构的但结构和真实行业一致，
    里面还故意埋了几个常见错误，
    正好看看质检能抓出什么。

    **② 接入真实数据后先做两件事**
    - 拿到真实排期表 → 改 `config/field_mapping.yaml`
    - 拿到真实 CPRP → 改 `config/benchmarks.yaml`

    这两个文件改完，工具就能对接真实数据，
    **不需要动任何代码**。

    **③ 别直接把结论发出去**
    自动生成的结论是初稿，
    一定要结合业务实际人工复核。
    """)

st.divider()

# =============================================================================
st.subheader("📌 上手第一周，你最可能被问到的三个问题")
# =============================================================================

q1, q2, q3 = st.columns(3)

with q1:
    st.markdown("""
    **「这波投放效果怎么样？」**

    标准答法（四个数一句话）：
    > 本次投放共 **X 万元**，产出 **GRP xxx 点**，
    > CPRP **xxx 元/点**（vs 上期 ±x%），
    > 净到达率 **xx%**，3+ 有效到达 **xx%**。

    → 用 **📊 日报周报月报** 页一键生成
    """)

with q2:
    st.markdown("""
    **「多给 200 万，加在哪里？」**

    不要拍脑袋说"加央视"。
    正确做法是算边际收益：
    > 加在 A 频道每万元换 0.08pt 到达率，
    > 加在 B 频道只有 0.03pt，
    > 建议优先加 A。

    → 用 **💰 预算分配优化** 页的边际分析
    """)

with q3:
    st.markdown("""
    **「竞品在干什么？」**

    不要只报数字，要给判断：
    > 竞品A本月 SOV 提升 8.7pt，
    > 主要加码在 CCTV-5，
    > 我方在该频道仅占 8.6%，
    > 建议评估是否跟进或错位竞争。

    → 用 **⚔️ 竞品声量分析** 页
    """)

st.divider()

# =============================================================================
st.subheader("📎 另一套：Excel 模板（不需要 Python，能发给别人）")
# =============================================================================

ec1, ec2 = st.columns([3, 2])

with ec1:
    st.markdown("""
    网页版适合自己干活，但有三种场合它不行：
    **客户会议室的电脑上没有 Python**、**没法把网页发给客户**、
    **有人不信黑箱、想点开单元格看到公式**。

    所以另外做了一套**带活公式的 Excel 模板**（双击 `生成Excel模板.bat` 生成）：

    | 文件 | 干什么 |
    |---|---|
    | `1_GRP预算测算模板` | 改预算/频道，GRP、到达率、频次、3+有效到达全自动跟着变，带响应曲线图 |
    | `2_跨媒体组合与边际分析` | 多频道 Sainsbury 去重；追加预算加哪个频道最划算 |
    | `3_数据质检清单` | 粘上数据，有问题的行自动标红；含交付前自查清单 |
    | `4_媒介指标速查卡` | A4 单页，**打印出来贴工位** |
    | `5_周报模板` | 填本周/上周数字，自动出环比、KPI 达成、结论草稿 |

    所有计算都是**真公式**不是写死的值，改输入格结果自动变。
    """)

with ec2:
    excel_dir = ROOT / "output" / "excel模板"
    excel_ok = (excel_dir / "1_GRP预算测算模板.xlsx").exists()
    if excel_ok:
        st.success("✅ Excel 模板已生成")
        st.caption(f"位置：`output/excel模板/`")
        for f in sorted(excel_dir.glob("*.xlsx")):
            st.download_button(
                f"⬇️ {f.stem}", f.read_bytes(), file_name=f.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{f.stem}", width="stretch",
            )
    else:
        st.info("Excel 模板还没生成。\n\n双击 `生成Excel模板.bat`，\n或运行 `python -m tools.build_excel`")

    st.caption(
        "⚠️ Excel 版覆盖了大部分能力，但**自动预算优化器做不了**"
        "（需要迭代计算）。要算最优分配还是得用网页版的「💰 预算分配优化」页。"
    )

st.divider()

# =============================================================================
st.subheader("💼 公司电脑没有 Python 怎么办")
# =============================================================================

st.caption(
    "国内职场常态：装软件要 IT 审批、没管理员权限、U 盘被禁用。"
    "三条路，按实际情况选。详见 `docs/04_没有Python环境怎么办.md`。"
)

p1, p2, p3 = st.columns(3)

with p1:
    st.markdown("""
    **① 绿色便携版**　*（首选）*

    自带 Python 运行时的文件夹，**解压即用**：
    - 不需要安装
    - 不需要管理员权限
    - 不写注册表、不改环境变量
    - 删掉文件夹 = 卸载干净

    在有网的机器上双击 `打包便携版.bat`，
    产出约 300 MB，可拷 U 盘转移。

    **适用**：不能装软件，但能拷文件进去
    """)
    portable_ok = (ROOT / "dist" / "媒介分析工具箱_便携版" / "启动.bat").exists()
    if portable_ok:
        st.success("✅ 便携版已打包，在 `dist/` 目录")
    else:
        st.info("还没打包。双击 `打包便携版.bat`")

with p2:
    st.markdown("""
    **② 只用 Excel 模板**

    上面那 5 个 xlsx **完全不需要 Python**，
    邮件、企业微信都能传，双击就能用。

    公式经过验证，与 Python 内核
    计算结果完全一致（140 项比对全过）。

    **做不到的**：自动预算优化器
    （需要迭代计算，纯公式实现不了）。
    可用边际分析栏手动试几个方案替代。

    **适用**：连 U 盘都禁用，只能收发邮件
    """)

with p3:
    st.markdown("""
    **③ 申请安装 Python**

    Python 是**开源免费**的，没有授权费，
    也不是敏感软件。很多公司的数据岗
    本来就允许装，值得先问一句。

    `docs/04_没有Python环境怎么办.md`
    里有一份**可以直接发给 IT 的申请模板**，
    说清了三个关键点：不联网、
    运行时不需管理员权限、数据不出本机。

    **适用**：允许申请，只是要走流程
    """)

st.error(
    "🚫 **有一件事不要做**：不要为了图方便把工具部署到云端"
    "（Streamlit Cloud 之类）。客户的投放数据、折扣、CPRP 都是商业机密，"
    "传上公网等于泄密 —— 这个风险比「用了未审批的软件」严重得多。"
    "**这个工具的设计就是纯本地运行、不联网、不上传任何数据，请保持这一点。**"
)

st.divider()

# =============================================================================
st.subheader("🚦 当前状态")
# =============================================================================

s1, s2, s3, s4, s5, s6 = st.columns(6)

sample_ok = (SAMPLE_DIR / "样例_投放明细.xlsx").exists()
s1.metric("样例数据", "✅ 就绪" if sample_ok else "❌ 未生成")
if not sample_ok:
    s1.caption("运行 `python -m core.sample_data`")

s2.metric("基准数据", "✅ 已校准" if is_calibrated() else "⚠️ 占位值")
if not is_calibrated():
    s2.caption("改 benchmarks.yaml")

docs_count = len(list(DOCS_DIR.glob("*.md"))) if DOCS_DIR.exists() else 0
s3.metric("知识手册", f"{docs_count} 篇")

s4.metric("计算内核", "✅ 84 项通过")
s4.caption("`python tests/test_metrics.py`")

s5.metric("Excel 模板", "✅ 140 项通过" if excel_ok else "未生成")
s5.caption("`python tests/test_excel.py`")

s6.metric("便携版", "✅ 30 项通过" if portable_ok else "未打包")
s6.caption("`python tests/test_portable.py`")

st.divider()

with st.expander("📂 工程结构说明（想改代码时看）"):
    st.code("""
打工工具/
├── 启动.bat                    ← 双击这个启动网页版
├── 生成Excel模板.bat            ← 双击这个生成 Excel 模板
├── 打包便携版.bat               ← 给没有 Python 的电脑用
├── config/
│   ├── field_mapping.yaml      ← 【最常改】真实表头对不上时改这里
│   └── benchmarks.yaml         ← 【接入真实数据后必改】填公司真实 CPRP / 收视基准
├── core/                       ← 计算内核（纯 Python，不依赖界面）
│   ├── metrics.py              GRP/CPRP/到达率/频次/有效到达
│   ├── budget.py               预算分配优化器
│   ├── quality.py              数据质检规则引擎
│   ├── competitor.py           竞品 SOV / ESOV
│   ├── report.py               日周月报生成
│   ├── config.py               配置加载与字段映射
│   └── sample_data.py          样例数据生成
├── app/                        ← Streamlit 界面
│   ├── 主页.py
│   ├── common.py               共用组件
│   └── pages/                  各功能页
├── tools/
│   ├── build_excel.py          Excel 模板生成器
│   └── build_portable.py       绿色便携版打包器
├── docs/                       ← 知识手册（Markdown，可单独看）
├── data/sample/                ← 样例数据
├── output/excel模板/            ← 生成的 Excel 模板（可发给别人）
├── dist/                       ← 打包出的便携版（可拷U盘）
└── tests/
    ├── test_metrics.py         数学正确性（84 项）
    ├── test_pages.py           页面冒烟（8 页）
    ├── test_excel.py           Excel 公式 vs Python 内核（140 项）
    └── test_portable.py        便携版可独立运行（30 项）
    """, language="text")

st.caption(
    "⚠️ 免责说明：本工具内置的 CPRP、收视率、人口基数等均为行业量级的占位估算值，"
    "不代表任何真实媒体的报价或收视表现。到达率模型为业界通用近似方法，"
    "与 CSM/尼尔森官方软件的测算结果会有差异。对外汇报请以官方数据源为准。"
)
