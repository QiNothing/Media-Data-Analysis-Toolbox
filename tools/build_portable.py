"""
绿色便携版打包器
================
把整个工具箱打成一个【拷过去双击就能跑】的文件夹，用于：
  - 公司电脑没有 Python
  - 没有管理员权限，装不了软件
  - IT 不给审批

原理：用 Python 官方的 embeddable（嵌入式）发行版。它就是一堆 dll 和 pyd，
      解压即用，不写注册表、不改环境变量、不需要任何权限。

产出：dist/媒介分析工具箱_便携版/
      整个文件夹拷到 U 盘或公司电脑任意位置，双击里面的「启动.bat」即可。

用法（在有网的电脑上跑一次）：
    python -m tools.build_portable

⚠️ 重要限制，必须知道：
  1. 只能在【和目标机器同架构】的 Windows 上跑（都是 64 位就没问题）
  2. 打包机需要联网（要下载 Python 和依赖包）
  3. 成品约 250~400 MB，U 盘/个人网盘都放得下
  4. 【不要】把含有客户数据的成品传到公网网盘
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "媒介分析工具箱_便携版"

# Python 3.11 是兼容性最好的版本：依赖包的预编译 wheel 最全
PY_VERSION = "3.11.9"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# 要拷进便携版的项目文件
COPY_ITEMS = ["core", "app", "config", "docs", "tools", "README.md", "requirements.txt"]


def _log(msg: str):
    print(f"  {msg}", flush=True)


def _download(url: str, dest: Path, desc: str):
    if dest.exists() and dest.stat().st_size > 0:
        _log(f"✓ {desc} 已存在，跳过下载（{dest.stat().st_size/1024/1024:.1f} MB）")
        return
    _log(f"↓ 正在下载 {desc} …")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:                                    # noqa: BLE001
        raise RuntimeError(
            f"下载失败：{url}\n{e}\n\n"
            f"如果是网络问题，可以手动下载后放到：{dest}"
        ) from e
    _log(f"✓ {desc} 下载完成（{dest.stat().st_size/1024/1024:.1f} MB）")


def _enable_site_packages(py_dir: Path):
    """嵌入式 Python 默认禁用 site-packages 且屏蔽当前目录，必须改 ._pth 打开。

    这一步是整个打包最容易踩坑的地方，有两个独立的坑：

    坑 1：不加 `import site` + `Lib\\site-packages`
          → pip 装的包一个都 import 不到

    坑 2：不加 `..`
          → `python -m core.sample_data` 报 ModuleNotFoundError
          因为 ._pth 存在时会进入 isolated 模式，当前目录不在 sys.path，
          而且 PYTHONPATH 环境变量会被【完全忽略】，只能靠 ._pth 解决。

    注意 ._pth 里的相对路径是相对【python.exe 所在目录】解析的，
    所以项目根目录（python/ 的上一级）要写成 `..`。
    """
    pth_files = list(py_dir.glob("python*._pth"))
    if not pth_files:
        raise RuntimeError(f"在 {py_dir} 找不到 ._pth 文件，嵌入式包可能不完整")
    pth = pth_files[0]

    lines = []
    for line in pth.read_text(encoding="utf-8").splitlines():
        if line.strip() in ("#import site", "# import site"):
            lines.append("import site")
        else:
            lines.append(line)

    joined = "\n".join(lines)
    if "import site" not in joined:
        lines.append("import site")
    if "Lib\\site-packages" not in joined:
        lines.append("Lib\\site-packages")
    # 项目根目录（python.exe 的上一级）—— 让 core / app / tools 能被 import
    if not any(l.strip() == ".." for l in lines):
        lines.insert(0, "..")

    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"✓ 已启用 site-packages 并把项目根目录加入 sys.path（{pth.name}）")


def _install_pip(py_exe: Path, cache: Path):
    _log("→ 正在安装 pip …")
    get_pip = cache / "get-pip.py"
    _download(GET_PIP_URL, get_pip, "get-pip.py")
    r = subprocess.run([str(py_exe), str(get_pip), "--no-warn-script-location"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"pip 安装失败：\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    _log("✓ pip 安装完成")


def _install_deps(py_exe: Path):
    _log("→ 正在安装依赖包（这一步最慢，约 2~5 分钟）…")
    req = ROOT / "requirements.txt"
    r = subprocess.run(
        [str(py_exe), "-m", "pip", "install", "-r", str(req),
         "--no-warn-script-location", "--no-cache-dir"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"依赖安装失败：\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    _log("✓ 依赖安装完成")


def _slim(py_dir: Path):
    """删掉用不到的东西，减小体积。保守删除，只删确定不影响运行的。"""
    before = sum(f.stat().st_size for f in py_dir.rglob("*") if f.is_file())
    sp = py_dir / "Lib" / "site-packages"
    removed = 0

    # 测试目录、缓存、类型存根
    patterns = ["**/tests", "**/test", "**/__pycache__", "**/*.dist-info/RECORD"]
    for pat in patterns:
        for p in sp.glob(pat):
            if p.is_dir():
                try:
                    sz = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    removed += sz
                except OSError:
                    pass

    # pip 自己也不需要留（用户不会在便携版里装包）
    for name in ("pip", "setuptools", "wheel", "pkg_resources"):
        for p in sp.glob(f"{name}*"):
            try:
                if p.is_dir():
                    sz = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    removed += sz
            except OSError:
                pass

    after = sum(f.stat().st_size for f in py_dir.rglob("*") if f.is_file())
    _log(f"✓ 精简完成：{before/1024/1024:.0f} MB → {after/1024/1024:.0f} MB "
         f"（省了 {removed/1024/1024:.0f} MB）")


def _write_launcher(out: Path):
    """写便携版的启动脚本。关键是所有路径都用相对路径。"""
    launcher = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"

title 媒介数据分析工具箱

echo ================================================================
echo    媒介数据分析工具箱  (便携版 - 无需安装 Python)
echo ================================================================
echo.

set PYEXE=python\python.exe

if not exist "%PYEXE%" (
    echo [错误] 找不到 python\python.exe
    echo.
    echo 可能原因：
    echo   1. 文件夹没有【完整】拷贝，缺了 python 目录
    echo   2. 从压缩包里直接双击运行了 —— 请先【完整解压】再运行
    echo.
    pause
    exit /b 1
)

REM ---- 首次运行：生成样例数据和 Excel 模板 ----
if not exist "data\sample\样例_投放明细.xlsx" (
    echo [首次运行] 正在生成样例数据...
    "%PYEXE%" -m core.sample_data
    echo.
)

if not exist "output\excel模板\1_GRP预算测算模板.xlsx" (
    echo [首次运行] 正在生成 Excel 模板...
    "%PYEXE%" -m tools.build_excel
    echo.
)

echo 正在启动，浏览器会自动打开...
echo.
echo   地址：http://localhost:8501
echo   关闭这个黑窗口 = 关闭工具
echo.
echo   Excel 模板在 output\excel模板\ 目录，可单独使用、也可发给同事
echo.
echo ================================================================
echo.

"%PYEXE%" -m streamlit run "app\主页.py"

echo.
echo 工具已关闭。
pause
"""
    (out / "启动.bat").write_text(launcher, encoding="utf-8")

    excel_only = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 生成 Excel 模板

echo ================================================================
echo    生成 Excel 模板（生成后可脱离本工具单独使用）
echo ================================================================
echo.

set PYEXE=python\python.exe
if not exist "%PYEXE%" (
    echo [错误] 找不到 python\python.exe，请确认文件夹完整解压。
    pause
    exit /b 1
)

"%PYEXE%" -m tools.build_excel
if errorlevel 1 (
    echo.
    echo [错误] 生成失败。
    pause
    exit /b 1
)

echo.
echo 完成。正在打开输出目录...
start "" "output\excel模板"
timeout /t 3 >nul
"""
    (out / "生成Excel模板.bat").write_text(excel_only, encoding="utf-8")

    selftest = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 自检

echo ================================================================
echo    便携版自检 —— 换电脑后先跑这个
echo ================================================================
echo.

set PYEXE=python\python.exe
if not exist "%PYEXE%" (
    echo [X] 找不到 python\python.exe  —— 文件夹不完整
    pause
    exit /b 1
)
echo [OK] Python 存在

"%PYEXE%" -c "import sys; print('[OK] Python', sys.version.split()[0])"
if errorlevel 1 ( echo [X] Python 无法运行 & pause & exit /b 1 )

"%PYEXE%" -c "import streamlit, pandas, numpy, plotly, yaml, xlsxwriter, openpyxl; print('[OK] 全部依赖包正常')"
if errorlevel 1 ( echo [X] 依赖包缺失 & pause & exit /b 1 )

"%PYEXE%" -c "import sys; sys.path.insert(0,'.'); from core.metrics import reach_from_grp; r=reach_from_grp(180,62,0.16); print(f'[OK] 计算内核正常 (GRP180 -> 到达率 {r:.2f}%%)')"
if errorlevel 1 ( echo [X] 计算内核异常 & pause & exit /b 1 )

echo.
echo ================================================================
echo    自检全部通过，可以双击「启动.bat」使用
echo ================================================================
pause
"""
    (out / "自检.bat").write_text(selftest, encoding="utf-8")
    _log("✓ 已写入 启动.bat / 生成Excel模板.bat / 自检.bat")


def _write_readme(out: Path):
    txt = """# 媒介数据分析工具箱（便携版）

## 怎么用

1. 把【整个文件夹】拷到公司电脑上（U 盘、个人网盘都行）
   ⚠️ 如果是压缩包，一定要【先完整解压】再用，不能在压缩包里直接双击

2. 双击 `自检.bat` —— 确认换了电脑之后一切正常（10 秒）

3. 双击 `启动.bat` —— 浏览器自动打开，开始用

关闭那个黑窗口就是关闭工具。

## 它不需要什么

- ❌ 不需要装 Python
- ❌ 不需要管理员权限
- ❌ 不写注册表、不改系统环境变量
- ❌ 不需要联网（除了第一次生成样例数据，其实也不用）

整个工具就是这一个文件夹，删掉文件夹 = 卸载干净，不留任何痕迹。

## 放哪里

建议放在你的个人目录下，例如：
    D:\\我的文档\\媒介分析工具箱_便携版\\

不要放在 C:\\Program Files\\（那里通常需要管理员权限才能写文件）。

## 如果公司连 U 盘都禁用

那就只用 `output\\excel模板\\` 里的 5 个 Excel 文件 —— 它们不需要 Python，
可以通过邮件或企业网盘传输，双击就能用。
详见 `docs/04_没有Python环境怎么办.md`。

## 数据安全

⚠️ 这个工具**完全在你本机运行**，不联网、不上传任何数据。
但请注意：**不要把装了客户数据的成品文件夹传到公网网盘**。
客户的投放数据、折扣、CPRP 都是商业机密。

## 遇到问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 双击没反应 | 在压缩包里直接运行了 | 先完整解压到硬盘 |
| 提示找不到 python.exe | 文件夹没拷全 | 重新完整拷贝 |
| 浏览器没自动打开 | 默认浏览器设置问题 | 手动打开 http://localhost:8501 |
| 提示端口被占用 | 8501 被别的程序占了 | 关掉黑窗口，重新双击启动 |
| 杀毒软件报警 | 对 python.exe 的误报 | 把整个文件夹加入白名单 |
"""
    (out / "使用说明.txt").write_text(txt, encoding="utf-8")


def build(out_dir: Path | None = None, slim: bool = True) -> Path:
    out = (out_dir or DIST) / APP_NAME
    cache = BUILD / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*66}")
    print("  打包绿色便携版")
    print(f"{'='*66}\n")

    # --- 1. 清理旧的 ---
    if out.exists():
        _log("→ 清理上次的成品 …")
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    # --- 2. 下载并解压嵌入式 Python ---
    print("\n[1/6] 准备 Python 运行时")
    py_zip = cache / f"python-{PY_VERSION}-embed-amd64.zip"
    _download(PY_URL, py_zip, f"Python {PY_VERSION} 嵌入式版")

    py_dir = out / "python"
    py_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(py_zip) as z:
        z.extractall(py_dir)
    _log(f"✓ 已解压到 {py_dir.name}/")

    _enable_site_packages(py_dir)
    py_exe = py_dir / "python.exe"

    # --- 3. 装 pip 和依赖 ---
    print("\n[2/6] 安装 pip")
    _install_pip(py_exe, cache)

    print("\n[3/6] 安装依赖包")
    _install_deps(py_exe)

    # --- 4. 拷项目文件 ---
    print("\n[4/6] 拷贝项目文件")
    for item in COPY_ITEMS:
        src = ROOT / item
        if not src.exists():
            _log(f"⚠ 跳过不存在的 {item}")
            continue
        dst = out / item
        if src.is_dir():
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*"))
        else:
            shutil.copy2(src, dst)
        _log(f"✓ {item}")

    (out / "data" / "sample").mkdir(parents=True, exist_ok=True)
    (out / "output").mkdir(parents=True, exist_ok=True)

    # --- 5. 写启动脚本和说明 ---
    print("\n[5/6] 生成启动脚本")
    _write_launcher(out)
    _write_readme(out)

    # --- 6. 精简 ---
    print("\n[6/6] 精简体积")
    if slim:
        _slim(py_dir)
    else:
        _log("（跳过精简）")

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    n_files = sum(1 for f in out.rglob("*") if f.is_file())

    print(f"\n{'='*66}")
    print(f"  ✅ 打包完成")
    print(f"{'='*66}")
    print(f"\n  位置：{out}")
    print(f"  体积：{total/1024/1024:.0f} MB（{n_files:,} 个文件）")
    print(f"\n  下一步：")
    print(f"    1. 跑一下 python tests/test_portable.py 验证成品能用")
    print(f"    2. 把整个「{APP_NAME}」文件夹拷到 U 盘")
    print(f"    3. 在公司电脑上先双击「自检.bat」，再双击「启动.bat」")
    print()
    return out


if __name__ == "__main__":
    slim = "--no-slim" not in sys.argv
    try:
        build(slim=slim)
    except Exception as e:                                    # noqa: BLE001
        print(f"\n❌ 打包失败：{e}\n")
        sys.exit(1)
