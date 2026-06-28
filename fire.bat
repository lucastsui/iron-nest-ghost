@echo off
REM ============================================================
REM  IRON NEST - one-click fire.
REM  Double-click this file. It launches the game (if needed),
REM  enters the Chill sandbox, dismisses the popup, and makes
REM  both turrets start firing on their own.
REM
REM  Optional: fire.bat 20            (20 shots)
REM            fire.bat 20 ARTILLERY  (20 shots, artillery targets)
REM ============================================================
setlocal
set SHOTS=%1
set MODE=%2
if "%SHOTS%"=="" set SHOTS=12
if "%MODE%"=="" set MODE=RANDOMENEMY
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fire.ps1" -shots %SHOTS% -mode %MODE%
echo.
echo Done. Press any key to close.
pause >nul
