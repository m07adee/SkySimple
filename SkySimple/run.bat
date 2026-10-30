@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe goto run

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY goto nopy

echo First run: preparing environment, this may take a few minutes...
%PY% -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail

:run
start "" .venv\Scripts\pythonw.exe app.py
exit /b 0

:nopy
echo Python was not found. Install Python 3.10+ from python.org then run this file again.
pause
exit /b 1

:fail
echo Setup failed. See the messages above.
pause
exit /b 1