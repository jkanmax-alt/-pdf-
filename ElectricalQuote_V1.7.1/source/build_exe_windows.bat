@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo First run install_windows.bat & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 (echo PyInstaller installation failed & pause & exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name ElectricalQuoteV171 --collect-all openpyxl --hidden-import core --hidden-import recognition_v14 --hidden-import segmentation_v15 --hidden-import segmentation_v16 --hidden-import worker_v16 --hidden-import feeder_geometry_v152 --hidden-import incoming_v153 --hidden-import compact_v153 --hidden-import motor_v153 --hidden-import orientation_v16 --hidden-import vertical_recognition_v16 --hidden-import surge_recognition_v17 --hidden-import precise_locator_v161 app_v16.py
if errorlevel 1 (echo EXE build failed & pause & exit /b 1)
echo Output folder: dist\ElectricalQuoteV171
pause
endlocal
