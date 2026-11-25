@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Legt auf dem Desktop eine Verknuepfung "Mein Ueberblick" mit dem App-Icon an.
call "%~dp0_python_finden.bat"
if not defined PY (
    echo Python wurde nicht gefunden. Bitte zuerst 1_installieren.bat ausfuehren.
    pause
    exit /b 1
)
set "ZIEL=%~dp0app.py"
set "ORDNER=%~dp0"
set "ICON=%~dp0icon.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$name='Mein '+[char]0xDC+'berblick.lnk'; $s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\'+$name); $s.TargetPath=$env:PYW; $s.Arguments='\"'+$env:ZIEL+'\"'; $s.WorkingDirectory=$env:ORDNER; $s.IconLocation=$env:ICON+',0'; $s.Description='Kalender, Hausaufgaben und mehr'; $s.Save()"
if errorlevel 1 (
    echo Das hat leider nicht geklappt.
) else (
    echo Fertig! Auf deinem Desktop liegt jetzt "Mein Ueberblick" mit dem neuen Icon.
)
echo.
pause
