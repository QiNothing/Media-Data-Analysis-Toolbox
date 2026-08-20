@echo off
chcp 65001 >nul
cd /d "%~dp0"

title 打包绿色便携版

echo ================================================================
echo    打包绿色便携版（给没有 Python 的电脑用）
echo ================================================================
echo.
echo   产出一个【拷过去双击就能跑】的文件夹：
echo     - 不需要安装 Python
echo     - 不需要管理员权限
echo     - 不写注册表、不改环境变量
echo     - 删掉文件夹 = 卸载干净
echo.
echo   约 300 MB，U 盘和个人网盘都放得下。
echo.
echo   ⚠️ 这台电脑需要联网（要下载 Python 运行时和依赖包）
echo   ⚠️ 第一次打包约 5~10 分钟，请耐心等
echo.
echo ================================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 这台电脑没有 Python，无法打包。
    echo        请在【有 Python 的电脑】上运行本脚本。
    pause
    exit /b 1
)

python -m tools.build_portable
if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请看上面的错误信息。
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   建议现在验证一下成品能不能独立运行：
echo.
echo      python tests/test_portable.py
echo.
echo   这个测试会清空所有 Python 环境变量再跑，
echo   模拟一台从没装过 Python 的电脑。
echo ================================================================
echo.

set /p RUNTEST="现在就验证吗？(Y/N): "
if /i "%RUNTEST%"=="Y" (
    echo.
    python tests/test_portable.py
    echo.
)

echo 正在打开输出目录...
start "" "dist"
pause
