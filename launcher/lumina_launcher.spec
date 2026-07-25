# -*- mode: python ; coding: utf-8 -*-
# Optional PyInstaller spec. PyInstaller is NOT required to run LUMINA.
# Build (from repo root): pyinstaller launcher/lumina_launcher.spec

block_cipher = None

a = Analysis(
    ['lumina_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['lumina', 'lumina.config', 'lumina.services', 'lumina.doctor'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LUMINA',
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
)
