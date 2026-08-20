"""
Excel 模板生成器
================
生成一套【带活公式】的 Excel 模板，脱离 Python 也能用。

为什么要有这个：
  - 客户电脑、会议室机器上没有 Python，Excel 是唯一的通用语言
  - 网页版没法发给别人，Excel 可以
  - 有些人不信黑箱，能点开单元格看到 =花费/GRP 才放心
  - 开会时客户说"预算砍 20% 看看"，投屏上直接改一格

关键设计：所有计算都是【真公式】不是写死的值。
改输入格，结果和图表自动跟着变。

⚠️ 一个技术说明：
有效到达率 nR+ 需要解截断泊松分布，纯 Excel 公式做不出来。
解决办法是预生成一张查表（有效到达占比只取决于平均频次，与到达率无关，
这一点已在 tests 里验证），Excel 用 MATCH+INDEX 线性插值查。
实测误差 < 0.6 个百分点，可忽略。

跑法：python -m tools.build_excel
输出：output/excel模板/ 下面几个 xlsx
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xlsxwriter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import benchmark_table, load_benchmarks          # noqa: E402
from core.metrics import effective_reach                          # noqa: E402

OUT_DIR = ROOT / "output" / "excel模板"

# =============================================================================
# 配色（跟网页版保持一致，看起来像一套东西）
# =============================================================================
C_HEAD = "#1F4E79"      # 深蓝，标题栏
C_SUB = "#D9E2F3"       # 浅蓝，表头
C_INPUT = "#FFF2CC"     # 浅黄，输入格（用户要改的）
C_CALC = "#E2EFDA"      # 浅绿，计算格（自动算的）
C_WARN = "#FCE4D6"      # 浅橙，警示
C_NOTE = "#F2F2F2"      # 浅灰，说明


def _formats(wb: xlsxwriter.Workbook) -> dict:
    """统一的单元格格式。"""
    return {
        "title": wb.add_format({
            "bold": True, "font_size": 15, "bg_color": C_HEAD, "font_color": "white",
            "align": "left", "valign": "vcenter", "indent": 1,
        }),
        "section": wb.add_format({
            "bold": True, "font_size": 11, "bg_color": C_SUB,
            "align": "left", "valign": "vcenter", "indent": 1, "border": 1,
        }),
        "head": wb.add_format({
            "bold": True, "bg_color": C_SUB, "border": 1,
            "align": "center", "valign": "vcenter", "text_wrap": True,
        }),
        "label": wb.add_format({"align": "right", "valign": "vcenter", "indent": 1}),
        "label_b": wb.add_format({"bold": True, "align": "right", "valign": "vcenter", "indent": 1}),
        "input": wb.add_format({
            "bg_color": C_INPUT, "border": 1, "num_format": "#,##0.00",
            "align": "center", "valign": "vcenter",
        }),
        "input_int": wb.add_format({
            "bg_color": C_INPUT, "border": 1, "num_format": "#,##0",
            "align": "center", "valign": "vcenter",
        }),
        "input_txt": wb.add_format({
            "bg_color": C_INPUT, "border": 1, "align": "center", "valign": "vcenter",
        }),
        "calc": wb.add_format({
            "bg_color": C_CALC, "border": 1, "num_format": "#,##0.00",
            "align": "center", "valign": "vcenter",
        }),
        "calc_int": wb.add_format({
            "bg_color": C_CALC, "border": 1, "num_format": "#,##0",
            "align": "center", "valign": "vcenter",
        }),
        "calc_pct": wb.add_format({
            "bg_color": C_CALC, "border": 1, "num_format": '0.00"%"',
            "align": "center", "valign": "vcenter",
        }),
        "calc_big": wb.add_format({
            "bg_color": C_CALC, "border": 2, "num_format": "#,##0", "bold": True,
            "font_size": 13, "align": "center", "valign": "vcenter",
        }),
        "calc_big_pct": wb.add_format({
            "bg_color": C_CALC, "border": 2, "num_format": '0.0"%"', "bold": True,
            "font_size": 13, "align": "center", "valign": "vcenter",
        }),
        "num": wb.add_format({"border": 1, "num_format": "#,##0.00", "align": "center"}),
        "int": wb.add_format({"border": 1, "num_format": "#,##0", "align": "center"}),
        "pct": wb.add_format({"border": 1, "num_format": '0.00"%"', "align": "center"}),
        "txt": wb.add_format({"border": 1, "valign": "top", "text_wrap": True}),
        "txt_l": wb.add_format({"border": 1, "valign": "top", "text_wrap": True, "align": "left"}),
        "note": wb.add_format({
            "bg_color": C_NOTE, "italic": True, "font_size": 9,
            "valign": "top", "text_wrap": True, "align": "left", "indent": 1,
        }),
        "warn": wb.add_format({
            "bg_color": C_WARN, "border": 1, "valign": "top", "text_wrap": True,
            "align": "left", "indent": 1, "font_size": 10,
        }),
        "formula_show": wb.add_format({
            "font_name": "Consolas", "font_size": 9, "font_color": "#555555",
            "align": "left", "valign": "vcenter", "indent": 1,
        }),
    }


def _legend(ws, fmt, row: int, col: int = 0):
    """在表格顶部画一个颜色图例，告诉用户哪些格子该改。"""
    ws.write(row, col, "填这里 →", fmt["label"])
    ws.write(row, col + 1, "输入格", fmt["input_txt"])
    ws.write(row, col + 2, "自动算 →", fmt["label"])
    ws.write(row, col + 3, "结果格", fmt["calc"])
    return row + 1


# =============================================================================
# 有效到达率查表（关键技术点）
# =============================================================================

def _build_er_lookup() -> list[tuple[float, float, float, float]]:
    """预生成 (频次, 2+占比, 3+占比, 5+占比) 查表。

    数学依据：在截断泊松模型下，nR+ / Reach 只是平均频次 f 的函数，
    与 Reach 本身无关（已在 tests 里验证）。所以一张一维表就够了。

    频次范围 1.00 ~ 30.00，步长 0.01，共 2901 行。
    实测线性查表误差 < 0.6 个百分点。
    """
    rows = []
    R = 50.0                      # 任取一个到达率，比值与它无关
    for f in np.arange(1.00, 30.001, 0.01):
        grp = f * R
        rows.append((
            round(float(f), 2),
            effective_reach(grp, R, 2) / R,
            effective_reach(grp, R, 3) / R,
            effective_reach(grp, R, 5) / R,
        ))
    return rows


def _write_lookup_sheet(wb, fmt, er_rows):
    """写查表 sheet（隐藏起来，用户不用看）。"""
    ws = wb.add_worksheet("_查表")
    ws.hide()
    ws.write_row(0, 0, ["频次", "2+占比", "3+占比", "5+占比"], fmt["head"])
    for i, (f, r2, r3, r5) in enumerate(er_rows, start=1):
        ws.write_number(i, 0, f)
        ws.write_number(i, 1, r2)
        ws.write_number(i, 2, r3)
        ws.write_number(i, 3, r5)
    ws.write(0, 5, "本表由 tools/build_excel.py 预生成：截断泊松模型下 nR+/Reach 仅取决于平均频次")
    return len(er_rows)


def _er_formula(freq_cell: str, reach_cell: str, n_col: int, n_rows: int) -> str:
    """生成有效到达率的查表公式（带线性插值）。

    n_col: 2 = 2+, 3 = 3+, 4 = 5+（对应查表的列号）
    """
    tbl_f = f"_查表!$A$2:$A${n_rows+1}"
    tbl_v = f"_查表!${chr(64+n_col)}$2:${chr(64+n_col)}${n_rows+1}"
    # MATCH 找下界位置，然后在相邻两点间线性插值
    m = f"MATCH(MIN(MAX({freq_cell},1),29.99),{tbl_f},1)"
    lo_f = f"INDEX({tbl_f},{m})"
    hi_f = f"INDEX({tbl_f},{m}+1)"
    lo_v = f"INDEX({tbl_v},{m})"
    hi_v = f"INDEX({tbl_v},{m}+1)"
    interp = (f"({lo_v}+({hi_v}-{lo_v})*"
              f"IF({hi_f}={lo_f},0,(MIN(MAX({freq_cell},1),29.99)-{lo_f})/({hi_f}-{lo_f})))")
    return f"=IF({freq_cell}<=1,{reach_cell},{reach_cell}*{interp})"


# =============================================================================
# 模板 1：GRP 预算测算 + 到达率曲线
# =============================================================================

def build_grp_calculator(path: Path, er_rows):
    wb = xlsxwriter.Workbook(str(path))
    fmt = _formats(wb)
    n_rows = _write_lookup_sheet(wb, fmt, er_rows)

    bm = load_benchmarks()
    bt = benchmark_table()

    # ---------- 频道基准 sheet ----------
    wsb = wb.add_worksheet("频道基准")
    wsb.set_column(0, 0, 16)
    wsb.set_column(1, 5, 15)
    wsb.merge_range(0, 0, 0, 5, "频道基准数据　※ 接入真实数据后请用公司真实数据替换整张表", fmt["title"])
    wsb.set_row(0, 26)
    wsb.merge_range(1, 0, 1, 5,
                    "这张表是所有测算的地基。CPRP 建议用『历史成交价反算』："
                    "该频道历史总花费 ÷ 该频道历史总GRP，取近3~6个月。",
                    fmt["warn"])
    heads = ["频道", "类型", "CPRP(元/点)", "平均收视率(%)", "覆盖天花板(%)", "重复系数ρ"]
    wsb.write_row(3, 0, heads, fmt["head"])
    for i, (_, r) in enumerate(bt.iterrows(), start=4):
        wsb.write(i, 0, r["channel"], fmt["input_txt"])
        wsb.write(i, 1, r["channel_type"], fmt["txt"])
        wsb.write_number(i, 2, float(r["cprp"]), fmt["input_int"])
        wsb.write_number(i, 3, float(r["avg_rating"]), fmt["input"])
        wsb.write_number(i, 4, float(r["max_reach"]), fmt["input"])
        wsb.write_number(i, 5, float(r["rho"]), fmt["input"])
    last = 3 + len(bt)
    wb.define_name("频道列表", f"=频道基准!$A$5:$A${last+1}")
    wb.define_name("基准区", f"=频道基准!$A$5:$F${last+1}")
    wsb.write(last + 2, 0,
              "⚠️ 内置数值为行业量级占位估算，不代表任何真实媒体报价。校准前勿对外汇报。",
              fmt["note"])

    # ---------- 主测算 sheet ----------
    ws = wb.add_worksheet("GRP测算")
    ws.set_column(0, 0, 22)
    ws.set_column(1, 1, 16)
    ws.set_column(2, 2, 3)
    ws.set_column(3, 3, 22)
    ws.set_column(4, 4, 16)
    ws.set_column(5, 8, 14)
    ws.activate()

    ws.merge_range(0, 0, 0, 8, "GRP · 预算 · 到达率　一体测算表", fmt["title"])
    ws.set_row(0, 30)
    r = _legend(ws, fmt, 1)

    # --- 输入区 ---
    ws.merge_range(r, 0, r, 8, "① 输入条件（改黄色格子）", fmt["section"])
    r += 1
    IN0 = r

    ws.write(r, 0, "选择频道", fmt["label_b"])
    ws.write(r, 1, "CCTV-1", fmt["input_txt"])
    ws.data_validation(r, 1, r, 1, {"validate": "list", "source": "=频道列表"})
    ws.write(r, 3, "总预算（元）", fmt["label_b"])
    ws.write_number(r, 4, 3_000_000, fmt["input_int"])
    CH, BUD = f"$B${r+1}", f"$E${r+1}"
    r += 1

    ws.write(r, 0, "CPRP（元/点）", fmt["label"])
    ws.write_formula(r, 1, f"=VLOOKUP({CH},基准区,3,FALSE)", fmt["calc_int"])
    ws.write(r, 3, "有效频次门槛 n", fmt["label_b"])
    ws.write_number(r, 4, 3, fmt["input_int"])
    ws.data_validation(r, 4, r, 4, {"validate": "list", "source": [2, 3, 5]})
    CPRP, EFN = f"$B${r+1}", f"$E${r+1}"
    r += 1

    ws.write(r, 0, "覆盖天花板（%）", fmt["label"])
    ws.write_formula(r, 1, f"=VLOOKUP({CH},基准区,5,FALSE)", fmt["calc"])
    ws.write(r, 3, "目标人群基数（万人）", fmt["label_b"])
    uni_key = bm.get("default_universe", "全国4+")
    ws.write_number(r, 4, float(bm.get("universe", {}).get(uni_key, 130000)), fmt["input_int"])
    MR, UNI = f"$B${r+1}", f"$E${r+1}"
    r += 1

    ws.write(r, 0, "重复系数 ρ", fmt["label"])
    ws.write_formula(r, 1, f"=VLOOKUP({CH},基准区,6,FALSE)", fmt["calc"])
    ws.write(r, 3, "（ρ 越大观众越忠诚，到达率涨得越慢）", fmt["note"])
    RHO = f"$B${r+1}"
    r += 2

    # --- 结果区 ---
    ws.merge_range(r, 0, r, 8, "② 测算结果（自动算，别手改）", fmt["section"])
    r += 1
    RES0 = r

    res_defs = [
        ("GRP（毛评点）", f"={BUD}/{CPRP}", "calc_big", "GRP = 总预算 ÷ CPRP"),
        ("净到达率 1+（%）", None, "calc_big_pct", "Reach = 天花板×(1−EXP(−(1−ρ)×GRP÷天花板))"),
        ("平均频次", None, "calc_big", "频次 = GRP ÷ 到达率"),
        (None, None, "calc_big_pct", "查表插值（截断泊松）"),
        ("触达人数（万人）", None, "calc_big", "到达率 ÷ 100 × 人群基数"),
        ("曝光（万人次）", None, "calc_big", "GRP ÷ 100 × 人群基数"),
        ("CPM（元/千人次）", None, "calc_big", "花费 ÷ 曝光人次 × 1000"),
    ]

    GRP_C = f"$B${r+1}"
    ws.write(r, 0, res_defs[0][0], fmt["label_b"])
    ws.write_formula(r, 1, res_defs[0][1], fmt["calc_big"])
    ws.write(r, 2, "", None)
    ws.merge_range(r, 3, r, 8, res_defs[0][3], fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    REACH_C = f"$B${r+1}"
    ws.write(r, 0, "净到达率 1+（%）", fmt["label_b"])
    ws.write_formula(
        r, 1,
        f"=IF({GRP_C}<=0,0,{MR}*(1-EXP(-(1-{RHO})*{GRP_C}/{MR})))",
        fmt["calc_big_pct"])
    ws.merge_range(r, 3, r, 8, "Reach = 天花板 × (1 − EXP(−(1−ρ) × GRP ÷ 天花板))", fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    FREQ_C = f"$B${r+1}"
    ws.write(r, 0, "平均频次", fmt["label_b"])
    ws.write_formula(r, 1, f"=IF({REACH_C}<=0,0,{GRP_C}/{REACH_C})", fmt["calc_big"])
    ws.merge_range(r, 3, r, 8, "频次 = GRP ÷ 净到达率　（<2 太散记不住；>10 是浪费）",
                   fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    ER_C = f"$B${r+1}"
    ws.write_formula(r, 0, f'=CONCATENATE({EFN},"+ 有效到达率（%）")', fmt["label_b"])
    # 根据 n 选查表列：2->B, 3->C, 5->D
    er2 = _er_formula(FREQ_C, REACH_C, 2, n_rows)[1:]
    er3 = _er_formula(FREQ_C, REACH_C, 3, n_rows)[1:]
    er5 = _er_formula(FREQ_C, REACH_C, 4, n_rows)[1:]
    ws.write_formula(r, 1, f"=IF({EFN}=2,{er2},IF({EFN}=5,{er5},{er3}))", fmt["calc_big_pct"])
    ws.merge_range(r, 3, r, 8, "查表插值（截断泊松）—— 真正记住广告的人", fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    ws.write(r, 0, "触达人数（万人）", fmt["label_b"])
    ws.write_formula(r, 1, f"={REACH_C}/100*{UNI}", fmt["calc_big"])
    ws.merge_range(r, 3, r, 8, "到达率 ÷ 100 × 人群基数　（去重后的人数）", fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    IMP_C = f"$B${r+1}"
    ws.write(r, 0, "曝光（万人次）", fmt["label_b"])
    ws.write_formula(r, 1, f"={GRP_C}/100*{UNI}", fmt["calc_big"])
    ws.merge_range(r, 3, r, 8, "GRP ÷ 100 × 人群基数　※ 是人次不是人数", fmt["formula_show"])
    ws.set_row(r, 20)
    r += 1

    ws.write(r, 0, "CPM（元/千人次）", fmt["label_b"])
    ws.write_formula(r, 1, f"=IF({IMP_C}<=0,0,{BUD}/({IMP_C}*10000)*1000)", fmt["calc_big"])
    ws.merge_range(r, 3, r, 8, "花费 ÷ 曝光人次 × 1000　（跨媒体比价用这个）", fmt["formula_show"])
    ws.set_row(r, 20)
    r += 2

    # --- 频次诊断 ---
    ws.merge_range(r, 0, r, 8, "③ 自动诊断", fmt["section"])
    r += 1
    ws.write(r, 0, "频次诊断", fmt["label_b"])
    ws.merge_range(
        r, 1, r, 8,
        f'=IF({FREQ_C}<2,"⚠ 频次偏低（"&TEXT({FREQ_C},"0.0")&"次）：观众记不住，建议集中投放或减少频道数",'
        f'IF({FREQ_C}>10,"⚠ 频次过高（"&TEXT({FREQ_C},"0.0")&"次）：净到达率已接近天花板，'
        f'再加预算是重复轰炸，建议增补覆盖互补的媒体",'
        f'"✓ 频次 "&TEXT({FREQ_C},"0.0")&" 次，处于合理区间（3~8）"))',
        fmt["warn"])
    ws.set_row(r, 32)
    r += 2

    # --- 反算区 ---
    ws.merge_range(r, 0, r, 8, "④ 反算：想达到某个到达率，需要多少预算", fmt["section"])
    r += 1
    ws.write(r, 0, "目标净到达率（%）", fmt["label_b"])
    ws.write_number(r, 1, 45.0, fmt["input"])
    TGT = f"$B${r+1}"
    ws.merge_range(r, 3, r, 8,
                   "改这个黄格子，下面自动算出需要的 GRP 和预算", fmt["note"])
    r += 1
    ws.write(r, 0, "需要 GRP", fmt["label_b"])
    ws.write_formula(
        r, 1,
        f'=IF({TGT}>={MR},"做不到",-{MR}/(1-{RHO})*LN(1-{TGT}/{MR}))',
        fmt["calc"])
    NGRP = f"$B${r+1}"
    ws.merge_range(r, 3, r, 8, "GRP = −天花板÷(1−ρ) × LN(1 − 目标÷天花板)　※ 到达率公式的反函数",
                   fmt["formula_show"])
    r += 1
    ws.write(r, 0, "需要预算（元）", fmt["label_b"])
    ws.write_formula(r, 1, f'=IF(ISNUMBER({NGRP}),{NGRP}*{CPRP},"—")', fmt["calc_int"])
    ws.merge_range(
        r, 3, r, 8,
        f'=IF({TGT}>={MR},"❌ 单靠这个频道做不到：天花板只有 "&TEXT({MR},"0.0")&'
        f'"%。这不是加钱能解决的，必须增加媒体。","")',
        fmt["warn"])
    r += 2

    # --- 曲线数据 ---
    ws.merge_range(r, 0, r, 8, "⑤ 响应曲线数据（图表在「到达率曲线」sheet）", fmt["section"])
    r += 1
    CURVE0 = r + 1
    ws.write_row(r, 0, ["预算(万元)", "GRP", "净到达率(%)", "平均频次", "3+有效到达(%)"], fmt["head"])
    r += 1
    n_pts = 40
    for i in range(n_pts):
        budget_wan = (i + 1) * 25
        rr = r + i
        ws.write_number(rr, 0, budget_wan, fmt["int"])
        ws.write_formula(rr, 1, f"=A{rr+1}*10000/{CPRP}", fmt["num"])
        ws.write_formula(rr, 2, f"={MR}*(1-EXP(-(1-{RHO})*B{rr+1}/{MR}))", fmt["pct"])
        ws.write_formula(rr, 3, f"=IF(C{rr+1}<=0,0,B{rr+1}/C{rr+1})", fmt["num"])
        f_ref = f"$D${rr+1}"
        reach_ref = f"$C${rr+1}"
        ws.write_formula(rr, 4, _er_formula(f_ref, reach_ref, 3, n_rows), fmt["pct"])
    CURVE_END = r + n_pts

    # ---------- 曲线图 sheet ----------
    wsc = wb.add_worksheet("到达率曲线")
    chart = wb.add_chart({"type": "scatter", "subtype": "smooth"})
    chart.add_series({
        "name": "净到达率 1+",
        "categories": ["GRP测算", CURVE0, 0, CURVE_END - 1, 0],
        "values": ["GRP测算", CURVE0, 2, CURVE_END - 1, 2],
        "line": {"color": "#2E86AB", "width": 2.75},
    })
    chart.add_series({
        "name": "3+ 有效到达",
        "categories": ["GRP测算", CURVE0, 0, CURVE_END - 1, 0],
        "values": ["GRP测算", CURVE0, 4, CURVE_END - 1, 4],
        "line": {"color": "#A23B72", "width": 2, "dash_type": "dash"},
    })
    chart.set_title({"name": "预算 → 到达率 响应曲线"})
    chart.set_x_axis({"name": "预算（万元）"})
    chart.set_y_axis({"name": "到达率 (%)"})
    chart.set_size({"width": 760, "height": 440})
    wsc.insert_chart(1, 1, chart)

    chart2 = wb.add_chart({"type": "scatter", "subtype": "smooth"})
    chart2.add_series({
        "name": "平均频次",
        "categories": ["GRP测算", CURVE0, 0, CURVE_END - 1, 0],
        "values": ["GRP测算", CURVE0, 3, CURVE_END - 1, 3],
        "line": {"color": "#F18F01", "width": 2.5},
    })
    chart2.set_title({"name": "预算 → 平均频次"})
    chart2.set_x_axis({"name": "预算（万元）"})
    chart2.set_y_axis({"name": "频次"})
    chart2.set_size({"width": 760, "height": 330})
    wsc.insert_chart(25, 1, chart2)

    wsc.merge_range(0, 1, 0, 10,
                    "曲线越往后越平 = 边际到达递减。这是解释『为什么不能无限加预算』最直观的一张图。",
                    fmt["note"])

    wb.close()


# =============================================================================
# 模板 2：跨媒体组合 + 边际分析
# =============================================================================

def build_multimedia(path: Path, er_rows):
    wb = xlsxwriter.Workbook(str(path))
    fmt = _formats(wb)
    n_rows = _write_lookup_sheet(wb, fmt, er_rows)

    bm = load_benchmarks()
    bt = benchmark_table()

    # ---------- 基准 ----------
    wsb = wb.add_worksheet("频道基准")
    wsb.set_column(0, 0, 16)
    wsb.set_column(1, 5, 15)
    wsb.merge_range(0, 0, 0, 5, "频道基准数据　※ 接入真实数据后请替换为公司真实数据", fmt["title"])
    wsb.set_row(0, 26)
    wsb.write_row(2, 0, ["频道", "类型", "CPRP(元/点)", "平均收视率(%)", "覆盖天花板(%)", "重复系数ρ"],
                  fmt["head"])
    for i, (_, r) in enumerate(bt.iterrows(), start=3):
        wsb.write(i, 0, r["channel"], fmt["input_txt"])
        wsb.write(i, 1, r["channel_type"], fmt["txt"])
        wsb.write_number(i, 2, float(r["cprp"]), fmt["input_int"])
        wsb.write_number(i, 3, float(r["avg_rating"]), fmt["input"])
        wsb.write_number(i, 4, float(r["max_reach"]), fmt["input"])
        wsb.write_number(i, 5, float(r["rho"]), fmt["input"])
    last = 2 + len(bt)
    wb.define_name("频道列表", f"=频道基准!$A$4:$A${last+1}")
    wb.define_name("基准区", f"=频道基准!$A$4:$F${last+1}")

    # ---------- 组合排期 ----------
    ws = wb.add_worksheet("跨媒体组合")
    ws.activate()
    ws.set_column(0, 0, 16)
    ws.set_column(1, 1, 14)
    ws.set_column(2, 9, 13)

    ws.merge_range(0, 0, 0, 9, "跨媒体组合测算　—— 多个频道一起投，去重后能覆盖多少人", fmt["title"])
    ws.set_row(0, 30)
    r = _legend(ws, fmt, 1)

    ws.merge_range(r, 0, r, 9,
                   "⚠️ 各频道到达率【绝对不能直接相加】。本表用 Sainsbury 公式逐行去重累积，"
                   "这是行业标准做法。直接相加是新人汇报最容易被抓包的错误。",
                   fmt["warn"])
    ws.set_row(r, 30)
    r += 2

    ws.write(r, 0, "目标人群（万人）", fmt["label_b"])
    uni_key = bm.get("default_universe", "全国4+")
    ws.write_number(r, 1, float(bm.get("universe", {}).get(uni_key, 130000)), fmt["input_int"])
    UNI = f"$B${r+1}"
    ws.write(r, 3, "有效频次 n", fmt["label_b"])
    ws.write_number(r, 4, 3, fmt["input_int"])
    ws.data_validation(r, 4, r, 4, {"validate": "list", "source": [2, 3, 5]})
    EFN = f"$E${r+1}"
    r += 2

    ws.merge_range(r, 0, r, 9, "① 填频道和预算（黄色格子），其余自动算", fmt["section"])
    r += 1
    heads = ["频道", "预算(元)", "CPRP", "GRP", "单媒体到达率(%)",
             "天花板(%)", "ρ", "累积净到达率(%)", "本频道新增(pt)", "每万元换到达(pt)"]
    ws.write_row(r, 0, heads, fmt["head"])
    ws.set_row(r, 30)
    r += 1
    ROW0 = r
    N_MEDIA = 10
    defaults = [("CCTV-1", 2_000_000), ("湖南卫视", 1_500_000), ("浙江卫视", 1_000_000),
                ("OTT开机屏", 800_000)]

    for i in range(N_MEDIA):
        rr = r + i
        e = rr + 1                                     # Excel 行号
        if i < len(defaults):
            ws.write(rr, 0, defaults[i][0], fmt["input_txt"])
            ws.write_number(rr, 1, defaults[i][1], fmt["input_int"])
        else:
            ws.write(rr, 0, "", fmt["input_txt"])
            ws.write_number(rr, 1, 0, fmt["input_int"])
        ws.data_validation(rr, 0, rr, 0,
                           {"validate": "list", "source": "=频道列表",
                            "ignore_blank": True})
        ws.write_formula(rr, 2, f'=IFERROR(VLOOKUP($A{e},基准区,3,FALSE),"")', fmt["int"])
        ws.write_formula(rr, 3, f'=IF(OR($A{e}="",$C{e}=""),0,$B{e}/$C{e})', fmt["num"])
        ws.write_formula(rr, 5, f'=IFERROR(VLOOKUP($A{e},基准区,5,FALSE),0)', fmt["pct"])
        ws.write_formula(rr, 6, f'=IFERROR(VLOOKUP($A{e},基准区,6,FALSE),0.2)', fmt["num"])
        ws.write_formula(rr, 4, f'=IF(OR($D{e}<=0,$F{e}<=0),0,$F{e}*(1-EXP(-(1-$G{e})*$D{e}/$F{e})))',
                         fmt["pct"])
        # Sainsbury 逐行累积：cum_i = cum_{i-1} + r_i - cum_{i-1}*r_i/100
        prev = "0" if i == 0 else f"$H{e-1}"
        ws.write_formula(rr, 7, f"={prev}+$E{e}-{prev}*$E{e}/100", fmt["pct"])
        ws.write_formula(rr, 8, f"=$H{e}-{prev}", fmt["num"])
        ws.write_formula(rr, 9, f'=IF($B{e}<=0,"",$I{e}/($B{e}/10000))', fmt["num"])

    LAST_E = r + N_MEDIA                               # Excel 行号（最后一行）
    r += N_MEDIA + 1

    # --- 汇总 ---
    ws.merge_range(r, 0, r, 9, "② 组合汇总", fmt["section"])
    r += 1
    S0 = r
    ws.write(r, 0, "总预算（元）", fmt["label_b"])
    ws.write_formula(r, 1, f"=SUM($B${ROW0+1}:$B${LAST_E})", fmt["calc_big"])
    TCOST = f"$B${r+1}"
    ws.write(r, 3, "总 GRP", fmt["label_b"])
    ws.write_formula(r, 4, f"=SUM($D${ROW0+1}:$D${LAST_E})", fmt["calc_big"])
    TGRP = f"$E${r+1}"
    ws.write(r, 6, "投放频道数", fmt["label_b"])
    ws.write_formula(r, 7, f'=COUNTIF($B${ROW0+1}:$B${LAST_E},">0")', fmt["calc_big"])
    r += 1

    ws.write(r, 0, "净到达率（%）", fmt["label_b"])
    ws.write_formula(r, 1, f"=$H${LAST_E}", fmt["calc_big_pct"])
    NREACH = f"$B${r+1}"
    ws.write(r, 3, "平均频次", fmt["label_b"])
    ws.write_formula(r, 4, f"=IF({NREACH}<=0,0,{TGRP}/{NREACH})", fmt["calc_big"])
    NFREQ = f"$E${r+1}"
    ws.write(r, 6, "CPRP（元/点）", fmt["label_b"])
    ws.write_formula(r, 7, f"=IF({TGRP}<=0,0,{TCOST}/{TGRP})", fmt["calc_big"])
    r += 1

    ws.write(r, 0, "n+ 有效到达（%）", fmt["label_b"])
    e2 = _er_formula(NFREQ, NREACH, 2, n_rows)[1:]
    e3 = _er_formula(NFREQ, NREACH, 3, n_rows)[1:]
    e5 = _er_formula(NFREQ, NREACH, 4, n_rows)[1:]
    ws.write_formula(r, 1, f"=IF({EFN}=2,{e2},IF({EFN}=5,{e5},{e3}))", fmt["calc_big_pct"])
    ws.write(r, 3, "曝光（万人次）", fmt["label_b"])
    ws.write_formula(r, 4, f"={TGRP}/100*{UNI}", fmt["calc_big"])
    ws.write(r, 6, "触达人数（万人）", fmt["label_b"])
    ws.write_formula(r, 7, f"={NREACH}/100*{UNI}", fmt["calc_big"])
    r += 2

    # --- 直接相加 vs 去重 的对比 ---
    ws.merge_range(r, 0, r, 9, "③ 为什么不能直接相加（这一栏拿去说服同事）", fmt["section"])
    r += 1
    ws.write(r, 0, "各频道到达率直接相加", fmt["label_b"])
    ws.write_formula(r, 1, f"=SUM($E${ROW0+1}:$E${LAST_E})", fmt["pct"])
    SUMNAIVE = f"$B${r+1}"
    ws.merge_range(r, 3, r, 9, "❌ 这是错的写法", fmt["note"])
    r += 1
    ws.write(r, 0, "Sainsbury 去重后", fmt["label_b"])
    ws.write_formula(r, 1, f"={NREACH}", fmt["calc_pct"])
    ws.merge_range(r, 3, r, 9, "✓ 正确的净到达率", fmt["note"])
    r += 1
    ws.write(r, 0, "虚高了", fmt["label_b"])
    ws.write_formula(r, 1, f"={SUMNAIVE}-{NREACH}", fmt["calc_pct"])
    ws.merge_range(
        r, 3, r, 9,
        f'=CONCATENATE("直接相加会把净到达率虚报 ",TEXT({SUMNAIVE}-{NREACH},"0.0"),'
        f'" 个百分点。Sainsbury 公式：合并 = A + B − A×B÷100")',
        fmt["warn"])
    r += 2

    # --- 边际分析 ---
    ws.merge_range(r, 0, r, 9, "④ 边际分析：再加一笔钱，加到哪个频道最划算", fmt["section"])
    r += 1
    ws.write(r, 0, "追加金额（元）", fmt["label_b"])
    ws.write_number(r, 1, 1_000_000, fmt["input_int"])
    INC = f"$B${r+1}"
    ws.merge_range(r, 3, r, 9,
                   "改这个黄格子。下表算的是：把这笔钱【全部】加到某个频道，净到达率能涨多少。",
                   fmt["note"])
    r += 1
    ws.write_row(r, 0, ["频道", "当前预算", "加钱后GRP", "加钱后单媒体到达(%)",
                        "组合净到达(%)", "净到达增量(pt)", "每万元换到达(pt)", "排名"], fmt["head"])
    ws.set_row(r, 30)
    r += 1
    M0 = r
    for i in range(N_MEDIA):
        rr = r + i
        e = rr + 1
        src = ROW0 + 1 + i                              # 对应上面排期表的 Excel 行号
        ws.write_formula(rr, 0, f"=$A${src}", fmt["txt"])
        ws.write_formula(rr, 1, f"=$B${src}", fmt["int"])
        ws.write_formula(rr, 2, f'=IF(OR($A{e}="",$C${src}=""),0,($B${src}+{INC})/$C${src})',
                         fmt["num"])
        ws.write_formula(
            rr, 3,
            f'=IF(OR($C{e}<=0,$F${src}<=0),0,$F${src}*(1-EXP(-(1-$G${src})*$C{e}/$F${src})))',
            fmt["pct"])
        # 组合净到达 = 其他频道的 Sainsbury 累积 与 本频道加钱后到达率 合并
        # 其他频道累积 = 1-PRODUCT(1-r_j/100) for j != i
        others = (f"(1-PRODUCT(IF(ROW($E${ROW0+1}:$E${LAST_E})<>{src},"
                  f"1-$E${ROW0+1}:$E${LAST_E}/100,1)))*100")
        ws.write_formula(
            rr, 4,
            f'{{=IF($A{e}="","",({others})+$D{e}-({others})*$D{e}/100)}}',
            fmt["pct"])
        ws.write_formula(rr, 5, f'=IF($A{e}="","",$E{e}-{NREACH})', fmt["num"])
        ws.write_formula(rr, 6, f'=IF(OR($A{e}="",{INC}<=0),"",$F{e}/({INC}/10000))', fmt["num"])
        ws.write_formula(rr, 7,
                         f'=IF($A{e}="","",RANK($F{e},$F${M0+1}:$F${M0+N_MEDIA}))', fmt["int"])
    r += N_MEDIA + 1

    ws.merge_range(r, 0, r, 9,
                   "💡 汇报话术：『同样追加 XX 万，加到 A 频道净到达 +X.Xpt，加到 B 只有 +X.Xpt，"
                   "建议优先 A。』—— 给数字、给排序，比说「加央视吧」专业一个量级。",
                   fmt["note"])
    ws.set_row(r, 30)

    wb.close()


# =============================================================================
# 模板 3：数据质检清单
# =============================================================================

def build_qc_template(path: Path):
    wb = xlsxwriter.Workbook(str(path))
    fmt = _formats(wb)
    q = load_benchmarks().get("quality", {})

    # ---------- 说明 ----------
    ws0 = wb.add_worksheet("使用说明")
    ws0.set_column(0, 0, 100)
    ws0.merge_range(0, 0, 0, 3, "数据质检清单　使用说明", fmt["title"])
    ws0.set_row(0, 30)
    steps = [
        "① 把你的投放明细【粘贴】到「投放数据」sheet 的对应列（从第 4 行开始）。",
        "　　列的顺序不用完全一致，但表头要对得上。多余的列可以贴到右边空白处。",
        "",
        "② 粘贴后，「自动检查」那几列会立刻标红有问题的行。",
        "",
        "③ 到「检查汇总」sheet 看有多少条问题、分别是什么类型。",
        "",
        "④ 逐条处理完，再看「交付自查」sheet 的清单，全部勾完才发出去。",
        "",
        "⚠️ 这个 Excel 版只覆盖了单行就能判断的规则（数值范围、勾稽关系）。",
        "　　跨行的规则（重复记录、日期断档、统计异常值）建议用 Python 版的",
        "　　「🔍 数据质量检查」页，它会一次性全查完并给出可下载的质检报告。",
    ]
    for i, s in enumerate(steps, start=2):
        ws0.write(i, 0, s, fmt["note"] if s.startswith("　") or not s else fmt["txt_l"])
    ws0.set_column(0, 0, 100)

    # ---------- 数据表 ----------
    ws = wb.add_worksheet("投放数据")
    ws.activate()
    cols = ["日期", "频道", "时段", "节目", "时长(秒)", "播出次数",
            "收视率(%)", "GRP", "刊例价", "折扣", "花费"]
    widths = [12, 14, 18, 14, 10, 10, 11, 10, 12, 8, 13]
    ws.merge_range(0, 0, 0, len(cols) + 4, "投放明细　—— 把数据粘贴到下面（从第 4 行开始）", fmt["title"])
    ws.set_row(0, 28)
    ws.merge_range(1, 0, 1, len(cols) + 4,
                   "黄色 = 你要粘的数据　|　右侧「自动检查」列会实时标红有问题的行",
                   fmt["note"])
    ws.write_row(2, 0, cols, fmt["head"])
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)

    N = 500
    chk0 = len(cols)
    ws.write_row(2, chk0, ["自动检查：收视率", "自动检查：折扣", "自动检查：花费勾稽",
                           "自动检查：GRP勾稽", "汇总"], fmt["head"])
    ws.set_row(2, 32)
    for i in range(chk0, chk0 + 5):
        ws.set_column(i, i, 20)

    rating_max = float(q.get("rating_max", 15.0))
    cost_tol = float(q.get("cost_consistency_tol", 0.02))
    grp_tol = float(q.get("grp_consistency_tol", 0.05))

    for i in range(N):
        rr = 3 + i
        e = rr + 1
        for c in range(len(cols)):
            ws.write_blank(rr, c, None, fmt["input"] if c not in (0, 1, 2, 3) else fmt["input_txt"])
        # 收视率
        ws.write_formula(
            rr, chk0,
            f'=IF($G{e}="","",IF($G{e}>{rating_max},"❌ 收视率>{rating_max}%，'
            f'几乎一定是单位错误（0.85%被写成85）",IF($G{e}<0,"❌ 收视率为负","")))',
            fmt["txt_l"])
        # 折扣
        ws.write_formula(
            rr, chk0 + 1,
            f'=IF($J{e}="","",IF($J{e}>1,"❌ 折扣>1，应为小数（0.3=3折）；'
            f'若原意是"&TEXT($J{e}/100,"0.00")&"需整列除以100",'
            f'IF($J{e}<{q.get("discount_min", 0.01)},"⚠ 折扣异常低，确认是否资源置换","")))',
            fmt["txt_l"])
        # 花费勾稽
        ws.write_formula(
            rr, chk0 + 2,
            f'=IF(OR($K{e}="",$I{e}="",$J{e}=""),"",'
            f'IF($I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e})=0,"",'
            f'IF(ABS($K{e}-$I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e}))'
            f'/($I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e}))>{cost_tol},'
            f'"❌ 应为 "&TEXT($I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e}),"#,##0")'
            f'&"，偏差 "&TEXT(ABS($K{e}-$I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e}))'
            f'/($I{e}*IF($J{e}>1,$J{e}/100,$J{e})*IF($F{e}="",1,$F{e}))*100,"0.0")&"%","")))',
            fmt["txt_l"])
        # GRP 勾稽
        ws.write_formula(
            rr, chk0 + 3,
            f'=IF(OR($H{e}="",$G{e}="",$F{e}=""),"",IF($G{e}*$F{e}=0,"",'
            f'IF(ABS($H{e}-$G{e}*$F{e})/($G{e}*$F{e})>{grp_tol},'
            f'"❌ 应为 "&TEXT($G{e}*$F{e},"0.00")&"（确认是GRP还是TRP口径）","")))',
            fmt["txt_l"])
        # 汇总
        ws.write_formula(
            rr, chk0 + 4,
            f'=IF(COUNTIF(${chr(65+chk0)}{e}:${chr(65+chk0+3)}{e},"❌*")>0,"❌ 有错误",'
            f'IF(COUNTIF(${chr(65+chk0)}{e}:${chr(65+chk0+3)}{e},"⚠*")>0,"⚠ 需确认",'
            f'IF($A{e}="","","✓")))',
            fmt["txt"])

    # 条件格式：整行标红
    red = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
    orange = wb.add_format({"bg_color": "#FFEB9C", "font_color": "#9C6500"})
    last_col = chk0 + 4
    rng = f"A4:{chr(65+last_col)}{3+N}"
    ws.conditional_format(rng, {
        "type": "formula",
        "criteria": f'=LEFT(${chr(65+last_col)}4,1)="❌"',
        "format": red,
    })
    ws.conditional_format(rng, {
        "type": "formula",
        "criteria": f'=LEFT(${chr(65+last_col)}4,1)="⚠"',
        "format": orange,
    })
    ws.freeze_panes(3, 2)
    ws.autofilter(2, 0, 3 + N, last_col)

    # ---------- 汇总 ----------
    wss = wb.add_worksheet("检查汇总")
    wss.set_column(0, 0, 26)
    wss.set_column(1, 1, 14)
    wss.set_column(2, 2, 70)
    wss.merge_range(0, 0, 0, 2, "检查汇总", fmt["title"])
    wss.set_row(0, 28)
    sc = chr(65 + chk0 + 4)
    rows = [
        ("已粘贴数据行数", f'=COUNTA(投放数据!$A$4:$A${3+N})', "有效行数"),
        ("❌ 错误行数", f'=COUNTIF(投放数据!${sc}$4:${sc}${3+N},"❌*")', "必须修正后才能交付"),
        ("⚠ 需确认行数", f'=COUNTIF(投放数据!${sc}$4:${sc}${3+N},"⚠*")', "逐条确认，可能是正常业务"),
        ("✓ 通过行数", f'=COUNTIF(投放数据!${sc}$4:${sc}${3+N},"✓")', ""),
    ]
    r = 2
    for label, f, note in rows:
        wss.write(r, 0, label, fmt["label_b"])
        wss.write_formula(r, 1, f, fmt["calc_big"])
        wss.write(r, 2, note, fmt["note"])
        r += 1
    r += 1
    wss.write(r, 0, "结论", fmt["label_b"])
    wss.merge_range(
        r, 1, r, 2,
        f'=IF(COUNTIF(投放数据!${sc}$4:${sc}${3+N},"❌*")>0,'
        f'"❌ 质检未通过：有 "&COUNTIF(投放数据!${sc}$4:${sc}${3+N},"❌*")&" 行错误，修正前不要交付",'
        f'IF(COUNTIF(投放数据!${sc}$4:${sc}${3+N},"⚠*")>0,'
        f'"⚠ 有条件通过：有 "&COUNTIF(投放数据!${sc}$4:${sc}${3+N},"⚠*")&" 行需确认",'
        f'"✅ 质检通过，可以交付"))',
        fmt["warn"])
    wss.set_row(r, 30)
    r += 2

    wss.merge_range(r, 0, r, 2, "汇总数据（跟结算单核对用）", fmt["section"])
    r += 1
    totals = [
        ("总花费", f'=SUM(投放数据!$K$4:$K${3+N})'),
        ("总GRP", f'=SUM(投放数据!$H$4:$H${3+N})'),
        ("总播出次数", f'=SUM(投放数据!$F$4:$F${3+N})'),
        ("CPRP（元/点）", f'=IF(SUM(投放数据!$H$4:$H${3+N})=0,0,'
                        f'SUM(投放数据!$K$4:$K${3+N})/SUM(投放数据!$H$4:$H${3+N}))'),
        ("投放频道数", f'=SUMPRODUCT((投放数据!$B$4:$B${3+N}<>"")/'
                    f'COUNTIF(投放数据!$B$4:$B${3+N},投放数据!$B$4:$B${3+N}&""))'),
    ]
    for label, f in totals:
        wss.write(r, 0, label, fmt["label_b"])
        wss.write_formula(r, 1, f, fmt["calc_big"])
        r += 1
    wss.write(r + 1, 0, "⚠️ 交付前必做：把上面的「总花费」跟结算单逐分核对。", fmt["note"])

    # ---------- 自查清单 ----------
    wsc = wb.add_worksheet("交付自查")
    wsc.set_column(0, 0, 6)
    wsc.set_column(1, 1, 18)
    wsc.set_column(2, 2, 78)
    wsc.merge_range(0, 0, 0, 2, "交付前自查清单　—— 质检只能查数据，这些要靠人", fmt["title"])
    wsc.set_row(0, 28)
    wsc.write_row(2, 0, ["✓", "检查项", "具体要确认什么"], fmt["head"])
    CHECKLIST = [
        ("口径确认", "人群口径（4+/目标人群）、区域口径（全国网/城域网/省网）、数据源（CSM/勾正）是否与客户约定一致"),
        ("总数对账", "报告里的总花费，是否与结算单/客户系统里的数字完全一致"),
        ("时间区间", "报告标注的时间区间，是否与实际数据覆盖的区间一致（有没有漏头漏尾）"),
        ("GRP口径", "报告里的 GRP 是全人群还是目标人群（TRP）？有没有在标题或脚注里注明"),
        ("同比环比", "对比的上期是否可比（投放天数、频道组合是否大致相当）"),
        ("异常解释", "每一条警告是否都有了解释（哪怕结论是「正常」）"),
        ("结论复核", "自动生成的分析结论，是否结合业务实际做过人工判断，而不是照抄"),
        ("敏感信息", "报告里有没有不该出现的内容（其他客户数据、内部成本、未公开折扣）"),
        ("文件命名", "文件名是否规范（客户_报告类型_日期），版本号是否正确"),
        ("发送对象", "收件人是否正确，抄送是否需要，附件是否都带上了"),
    ]
    for i, (title, desc) in enumerate(CHECKLIST, start=3):
        wsc.write(i, 0, "☐", fmt["input_txt"])
        wsc.write(i, 1, title, fmt["txt"])
        wsc.write(i, 2, desc, fmt["txt_l"])
        wsc.set_row(i, 30)
    wsc.write(len(CHECKLIST) + 5, 1,
              "把「☐」改成「☑」表示已确认。全部确认 + 质检通过，才能发出去。", fmt["note"])

    wb.close()


# =============================================================================
# 模板 4：可打印速查卡（A4 单页）
# =============================================================================

def build_cheatsheet(path: Path):
    wb = xlsxwriter.Workbook(str(path))
    fmt = _formats(wb)
    ws = wb.add_worksheet("速查卡")

    # A4 纵向，缩放到一页
    ws.set_paper(9)
    ws.set_portrait()
    ws.fit_to_pages(1, 1)
    ws.set_margins(0.3, 0.3, 0.4, 0.3)
    ws.set_column(0, 0, 13)
    ws.set_column(1, 1, 30)
    ws.set_column(2, 2, 46)

    tiny = wb.add_format({"font_size": 8, "valign": "top", "text_wrap": True,
                          "border": 1, "align": "left"})
    tiny_b = wb.add_format({"font_size": 8, "bold": True, "valign": "vcenter",
                            "border": 1, "align": "center", "bg_color": C_SUB})
    tiny_f = wb.add_format({"font_size": 8, "font_name": "Consolas", "valign": "vcenter",
                            "border": 1, "align": "left"})
    sec = wb.add_format({"font_size": 9, "bold": True, "bg_color": C_HEAD,
                         "font_color": "white", "align": "left", "indent": 1})

    r = 0
    ws.merge_range(r, 0, r, 2, "媒介指标速查卡　（打印贴工位）", fmt["title"])
    ws.set_row(r, 24)
    r += 1

    ws.merge_range(r, 0, r, 2, "一、核心公式", sec)
    r += 1
    ws.write_row(r, 0, ["指标", "公式", "一句话理解 / 坑"], tiny_b)
    r += 1

    FORMULAS = [
        ("GRP", "Σ(单次收视率 × 次数)", "投放总量。GRP 100 = 广告在全人群前平均露 1 遍。可超过 100。"),
        ("TRP", "Σ(目标人群收视率)", "同 GRP 但只算目标人群。⚠ 绝不能和 GRP 混着比。"),
        ("CPRP", "总花费 ÷ GRP", "★最核心★ 买一个收视点多少钱。比它必须同人群/同区域/同时段。"),
        ("CPM", "花费 ÷ 曝光 × 1000", "跨媒体比价用。电视和 OTT/信息流只能换算成 CPM 才可比。"),
        ("曝光人次", "GRP ÷ 100 × 人口基数", "是人次不是人数。同一人看 3 次算 3 人次。"),
        ("净到达率", "至少看 1 次的人 ÷ 目标人群", "去重。有天花板，加钱也突破不了，只能加媒体。"),
        ("平均频次", "GRP ÷ 到达率", "<2 记不住｜3~8 合理｜>10 浪费，该扩媒体了。"),
        ("3+有效到达", "至少看 3 次的人口占比", "真正记住广告的人。客户问『多少人记住了』答这个。"),
        ("SOV", "本品投放 ÷ 市场总投放", "声量份额。花费口径和 GRP 口径结论可能不同。"),
        ("ESOV", "SOV − SOM", "每高 10pt 约带来 0.5pt 年份额增长（Binet & Field）。"),
    ]
    for k, f, note in FORMULAS:
        ws.write(r, 0, k, tiny_b)
        ws.write(r, 1, f, tiny_f)
        ws.write(r, 2, note, tiny)
        ws.set_row(r, 20)
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 2, "二、模型公式（被问起来要答得上）", sec)
    r += 1
    MODELS = [
        ("到达率", "Reach = 天花板 × (1−EXP(−(1−ρ)×GRP÷天花板))", "凹函数，边际递减，收敛到天花板"),
        ("反算GRP", "GRP = −天花板÷(1−ρ) × LN(1−目标÷天花板)", "目标≥天花板时无解 → 必须加媒体"),
        ("跨媒体", "合并 = A + B − A×B ÷ 100", "Sainsbury。假设独立，会略微高估。"),
        ("ρ 取值", "央视0.16｜一线卫视0.22｜二线0.26｜地面0.32", "观众忠诚度，越大到达率涨得越慢"),
    ]
    ws.write_row(r, 0, ["名称", "公式", "说明"], tiny_b)
    r += 1
    for k, f, note in MODELS:
        ws.write(r, 0, k, tiny_b)
        ws.write(r, 1, f, tiny_f)
        ws.write(r, 2, note, tiny)
        ws.set_row(r, 20)
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 2, "三、口径三问（拿到任何数据先问）", sec)
    r += 1
    for i, q in enumerate([
        "① 人群口径？　全人群(4+) / 目标人群？目标人群怎么定义的？",
        "② 区域口径？　全国网 / 城域网(哪几个城市) / 省网？",
        "③ 数据源？　　CSM / 勾正 / 尼尔森？不同源不能相加、不能对比。",
    ], start=1):
        ws.merge_range(r, 0, r, 2, q, tiny)
        ws.set_row(r, 15)
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 2, "四、五个致命错误（犯了很难挽回）", sec)
    r += 1
    for e in [
        "1. 各频道到达率【直接相加】—— 必须用 Sainsbury 去重，这是最容易被当场抓包的",
        "2. GRP 和 TRP 混着比 —— 口径不同，数字没有可比性",
        "3. 收视率单位搞错 —— 0.85% 写成 85，整套数字差 100 倍",
        "4. 折扣写成 30 而不是 0.3 —— 花费勾稽全对不上",
        "5. 发现异常直接改掉 —— 先问业务！异常≠错误，抹平了可能掩盖真问题",
    ]:
        ws.merge_range(r, 0, r, 2, e, tiny)
        ws.set_row(r, 15)
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 2, "五、常被问到的三句话", sec)
    r += 1
    QA = [
        ("效果好不好？", "花 X 万，GRP xxx，CPRP xxx（vs上期±x%），净到达 xx%，3+有效 xx%"),
        ("加钱加哪？", "加 A 每万元换 0.019pt，加 B 只 0.012pt，建议 A —— 给数字给排序"),
        ("竞品在干嘛？", "竞品A SOV +8.7pt，主要加码 CCTV-5，我方仅 8.6%，建议跟进/错位"),
    ]
    for q, a in QA:
        ws.write(r, 0, q, tiny_b)
        ws.merge_range(r, 1, r, 2, a, tiny)
        ws.set_row(r, 18)
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 2,
                   "⚠️ 到达率模型为业界通用近似，与 CSM/尼尔森官方测算有差异，"
                   "不考虑排期节奏/素材损耗/季节性/竞品干扰。适合方案相对比较，勿作对客户的承诺数字。",
                   fmt["note"])
    ws.set_row(r, 24)

    wb.close()


# =============================================================================
# 模板 5：周报模板
# =============================================================================

def build_weekly_report(path: Path, er_rows):
    """周报模板：填本周/上周数据 → 自动算环比、KPI 达成、生成结论草稿。

    设计意图：报告的价值不在罗列数字，而在「所以呢」。
    这个模板会把环比方向、KPI 风险自动转成中文句子，你在此基础上改。
    """
    wb = xlsxwriter.Workbook(str(path))
    fmt = _formats(wb)
    n_rows = _write_lookup_sheet(wb, fmt, er_rows)

    ws = wb.add_worksheet("周报")
    ws.activate()
    ws.set_column(0, 0, 20)
    ws.set_column(1, 3, 15)
    ws.set_column(4, 4, 12)
    ws.set_column(5, 5, 52)

    ws.merge_range(0, 0, 0, 5, "媒介投放周报", fmt["title"])
    ws.set_row(0, 30)
    r = _legend(ws, fmt, 1)

    # --- 报告信息 ---
    ws.merge_range(r, 0, r, 5, "① 报告信息", fmt["section"])
    r += 1
    for label, default in (("客户 / 品牌", "示例客户"), ("本周区间", "2026-07-27 ~ 2026-08-02"),
                           ("上周区间", "2026-07-20 ~ 2026-07-26")):
        ws.write(r, 0, label, fmt["label_b"])
        ws.merge_range(r, 1, r, 3, default, fmt["input_txt"])
        r += 1
    ws.write(r, 0, "人群口径", fmt["label_b"])
    ws.merge_range(r, 1, r, 3, "全国4+", fmt["input_txt"])
    ws.write(r, 4, "数据源", fmt["label_b"])
    ws.write(r, 5, "CSM / 勾正（务必填写）", fmt["input_txt"])
    r += 2

    # --- 核心指标 ---
    ws.merge_range(r, 0, r, 5, "② 核心指标（填黄色，绿色自动算）", fmt["section"])
    r += 1
    ws.write_row(r, 0, ["指标", "本周", "上周", "变化", "变化率", "评价"], fmt["head"])
    r += 1
    M0 = r

    # (标签, 本周默认, 上周默认, 是否成本类指标)
    METRICS = [
        ("花费（元）", 934617, 1331000, False),
        ("GRP", 53.5, 76.2, False),
        ("播出次数", 128, 165, False),
        ("投放频道数", 9, 10, False),
    ]
    for label, cur, prev, _ in METRICS:
        e = r + 1
        ws.write(r, 0, label, fmt["label_b"])
        ws.write_number(r, 1, cur, fmt["input_int"])
        ws.write_number(r, 2, prev, fmt["input_int"])
        ws.write_formula(r, 3, f'=IF($C{e}="","",$B{e}-$C{e})', fmt["calc"])
        ws.write_formula(r, 4, f'=IF(OR($C{e}="",$C{e}=0),"",($B{e}-$C{e})/$C{e}*100)', fmt["calc_pct"])
        ws.write_formula(
            r, 5,
            f'=IF($E{e}="","—",IF(ABS($E{e})<0.5,"→ 基本持平",'
            f'IF($E{e}>0,"↑ 上升 "&TEXT($E{e},"0.0")&"%","↓ 下降 "&TEXT(-$E{e},"0.0")&"%")))',
            fmt["txt_l"])
        r += 1

    # CPRP（成本类，箭头方向要反过来）
    e = r + 1
    grp_row = M0 + 2          # GRP 行的 Excel 行号
    cost_row = M0 + 1
    ws.write(r, 0, "CPRP（元/点）", fmt["label_b"])
    ws.write_formula(r, 1, f'=IF($B{grp_row}=0,"",$B{cost_row}/$B{grp_row})', fmt["calc_int"])
    ws.write_formula(r, 2, f'=IF($C{grp_row}=0,"",$C{cost_row}/$C{grp_row})', fmt["calc_int"])
    ws.write_formula(r, 3, f'=IF(OR($B{e}="",$C{e}=""),"",$B{e}-$C{e})', fmt["calc"])
    ws.write_formula(r, 4, f'=IF(OR($C{e}="",$C{e}=0),"",($B{e}-$C{e})/$C{e}*100)', fmt["calc_pct"])
    ws.write_formula(
        r, 5,
        f'=IF($E{e}="","—",IF(ABS($E{e})<0.5,"→ 基本持平",'
        f'IF($E{e}<0,"↓ 下降 "&TEXT(-$E{e},"0.0")&"% —— 效率改善（成本指标降是好事）",'
        f'"↑ 上升 "&TEXT($E{e},"0.0")&"% —— 效率下滑，需核查收视或折扣")))',
        fmt["txt_l"])
    CPRP_CUR = f"$B${e}"
    r += 2

    # --- KPI ---
    ws.merge_range(r, 0, r, 5, "③ KPI 达成（目标填黄色；成本类指标实际低于目标才算达成）", fmt["section"])
    r += 1
    ws.write_row(r, 0, ["KPI", "目标", "实际", "完成率", "判定", "说明"], fmt["head"])
    r += 1
    K0 = r
    KPIS = [
        ("GRP", 80.0, f"$B${grp_row}", False),
        ("花费（元）", 1_200_000, f"$B${cost_row}", False),
        ("CPRP（元/点）", 16000, CPRP_CUR, True),
    ]
    for label, target, actual_ref, is_cost in KPIS:
        e = r + 1
        ws.write(r, 0, label, fmt["label_b"])
        ws.write_number(r, 1, target, fmt["input_int"])
        ws.write_formula(r, 2, f"={actual_ref}", fmt["calc_int"])
        if is_cost:
            rate = f'IF(OR($C{e}="",$C{e}=0),"",$B{e}/$C{e}*100)'
        else:
            rate = f'IF(OR($B{e}="",$B{e}=0),"",$C{e}/$B{e}*100)'
        ws.write_formula(r, 3, f"={rate}", fmt["calc_pct"])
        ws.write_formula(
            r, 4,
            f'=IF($D{e}="","—",IF($D{e}>=100,"✅ 达标",IF($D{e}>=95,"🟡 基本达标",'
            f'IF($D{e}>=85,"🟠 预警","🔴 未达标"))))',
            fmt["txt"])
        ws.write(r, 5, "成本类：实际低于目标为达成" if is_cost else "", fmt["note"])
        r += 1
    K_END = r
    r += 1

    # --- 频道拆解 ---
    ws.merge_range(r, 0, r, 5, "④ 频道拆解（填频道、花费、GRP，其余自动算）", fmt["section"])
    r += 1
    ws.write_row(r, 0, ["频道", "花费(元)", "GRP", "CPRP", "花费占比(%)", "效率评价"], fmt["head"])
    r += 1
    CH0 = r
    N_CH = 12
    for i in range(N_CH):
        rr = r + i
        e = rr + 1
        ws.write_blank(rr, 0, None, fmt["input_txt"])
        ws.write_blank(rr, 1, None, fmt["input_int"])
        ws.write_blank(rr, 2, None, fmt["input"])
        ws.write_formula(rr, 3, f'=IF(OR($C{e}="",$C{e}=0),"",$B{e}/$C{e})', fmt["int"])
        ws.write_formula(
            rr, 4,
            f'=IF($B{e}="","",$B{e}/SUM($B${CH0+1}:$B${CH0+N_CH})*100)', fmt["pct"])
        ws.write_formula(
            rr, 5,
            f'=IF($D{e}="","",IF($D{e}<=MEDIAN($D${CH0+1}:$D${CH0+N_CH})*0.85,"🟢 效率优于中位数",'
            f'IF($D{e}>=MEDIAN($D${CH0+1}:$D${CH0+N_CH})*1.15,"🔴 效率低于中位数，评估是否调整","⚪ 接近中位数")))',
            fmt["txt_l"])
    r += N_CH + 1

    # --- 自动结论 ---
    ws.merge_range(r, 0, r, 5, "⑤ 结论草稿（自动生成，务必人工改写后再发）", fmt["section"])
    r += 1
    ws.merge_range(r, 0, r, 5,
                   "⚠️ 下面几句是机器根据数字拼的。它看不到业务背景（客户临时停投、竞品动作、"
                   "节假日、媒体资源变动）。照抄发出去迟早出事 —— 请逐条判断后改写。",
                   fmt["warn"])
    ws.set_row(r, 30)
    r += 1

    cprp_e = M0 + 5           # CPRP 行 Excel 行号
    concl = [
        (f'=CONCATENATE("1. 本周投放花费 ",TEXT($B${cost_row},"#,##0")," 元，'
         f'产出 GRP ",TEXT($B${grp_row},"0.0")," 点，CPRP ",TEXT({CPRP_CUR},"#,##0")," 元/点。")'),
        (f'=IF($E${grp_row}="","2. （上周无数据，无法环比）",'
         f'CONCATENATE("2. GRP 环比",IF($E${grp_row}>0,"上升","下降")," ",'
         f'TEXT(ABS($E${grp_row}),"0.0"),"%，",IF($E${grp_row}>0,"投放强度加大","投放强度收缩"),"。"))'),
        (f'=IF($E${cprp_e}="","3. （无法计算 CPRP 环比）",'
         f'CONCATENATE("3. CPRP 环比",IF($E${cprp_e}<0,"下降","上升")," ",TEXT(ABS($E${cprp_e}),"0.0"),"%，",'
         f'IF($E${cprp_e}<0,"投放效率改善。","投放效率下滑，需核查是否收视不及预期或折扣条件变差。")))'),
        (f'=IF(COUNTA($A${CH0+1}:$A${CH0+N_CH})=0,"4. （未填写频道拆解）",'
         f'CONCATENATE("4. 效率最优频道为 ",'
         f'INDEX($A${CH0+1}:$A${CH0+N_CH},MATCH(MIN(IF($D${CH0+1}:$D${CH0+N_CH}<>"",$D${CH0+1}:$D${CH0+N_CH})),'
         f'$D${CH0+1}:$D${CH0+N_CH},0)),"（CPRP ",'
         f'TEXT(MIN(IF($D${CH0+1}:$D${CH0+N_CH}<>"",$D${CH0+1}:$D${CH0+N_CH})),"#,##0"),'
         f' " 元/点），最差为 ",'
         f'INDEX($A${CH0+1}:$A${CH0+N_CH},MATCH(MAX($D${CH0+1}:$D${CH0+N_CH}),$D${CH0+1}:$D${CH0+N_CH},0)),'
         f'"（CPRP ",TEXT(MAX($D${CH0+1}:$D${CH0+N_CH}),"#,##0")," 元/点）。"))'),
        (f'=IF(COUNTIF($E${K0+1}:$E${K_END},"🔴*")+COUNTIF($E${K0+1}:$E${K_END},"🟠*")=0,'
         f'"5. 全部 KPI 达成情况正常。",'
         f'CONCATENATE("5. ⚠ 有 ",COUNTIF($E${K0+1}:$E${K_END},"🔴*")+COUNTIF($E${K0+1}:$E${K_END},"🟠*"),'
         f'" 项 KPI 存在风险，需在报告中主动说明原因和补救措施（主动报出来比被客户发现要好得多）。"))'),
    ]
    for f in concl:
        ws.merge_range(r, 0, r, 5, f, fmt["txt_l"])
        ws.set_row(r, 30)
        r += 1
    # 第4条用数组公式（MIN(IF(...)) 需要）
    r += 1

    ws.merge_range(r, 0, r, 5, "⑥ 人工补充（这部分才是你的价值）", fmt["section"])
    r += 1
    for label, hint in (
        ("异常说明", "本周有哪些数据异常？原因是什么？（已跟谁确认过）"),
        ("业务归因", "数字变化背后的业务原因（排期调整/媒体资源/竞品动作/节假日）"),
        ("下周计划", "下周排期重点、需要客户配合的事项"),
        ("风险提示", "有什么需要提前预警的？（KPI 缺口、资源紧张、数据延迟）"),
    ):
        ws.write(r, 0, label, fmt["label_b"])
        ws.merge_range(r, 1, r, 5, "", fmt["input_txt"])
        ws.set_row(r, 34)
        r += 1
        ws.merge_range(r, 1, r, 5, hint, fmt["note"])
        r += 1

    r += 1
    ws.merge_range(r, 0, r, 5,
                   "口径说明（发报告时不要省这一段）：本报告数据来源 ____，人群口径 ____，"
                   "区域口径 ____。GRP 为 ____ 人群口径。跨媒体到达率采用 Sainsbury 方法去重。",
                   fmt["warn"])
    ws.set_row(r, 30)

    wb.close()


# =============================================================================
def build_all(out_dir: Path | None = None) -> dict[str, Path]:
    out = Path(out_dir) if out_dir else OUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    er_rows = _build_er_lookup()

    files = {}
    p = out / "1_GRP预算测算模板.xlsx"
    build_grp_calculator(p, er_rows)
    files["GRP预算测算"] = p

    p = out / "2_跨媒体组合与边际分析.xlsx"
    build_multimedia(p, er_rows)
    files["跨媒体组合"] = p

    p = out / "3_数据质检清单.xlsx"
    build_qc_template(p)
    files["数据质检清单"] = p

    p = out / "4_媒介指标速查卡_可打印.xlsx"
    build_cheatsheet(p)
    files["速查卡"] = p

    p = out / "5_周报模板.xlsx"
    build_weekly_report(p, er_rows)
    files["周报模板"] = p

    return files


if __name__ == "__main__":
    created = build_all()
    print()
    for name, path in created.items():
        size = path.stat().st_size / 1024
        print(f"✅ {name:<14} {path.name:<34} {size:>7.1f} KB")
    print(f"\n输出目录：{OUT_DIR}")
