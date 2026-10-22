@echo off
setlocal
cd /d "%~dp0"
echo Starting Option Chain service on http://127.0.0.1:8765
where python >nul 2>nul
if errorlevel 1 (
  py -3 -m src.server
) else (
  python -m src.server
)
pause
