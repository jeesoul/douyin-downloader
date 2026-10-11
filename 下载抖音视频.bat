@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" douyin_download.py --gui %*
) else (
    python douyin_download.py --gui %*
)
if errorlevel 1 pause
