# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

binaries = []
binaries += collect_dynamic_libs('cv2')
binaries += collect_dynamic_libs('numpy')

datas = [
    ('index.html', '.'),
    ('README_AR.md', '.'),
    ('PHASE1_STATUS_AR.md', '.'),
]

hiddenimports = [
    'cv2',
    'numpy',
    'sim_engine',
    'http.server',
    'socketserver',
    'cgi',
]

a = Analysis(
    ['lab_server.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'torch', 'ultralytics', 'easyocr'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MERSAD_LAB',
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
    name='MERSAD_LAB',
)
