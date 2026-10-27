@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能体 - 启动崩溃监视（procdump 常驻）

rem 后台常驻监视：不占窗口、关掉这个窗口也不影响。
rem 崩了会把进程级 dump 存到 data\dumps\，日志在 data\logs\procdump_watch.log。
rem 默认盯 小6智能体.exe；从源码跑：start_crash_watch.bat python.exe

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=小6智能体.exe"

echo ========================================
echo  启动崩溃监视（procdump）
echo ========================================
echo  目标进程: %TARGET%
echo  dump 目录: data\dumps\
echo  日志     : data\logs\procdump_watch.log
echo.

py -3 tools\setup_crash_dumps.py --watch-run --target "%TARGET%"

echo.
echo ========================================
echo  说明
echo ========================================
echo  1. 现在去启动小6 就行，procdump 已经在后台等着了
echo  2. 崩了之后 dump 在 data\dumps\，用 WinDbg 打开：!analyze -v
echo  3. 停掉监视：py -3 tools\setup_crash_dumps.py --stop-watch
echo.
echo  ⚠️ dump 是进程内存快照 —— 里面有聊天记录、记忆和 API Key，
echo     发给别人之前想清楚。
echo.
pause
