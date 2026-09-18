@echo off
REM Build DSI Redline on Windows. Run from anywhere; it cd's to the repo root.
setlocal
cd /d "%~dp0\.."

echo === Installing dependencies ===
python -m pip install -r requirements.txt || goto :error
python -m pip install -r packaging\requirements-build.txt || goto :error

echo === Building the app (PyInstaller) ===
python -m PyInstaller packaging\DSI_Redline.spec --noconfirm || goto :error

echo.
echo Built: dist\DSI Redline\  (run "DSI Redline.exe")
echo To build the installer, compile packaging\installer.iss with Inno Setup 6:
echo     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
echo.
goto :eof

:error
echo Build failed.
exit /b 1
