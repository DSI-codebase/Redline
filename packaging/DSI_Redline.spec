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

# PyMuPDF's optional add-ons stay OUT of the frozen build. From PyMuPDF 2.0 the
# wheel carries `pymupdf.layout` and requires `pymupdf4llm`, and `import fitz`
# imports both, each inside `try/except ImportError`. The layout package then
# loads an ONNX model from YAML and .onnx files beside its own modules, which
# the analysis does not collect (no hook for them in hooks-contrib 2026.9), so
# v1.8.0 died on launch with FileNotFoundError on layout_rf2.4.1+imf1.yaml.
# Redline calls neither (no find_tables, get_layout or to_markdown), so a
# module that is absent is the state PyMuPDF already handles, and it is the
# state every PyMuPDF 1.x build ran in. Collecting the models instead would
# ship onnxruntime (69 MB on Linux) and 51 MB of models to load at every
# launch for nothing. The self-test step in build-windows.yml is what catches
# this class of defect, a bundle missing a file the source install has.
excludes = ["tkinter", "pymupdf.layout", "pymupdf4llm"]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
