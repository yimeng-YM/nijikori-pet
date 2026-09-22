# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

PROJECT = Path(SPECPATH).resolve().parent
SOURCE = PROJECT / "src"
RESOURCES = PROJECT / "resources"

a = Analysis(
    [str(SOURCE / 'main.py')],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=[
        (str(RESOURCES / 'assets'), 'assets'),
        (str(SOURCE / 'pet_tools'), 'pet_tools'),
        (str(SOURCE / 'pet_plugins'), 'pet_plugins'),
        (str(RESOURCES / 'plugins'), 'plugins'),
        (str(RESOURCES / 'prompt.txt'), '.'),
        (str(RESOURCES / 'skills/配置文件管理'), 'skills/配置文件管理'),
        (str(RESOURCES / 'skills/项目接手法'), 'skills/项目接手法'),
        (str(RESOURCES / 'skills/agent-reach'), 'skills/agent-reach'),
        (str(RESOURCES / 'skills/harness委托流程'), 'skills/harness委托流程'),
        (str(RESOURCES / 'skills/web-access'), 'skills/web-access'),
        (str(RESOURCES / 'skills/代码编辑流程手册'), 'skills/代码编辑流程手册'),
        (str(RESOURCES / 'skills/computer-use'), 'skills/computer-use'),
        (str(RESOURCES / 'skills/插件开发指南'), 'skills/插件开发指南'),
    ],
    hiddenimports=['pystray._win32', 'window_capture'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='虹语织-桌宠v2',
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
    icon=[str(RESOURCES / 'assets/icon.ico')],
)
