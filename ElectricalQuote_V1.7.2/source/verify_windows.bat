@echo off
setlocal
cd /d "%~dp0"
set "OMP_THREAD_LIMIT=1"
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" verify_v172.py %*
) else (
  python verify_v172.py %*
)
set "CHECK_EXIT=%ERRORLEVEL%"
if not "%CHECK_EXIT%"=="0" echo CHECK FAILED - send us this screen.
echo.
pause
endlocal & exit /b %CHECK_EXIT%
