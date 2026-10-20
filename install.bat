@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 小6智能体 - 安装依赖
echo.
echo  ========================================
echo   小6智能体  一键安装依赖
echo  ========================================
echo.
echo  [1/4] 正在检测 Python...

rem ---- 解析受支持的 Python ----
rem 优先精确选择 3.12 / 3.11 / 3.10，避免 py -3 默认选到尚未验证的 3.13。
set "PYCMD="
for %%V in (3.12 3.11 3.10) do (
    if not defined PYCMD (
        py -%%V --version >nul 2>&1
        if not errorlevel 1 set "PYCMD=py -%%V"
    )
)
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo.
    echo  [X] 没找到 Python。
    echo.
    echo  支持 Python 3.10 / 3.11 / 3.12（推荐 3.12）。
    echo  Python 3.13 尚未验证，Python 3.9 及以下不支持。
    echo  下载地址：https://www.python.org/downloads/
    echo  安装时务必勾选 "Add Python to PATH"。
    echo.
    echo  如果已经装过，可能是被 Microsoft Store 的占位程序挡住了，
    echo  可在「设置 -> 应用 -> 高级应用设置 -> 应用执行别名」里关掉 python.exe。
    echo.
    pause
    exit /b 1
)

%PYCMD% --version
%PYCMD% -c "import sys; v=sys.version_info[:2]; sys.exit(0 if v in [(3,10),(3,11),(3,12)] else 1)"
if errorlevel 1 (
    echo.
    echo  [X] 当前 Python 版本不在支持范围。
    echo      支持：3.10 / 3.11 / 3.12；3.13 尚未验证。
    echo      请安装受支持版本后重试。
    echo.
    pause
    exit /b 1
)
echo  [OK] Python 版本受支持
echo.

echo  [2/4] 正在升级 pip...
%PYCMD% -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
echo  [OK] pip 已更新
echo.

echo  [3/4] 正在安装核心依赖（走清华镜像，速度快）...
echo.
%PYCMD% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo.
    echo  [X] 安装失败，请检查网络后重试。
    echo.
    pause
    exit /b 1
)
echo.

echo  [4/4] 运行兼容性检查...
%PYCMD% tools\check_runtime_compat.py --allow-server
if errorlevel 1 (
    echo.
    echo  [X] 兼容性检查未通过，请先按上面的提示处理。
    echo.
    pause
    exit /b 1
)
echo.
echo  ========================================
echo   安装完成！
echo  ========================================
echo.
echo  现在可以双击 启动PyQt.bat 启动程序。
echo.
echo  可选：想用电脑控制/语音功能，再执行：
echo    %PYCMD% -m pip install -r requirements-optional.txt
echo.
pause
