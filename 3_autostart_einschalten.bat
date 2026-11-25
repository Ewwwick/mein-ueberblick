@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Legt eine Verknuepfung im Autostart-Ordner an: Das Programm startet dann
rem bei jedem Windows-Start unsichtbar im Hintergrund und traegt Aufgaben ein.
call "%~dp0_python_finden.bat"
if not defined PY (
    echo Python wurde nicht gefunden. Bitte zuerst 1_installieren.bat ausfuehren.
    pause
    exit /b 1
)
set "ZIEL=%~dp0app.py"
set "ORDNER=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Mein Ueberblick.lnk'); $s.TargetPath=$env:PYW; $s.Arguments='\"'+$env:ZIEL+'\" --ohne-fenster'; $s.WorkingDirectory=$env:ORDNER; $s.WindowStyle=7; $s.Save()"
if errorlevel 1 (
    echo Das hat leider nicht geklappt.
) else (
    echo Autostart ist eingeschaltet. Ab dem naechsten Windows-Start laeuft
    echo "Mein Ueberblick" automatisch im Hintergrund.
)
echo.
pause
