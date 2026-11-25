@echo off
rem Sucht eine funktionierende Python-Installation und setzt PY und PYW.
rem Wird von den anderen .bat-Dateien aufgerufen.
set "PY="
set "PYW="

rem 1) Befehle testen (der Microsoft-Store-Platzhalter faellt hier durch)
for %%G in (py python python3) do (
    if not defined PY (
        %%G -c "import sys" >nul 2>nul && set "PY=%%G"
    )
)

rem 2) Uebliche Installationsordner durchsuchen (falls "PATH" nicht gesetzt ist)
if not defined PY (
    for /d %%G in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "%ProgramFiles(x86)%\Python3*" "C:\Python3*") do (
        if not defined PY if exist "%%~G\python.exe" (
            "%%~G\python.exe" -c "import sys" >nul 2>nul && set "PY=%%~G\python.exe"
        )
    )
)

if not defined PY goto :eof

rem 3) pythonw.exe (ohne schwarzes Fenster) neben der echten python.exe suchen
set "PYEXE="
"%PY%" -c "import sys;print(sys.executable)" > "%TEMP%\meinueberblick_py.txt" 2>nul
set /p PYEXE=<"%TEMP%\meinueberblick_py.txt"
del "%TEMP%\meinueberblick_py.txt" >nul 2>nul
if defined PYEXE (
    for %%H in ("%PYEXE%") do if exist "%%~dpHpythonw.exe" set "PYW=%%~dpHpythonw.exe"
)
if not defined PYW set "PYW=%PY%"
