# PyInstaller build spec for MatchdayDB's standalone desktop build.
#
# Build on the OS you're targeting -- PyInstaller does not cross-compile,
# so a Windows .exe must be built on Windows and a macOS app on macOS.
# See packaging/BUILD.md for the exact commands and what you get back.
#
#   pyinstaller packaging/matchdaydb.spec --distpath dist --workpath build
#
# Produces dist/MatchdayDB/ containing the MatchdayDB(.exe) launcher at the
# top level plus a supporting _internal/ folder beside it. Zip the whole
# dist/MatchdayDB/ folder -- that's what gets handed out.

from __future__ import annotations

from pathlib import Path

block_cipher = None
# SPECPATH is injected by PyInstaller into the spec file's exec namespace
# (spec files have no __file__ of their own).
REPO_ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(REPO_ROOT / "desktop.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "static"), "static"),
        (str(REPO_ROOT / "schema.sql"), "."),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "onnxruntime",
        "tokenizers",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MatchdayDB",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keeps a visible window: the user's stop button, and
    # where any startup error is printed. See BUILD.md for the tray-icon
    # alternative if a fully console-free build is wanted later.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MatchdayDB",
)
