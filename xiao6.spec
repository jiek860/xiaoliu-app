# -*- mode: python ; coding: utf-8 -*-
# pyinstaller spec - 小6智能体打包配置

block_cipher = None

from PyInstaller.building.datastruct import Tree

# 可选的真终端后端：装了 pywinpty 才打包（没装时 gui/ide_terminal.py 自动回退管道）。
# 依赖在 requirements-optional.txt，构建环境（.build-venv）默认没装，
# 所以这里必须 try，不能让打包因为可选依赖直接失败。
_pty_hidden = []
_pty_datas = []
try:
    import winpty  # noqa: F401
    _pty_hidden = ['winpty', 'winpty._winpty', 'winpty.enums',
                   'winpty.ptyprocess']
    from PyInstaller.utils.hooks import collect_data_files as _collect
    _pty_datas = _collect('winpty', includes=['*.dll', '*.exe'])
except Exception:
    pass


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app.ico', '.'),
        # 只打包脱敏模板；data/config.json 里有 API Key / 邮箱授权码，绝不打进发布包。
        # 首次运行时 Trunk._load_config() 会自动用它生成 data/config.json。
        ('config.default.json', '.'),
        # 程序端只需公钥（私钥在 E:\xiao6-keys，不打包）
        ('core/公钥.pem', 'core'),
        ('core/激活公钥.pem', 'core'),
    ],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'cryptography',
        'requests',
        'numpy',
        # 电脑控制 / 窗口操作（2026-10-27 起 exe 也保留这些功能，见 docs/20 批次 26）：
        # pywin32 的动态导入 PyInstaller 扫不到，必须显式列出来
        'win32gui',
        'win32api',
        'win32con',
        'win32process',
        'win32timezone',
        'win32com',
        'win32com.client',
    ] + _pty_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        # ⚠️ 2026-10-27 移出：PIL 曾被排除给包瘦身，但截图（computer_system_tools）、
        # 图像对比（computer_verifier）、目标框标注、图片 OCR 都在用它 —— 排掉之后
        # 打包版的"电脑控制"整条链路是废的，且图像对比会把异常吞成"没变化"。
        # 这条由 tools/check_runtime_imports.py 兜底，防止再被误删。
        'scipy',
        'pandas',
        # Keep only the Qt families the desktop UI actually imports.
        'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebEngine', 'PyQt5.QtQml', 'PyQt5.QtQuick',
        'PyQt5.QtSql', 'PyQt5.QtTest', 'PyQt5.QtXml',
        'PyQt5.QtDesigner', 'PyQt5.QtHelp', 'PyQt5.QtBluetooth',
        'PyQt5.QtNfc', 'PyQt5.QtPositioning', 'PyQt5.QtSerialPort',
        'PyQt5.QtSensors', 'PyQt5.QtWebSockets', 'PyQt5.QtOpenGL',
        'PyQt5.QtPrintSupport', 'PyQt5.QtSvg',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 目录用 Tree 追加到 a.datas，便于排除 .git / __pycache__ / .pyc。
# 这些源文件是插件市场和热加载需要的数据，不是 Python import 依赖。
a.datas += Tree('modules/installed', prefix='modules/installed',
                excludes=['__pycache__', '*.pyc', '*.pyo'])
a.datas += Tree('modules_repo', prefix='modules_repo',
                excludes=['.git', '.githooks', '__pycache__', '*.pyc', '*.pyo'])
# GUI/core Python modules are already embedded in the PYZ. Only the one
# source file that plugin uninstall edits at runtime is shipped as data.
a.datas.append(('core/lazy_config.py', 'core/lazy_config.py', 'DATA'))

# uiautomation（电脑控制的"控件级操作"）用 ctypes 在运行时才去加载
# uiautomation/bin/UIAutomationClient_VC140_*.dll，PyInstaller 静态分析看不到。
# 少了这两个 dll，exe 里 ui_windows/ui_click 一律报"没装 uiautomation"。
from PyInstaller.utils.hooks import collect_data_files
import os as _os
# ⚠️ collect_data_files 返回的是 2 元组 (源文件, 目标目录)，而 a.datas 的 TOC
# 是 3 元组 (目标路径, 源文件, 类型)，**顺序相反且目标要带文件名**。
# 顺序搞反时 PyInstaller 不报错，只在日志里写
# "Ignoring non-existent resource uiautomation\bin"，dll 静默丢失
# （2026-10-28 实测踩到：COLLECT 报 2 元组解包失败 → 改成 3 元组但顺序错了）。
a.datas += [(_os.path.join(d[1], _os.path.basename(d[0])), d[0], 'DATA')
            for d in collect_data_files('uiautomation', includes=['bin/*.dll'])]

# 可选 PTY 后端的运行时文件（winpty.dll / conpty.dll / OpenConsole.exe …）
a.datas += [(_os.path.join(d[1], _os.path.basename(d[0])), d[0], 'DATA')
            for d in _pty_datas]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='小6智能体',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='小6智能体',
)
