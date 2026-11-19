@echo off
REM ============================================================
REM  ScanForge 3D - baut die Setup.exe auf einem Windows-PC
REM  Voraussetzungen: Python 3.11+ (python.org, "Add to PATH")
REM                   Inno Setup 6 (jrsoftware.org)  - fuer die Setup.exe
REM ============================================================
setlocal
cd /d %~dp0

if not exist .venv (
  echo [1/5] Virtuelle Umgebung anlegen ...
  python -m venv .venv || goto :err
)
call .venv\Scripts\activate.bat

echo [2/5] Python-Pakete installieren ...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt pyinstaller py7zr || goto :err

echo [3/5] COLMAP und OpenMVS herunterladen ...
python tools\download_tools.py || goto :err

echo [4/5] Programm bauen (PyInstaller) ...
pyinstaller --noconfirm --clean --windowed --name ScanForge3D ^
  --icon assets\icon.ico --add-data "assets;assets" ^
  --collect-submodules pyqtgraph --collect-data trimesh ^
  main.py || goto :err
xcopy /e /i /y /q tools\colmap dist\ScanForge3D\tools\colmap >nul
xcopy /e /i /y /q tools\openmvs dist\ScanForge3D\tools\openmvs >nul

echo [5/5] Installer erstellen (Inno Setup) ...
if not exist vc_redist.x64.exe (
  powershell -Command "Invoke-WebRequest https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile vc_redist.x64.exe"
)
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo Inno Setup nicht gefunden - das Programm liegt trotzdem fertig in dist\ScanForge3D\ScanForge3D.exe
  goto :ok
)
%ISCC% installer.iss || goto :err
echo.
echo FERTIG:  Output\ScanForge3D_Setup.exe
:ok
pause
exit /b 0
:err
echo.
echo FEHLER beim Bauen - siehe Meldungen oben.
pause
exit /b 1
