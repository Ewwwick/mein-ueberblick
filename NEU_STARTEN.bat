@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Mein Überblick - Neustart
echo.
echo   Mein Ueberblick wird neu gestartet ...
echo   (Eine alte Version im Hintergrund wird automatisch beendet.)
echo.
call "%~dp0_python_finden.bat"
if not defined PY (
    echo   Python wurde nicht gefunden. Bitte 1_installieren.bat ausfuehren.
    pause
    exit /b 1
)
echo   Python: %PY%
echo.
"%PY%" "%~dp0app.py" --nur-starten
if errorlevel 1 (
    echo.
    echo   FEHLER - bitte einen Screenshot von diesem Fenster machen.
    pause
    exit /b 1
)
echo.
echo   Fertig! Das Fenster oeffnet sich gleich. Dieses schwarze Fenster
echo   schliesst sich in 5 Sekunden von selbst.
timeout /t 5 >nul
