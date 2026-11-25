@echo off
chcp 65001 >nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Mein Ueberblick.lnk" 2>nul
echo Autostart ist ausgeschaltet.
echo.
pause
