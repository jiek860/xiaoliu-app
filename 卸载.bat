@echo off
chcp 65001 >nul
title 小6智能助手 - 卸载
echo ================================
echo   小6智能助手 卸载程序
echo ================================
echo.
echo 将删除：
echo   - 本程序所在文件夹
echo   - data\ 里的聊天记录、配置、记忆
echo.
set /p sure="确定卸载吗？输入 Y 继续，其他键取消: "
if /i not "%sure%"=="Y" (
    echo 已取消。
    pause
    exit /b
)
echo.
echo 正在退出程序...
taskkill /f /im 小6智能助手.exe 2>nul
timeout /t 2 /nobreak >nul
echo 正在删除文件...
cd /d "%~dp0.."
rmdir /s /q "%~dp0" 2>nul
echo 完成。
pause
