@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能体 - 同步打包目录

echo ========================================
echo  同步打包目录（开发目录 -^> 打包源）
echo ========================================
echo.
echo  把 E:\xiaoliu 里"程序运行需要的东西"复制到 E:\xiao6-package
echo  **每次改完代码，打包前都要先跑一次这个**，
echo  否则会把旧代码打进安装包（装出来照样能跑，只是行为是旧的，
echo  很难发现）。
echo.
echo  不会复制：data\ backups\ optional_libs\ tests\ tools\ .git\
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

echo  先看一眼要改什么（不动文件）：
echo.
%PYCMD% tools\sync_package.py --dry-run

echo.
set /p go="  确认同步吗？(y/N): "
if /i not "%go%"=="y" (
    echo.
    echo  已取消，什么都没改。
    pause
    exit /b 0
)

echo.
%PYCMD% tools\sync_package.py
if errorlevel 1 (
    echo.
    echo  [X] 同步失败或安全检查没过（上面有说明），**先别打包**。
    pause
    exit /b 1
)

echo.
echo ========================================
echo  同步完成
echo ========================================
echo.
echo  下一步：
echo    1. 双击 C:\Users\tt\Desktop\小工具\加固打包\加固打包.exe
echo       选 E:\xiao6-package\run.py 编译成 exe
echo    2. 双击 安装包生成器.exe
echo       第 (5) 项文件夹选 E:\xiao6-package
echo.
pause
