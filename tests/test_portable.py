"""
便携版验证
==========
打包出来能不能真跑，必须验证。而且要验证的不只是"能跑"，
更关键的是【它用的是自带的 Python，不是打包机上装的那个】——
否则拷到没装 Python 的电脑上就废了。

验证手段：清空所有 Python 相关环境变量后再跑，模拟一台干净的电脑。

跑法：python tests/test_portable.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "媒介分析工具箱_便携版"

PASS, FAIL = [], []


def ok(name: str, detail: str = ""):
    PASS.append(name)
    print(f"  ✅ {name:<44} {detail}")


def bad(name: str, detail: str = ""):
    FAIL.append((name, detail))
    print(f"  ❌ {name:<44} {detail}")


def clean_env() -> dict:
    """构造一个"干净电脑"的环境变量：抹掉所有 Python 痕迹。

    这是这个测试的核心 —— 如果便携版偷偷用了系统 Python，
    在这个环境下就会暴露。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON")}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    # PATH 里剔掉所有含 python 的目录
    parts = [p for p in env.get("PATH", "").split(os.pathsep)
             if p and "python" not in p.lower()]
    env["PATH"] = os.pathsep.join(parts)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(DIST), env=clean_env(), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def main() -> int:
    print(f"\n{'='*72}")
    print("  便携版验证（模拟一台没装过 Python 的电脑）")
    print(f"{'='*72}\n")

    if not DIST.exists():
        print(f"❌ 找不到便携版：{DIST}")
        print("   先运行：python -m tools.build_portable")
        return 1

    py = DIST / "python" / "python.exe"

    # =====================================================================
    print("【1】文件结构完整性")
    # =====================================================================
    required = [
        "python/python.exe", "启动.bat", "生成Excel模板.bat", "自检.bat",
        "使用说明.txt", "core/metrics.py", "core/budget.py", "core/quality.py",
        "app/主页.py", "config/benchmarks.yaml", "config/field_mapping.yaml",
        "tools/build_excel.py",
    ]
    for rel in required:
        p = DIST / rel
        if p.exists():
            ok(f"存在 {rel}")
        else:
            bad(f"缺失 {rel}")

    n_pages = len(list((DIST / "app" / "pages").glob("*.py"))) if (DIST / "app" / "pages").exists() else 0
    (ok if n_pages == 7 else bad)(f"7 个功能页", f"实际 {n_pages} 个")

    n_docs = len(list((DIST / "docs").glob("*.md"))) if (DIST / "docs").exists() else 0
    (ok if n_docs >= 3 else bad)(f"知识手册", f"{n_docs} 篇")

    # =====================================================================
    print("\n【2】自带 Python 能否独立运行（关键项）")
    # =====================================================================
    r = run([str(py), "-c",
             "import sys; print(sys.version.split()[0]); print(sys.executable)"])
    if r.returncode != 0:
        bad("自带 Python 可运行", r.stderr[-300:])
        return _summary()
    lines = r.stdout.strip().splitlines()
    ver, exe = lines[0], lines[1]
    ok("自带 Python 可运行", f"版本 {ver}")

    # 必须用的是便携版自己的 python.exe
    if str(DIST).lower() in exe.lower():
        ok("用的是自带 Python 而非系统 Python", exe.replace(str(DIST), "…"))
    else:
        bad("用的是自带 Python", f"实际用了 {exe}")

    # =====================================================================
    print("\n【3】依赖包完整（干净环境下）")
    # =====================================================================
    for mod in ("streamlit", "pandas", "numpy", "plotly", "yaml",
                "xlsxwriter", "openpyxl"):
        r = run([str(py), "-c", f"import {mod}; "
                 f"print(getattr({mod},'__version__','?'))"])
        if r.returncode == 0:
            ok(f"import {mod}", r.stdout.strip())
        else:
            bad(f"import {mod}", r.stderr.strip()[-200:])

    # =====================================================================
    print("\n【4】计算内核正确性（在便携版里重跑数学测试）")
    # =====================================================================
    code = (
        "import sys; sys.path.insert(0,'.');"
        "from core.metrics import *;"
        "g=grp_from_rating(0.85,20);"
        "r=reach_from_grp(g*10,62,0.16);"
        "f=frequency(g*10,r);"
        "e=effective_reach(g*10,r,3);"
        "c=combine_reach_list([50,50,50]);"
        "print(f'{g:.4f}|{r:.6f}|{f:.6f}|{e:.6f}|{c:.6f}')"
    )
    r = run([str(py), "-c", code])
    if r.returncode != 0:
        bad("计算内核可用", r.stderr[-400:])
    else:
        got = r.stdout.strip()
        # 用打包机的 Python 算一遍作为基准
        sys.path.insert(0, str(ROOT))
        from core.metrics import (combine_reach_list, effective_reach, frequency,
                                  grp_from_rating, reach_from_grp)
        g = grp_from_rating(0.85, 20)
        rr = reach_from_grp(g * 10, 62, 0.16)
        want = (f"{g:.4f}|{rr:.6f}|{frequency(g*10, rr):.6f}|"
                f"{effective_reach(g*10, rr, 3):.6f}|{combine_reach_list([50,50,50]):.6f}")
        if got == want:
            ok("计算结果与开发机完全一致", got)
        else:
            bad("计算结果一致", f"便携版={got}  开发机={want}")

    # =====================================================================
    print("\n【5】能生成样例数据与 Excel 模板")
    # =====================================================================
    r = run([str(py), "-m", "core.sample_data"], timeout=300)
    if r.returncode == 0 and (DIST / "data" / "sample" / "样例_投放明细.xlsx").exists():
        ok("生成样例数据")
    else:
        bad("生成样例数据", (r.stderr or r.stdout)[-300:])

    r = run([str(py), "-m", "tools.build_excel"], timeout=600)
    xls = list((DIST / "output" / "excel模板").glob("*.xlsx")) \
        if (DIST / "output" / "excel模板").exists() else []
    if r.returncode == 0 and len(xls) == 5:
        ok("生成 Excel 模板", f"{len(xls)} 个文件")
    else:
        bad("生成 Excel 模板", f"{len(xls)} 个文件；{(r.stderr or r.stdout)[-300:]}")

    # =====================================================================
    print("\n【6】端到端：读数据 → 质检 → 出报告")
    # =====================================================================
    code = (
        "import sys; sys.path.insert(0,'.');"
        "import pandas as pd;"
        "from core.config import map_columns, coerce_dtypes, normalize_channel_column;"
        "from core.quality import run_quality_check;"
        "from core.report import build_report, report_to_excel;"
        "df=pd.read_excel('data/sample/样例_投放明细.xlsx');"
        "df,_,_=map_columns(df,'placement');"
        "df,_=coerce_dtypes(df,'placement');"
        "df,_=normalize_channel_column(df);"
        "q=run_quality_check(df,'placement');"
        "rep=build_report(df,'monthly',targets={'GRP':800});"
        "xl=report_to_excel(rep);"
        "print(f'{len(df)}|{q.error_count}|{rep[\"row_count\"]}|{len(rep[\"insights\"])}|{len(xl)}')"
    )
    r = run([str(py), "-c", code], timeout=300)
    if r.returncode == 0:
        parts = r.stdout.strip().split("|")
        ok("端到端流程跑通",
           f"读入{parts[0]}行 质检抓到{parts[1]}项错误 "
           f"月报{parts[2]}行 {parts[3]}条结论 Excel {int(parts[4])/1024:.0f}KB")
    else:
        bad("端到端流程", (r.stderr or r.stdout)[-500:])

    # =====================================================================
    print("\n【7】Streamlit 页面可加载")
    # =====================================================================
    code = (
        "import sys; sys.path.insert(0,'.');"
        "from streamlit.testing.v1 import AppTest;"
        "at=AppTest.from_file('app/主页.py', default_timeout=120).run();"
        "print('EXC' if at.exception else 'OK')"
    )
    r = run([str(py), "-c", code], timeout=400)
    if r.returncode == 0 and "OK" in r.stdout:
        ok("主页渲染通过")
    else:
        bad("主页渲染", (r.stderr or r.stdout)[-500:])

    # =====================================================================
    print("\n【8】体积与可移植性")
    # =====================================================================
    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    mb = total / 1024 / 1024
    (ok if mb < 600 else bad)("体积可接受", f"{mb:.0f} MB（U盘/网盘都放得下）")

    # 不该有绝对路径残留（会导致换机器失效）
    leaked = []
    for pth in (DIST / "python").glob("python*._pth"):
        content = pth.read_text(encoding="utf-8", errors="replace")
        if str(ROOT).lower() in content.lower() or "d:\\" in content.lower():
            leaked.append(pth.name)
    (ok if not leaked else bad)("._pth 无绝对路径残留",
                                "换机器不会失效" if not leaked else str(leaked))

    return _summary()


def _summary() -> int:
    print(f"\n{'='*72}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败清单：")
        for name, detail in FAIL:
            print(f"  ❌ {name}：{detail}")
        return 1
    print("✅ 便携版验证通过 —— 可以拷到没装 Python 的电脑上使用")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
