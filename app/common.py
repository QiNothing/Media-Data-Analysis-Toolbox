"""
Streamlit 共用组件
==================
放页面之间反复用到的东西：数据加载、缓存、格式化、侧边栏。
目的是让每个页面文件只写自己那点业务，不重复造轮子。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import (                                    # noqa: E402
    check_required,
    clear_config_cache,
    coerce_dtypes,
    is_calibrated,
    load_benchmarks,
    map_columns,
    normalize_channel_column,
)

SAMPLE_DIR = ROOT / "data" / "sample"
DOCS_DIR = ROOT / "docs"


# =============================================================================
# 页面初始化
# =============================================================================

def setup_page(title: str, icon: str = "📊"):
    """每个页面开头调一次。统一页面配置 + 未校准基准警告。"""
    st.set_page_config(page_title=f"{title} · 媒介分析工具箱",
                       page_icon=icon, layout="wide")
    st.title(f"{icon} {title}")
    if not is_calibrated():
        st.warning(
            "⚠️ **当前使用的是占位基准数据**（CPRP、收视率、人口基数都是行业量级估算值，"
            "不是真实报价）。测算结果只能用于练手和方法验证，**不能直接对外汇报**。"
            "拿到公司真实基准后，请修改 `config/benchmarks.yaml` 并把 `verified` 改为 `true`。",
            icon="⚠️",
        )


# =============================================================================
# 数据加载
# =============================================================================

@st.cache_data(show_spinner=False)
def _read_any(file_bytes: bytes, filename: str, sheet: str | int = 0) -> pd.DataFrame:
    """读 Excel 或 CSV。CSV 自动尝试多种中文编码。"""
    import io
    bio = io.BytesIO(file_bytes)
    if filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        return pd.read_excel(bio, sheet_name=sheet)
    for enc in ("utf-8-sig", "gbk", "gb18030", "utf-8"):
        try:
            bio.seek(0)
            return pd.read_csv(bio, encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    bio.seek(0)
    return pd.read_csv(bio, encoding="utf-8", errors="replace")


def list_sheets(file_bytes: bytes, filename: str) -> list[str]:
    """列出 Excel 的所有 sheet 名。"""
    if not filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        return []
    import io
    try:
        return pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names
    except Exception:                                        # noqa: BLE001
        return []


def load_and_map(
    file_bytes: bytes,
    filename: str,
    section: str,
    sheet: str | int = 0,
    show_detail: bool = True,
) -> pd.DataFrame | None:
    """读文件 → 字段映射 → 类型转换 → 频道归一，全套走完。

    每一步的结果都在界面上告诉你，出问题能立刻定位是哪一环。
    """
    try:
        raw = _read_any(file_bytes, filename, sheet)
    except Exception as e:                                   # noqa: BLE001
        st.error(f"文件读取失败：{e}")
        return None

    if raw.empty:
        st.error("文件里没有数据行。")
        return None

    df, rename, unmapped = map_columns(raw, section)
    missing = check_required(df, section)
    df, type_warns = coerce_dtypes(df, section)
    df, unknown_ch = normalize_channel_column(df)

    if show_detail:
        c1, c2, c3 = st.columns(3)
        c1.metric("读入行数", f"{len(raw):,}")
        c2.metric("识别字段", f"{len(rename)} / {len(raw.columns)}")
        c3.metric("必填缺失", len(missing), delta_color="inverse")

        with st.expander("🔍 字段映射详情（对不上的时候点开看）", expanded=bool(missing)):
            if rename:
                st.write("**已识别的字段**")
                st.dataframe(
                    pd.DataFrame({"原始表头": list(rename.keys()),
                                  "映射为": list(rename.values())}),
                    width="stretch", hide_index=True,
                )
            if unmapped:
                st.write("**未识别的列**（数据仍保留，但工具不会用到它们）")
                st.code("、".join(unmapped))
                st.caption(
                    "如果这些列其实是有用的，把它们的名字加到 "
                    "`config/field_mapping.yaml` 对应字段的 aliases 里即可。"
                )
            if type_warns:
                st.write("**类型转换提示**")
                for w in type_warns:
                    st.caption(f"• {w}")
            if unknown_ch:
                st.write("**未归一的频道名**")
                st.code("、".join(unknown_ch[:40]))
                st.caption(
                    "这些频道保持原样。若它们其实是同一频道的不同写法，"
                    "请在 `field_mapping.yaml` 的 `channel_normalize` 里补充。"
                )

    if missing:
        st.error(
            f"**缺少必填字段：{'、'.join(missing)}**\n\n"
            "两种解决办法：① 数据源里补上这些列；"
            "② 如果列存在只是名字不一样，把实际名字加到 `field_mapping.yaml` 的 aliases 里。"
        )
        return None

    return df


def data_source_widget(section: str, key: str, label: str = "数据") -> pd.DataFrame | None:
    """统一的数据源选择控件：上传文件 or 用样例数据。"""
    mode = st.radio(
        f"{label}来源", ["📁 上传文件", "🧪 使用样例数据"],
        horizontal=True, key=f"{key}_mode",
        help="第一次用建议先选样例数据，把功能点一遍熟悉流程",
    )

    if mode == "🧪 使用样例数据":
        name_map = {
            "placement": "样例_投放明细.xlsx",
            "competitor": "样例_竞品投放.xlsx",
            "benchmark": "样例_频道基准.xlsx",
        }
        path = SAMPLE_DIR / name_map.get(section, "")
        if not path.exists():
            st.error(
                f"样例文件不存在：{path}\n\n"
                "请在 打工工具 目录下运行：`python -m core.sample_data`"
            )
            return None
        st.caption(f"📎 正在使用样例：{path.name}　（虚构数据，仅供练手）")
        return load_and_map(path.read_bytes(), path.name, section)

    up = st.file_uploader(
        f"上传{label}（Excel 或 CSV）", type=["xlsx", "xls", "xlsm", "csv"], key=f"{key}_file",
    )
    if up is None:
        st.info("请上传文件，或切换到「使用样例数据」先试用。")
        return None

    data = up.getvalue()
    sheets = list_sheets(data, up.name)
    sheet: str | int = 0
    if len(sheets) > 1:
        sheet = st.selectbox("选择工作表", sheets, key=f"{key}_sheet")
    return load_and_map(data, up.name, section, sheet)


# =============================================================================
# 显示格式化
# =============================================================================

def fmt_money(v: float) -> str:
    """金额自动选单位：万 / 亿。"""
    if v is None or pd.isna(v):
        return "—"
    v = float(v)
    if abs(v) >= 1e8:
        return f"{v/1e8:,.2f} 亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:,.1f} 万"
    return f"{v:,.0f}"


def fmt_num(v: float, digits: int = 1) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):,.{digits}f}"


def fmt_pct(v: float, digits: int = 1) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):.{digits}f}%"


def style_table(df: pd.DataFrame, money_cols=(), pct_cols=(), num_cols=()) -> pd.DataFrame:
    """把数值列格式化成好读的字符串，用于展示（不要拿去做后续计算）。"""
    out = df.copy()
    for c in money_cols:
        if c in out.columns:
            out[c] = out[c].map(fmt_money)
    for c in pct_cols:
        if c in out.columns:
            out[c] = out[c].map(lambda x: fmt_pct(x))
    for c in num_cols:
        if c in out.columns:
            out[c] = out[c].map(lambda x: fmt_num(x))
    return out


def download_df(df: pd.DataFrame, filename: str, label: str = "⬇️ 下载为 Excel", key=None):
    """给 DataFrame 加一个 Excel 下载按钮。"""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as xw:
        df.to_excel(xw, index=False, sheet_name="数据")
    st.download_button(
        label, buf.getvalue(), file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )


# =============================================================================
# 侧边栏
# =============================================================================

def sidebar_settings() -> dict:
    """侧边栏的全局参数。返回 dict 供页面使用。"""
    bm = load_benchmarks()
    with st.sidebar:
        st.markdown("### ⚙️ 全局参数")

        uni_map = bm.get("universe", {})
        uni_name = st.selectbox(
            "目标人群", list(uni_map.keys()),
            index=list(uni_map.keys()).index(bm.get("default_universe", list(uni_map)[0]))
            if bm.get("default_universe") in uni_map else 0,
            help="决定 GRP 换算成绝对曝光人次时用哪个人口基数",
        )
        universe = float(uni_map.get(uni_name, 130000))
        st.caption(f"人口基数：{universe:,.0f} 万人")

        ef_map = bm.get("effective_frequency", {})
        ef_scene = st.selectbox(
            "投放场景", list(ef_map.keys()),
            index=1 if len(ef_map) > 1 else 0,
            help="不同场景对'看几次才算记住'的要求不同，会影响有效到达率的计算",
        )
        eff_n = int(ef_map.get(ef_scene, bm.get("default_ef", 3)))
        st.caption(f"有效频次门槛：{eff_n}+ 次")

        method = st.radio(
            "跨媒体去重方法", ["sainsbury", "max"],
            format_func=lambda x: {"sainsbury": "Sainsbury（行业标准，假设独立）",
                                   "max": "保守法（取最大值）"}[x],
            help="Sainsbury 假设各媒体受众相互独立，会略微高估净到达；"
                 "保守法给出下限。对外汇报建议用 Sainsbury 并注明方法。",
        )

        st.divider()
        if st.button("🔄 重载配置文件", width="stretch",
                     help="改完 config/*.yaml 之后点这里，不用重启程序"):
            clear_config_cache()
            st.cache_data.clear()
            st.success("配置已重载")
            st.rerun()

        st.caption(
            "校准状态：" + ("✅ 已用真实数据校准" if is_calibrated()
                          else "⚠️ 使用占位基准")
        )

    return {"universe_wan": universe, "universe_name": uni_name,
            "effective_n": eff_n, "scene": ef_scene, "cross_media_method": method}
