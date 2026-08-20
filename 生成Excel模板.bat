@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   生成 Excel 模板
echo ================================================
echo.
echo   会在 output\excel模板\ 下生成 5 个文件：
echo     1_GRP预算测算模板.xlsx        GRP/到达率/频次一体测算 + 响应曲线图
echo     2_跨媒体组合与边际分析.xlsx    多频道去重 + 追加预算加哪里
echo     3_数据质检清单.xlsx           粘数据自动标红 + 交付自查
echo     4_媒介指标速查卡_可打印.xlsx   A4 单页，打印贴工位
echo     5_周报模板.xlsx               填数字自动出环比/KPI/结论草稿
echo.
echo   这些文件【不需要 Python】，可以单独用、也可以发给客户和同事。
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 没有找到 Python，无法生成模板。
    pause
    exit /b 1
)

python -c "import xlsxwriter, yaml, numpy" >nul 2>&1
if errorlevel 1 (
    echo [提示] 缺少依赖，正在安装...
    python -m pip install -r requirements.txt
    echo.
)

python -m tools.build_excel
if errorlevel 1 (
    echo.
    echo [错误] 生成失败。
    pause
    exit /b 1
)

echo.
echo ================================================
echo   完成。正在打开输出目录...
echo ================================================
start "" "output\excel模板"
timeout /t 3 >nul
