@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Mein Überblick - Installation
echo.
echo   Suche Python ...
call "%~dp0_python_finden.bat"
if not defined PY (
    echo.
    echo   Python wurde auf diesem PC nicht gefunden.
    echo.
    echo   Loesung: Python neu installieren von https://www.python.org/downloads/
    echo   und im ersten Fenster UNTEN den Haken bei
    echo   "Add python.exe to PATH" setzen. Danach diese Datei nochmal starten.
    echo.
    pause
    exit /b 1
)
echo   Gefunden: %PY%
echo.
echo   Installiere die Zusatzpakete fuer "Mein Ueberblick" ...
echo.
"%PY%" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo.
    echo   FEHLER beim Installieren der Pakete. Bitte ein Foto/Screenshot
    echo   von diesem Fenster machen, dann kann man sehen, woran es liegt.
    echo.
    pause
    exit /b 1
)
echo.
echo   Fertig! Jetzt "2_starten.bat" doppelklicken.
echo.
pause
