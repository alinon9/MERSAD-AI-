# -*- mode: python ; coding: utf-8 -*-
"""Dedicated PyInstaller spec for the native MERSAD Windows desktop shell.

Keep desktop-only WebView2/pythonnet imports isolated from mersad_ai.spec.
The legacy AI build parity audit intentionally compares only the AI engine's
hidden-import inventory against BUILD_EXE.bat.
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = [
    "clr",
    "clr_loader",
    "pythonnet",
    "webview.platforms.edgechromium",
]

for package in ("webview", "pythonnet", "clr_loader"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    ["desktop_shell.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MERSAD_Desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="MERSAD_Desktop.ico",
    version="desktop_version_info.txt",
)
