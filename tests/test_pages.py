"""
页面冒烟测试
============
Streamlit 页面的 bug 只有真跑起来才暴露。这个脚本用 Streamlit 官方的
AppTest 把 7 个页面全部无头执行一遍，任何异常都会被抓出来。

跑法：python tests/test_pages.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

PAGES = [
    "app/主页.py",
    "app/pages/1_📖_媒介知识速查.py",
    "app/pages/2_🧮_指标计算器.py",
    "app/pages/3_🔍_数据质量检查.py",
    "app/pages/4_💰_预算分配优化.py",
    "app/pages/5_⚔️_竞品声量分析.py",
    "app/pages/6_📊_日报周报月报.py",
    "app/pages/7_🎯_排期方案对比.py",
]

failures = []

for page in PAGES:
    path = ROOT / page
    name = path.stem
    print(f"\n{'='*60}\n▶ {name}")

    try:
        at = AppTest.from_file(str(path), default_timeout=180).run()
    except Exception as e:                                   # noqa: BLE001
        print(f"  ❌ 启动失败: {type(e).__name__}: {e}")
        failures.append((name, "启动", f"{type(e).__name__}: {e}"))
        continue

    if at.exception:
        for ex in at.exception:
            print(f"  ❌ 初始渲染异常: {ex.value}")
            failures.append((name, "初始渲染", str(ex.value)))
        continue

    print(f"  ✅ 初始渲染通过"
          f"（{len(at.button)} 按钮 / {len(at.tabs)} 标签 / {len(at.dataframe)} 表格）")

    # --- 需要选样例数据 + 点按钮的页面，走完整流程 ---
    needs_sample = any(k in name for k in ("质量检查", "竞品", "日报"))
    if needs_sample:
        try:
            if at.radio:
                at.radio[0].set_value("🧪 使用样例数据").run()
            if at.exception:
                for ex in at.exception:
                    print(f"  ❌ 加载样例数据异常: {ex.value}")
                    failures.append((name, "加载样例", str(ex.value)))
                continue
            print(f"  ✅ 样例数据加载通过")

            # 点主按钮（质检/生成报告）
            primary = [b for b in at.button if "检查" in b.label or "生成" in b.label]
            if primary:
                primary[0].click().run()
                if at.exception:
                    for ex in at.exception:
                        print(f"  ❌ 执行「{primary[0].label}」异常: {ex.value}")
                        failures.append((name, primary[0].label, str(ex.value)))
                    continue
                print(f"  ✅ 「{primary[0].label}」执行通过")
        except Exception as e:                               # noqa: BLE001
            print(f"  ❌ 交互流程失败: {type(e).__name__}: {e}")
            failures.append((name, "交互", f"{type(e).__name__}: {e}"))
            continue

    # --- 优化/对比页：直接点按钮 ---
    if "预算分配" in name:
        try:
            btns = [b for b in at.button if "优化" in b.label]
            if btns:
                btns[0].click().run()
                if at.exception:
                    for ex in at.exception:
                        print(f"  ❌ 执行优化异常: {ex.value}")
                        failures.append((name, "优化", str(ex.value)))
                    continue
                print(f"  ✅ 预算优化执行通过")
        except Exception as e:                               # noqa: BLE001
            print(f"  ❌ 优化流程失败: {type(e).__name__}: {e}")
            failures.append((name, "优化", f"{type(e).__name__}: {e}"))

print("\n" + "=" * 60)
if failures:
    print(f"❌ {len(failures)} 项失败：\n")
    for page, stage, err in failures:
        print(f"  [{page}] {stage}")
        print(f"    {err[:400]}\n")
    sys.exit(1)
print(f"✅ {len(PAGES)} 个页面全部通过")
print("=" * 60)
