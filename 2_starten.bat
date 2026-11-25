@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python_finden.bat"
if not defined PY (
    echo Python wurde nicht gefunden. Bitte zuerst 1_installieren.bat ausfuehren.
    pause
    exit /b 1
)
start "" "%PYW%" "%~dp0app.py"
