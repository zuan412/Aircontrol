# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Aircontrol Windows Standalone Portable Build.

Creates a high-performance, self-contained, zero-dependency release folder.
- Bundles Python bytecode (.pyc) without source code (.py).
- Bundles PySide6 GUI runtime, OpenGL/YUV shaders, and QtMultimedia audio.
- Bundles pymobiledevice3 data assets, plists, and pairing services.
- Bundles PyAV FFmpeg shared libraries (av.libs) and libfdk-aac-2.dll.
- Bundles pre-configured Apple simulator chassis skins.
"""

import os
import pathlib
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# 1. Collect all dynamic dependencies for complex packages
pmd_datas, pmd_binaries, pmd_hiddenimports = collect_all("pymobiledevice3")
av_datas, av_binaries, av_hiddenimports = collect_all("av")

# 2. Bundled application assets and skins
app_datas = [
    ("skins", "skins"),
    ("assets/aircontrol.ico", "assets"),
    ("aircontrol/bin/libfdk-aac-2.dll", "aircontrol/bin"),
    ("aircontrol/bin/libfdk-aac-2.dll", "."),
]

# 3. Explicit native C/C++ DLL binaries
project_dir = pathlib.Path.cwd()
extra_binaries = []

import av
site_packages_dir = pathlib.Path(av.__file__).parent.parent
av_libs_dir = site_packages_dir / "av.libs"
if av_libs_dir.exists():
    for dll in av_libs_dir.glob("*.dll"):
        extra_binaries.append((str(dll), "."))

fdk_dll = project_dir / "aircontrol" / "bin" / "libfdk-aac-2.dll"
if fdk_dll.exists():
    extra_binaries.append((str(fdk_dll), "."))
    extra_binaries.append((str(fdk_dll), "aircontrol/bin"))

all_datas = app_datas + pmd_datas + av_datas
all_binaries = pmd_binaries + av_binaries + extra_binaries
all_hiddenimports = list(set(
    pmd_hiddenimports
    + av_hiddenimports
    + [
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtNetwork",
        "numpy",
        "av",
        "pymobiledevice3",
        "construct",
        "cryptography",
    ]
))

a = Analysis(
    ["run_aircontrol.py"],
    pathex=["."],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pytest",
        "test",
        "tests",
        "IPython",
        "matplotlib",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aircontrol",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/aircontrol.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Aircontrol",
)
