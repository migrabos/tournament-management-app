# -*- mode: python ; coding: utf-8 -*-
# Budowanie:  python -m PyInstaller "Menedżer Turnieju.spec" --noconfirm
# Wynik:      dist/Menedżer Turnieju/  (folder do spakowania w ZIP na release)
#
# Tryb folderu (onedir), nie jednego pliku: biblioteki Qt/PySide6 leżą jako osobne
# pliki w _internal/, więc użytkownik może je podmienić — wymóg licencji LGPL-3.0.
import shutil
from pathlib import Path

APP_NAME = 'Menedżer Turnieju'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('db/schema.sql', 'db'), ('assets/icon.ico', 'assets')],
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
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # bez kompresji — biblioteki zostają w oryginalnej, podmienialnej postaci
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

# Instrukcja i licencje obok pliku .exe (nie w _internal), żeby były widoczne dla użytkownika.
out = Path(DISTPATH) / APP_NAME
for f in ('INSTRUKCJA.txt', 'LICENSE', 'THIRD-PARTY-NOTICES.txt'):
    shutil.copy(f, out / f)
