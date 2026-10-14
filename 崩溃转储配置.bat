@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能体 - 崩溃转储（排查用）

echo ========================================
echo  崩溃转储配置（排查崩溃用）
echo ========================================
echo.
echo  什么时候需要这个：
echo    小6 崩了 / 卡死了，而 data\logs\faulthandler.log 里的
echo    Python 栈看不出问题（崩在 DLL 里面）。
echo    那就要拿**进程级 dump** 才能定位。
echo.
echo  平时不用配 —— 只在真出问题时才需要。
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
    echo  [X] 没找到 Python
    pause
    exit /b 1
)

echo  先看现状：
echo.
%PYCMD% tools\setup_crash_dumps.py --status

echo.
echo ========================================
echo  想做什么？
echo ========================================
echo.
echo   [1] 下载 procdump（不用管理员，推荐先试这个）
echo   [2] 配 WER 本地转储（要管理员，配一次长期有效）
echo   [3] 撤掉 WER 配置
echo   [4] 打印"盯着启动小6"的命令
echo   [0] 什么都不做
echo.
set /p choice="  输入数字后回车: "

if "%choice%"=="1" (
    %PYCMD% tools\setup_crash_dumps.py --procdump
)
if "%choice%"=="2" (
    echo.
    echo  注意：这一步要写系统注册表，**必须以管理员身份运行本脚本**。
    echo  如果不是管理员，脚本会告诉你怎么办。
    echo.
    %PYCMD% tools\setup_crash_dumps.py --wer
)
if "%choice%"=="3" (
    %PYCMD% tools\setup_crash_dumps.py --disable
)
if "%choice%"=="4" (
    %PYCMD% tools\setup_crash_dumps.py --watch
)

echo.
echo ========================================
echo  下一步
echo ========================================
echo.
echo  配好之后：
echo    1. 跑第 [4] 项打印的命令（会开一个窗口在那儿等）
echo    2. **然后**再启动小6
echo    3. 崩了之后 dump 会出现在 data\dumps\
echo    4. 用 WinDbg 打开 .dmp，命令：!analyze -v
echo.
echo  ⚠️ dump 里有进程内存 —— 可能含聊天记录和 API Key。
echo     发给别人之前想清楚。
echo.
pause
