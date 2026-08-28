# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from scripts.build_policy import (
    assert_trusted_binary_sources,
    normalize_windows_binaries,
    trusted_build_roots,
)


project_root = Path(SPEC).resolve().parent

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app_icon.ico', 'assets')],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'sounddevice',
        'numpy',
        'scipy',
        'scipy.io',
        'scipy.io.wavfile',
        'openai',
        'docx',
        'pydantic',
        'pydantic_settings',
        'loguru',
        'sentry_sdk',
        'keyring',
        'keyring.backends',
        'keyring.backends.Windows',
        'psutil',
        'pydub',
        'win32gui',
        'win32process',
        'pynput',
        'pynput.keyboard',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
)

# PyInstaller resolves indirect DLLs through PATH. Refuse binaries from unrelated
# developer tools, then keep Windows-owned ICU/UCRT DLLs out of the bundle and
# use PySide6's newest compatible MSVC runtime for both Python and Qt.
assert_trusted_binary_sources(a.binaries, trusted_build_roots(project_root))
a.binaries = normalize_windows_binaries(
    a.binaries,
    pyside_directory=Path(sys.prefix) / 'Lib' / 'site-packages' / 'PySide6',
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MeetingNote',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)
