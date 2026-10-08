@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
title 小6智能体 - 安装可选功能组件

echo ========================================
echo  安装可选功能组件到 optional_libs\
echo ========================================
echo.
echo  说明：这些是语音识别、看图、浏览器自动化等可选功能，
echo        不装也能正常聊天，只是对应功能点不开。
echo        装到项目的 optional_libs\ 里，不会污染系统 Python。
echo.

rem ---- 解析可用的 Python ----
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo  [X] 没找到 Python，请先运行 install.bat
    pause
    exit /b 1
)

if not exist "optional_libs" mkdir optional_libs

echo  使用解释器: %PYCMD%
%PYCMD% --version
echo.
echo  正在安装（走清华镜像，首次可能要几分钟）...
echo.

%PYCMD% -m pip install --upgrade --target optional_libs ^
    -i https://pypi.tuna.tsinghua.edu.cn/simple ^
    -r requirements-optional.txt

if errorlevel 1 (
    echo.
    echo  [X] 安装失败，请检查网络后重试。
    echo      也可以打开程序里的「功能扩展组件」窗口逐个安装。
    pause
    exit /b 1
)

echo.
echo  ========================================
echo   安装完成
echo  ========================================
echo.
echo  浏览器自动化还需要再跑一次：
echo    %PYCMD% -m playwright install chromium
echo.
pause
