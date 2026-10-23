@echo off
setlocal
cd /d "%~dp0"
echo Live option chain: opening Excel and streaming from Upstox
echo Keep this window open. Press Ctrl+C to stop.
where python >nul 2>nul
if errorlevel 1 (
  py -3 -m src.live
) else (
  python -m src.live
)
pause
