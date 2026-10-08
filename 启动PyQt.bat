@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能助手
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs

rem ---- 解析可用的 Python ----
rem Windows 的 Microsoft Store 版 python.exe 是占位符，调用返回 9009，
rem 所以优先用官方安装自带的 py 启动器，其次才是 python。
rem 注意：这里用 "if not errorlevel 1" 而不是 "%errorlevel%==0"，
rem       后者写在括号块里会在解析期就展开，拿到的是过期的错误码。
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
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
