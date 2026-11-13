# -*- mode: python ; coding: utf-8 -*-
"""Build a windowed BabySitter.exe. No console window.

Run this on Windows, from the repo root:

    py -3.12 -m PyInstaller packaging/babysitter.spec --noconfirm
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
VERSION = (ROOT / "src" / "babysitter" / "version.py").read_text(encoding="utf-8")
APP_VERSION = "0.1.0"
for line in VERSION.splitlines():
    if line.startswith("__version__"):
        APP_VERSION = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

block_cipher = None

a = Analysis(
    [str(ROOT / "src" / "babysitter" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
    ],
    hiddenimports=[
        "babysitter",
        "babysitter.app",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BabySitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed: no command prompt
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(ROOT / "assets" / "icon.ico"),
    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BabySitter",
)
