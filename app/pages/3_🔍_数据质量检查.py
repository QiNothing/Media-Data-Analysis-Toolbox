"""数据质量检查 —— JD 第 2 条：对最终交付数据报告质量负责。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.common import data_source_widget, download_df, setup_page          # noqa: E402
from core.quality import RULE_CATALOG, run_quality_check                     # noqa: E402

setup_page("数据质量检查", "🔍")

st.markdown(
    "**这是这份工作里风险最高的一环。** 报告发出去数字错了，责任是你的。"
    "上传排期表/监播表/结算表，一键跑完 9 类检查，"
    "输出一份可以直接附在交付物后面的质检清单。"
)

df = data_source_widget("placement", "qc", "投放数据")

if df is None:
    st.divider()
    st.subheader("📋 检查规则清单")
    st.caption("这九条就是你能对同事说『我都查过了』的底气。")
    st.dataframe(RULE_CATALOG, width="stretch", hide_index=True)
    st.stop()

st.divider()

# =============================================================================
st.subheader("① 选择要跑的检查")
# =============================================================================

all_rules = RULE_CATALOG["规则"].tolist()
c1, c2 = st.columns([3, 1])
with c1:
    selected = st.multiselect("检查项", all_rules, default=all_rules,
                              help="第一次跑建议全选。熟悉后可以按需裁剪。")
with c2:
    st.write("")
    st.write("")
    run = st.button("🚀 开始检查", type="primary", width="stretch")

if not run and "qc_report" not in st.session_state:
    st.info("选好检查项后点「开始检查」。")
    st.stop()

if run:
    with st.spinner("正在检查…"):
        st.session_state["qc_report"] = run_quality_check(df, "placement", set(selected))

rep = st.session_state["qc_report"]

st.divider()

# =============================================================================
st.subheader("② 检查结果")
# =============================================================================

m1, m2, m3, m4 = st.columns(4)
m1.metric("检查行数", f"{rep.row_count:,}")
m2.metric("❌ 错误", rep.error_count, delta_color="inverse")
m3.metric("⚠️ 警告", rep.warning_count, delta_color="inverse")
m4.metric("ℹ️ 提示", rep.info_count)

if rep.passed and rep.warning_count == 0:
    st.success(rep.summary_text())
elif rep.passed:
    st.warning(rep.summary_text())
else:
    st.error(rep.summary_text())

qdf = rep.to_dataframe()

if qdf.empty:
    st.balloons()
    st.success("没有发现任何问题。可以放心交付。")
    st.stop()

# --- 按等级分组展示 ---
st.divider()
st.subheader("③ 问题明细")

lv = st.radio("筛选等级", ["全部", "❌ 错误", "⚠️ 警告", "ℹ️ 提示"], horizontal=True)
view = qdf if lv == "全部" else qdf[qdf["等级"] == lv]

if view.empty:
    st.info(f"没有{lv}级别的问题。")
else:
    # 汇总
    st.markdown("**问题分布**")
    summary = (view.groupby(["等级", "规则"]).size()
               .reset_index(name="条数").sort_values("条数", ascending=False))
    st.dataframe(summary, width="stretch", hide_index=True)

    st.markdown("**逐条明细**")
    st.dataframe(view, width="stretch", hide_index=True,
                 column_config={
                     "问题": st.column_config.TextColumn(width="large"),
                     "处理建议": st.column_config.TextColumn(width="large"),
                 })

    download_df(qdf, "数据质检报告.xlsx", "⬇️ 下载完整质检报告", key="dl_qc")

# =============================================================================
st.divider()
st.subheader("④ 交付前自查清单")
# =============================================================================

st.caption("质检工具只能查数据本身。下面这些要靠人，每次交付前过一遍。")

CHECKLIST = [
    ("口径确认", "人群口径（4+/目标人群）、区域口径（全国网/城域网/省网）、数据源（CSM/勾正）是否与客户约定一致"),
    ("总数对账", "报告里的总花费，是否与结算单/客户系统里的数字完全一致"),
    ("时间区间", "报告标注的时间区间，是否与实际数据覆盖的区间一致（有没有漏头漏尾）"),
    ("GRP口径", "报告里的 GRP 是全人群还是目标人群（TRP）？有没有在标题或脚注里注明"),
    ("同比环比", "对比的上期是否可比（投放天数、频道组合是否大致相当）"),
    ("异常解释", "质检报告里的每一条警告，是否都有了解释（哪怕结论是「正常」）"),
    ("结论复核", "自动生成的分析结论，是否结合业务实际做过人工判断，而不是照抄"),
    ("敏感信息", "报告里有没有不该出现的内容（其他客户数据、内部成本、未公开折扣）"),
    ("文件命名", "文件名是否规范（客户_报告类型_日期），版本号是否正确"),
    ("发送对象", "收件人是否正确，抄送是否需要，附件是否都带上了"),
]

done = 0
for i, (title, desc) in enumerate(CHECKLIST):
    if st.checkbox(f"**{title}** —— {desc}", key=f"chk_{i}"):
        done += 1

st.progress(done / len(CHECKLIST), text=f"自查进度 {done}/{len(CHECKLIST)}")
if done == len(CHECKLIST) and rep.passed:
    st.success("✅ 数据质检通过 + 自查清单完成。可以交付了。")
elif done == len(CHECKLIST):
    st.warning("⚠️ 自查清单已完成，但数据质检还有错误未修正。**先修数据再交付。**")

with st.expander("💡 关于数据质量，三条经验"):
    st.markdown("""
**1. 宁可晚交半小时，不要交错的数据。**
延迟交付顶多被催，交错数据是信任危机。发现来不及了，第一时间说，不要硬撑。

**2. 每次发现新的错误类型，就把它变成一条规则。**
这个工具的 `core/quality.py` 是可以加规则的。踩过一次的坑，让工具帮你记住，
下次自动就查了。半年后你的质检规则会比任何同事都全。

**3. 学会区分「数据错」和「业务异常」。**
收视率突然翻倍，可能是数据错，也可能是真的爆了。
不要看到异常就当错误改掉——**先去问业务，再决定怎么处理**。
把异常直接抹平，比留着异常更危险。
    """)
