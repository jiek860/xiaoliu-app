@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能助手
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs

rem ---- resolve python: 项目内 .venv 优先，其次 py 启动器（Store stub 返回 9009） ----
rem NOTE: use "if not errorlevel 1", not "%errorlevel%==0" -- the latter
rem is expanded at parse time inside blocks and gives a stale value.
set "PYCMD="
if exist ".venv\Scripts\python.exe" set "PYCMD=.venv\Scripts\python.exe"
if not defined PYCMD (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo.
    echo  [X] 没找到 Python。
    echo      请先安装 Python 3.10+ 并勾选 "Add Python to PATH"：
    echo      https://www.python.org/downloads/
    echo      装好后先双击 install.bat 安装依赖。
    echo.
    pause
    exit /b 1
)

%PYCMD% run.py
if errorlevel 1 pause
