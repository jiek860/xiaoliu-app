@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 小6智能体 - 安装依赖
echo.
echo  ========================================
echo   小6智能体 · 一键安装依赖
echo  ========================================
echo.
echo  [1/3] 正在检测Python...

rem ---- 解析可用的 Python ----
rem Windows 的 Microsoft Store 版 python.exe 是占位符，调用返回 9009，
rem 所以优先用官方安装自带的 py 启动器，其次才是 python。
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo.
    echo  [X] 没找到Python。
    echo.
    echo  请先去 https://www.python.org/downloads/ 下载安装Python 3.10+
    echo  安装时务必勾选 "Add Python to PATH"。
    echo.
    echo  如果已经装过，可能是被 Microsoft Store 的占位程序挡住了，
    echo  可在「设置 → 应用 → 高级应用设置 → 应用执行别名」里关掉 python.exe。
    echo.
    pause
    exit /b 1
)
%PYCMD% --version
echo  [OK] Python已就绪
echo.
echo  [2/3] 正在升级pip...
%PYCMD% -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
echo  [OK] pip已更新
echo.
echo  [3/3] 正在安装核心依赖（走清华镜像，速度快）...
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
echo  ========================================
echo   安装完成！
echo  ========================================
echo.
echo  现在可以双击 启动PyQt.bat 启动程序（或直接双击 gui\app_pyqt.py）。
echo.
echo  可选：想用电脑控制/语音功能，再执行：
echo    %PYCMD% -m pip install -r requirements-optional.txt
echo.
pause
