from pathlib import Path

root = Path(SPECPATH).parent
vendor = root / "vendor"
if not vendor.is_dir():
    raise SystemExit("Run scripts/fetch_tools.py before building.")

a = Analysis(
    [str(root / "scripts" / "launch.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(vendor), "vendor"), (str(root / "LICENSE"), "."),
           (str(root / "THIRD_PARTY.md"), "."), (str(root / "tools-lock.json"), ".")],
    hiddenimports=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SONATA", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          contents_directory="_internal")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SONATA")
