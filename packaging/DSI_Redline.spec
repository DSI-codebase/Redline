# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DSI Redline (one-folder, windowed).

Build from the repo root:
    pyinstaller packaging/DSI_Redline.spec --noconfirm
Produces dist/DSI Redline/  (run "DSI Redline.exe").
"""

import os

ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # repo root (packaging/..)

# Bundle the user-manual vault and app assets (icon) so they ship with every build.
#
# THIRD-PARTY-NOTICES.md and licenses/ are bundled here rather than added to
# installer.iss, and that placement is the whole point: MIT, BSD and the LGPL
# require the notice to travel with the DISTRIBUTED FORM, and this build has two
# of them -- the Inno installer and the portable zip, which are both packaged
# from `dist/DSI Redline/*`. Putting the files in `datas` puts them inside that
# directory once and both artifacts inherit them; wiring the installer alone
# would leave the portable zip non-compliant with nothing saying so.
#
# A notices file that sits only in the repository satisfies nothing for somebody
# who downloads the exe. Verified after a build by listing the artifact, not by
# reading this comment.
datas = [
    (os.path.join(ROOT, "docs"), "docs"),
    (os.path.join(ROOT, "app", "assets"), os.path.join("app", "assets")),
    (os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"), "."),
    (os.path.join(ROOT, "licenses"), "licenses"),
]

# Optionally bundle heavier optional deps only when installed, so builds without
# them still succeed and the app degrades gracefully.
hiddenimports = []
try:
    from PyInstaller.utils.hooks import collect_submodules, collect_data_files
    for _opt in ("anthropic", "pdf2docx", "pydrc"):
        try:
            __import__(_opt)
            hiddenimports += collect_submodules(_opt)
            # Rule packs are YAML data files, not modules. PyDRC finds its
            # built-ins relative to its own package directory, and
            # collect_data_files reproduces that layout in the frozen build.
            datas += collect_data_files(_opt, includes=["**/*.yaml"])
        except Exception:
            pass
    # PyDRC imports PyYAML lazily from inside its pack loader, so the analysis
    # does not always see it.
    hiddenimports += ["yaml"]
except Exception:
    pass

icon_path = os.path.join(ROOT, "app", "assets", "app.ico")  # brand icon

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DSI Redline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=icon_path if os.path.exists(icon_path) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DSI Redline",
)
