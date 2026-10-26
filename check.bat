@echo off
chcp 65001 >nul
rem 让 Python 输出按 UTF-8 走，与上面的 chcp 65001 对齐，避免中文乱码
set PYTHONIOENCODING=utf-8
title 小6智能体 - 提交前自检
echo ================================
echo  小6智能体 · 一键自检
echo ================================
echo.

rem ---- 解析可用的 Python ----
rem 注意：Windows 的 Microsoft Store 版 python.exe 是个占位符，直接调用会返回 9009，
rem       所以优先用官方安装自带的 py 启动器，其次才是 python。
set "PYCMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo  [X] 没找到可用的 Python。
    echo      请安装 Python 3.10+ 并勾选 "Add Python to PATH"：
    echo      https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo  使用解释器: %PYCMD%
%PYCMD% --version
echo.

echo [1/14] 语法检查...
%PYCMD% -m compileall -q core gui modules modules_repo tools scripts
if errorlevel 1 (
    echo [X] 存在语法错误
    pause
    exit /b 1
)
echo [OK] 语法全部通过
echo.

echo [2/14] 提交前测试（硬编码路径 / 私钥外泄 / 懒加载登记 / 更新验签 / 结构假设）...
echo       结构假设那组守的是「共享数据结构变了、调用方没跟上」，
echo       要单独看详细报告可以跑：%PYCMD% tools\check_shapes.py -v
%PYCMD% -m pytest tests/ -q
if errorlevel 1 (
    echo.
    echo [X] 测试不通过，请按上面提示修复后再提交
    pause
    exit /b 1
)
echo.
echo [3/14] 密钥合规检查...
%PYCMD% -c "import os,sys;hit=[];hit+=[p for p in ['core/密钥.key','密钥.key'] if os.path.exists(p)];[hit.append(os.path.join(r,f)) for r,_,fs in os.walk('.') for f in fs if 'libs' not in r and '私钥' in f];print('[X] 不应留在程序目录:',hit) if hit else print('[OK] 无私钥 / 共享密钥');sys.exit(1 if hit else 0)"
if errorlevel 1 (
    echo [X] 私钥或共享密钥不应随程序分发
    pause
    exit /b 1
)
echo.

echo [4/14] 版本号一致性...
%PYCMD% tools\check_version.py
if errorlevel 1 (
    echo [X] 版本号不一致，按上面提示改（权威来源 core/version.py）
    pause
    exit /b 1
)
echo.

echo [5/14] 复杂度与冻结预算（按钮 / 工具提示词 / 冻结基线）...
%PYCMD% tools\check_buttons.py
if errorlevel 1 (
    echo [X] 按钮数超预算 —— 加按钮前先说明为什么「说一句」替代不了它
    pause
    exit /b 1
)
%PYCMD% tools\check_tools.py
if errorlevel 1 (
    echo [X] 工具提示词超预算 —— 给新能力声明 hints，别都塞进 LLM 提示词
    pause
    exit /b 1
)
%PYCMD% tools\check_feature_freeze.py
if errorlevel 1 (
    echo [X] 冻结期内新增了 Feature / 模块 / 按钮，或下调了覆盖率门槛
    pause
    exit /b 1
)
echo.

echo [6/14] 线程安全（后台线程不许碰 Qt 控件）...
%PYCMD% tools\check_threads.py
if errorlevel 1 (
    echo [X] 有子线程直接操作控件 —— 会随机崩，改成 emit 信号再在槽里更新
    pause
    exit /b 1
)
echo.

echo [7/14] 插件仓库一致性（modules_repo 会推到 gitee，用户端拉它装插件）...
%PYCMD% tools\check_repo_sync.py
if errorlevel 1 (
    echo [X] 插件仓库与主仓库不一致或没签名 —— 推出去用户会装到旧版、或装不上
    pause
    exit /b 1
)
echo.

echo [8/14] 懒加载模块编译与导入检查...
%PYCMD% tools\check_lazy_imports.py
if errorlevel 1 (
    echo [X] 有懒加载模块无法编译或导入，用户点击时才暴露会很难排查
    pause
    exit /b 1
)
echo.

echo [9/14] 静态检查（Ruff + Mypy）...
%PYCMD% tools\check_types.py
if errorlevel 1 (
    echo [X] 静态检查失败，先修复再发版
    pause
    exit /b 1
)
echo.

echo [10/14] Agent 端到端回归...
%PYCMD% tools\run_agent_e2e.py
if errorlevel 1 (
    echo [X] Agent E2E 失败
    pause
    exit /b 1
)
echo.

echo ================================
echo  全部检查通过，程序可以正常运行

echo [11/14] 文件长度守卫（防止上帝对象继续增长）...
%PYCMD% tools\check_file_sizes.py
if errorlevel 1 (
    echo [X] 有文件过长，请先拆分模块
    pause
    exit /b 1
)
echo.


echo [12/14] 插件公共 API 边界检查...
%PYCMD% tools\check_plugin_api.py
if errorlevel 1 (
    echo [X] 插件依赖了禁止的 core 私有实现，请改用公共 API
    pause
    exit /b 1
)
echo.

echo [13/14] 运行环境兼容性检查...
%PYCMD% tools\check_runtime_compat.py --allow-server
if errorlevel 1 (
    echo [X] 当前 Python 或 Windows 环境不在支持范围
    pause
    exit /b 1
)
echo.

echo [14/14] 数据迁移预演...
%PYCMD% tools\migrate_data.py --dry-run --json
if errorlevel 1 (
    echo [X] 数据迁移预演失败
    pause
    exit /b 1
)
echo.

echo ================================
pause
