@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   媒介数据分析工具箱
echo ================================================
echo.

REM ---- 检查 Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python。
    echo 请先安装 Python 3.10 以上版本：https://www.python.org/downloads/
    echo 安装时记得勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

REM ---- 检查依赖 ----
python -c "import streamlit, pandas, plotly, yaml, xlsxwriter, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [提示] 缺少依赖包，正在安装...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。请手动运行：
        echo    python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo.
    echo [完成] 依赖安装完毕。
    echo.
)

REM ---- 生成样例数据（如果还没有） ----
if not exist "data\sample\样例_投放明细.xlsx" (
    echo [提示] 正在生成样例数据...
    python -m core.sample_data
    echo.
)

REM ---- 生成 Excel 模板（如果还没有） ----
if not exist "output\excel模板\1_GRP预算测算模板.xlsx" (
    echo [提示] 正在生成 Excel 模板...
    python -m tools.build_excel
    echo.
)

echo 正在启动... 浏览器会自动打开 http://localhost:8501
echo.
echo   关闭这个黑窗口 = 关闭工具
echo   Excel 模板在 output\excel模板\ 目录，可以单独用、也可以发给别人
echo.
echo ================================================
echo.

python -m streamlit run "app\主页.py"

pause
