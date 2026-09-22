@echo off
rem Launch the desktop pet silently: prefer pythonw (no console).
rem If only python.exe exists, start it with a hidden window so no
rem blank cmd window is left on the desktop.
setlocal
cd /d "%~dp0"
set "ENTRY=%~dp0src\main.py"
set "PYW="

if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW for /f "delims=" %%I in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do if exist "%%I" set "PYW=%%I"
if not defined PYW for /f "delims=" %%I in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do if exist "%%I" set "PYW=%%I"
if not defined PYW if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe" set "PYW=%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw.exe"

if defined PYW (
    start "" "%PYW%" -B "%ENTRY%"
    exit /b
)

powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath 'python' -ArgumentList '-B','%ENTRY%' -WindowStyle Hidden"
exit /b
