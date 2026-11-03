# Explicit onedir allowlist: no project-wide data collection or personal files.
from pathlib import Path
root=Path(SPECPATH)
a=Analysis([str(root/'tools/portable_entry.py')],pathex=[str(root)],
    binaries=[],datas=[],hiddenimports=['PIL.JpegImagePlugin','PIL.PngImagePlugin','PIL.GifImagePlugin'],
    hookspath=[],runtime_hooks=[],excludes=['pytest','tests'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='L4D2ModDatabase',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='L4D2ModDatabase')
