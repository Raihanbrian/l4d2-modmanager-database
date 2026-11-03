@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -B -m l4d2_mod_db.desktop %*
) else (
    python -B -m l4d2_mod_db.desktop %*
)
if errorlevel 1 pause
