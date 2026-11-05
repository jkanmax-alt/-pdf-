@echo off
setlocal
cd /d "%~dp0.."
set "EQ_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%EQ_PYTHON%" (
    py -3.11 -m venv "%~dp0.venv"
    if errorlevel 1 goto :failed
)
"%EQ_PYTHON%" -c "import struct,sys; assert sys.platform == 'win32' and struct.calcsize('P') == 8, 'Windows x64 Python is required'"
if errorlevel 1 goto :failed
"%EQ_PYTHON%" -m pip install -r requirements-build-windows.txt
if errorlevel 1 goto :failed
if exist "vendor\tesseract\BUNDLE-MANIFEST.json" (
    "%EQ_PYTHON%" tools\prepare_tesseract_windows.py --verify-only
) else (
    "%EQ_PYTHON%" tools\prepare_tesseract_windows.py
)
if errorlevel 1 goto :failed
"%EQ_PYTHON%" -m PyInstaller --clean --noconfirm source\ElectricalQuote.spec
if errorlevel 1 goto :failed
copy /y "PORTABLE_WINDOWS.md" "dist\ElectricalQuoteV172\PORTABLE_WINDOWS.md" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\ElectricalQuoteV172' -DestinationPath 'dist\ElectricalQuoteV172-Windows-x64-portable.zip' -Force"
if errorlevel 1 goto :failed
echo.
echo Portable folder: %CD%\dist\ElectricalQuoteV172
echo Distribution ZIP: %CD%\dist\ElectricalQuoteV172-Windows-x64-portable.zip
echo Keep ElectricalQuoteV172.exe and the entire _internal directory together.
pause
exit /b 0
:failed
echo.
echo Build failed. Read the error above; no incomplete build should be distributed.
echo See PORTABLE_WINDOWS.md for build prerequisites and validation.
pause
exit /b 1
