@echo off
@chcp 65001 > nul
title Abo-Eyad ERP - Cloud Backup Runner

echo ========================================================
echo       Abo-Eyad ERP - Automated Backup System
echo ========================================================
echo.

if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_EXEC=%~dp0venv\Scripts\python.exe"
) else (
    set "PY_EXEC=python"
)

echo [1/2] Checking Python environment...
"%PY_EXEC%" --version
if errorlevel 1 (
    echo [ERROR] Python not found. Please ensure Python is installed and in PATH.
    pause
    exit /b 1
)

echo.
echo [2/2] Running full backup and Telegram notification...
echo.

"%PY_EXEC%" "%~dp0run_daily_backup.py"
set BACKUP_EXIT_CODE=%errorlevel%

echo.
echo ========================================================
if %BACKUP_EXIT_CODE% EQU 0 (
    echo   [SUCCESS] Backup process completed successfully!
) else (
    echo   [FAILED] Backup process encountered errors!
)
echo ========================================================
echo.

pause
exit /b %BACKUP_EXIT_CODE%
