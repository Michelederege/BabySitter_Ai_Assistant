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


def _bundle(package: str, dest: str | None = None):
    """Libraries and data files a package opens by path.

    Empty when that package is not installed in the Python that builds the exe.
    PyInstaller follows an import and packs the Python. It does not pack a
    json file or a DLL that the package opens by path. Those have to be named.
    dest is the folder inside the exe. Leave it empty to keep the package's
    own folders. Vosk is the exception: it joins its own folder with
    libvosk.dll, so every Vosk library has to land in vosk/.
    """
    try:
        from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

        binaries = list(collect_dynamic_libs(package, destdir=dest))
        datas = list(collect_data_files(package))
        return binaries, datas
    except Exception:
        return [], []


# (package, destination folder or None to keep the package's own folders)
_PACKED = (
    ("vosk", "vosk"),
    ("sounddevice", None),
    ("_sounddevice_data", None),
    ("kokoro_onnx", None),
    ("espeakng_loader", None),
    ("phonemizer", None),
    ("onnxruntime", None),
    ("ctranslate2", None),
    ("faster_whisper", None),
    ("tokenizers", None),
    ("av", None),
)

_binaries = []
_datas = []
for _package, _dest in _PACKED:
    _found_binaries, _found_data = _bundle(_package, _dest)
    _binaries.extend(_found_binaries)
    _datas.extend(_found_data)
    print(f"Packing {_package}: {len(_found_binaries)} libraries, {len(_found_data)} data files")

a = Analysis(
    [str(ROOT / "src" / "babysitter" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=_binaries,
    datas=[
        (str(ROOT / "assets" / "icon.png"), "assets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
        (str(ROOT / "assets" / "hero.jpg"), "assets"),
        (str(ROOT / "assets" / "fonts"), "assets/fonts"),
        (str(ROOT / "assets" / "orb"), "assets/orb"),
        *_datas,
    ],
    hiddenimports=[
        "babysitter",
        "babysitter.app",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
        "vosk",
        "vosk.vosk_cffi",
        "sounddevice",
        "_sounddevice_data",
        "kokoro_onnx",
        "espeakng_loader",
        "phonemizer",
        "onnxruntime",
        "faster_whisper",
        "ctranslate2",
        "cffi",
        "_cffi_backend",
        "srt",
        "tqdm",
        "requests",
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
