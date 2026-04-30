@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
set "PYTHONW_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    set "PYTHONW_CMD=pyw -3"
)

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
        set "PYTHONW_CMD=pythonw"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo Python was not found. Please install Python 3 and try again.
    pause
    exit /b 1
)

if exist app.pyw (
    start "" %PYTHONW_CMD% app.pyw
    exit /b 0
)

call %PYTHON_CMD% app.py
