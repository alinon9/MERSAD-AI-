# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for MERSAD AI (--onedir distribution for Windows x64)."""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("dashboard.html", "."),
    ("README_AR.md", "."),
]
binaries = []
hiddenimports = [
    "registry",
    "insights",
    "analytics",
    "camera_history",
    "notify",
    "server",
    "check_install",
    "prefetch",
    "openpyxl",
]

import os as _os
_os.environ["YOLO_OFFLINE"] = "true"
_os.environ["ULTRALYTICS_AUTOINSTALL"] = "false"

_EXCLUDED_SUBMODULES = (
    "ultralytics.trackers",
    "torch.utils.tensorboard",
    "scipy.special._cdflib",
)

for pkg in ("easyocr", "ultralytics"):
    try:
        tmp_ret = collect_all(pkg)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += [
            m for m in tmp_ret[2]
            if not any(m == ex or m.startswith(ex + ".") for ex in _EXCLUDED_SUBMODULES)
        ]
    except Exception:
        pass

try:
    hiddenimports += collect_submodules("sklearn")
except Exception:
    pass

a = Analysis(
    ["mersad_live.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["opencv-python-headless", "ultralytics.trackers", "torch.utils.tensorboard", "scipy.special._cdflib", "tensorboard", "lap", "lapx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MERSAD_AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MERSAD_AI",
)
