@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title 小6智能体 - 打包给朋友

echo ========================================
echo  打包一个「干净版」发给朋友
echo ========================================
echo.
echo  说明：直接压缩整个项目文件夹，会把下面这些一起发出去 ——
echo    data\config.json   你的 API Key、邮箱授权码、企微 Webhook
echo    data\chats.db      你和它的全部聊天记录
echo    data\memory.json   它的长期记忆
echo    data\users\ data\logs\ data\backup_*\
echo  本脚本只带程序本体和人格设定，不带任何隐私。
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

echo  请选择打包方式：
echo.
echo    [1] 标准版（推荐）  约 15 MB   聊天/记忆/插件/更新都能用
echo    [2] 含语音版        约 1 GB    额外带语音识别和看图
echo.
set /p choice="  输入 1 或 2 后回车: "

if "%choice%"=="2" (
    echo.
    echo  正在打包「含语音版」，文件很多，请耐心等...
    %PYCMD% tools\make_share_zip.py --with-voice
) else (
    echo.
    echo  正在打包「标准版」...
    %PYCMD% tools\make_share_zip.py --yes
)

if errorlevel 1 (
    echo.
    echo  [X] 打包失败，或安全检查发现问题（上面有说明）。
    pause
    exit /b 1
)

echo.
echo  打包完成，zip 已生成在项目文件夹的**上一级目录**（E:\ 下）。
echo  包里附了「使用说明-朋友版.txt」，让朋友直接看那个。
echo.
pause
