@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The Bakery project environment is missing.
    echo Run: python -m venv .venv
    echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)
set "PYTHONHOME="
set "PYTHONPATH="
".venv\Scripts\python.exe" -u manage.py runserver 0.0.0.0:1122
