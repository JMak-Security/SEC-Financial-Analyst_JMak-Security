@echo off
setlocal
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo ERROR: Could not open the project folder.
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%.venv\Scripts\python.exe" (
    echo Setting up the project virtual environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.12 -m venv "%PROJECT_DIR%.venv"
        if errorlevel 1 python -m venv "%PROJECT_DIR%.venv"
    ) else (
        where python >nul 2>&1
        if errorlevel 1 (
            echo ERROR: Python 3.12 or later is required. Install Python and try again.
            pause
            exit /b 1
        )
        python -m venv "%PROJECT_DIR%.venv"
    )
    if errorlevel 1 (
        echo ERROR: Could not create the virtual environment.
        pause
        exit /b 1
    )
)

set "ANALYST_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"

"%ANALYST_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.12 or later is required. Install Python and try again.
    pause
    exit /b 1
)

"%ANALYST_PYTHON%" -c "import streamlit, requests, numpy, scipy, pandas, duckdb" >nul 2>&1
if errorlevel 1 (
    echo Installing application dependencies...
    "%ANALYST_PYTHON%" -m pip install -r "%PROJECT_DIR%requirements.txt"
    if errorlevel 1 (
        echo ERROR: Dependency installation failed. Check your internet connection.
        pause
        exit /b 1
    )
)

echo Starting SEC Financial Analyst on http://127.0.0.1:8501
echo Keep this window open while using the app. Press Ctrl+C to stop the server.
"%ANALYST_PYTHON%" "%PROJECT_DIR%launch.py"
if errorlevel 1 (
    echo.
    echo ERROR: The analyst web server could not start.
    pause
    exit /b 1
)
