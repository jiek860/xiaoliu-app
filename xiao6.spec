# -*- mode: python ; coding: utf-8 -*-
# pyinstaller spec - 小6智能体打包配置

block_cipher = None

from PyInstaller.building.datastruct import Tree


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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'scipy',
        'pandas',
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
a.datas += Tree('gui', prefix='gui',
                excludes=['__pycache__', '*.pyc', '*.pyo'])
a.datas += Tree('core', prefix='core',
                excludes=['__pycache__', '*.pyc', '*.pyo'])

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
