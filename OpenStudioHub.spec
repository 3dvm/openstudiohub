# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['openstudio_hub.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),                     # Incluye todos los íconos, logos y SVGs
        ('macuare_theme.qss', '.'),               # Incluye la hoja de estilos corporativa
        ('core/templates', 'core/templates'),     # Incluye los scripts de inyección y sandboxing
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name='OpenStudioHub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/openstudiohub.ico', 
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OpenStudioHub',
)
