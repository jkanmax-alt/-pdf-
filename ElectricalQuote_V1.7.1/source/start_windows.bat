@echo off
setlocal
cd /d "%~dp0"
set "OMP_THREAD_LIMIT=1"
set "OPENBLAS_NUM_THREADS=1"
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
if exist ".venv\Scripts\python.exe" (
 ".venv\Scripts\python.exe" app_v16.py
) else (
 python app_v16.py
)
if errorlevel 1 (echo. & echo Application failed. Please send the error text or screenshot. & pause)
endlocal
