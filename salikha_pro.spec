# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['salikha_pro.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PIL', 'PIL.Image', 'PIL.ImageOps', 'PIL.ImageTk', 'PIL.ImageWin', 'PIL.UnidentifiedImageError',
        'watchdog', 'watchdog.observers', 'watchdog.events',
        'win32print', 'win32ui', 'win32api', 'win32con', 'win32com',
        'queue', 'threading', 'json', 'stat', 'shutil',
    ],
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
    name='salikha_pro',
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
    icon='Salikha Photoman Ico.ico',
)