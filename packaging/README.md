# Packaging DSI Redline for Windows

This folder builds a Windows **executable** and an **installer**.

| File | Purpose |
|------|---------|
| `DSI_Redline.spec` | PyInstaller build (one-folder, windowed, bundles `docs/`) |
| `installer.iss` | Inno Setup script → a `Setup.exe` installer |
| `build_windows.bat` | One-shot local build helper |
| `requirements-build.txt` | Build-only deps (PyInstaller) |
| `../app/assets/app.ico` | Brand app icon (exe, installer, shortcut, window/taskbar) |
| `icons/` | Full brand icon source set (dark + light themes, all sizes) |
| `../.github/workflows/build-windows.yml` | CI that builds both on every tag / manual run |

## Easiest: let CI build it

Push a tag (e.g. `vX.Y.Z`) or run **Actions ▸ Build Windows ▸ Run workflow**.
The job runs the tests, builds the app, builds the installer, and uploads two
artifacts: **DSI-Redline-portable** (the app folder) and
**DSI-Redline-installer** (the `Setup.exe`). No local Windows machine needed.

## Build locally on Windows

Prereqs: Python 3.11+ and (for the installer) [Inno Setup 6](https://jrsoftware.org/isdl.php).

```bat
:: from the repo root
packaging\build_windows.bat

:: then build the installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

Outputs:
- `dist\DSI Redline\DSI Redline.exe` — the portable app (zip the folder to share).
- `dist_installer\DSI_Redline_Setup_<version>.exe` — the installer.

The `docs/` user-manual vault is bundled into the app (under `_internal\docs`),
so **Help ▸ User Manual** works on every machine — the docs travel with the app.

## A quick single-file exe (optional)

For a single portable `.exe` (slower to start, no installer):

```bat
pyinstaller --onefile --windowed --name "DSI Redline" ^
  --add-data "docs;docs" --add-data "app/assets;app/assets" ^
  --icon app\assets\app.ico main.py
```

## Notes

- The installer registers DSI Redline as a **PDF viewer** (opt-in checkbox,
  ticked by default): it's added to the Windows **Open with** list and the
  **Default apps** picker. This is *additive* — it never overrides the user's
  current default PDF app on install, and uninstall removes every key it added.
  See `[Registry]` in `installer.iss` and [[File Associations]] in the docs.
- **Tesseract** (OCR) and an **Anthropic API key** (AI) remain optional at
  runtime; neither is required to run the packaged app. If `anthropic` is
  installed in the build environment it is bundled automatically.
- Update the version in `installer.iss` (and `app/__init__.py`) when you cut a
  release.
- macOS/Linux builds use the same spec (`pyinstaller packaging/DSI_Redline.spec`);
  only the installer step is Windows-specific.
