# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 스펙: python -m PyInstaller microscope.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = os.path.abspath(SPECPATH)
SRC_DIR = os.path.abspath(os.path.join(SPEC_DIR, "..", "microscope_gui"))

# CustomTkinter 테마/폰트 리소스 포함
datas = collect_data_files("customtkinter")

a = Analysis(
    [os.path.join(SRC_DIR, "app.py")],
    pathex=[SRC_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=["wheel_hook", "scrcpy_manager"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MicroscopeController",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX 압축은 백신 오탐을 늘리므로 사용하지 않음
    console=False,      # 콘솔 창 숨김
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MicroscopeController",
)
