"""
Excel 模板公式验证
==================
xlsxwriter 只负责【写】公式，不负责【算】。所以生成的文件里公式对不对，
必须真的打开 Excel 重算一遍，再跟 Python 内核的结果比对。

这个脚本用 COM 驱动本机 Excel：
  1. 打开模板 → 改输入格 → 强制全量重算 → 读结果
  2. 跟 core/ 里的 Python 函数比，误差超阈值就报错

单元格位置【按行标签动态查找】，不写死行号 —— 这样以后调模板版式，
测试不用跟着改。

需要本机装了 Excel（或 WPS）。跑法：python tests/test_excel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import get_channel_benchmark                                # noqa: E402
from core.metrics import (                                                   # noqa: E402
    combine_reach_list, cprp, effective_reach, frequency, grp_needed_for_reach,
    impressions_from_grp, reach_from_grp,
)

TPL_DIR = ROOT / "output" / "excel模板"
PASS, FAIL = [], []

# 有效到达率走查表插值，允许 0.6 个百分点的绝对误差（已在 build_excel 里论证）
ER_TOL_PT = 0.6


def check(name: str, got, want, tol=1e-6, unit=""):
    """相对误差比对。"""
    if got is None:
        FAIL.append((name, None, want))
        print(f"  ❌ {name:<40} Excel 单元格为空")
        return
    got = float(got)
    ok = abs(got) <= tol if want == 0 else abs(got - want) / max(abs(want), 1e-12) <= tol
    (PASS if ok else FAIL).append(name if ok else (name, got, want))
    mark = "✅" if ok else "❌"
    tail = "" if ok else "  ← 不一致"
    print(f"  {mark} {name:<40} Excel={got:>13,.4f}  Python={want:>13,.4f} {unit}{tail}")


def check_abs(name: str, got, want, tol, unit=""):
    """绝对误差比对（查表插值用）。"""
    if got is None:
        FAIL.append((name, None, want))
        print(f"  ❌ {name:<40} Excel 单元格为空")
        return
    got = float(got)
    ok = abs(got - want) <= tol
    (PASS if ok else FAIL).append(name if ok else (name, got, want))
    mark = "✅" if ok else "❌"
    tail = "" if ok else "  ← 超差"
    print(f"  {mark} {name:<40} Excel={got:>13,.4f}  Python={want:>13,.4f} Δ={abs(got-want):.4f}{unit}{tail}")


def check_text(name: str, got, must_contain: str):
    got = str(got or "")
    ok = must_contain in got
    (PASS if ok else FAIL).append(name if ok else (name, got, must_contain))
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name:<40} 「{got[:46]}」")


def find_row(ws, label: str, col: int = 1, max_row: int = 80) -> int:
    """按 A 列的标签找行号。找不到就抛错，避免默默比错格子。"""
    for r in range(1, max_row + 1):
        v = ws.Cells(r, col).Value
        if v is not None and str(v).strip() == label:
            return r
    raise LookupError(f"在第 {col} 列找不到标签「{label}」")


def main():
    import win32com.client as win32

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.EnableEvents = False

    try:
        # =====================================================================
        print("\n【模板 1】GRP预算测算模板.xlsx")
        # =====================================================================
        wb = excel.Workbooks.Open(str(TPL_DIR / "1_GRP预算测算模板.xlsx"))
        try:
            ws = wb.Worksheets("GRP测算")
            R = {k: find_row(ws, k) for k in
                 ("选择频道", "CPRP（元/点）", "覆盖天花板（%）", "重复系数 ρ",
                  "GRP（毛评点）", "净到达率 1+（%）", "平均频次",
                  "触达人数（万人）", "曝光（万人次）", "CPM（元/千人次）",
                  "目标净到达率（%）", "需要 GRP", "需要预算（元）", "预算(万元)")}
            r_ch = R["选择频道"]
            # 有效到达那一行紧跟在「平均频次」后面（标签是公式，找不到文本）
            r_er = R["平均频次"] + 1

            for channel, budget, efn in (("CCTV-1", 3_000_000, 3),
                                         ("湖南卫视", 8_000_000, 5),
                                         ("安徽卫视", 1_200_000, 2)):
                print(f"\n  ── {channel}　预算 {budget:,} 元　有效频次 {efn}+ ──")
                ws.Cells(r_ch, 2).Value = channel
                ws.Cells(r_ch, 5).Value = budget
                ws.Cells(r_ch + 1, 5).Value = efn
                excel.CalculateFullRebuild()

                b = get_channel_benchmark(channel)
                py_cprp, py_mr, py_rho = float(b["cprp"]), float(b["max_reach"]), float(b["rho"])
                uni = float(ws.Cells(r_ch + 2, 5).Value)

                check("CPRP 查表", ws.Cells(R["CPRP（元/点）"], 2).Value, py_cprp)
                check("覆盖天花板 查表", ws.Cells(R["覆盖天花板（%）"], 2).Value, py_mr)
                check("ρ 查表", ws.Cells(R["重复系数 ρ"], 2).Value, py_rho)

                py_grp = budget / py_cprp
                py_reach = reach_from_grp(py_grp, py_mr, py_rho)
                py_freq = frequency(py_grp, py_reach)
                py_er = effective_reach(py_grp, py_reach, efn)
                py_imp_wan = impressions_from_grp(py_grp, uni) / 10000

                check("GRP", ws.Cells(R["GRP（毛评点）"], 2).Value, py_grp)
                check("净到达率(%)", ws.Cells(R["净到达率 1+（%）"], 2).Value, py_reach)
                check("平均频次", ws.Cells(R["平均频次"], 2).Value, py_freq)
                check_abs(f"{efn}+ 有效到达率(%)", ws.Cells(r_er, 2).Value, py_er,
                          ER_TOL_PT, unit=" pt")
                check("触达人数(万人)", ws.Cells(R["触达人数（万人）"], 2).Value,
                      py_reach / 100 * uni)
                check("曝光(万人次)", ws.Cells(R["曝光（万人次）"], 2).Value, py_imp_wan)
                check("CPM(元/千人次)", ws.Cells(R["CPM（元/千人次）"], 2).Value,
                      budget / (py_imp_wan * 10000) * 1000)

            # --- 反算 ---
            print("\n  ── 反算：目标到达率 → 需要多少预算 ──")
            ws.Cells(r_ch, 2).Value = "CCTV-1"
            ws.Cells(r_ch, 5).Value = 3_000_000
            b = get_channel_benchmark("CCTV-1")
            for target in (25.0, 45.0, 58.0):
                ws.Cells(R["目标净到达率（%）"], 2).Value = target
                excel.CalculateFullRebuild()
                py_need = grp_needed_for_reach(target, float(b["max_reach"]), float(b["rho"]))
                check(f"目标{target:.0f}% 需要GRP", ws.Cells(R["需要 GRP"], 2).Value, py_need)
                check(f"目标{target:.0f}% 需要预算", ws.Cells(R["需要预算（元）"], 2).Value,
                      py_need * float(b["cprp"]))

            ws.Cells(R["目标净到达率（%）"], 2).Value = 95.0
            excel.CalculateFullRebuild()
            check_text("超天花板返回提示而非数字", ws.Cells(R["需要 GRP"], 2).Value, "做不到")

            # --- 频次诊断 ---
            print("\n  ── 频次诊断文案 ──")
            for ch, bud, expect in (("安徽卫视", 300_000, "频次偏低"),
                                    ("CCTV-1", 12_000_000, "合理区间"),
                                    ("安徽卫视", 60_000_000, "频次过高")):
                ws.Cells(r_ch, 2).Value = ch
                ws.Cells(r_ch, 5).Value = bud
                excel.CalculateFullRebuild()
                r_diag = find_row(ws, "频次诊断")
                f_val = float(ws.Cells(R["平均频次"], 2).Value)
                check_text(f"{ch} {bud/10000:.0f}万(频次{f_val:.1f}) → {expect}",
                           ws.Cells(r_diag, 2).Value, expect)

            # --- 曲线数据抽查 ---
            print("\n  ── 响应曲线数据抽查 ──")
            ws.Cells(r_ch, 2).Value = "CCTV-1"
            ws.Cells(r_ch, 5).Value = 3_000_000
            excel.CalculateFullRebuild()
            b = get_channel_benchmark("CCTV-1")
            c0 = R["预算(万元)"] + 1
            for off in (0, 9, 19, 38):
                row = c0 + off
                bw = float(ws.Cells(row, 1).Value)
                py_g = bw * 10000 / float(b["cprp"])
                py_r = reach_from_grp(py_g, float(b["max_reach"]), float(b["rho"]))
                check(f"曲线@{bw:.0f}万 GRP", ws.Cells(row, 2).Value, py_g)
                check(f"曲线@{bw:.0f}万 到达率", ws.Cells(row, 3).Value, py_r)
                check_abs(f"曲线@{bw:.0f}万 3+有效", ws.Cells(row, 5).Value,
                          effective_reach(py_g, py_r, 3), ER_TOL_PT, unit=" pt")
        finally:
            wb.Close(SaveChanges=False)

        # =====================================================================
        print("\n【模板 2】跨媒体组合与边际分析.xlsx")
        # =====================================================================
        wb = excel.Workbooks.Open(str(TPL_DIR / "2_跨媒体组合与边际分析.xlsx"))
        try:
            ws = wb.Worksheets("跨媒体组合")
            r_hdr = find_row(ws, "频道")               # 排期表表头
            r_data = r_hdr + 1
            N = 10
            R = {k: find_row(ws, k) for k in
                 ("目标人群（万人）", "总预算（元）", "净到达率（%）", "n+ 有效到达（%）",
                  "各频道到达率直接相加", "Sainsbury 去重后", "虚高了", "追加金额（元）")}
            r_marg = find_row(ws, "频道", max_row=60) + 0
            # 边际表表头是第二个「频道」，从汇总区之后再找
            r_marg_hdr = None
            for rr in range(R["追加金额（元）"], R["追加金额（元）"] + 6):
                if str(ws.Cells(rr, 1).Value or "").strip() == "频道":
                    r_marg_hdr = rr
                    break
            assert r_marg_hdr, "找不到边际分析表头"
            r_marg0 = r_marg_hdr + 1

            combos = [
                [("CCTV-1", 2_000_000), ("湖南卫视", 1_500_000), ("浙江卫视", 1_000_000),
                 ("OTT开机屏", 800_000)],
                [("CCTV-5", 3_000_000), ("江苏卫视", 2_500_000)],
                [("CCTV-1", 1_000_000), ("CCTV-3", 1_000_000), ("CCTV-5", 1_000_000),
                 ("CCTV-6", 1_000_000), ("CCTV-8", 1_000_000), ("北京卫视", 1_000_000)],
            ]

            for ci, combo in enumerate(combos, 1):
                print(f"\n  ── 组合 {ci}：{len(combo)} 个频道 ──")
                for i in range(N):
                    ws.Cells(r_data + i, 1).Value = ""
                    ws.Cells(r_data + i, 2).Value = 0
                for i, (ch, cost) in enumerate(combo):
                    ws.Cells(r_data + i, 1).Value = ch
                    ws.Cells(r_data + i, 2).Value = cost
                excel.CalculateFullRebuild()

                py_reaches, py_grps = [], []
                for ch, cost in combo:
                    b = get_channel_benchmark(ch)
                    g = cost / float(b["cprp"])
                    py_grps.append(g)
                    py_reaches.append(reach_from_grp(g, float(b["max_reach"]), float(b["rho"])))
                py_grp_tot = sum(py_grps)
                py_cost_tot = sum(c for _, c in combo)
                py_net = combine_reach_list(py_reaches, "sainsbury")

                for i, (ch, _) in enumerate(combo):
                    check(f"  {ch} 单媒体到达率",
                          ws.Cells(r_data + i, 5).Value, py_reaches[i])

                check("总预算", ws.Cells(R["总预算（元）"], 2).Value, py_cost_tot)
                check("总GRP", ws.Cells(R["总预算（元）"], 5).Value, py_grp_tot)
                check("Sainsbury 净到达率", ws.Cells(R["净到达率（%）"], 2).Value, py_net)
                check("平均频次", ws.Cells(R["净到达率（%）"], 5).Value,
                      frequency(py_grp_tot, py_net))
                check("组合CPRP", ws.Cells(R["净到达率（%）"], 8).Value,
                      cprp(py_cost_tot, py_grp_tot))
                check_abs("3+ 有效到达率", ws.Cells(R["n+ 有效到达（%）"], 2).Value,
                          effective_reach(py_grp_tot, py_net, 3), ER_TOL_PT, unit=" pt")
                check("直接相加(错误写法)", ws.Cells(R["各频道到达率直接相加"], 2).Value,
                      sum(py_reaches))
                check("虚高幅度", ws.Cells(R["虚高了"], 2).Value, sum(py_reaches) - py_net)

            # --- 边际分析 ---
            print("\n  ── 边际分析：追加预算加到哪个频道 ──")
            combo = combos[0]
            for i in range(N):
                ws.Cells(r_data + i, 1).Value = ""
                ws.Cells(r_data + i, 2).Value = 0
            for i, (ch, cost) in enumerate(combo):
                ws.Cells(r_data + i, 1).Value = ch
                ws.Cells(r_data + i, 2).Value = cost
            INC = 1_000_000
            ws.Cells(R["追加金额（元）"], 2).Value = INC
            excel.CalculateFullRebuild()

            base_r = []
            for ch, cost in combo:
                b = get_channel_benchmark(ch)
                base_r.append(reach_from_grp(cost / float(b["cprp"]),
                                             float(b["max_reach"]), float(b["rho"])))
            base_net = combine_reach_list(base_r, "sainsbury")

            deltas = []
            for i, (ch, cost) in enumerate(combo):
                b = get_channel_benchmark(ch)
                nr = list(base_r)
                nr[i] = reach_from_grp((cost + INC) / float(b["cprp"]),
                                       float(b["max_reach"]), float(b["rho"]))
                py_new = combine_reach_list(nr, "sainsbury")
                deltas.append(py_new - base_net)
                check(f"  加{ch} 组合净到达",
                      ws.Cells(r_marg0 + i, 5).Value, py_new, tol=1e-5)
                check(f"  加{ch} 净到达增量",
                      ws.Cells(r_marg0 + i, 6).Value, py_new - base_net, tol=1e-4)

            # 排名是否正确（增量最大的排第 1）
            best_i = max(range(len(combo)), key=lambda i: deltas[i])
            rank_of_best = ws.Cells(r_marg0 + best_i, 8).Value
            check(f"  最优频道({combo[best_i][0]})排名为1", rank_of_best, 1)
        finally:
            wb.Close(SaveChanges=False)

        # =====================================================================
        print("\n【模板 3】数据质检清单.xlsx")
        # =====================================================================
        wb = excel.Workbooks.Open(str(TPL_DIR / "3_数据质检清单.xlsx"))
        try:
            ws = wb.Worksheets("投放数据")
            cases = [
                # 日期, 频道, 时段, 节目, 时长, 次数, 收视率, GRP, 刊例, 折扣, 花费
                ("2026-07-01", "CCTV-1", "黄金", "剧场", 15, 2, 0.85, 1.70, 100000, 0.25, 50000),
                ("2026-07-02", "CCTV-1", "黄金", "剧场", 15, 2, 85.0, 170.0, 100000, 0.25, 50000),
                ("2026-07-03", "CCTV-1", "黄金", "剧场", 15, 2, 0.85, 1.70, 100000, 25, 50000),
                ("2026-07-04", "CCTV-1", "黄金", "剧场", 15, 2, 0.85, 1.70, 100000, 0.25, 71000),
                ("2026-07-05", "CCTV-1", "黄金", "剧场", 15, 2, 0.85, 5.00, 100000, 0.25, 50000),
            ]
            labels = ["正常行", "收视率单位错(85)", "折扣写成25", "花费勾稽偏42%", "GRP勾稽错"]
            expect = ["✓", "❌", "❌", "❌", "❌"]

            for i, row in enumerate(cases):
                for j, v in enumerate(row):
                    ws.Cells(4 + i, 1 + j).Value = v
            excel.CalculateFullRebuild()

            print()
            for i, (exp, lab) in enumerate(zip(expect, labels)):
                check_text(lab, ws.Cells(4 + i, 16).Value, exp)

            wss = wb.Worksheets("检查汇总")
            RS = {k: find_row(wss, k, max_row=25) for k in
                  ("已粘贴数据行数", "❌ 错误行数", "✓ 通过行数", "结论", "总花费", "总GRP", "CPRP（元/点）")}
            excel.CalculateFullRebuild()
            print()
            check("汇总-数据行数", wss.Cells(RS["已粘贴数据行数"], 2).Value, 5)
            check("汇总-错误行数", wss.Cells(RS["❌ 错误行数"], 2).Value, 4)
            check("汇总-通过行数", wss.Cells(RS["✓ 通过行数"], 2).Value, 1)
            check("汇总-总花费", wss.Cells(RS["总花费"], 2).Value, sum(c[10] for c in cases))
            check("汇总-总GRP", wss.Cells(RS["总GRP"], 2).Value, sum(c[7] for c in cases))
            check("汇总-CPRP", wss.Cells(RS["CPRP（元/点）"], 2).Value,
                  sum(c[10] for c in cases) / sum(c[7] for c in cases))
            check_text("汇总-结论正确拦截", wss.Cells(RS["结论"], 2).Value, "未通过")

            # 全部改成正常行 → 结论应变为通过
            for i in range(1, 5):
                for j, v in enumerate(cases[0]):
                    ws.Cells(4 + i, 1 + j).Value = v
            excel.CalculateFullRebuild()
            check_text("全部正常时结论转为通过", wss.Cells(RS["结论"], 2).Value, "质检通过")
        finally:
            wb.Close(SaveChanges=False)

        # =====================================================================
        print("\n【模板 4】媒介指标速查卡（静态内容，验打开与打印设置）")
        # =====================================================================
        wb = excel.Workbooks.Open(str(TPL_DIR / "4_媒介指标速查卡_可打印.xlsx"))
        try:
            ws = wb.Worksheets("速查卡")
            fit_w = ws.PageSetup.FitToPagesWide
            ok = int(fit_w) == 1
            (PASS if ok else FAIL).append("速查卡-单页打印" if ok else ("速查卡-单页打印", fit_w, 1))
            print(f"  {'✅' if ok else '❌'} {'单页打印设置':<40} FitToPagesWide={fit_w}")
            rows = ws.UsedRange.Rows.Count
            ok2 = rows > 25
            (PASS if ok2 else FAIL).append("速查卡-内容" if ok2 else ("速查卡-内容", rows, ">25"))
            print(f"  {'✅' if ok2 else '❌'} {'内容行数':<40} {rows} 行")
        finally:
            wb.Close(SaveChanges=False)

        # =====================================================================
        print("\n【模板 5】周报模板.xlsx")
        # =====================================================================
        wb = excel.Workbooks.Open(str(TPL_DIR / "5_周报模板.xlsx"))
        try:
            ws = wb.Worksheets("周报")
            R = {k: find_row(ws, k, max_row=40) for k in
                 ("花费（元）", "GRP", "CPRP（元/点）")}
            r_cost, r_grp = R["花费（元）"], R["GRP"]
            r_cprp = R["CPRP（元/点）"]

            for cur_cost, cur_grp, prev_cost, prev_grp in (
                (934_617, 53.5, 1_331_000, 76.2),      # CPRP 几乎持平
                (2_000_000, 120.0, 1_500_000, 100.0),  # CPRP 上升 → 效率下滑
                (1_800_000, 150.0, 1_500_000, 100.0),  # CPRP 下降 → 效率改善
            ):
                print(f"\n  ── 本周 {cur_cost:,}元/{cur_grp}点　上周 {prev_cost:,}元/{prev_grp}点 ──")
                ws.Cells(r_cost, 2).Value = cur_cost
                ws.Cells(r_cost, 3).Value = prev_cost
                ws.Cells(r_grp, 2).Value = cur_grp
                ws.Cells(r_grp, 3).Value = prev_grp
                excel.CalculateFullRebuild()

                py_cur_cprp = cur_cost / cur_grp
                py_prev_cprp = prev_cost / prev_grp

                check("本周CPRP", ws.Cells(r_cprp, 2).Value, py_cur_cprp)
                check("上周CPRP", ws.Cells(r_cprp, 3).Value, py_prev_cprp)
                check("花费环比(%)", ws.Cells(r_cost, 5).Value,
                      (cur_cost - prev_cost) / prev_cost * 100)
                check("GRP环比(%)", ws.Cells(r_grp, 5).Value,
                      (cur_grp - prev_grp) / prev_grp * 100)
                check("CPRP环比(%)", ws.Cells(r_cprp, 5).Value,
                      (py_cur_cprp - py_prev_cprp) / py_prev_cprp * 100)

                # 成本类指标的评价方向必须反过来：CPRP 下降 = 效率改善
                # 注意模板有 0.5% 的"基本持平"阈值，变化太小时不判方向
                verdict = str(ws.Cells(r_cprp, 6).Value or "")
                pct = (py_cur_cprp - py_prev_cprp) / py_prev_cprp * 100
                if abs(pct) < 0.5:
                    check_text(f"CPRP变化仅{pct:+.2f}%→判基本持平", verdict, "基本持平")
                elif pct < 0:
                    check_text("CPRP下降→标注为效率改善", verdict, "效率改善")
                else:
                    check_text("CPRP上升→标注为效率下滑", verdict, "效率下滑")

            # --- KPI 达成（含成本类反向判定）---
            print("\n  ── KPI 达成判定 ──")
            r_kpi_grp = None
            for rr in range(r_cprp, r_cprp + 12):
                if str(ws.Cells(rr, 1).Value or "").strip() == "GRP":
                    r_kpi_grp = rr
                    break
            assert r_kpi_grp, "找不到 KPI 区的 GRP 行"
            r_kpi_cprp = r_kpi_grp + 2

            # GRP 目标 100，实际 120 → 完成率 120%，达标
            ws.Cells(r_cost, 2).Value = 2_000_000
            ws.Cells(r_grp, 2).Value = 120.0
            ws.Cells(r_kpi_grp, 2).Value = 100.0
            excel.CalculateFullRebuild()
            check("KPI GRP 完成率", ws.Cells(r_kpi_grp, 4).Value, 120.0)
            check_text("KPI GRP 判定达标", ws.Cells(r_kpi_grp, 5).Value, "达标")

            # CPRP 目标 20000，实际 16667 → 成本类反算完成率 120%，达标
            ws.Cells(r_kpi_cprp, 2).Value = 20000
            excel.CalculateFullRebuild()
            actual_cprp = 2_000_000 / 120.0
            check("KPI CPRP 完成率(成本类反算)",
                  ws.Cells(r_kpi_cprp, 4).Value, 20000 / actual_cprp * 100)
            check_text("KPI CPRP 判定达标", ws.Cells(r_kpi_cprp, 5).Value, "达标")

            # CPRP 目标 12000，实际 16667 → 完成率 72%，未达标
            ws.Cells(r_kpi_cprp, 2).Value = 12000
            excel.CalculateFullRebuild()
            check("KPI CPRP 未达标完成率",
                  ws.Cells(r_kpi_cprp, 4).Value, 12000 / actual_cprp * 100)
            check_text("KPI CPRP 判定未达标", ws.Cells(r_kpi_cprp, 5).Value, "未达标")

            # --- 结论草稿 ---
            print("\n  ── 结论草稿自动生成 ──")
            found = 0
            for rr in range(r_kpi_cprp, r_kpi_cprp + 40):
                v = str(ws.Cells(rr, 1).Value or "")
                if v.startswith("1. 本周投放花费"):
                    check_text("结论1-花费与GRP", v, "产出 GRP")
                    found += 1
                elif v.startswith("2. GRP 环比"):
                    check_text("结论2-GRP环比方向", v, "上升")
                    found += 1
                elif v.startswith("3. CPRP 环比"):
                    found += 1
                elif v.startswith("5."):
                    check_text("结论5-KPI风险提示", v, "KPI")
                    found += 1
            ok = found >= 4
            (PASS if ok else FAIL).append("结论草稿条数" if ok else ("结论草稿条数", found, ">=4"))
            print(f"  {'✅' if ok else '❌'} {'结论草稿生成条数':<40} {found} 条")
        finally:
            wb.Close(SaveChanges=False)

    finally:
        excel.Quit()

    print("\n" + "=" * 78)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败清单：")
        for item in FAIL:
            if isinstance(item, tuple):
                print(f"  ❌ {item[0]}：Excel={item[1]!r}　期望={item[2]!r}")
            else:
                print(f"  ❌ {item}")
        return 1
    print("✅ Excel 模板全部公式与 Python 内核一致")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
