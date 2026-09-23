# -*- mode: python ; coding: utf-8 -*-


import shutil
from pathlib import Path

PROJECT = Path(SPECPATH).resolve().parent
SOURCE = PROJECT / "src"
RESOURCES = PROJECT / "resources"

# Skills are staged before bundling so that local runtime files never ship inside
# the EXE: config.env is a per-machine preference recreated from templates/ on
# first run, and caches/logs are build noise.
STAGE = PROJECT / "tools" / ".build" / "_stage"
SKIP_IN_SKILLS = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo",
                                        "config.env", "*.log", "*.tmp")


def stage_skill(src):
    dst = STAGE / "skills" / src.name
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=SKIP_IN_SKILLS)
    return dst


datas = [
    (str(RESOURCES / 'assets'), 'assets'),
    (str(SOURCE / 'pet_tools'), 'pet_tools'),
    (str(SOURCE / 'pet_plugins'), 'pet_plugins'),
    (str(RESOURCES / 'plugins'), 'plugins'),
    (str(RESOURCES / 'prompt.txt'), '.'),
]
for _skill in sorted((RESOURCES / 'skills').iterdir()):
    if _skill.is_dir():
        datas.append((str(stage_skill(_skill)), 'skills/' + _skill.name))

a = Analysis(
    [str(SOURCE / 'main.py')],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=datas,
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
    name='虹语织-桌宠v3',
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
