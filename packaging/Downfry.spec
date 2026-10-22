# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

root_dir = Path.cwd()

datas = [
    (str(root_dir / 'packaging' / 'app_icon.png'), 'packaging'),
    (str(root_dir / 'packaging' / 'app_icon.ico'), 'packaging'),
]

binaries = []
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    if ffmpeg_exe and Path(ffmpeg_exe).exists():
        binaries.append((ffmpeg_exe, '.'))
except Exception:
    pass

hiddenimports = [
    'yt_dlp',
    'yt_dlp.extractor',
    'yt_dlp.downloader',
    'yt_dlp.postprocessor',
    'imageio_ffmpeg',
    'qfluentwidgets',
    'qfluentwidgets.components',
    'qfluentwidgets.common',
    'darkdetect',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
]

excludes = [
    'scipy',
    'numpy',
    'pytest',
    'IPython',
    'notebook',
    'torch',
    'torchvision',
    'torchaudio',
    'whisper',
    'tensorboard',
    'matplotlib',
    'pandas',
    'numba',
    'llvmlite',
    'sympy',
    'tkinter',
    'unittest',
]

a = Analysis(
    [str(root_dir / 'run.py')],
    pathex=[str(root_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Downfry',
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
    icon=str(root_dir / 'packaging' / 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Downfry',
)
