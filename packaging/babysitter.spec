# -*- mode: python ; coding: utf-8 -*-
"""Build one windowed BabySitter.exe. No console window.

The result is dist/BabySitter.exe. That file can move to the desktop.
It does not need a folder of DLLs beside it.

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
        (str(ROOT / "assets" / "hero.jpg"), "assets"),
        (str(ROOT / "assets" / "fonts"), "assets/fonts"),
        (str(ROOT / "assets" / "orb"), "assets/orb"),
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

# One file. Copy dist/BabySitter.exe to the desktop or any other folder.
# The pictures are inside the file. Settings stay in %LOCALAPPDATA%\BabySitter.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
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
