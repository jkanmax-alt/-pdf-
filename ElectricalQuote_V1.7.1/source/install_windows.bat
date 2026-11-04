@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Python not found. Please install Python 3.11. & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 (echo Failed to create virtual environment. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo Package installation failed. & pause & exit /b 1)
echo Installation complete. Run start_windows.bat.
pause
endlocal
