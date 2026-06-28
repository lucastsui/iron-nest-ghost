@echo off
REM ============================================================
REM  IRON NEST - one-click fire. No Python install required.
REM
REM  Picks a Python in this order:
REM    1) bundled  .\python\python.exe   (run setup.bat to get it)
REM    2) a system "python" on PATH
REM    3) otherwise downloads a portable copy (one time, internet)
REM
REM  Double-click, or:  fire.bat [shots] [RANDOMENEMY|ARTILLERY]
REM ============================================================
setlocal
set "DIR=%~dp0"
set "PYEMBED=%DIR%python\python.exe"
set "IRN_PYTHON="

if exist "%PYEMBED%" set "IRN_PYTHON=%PYEMBED%"

if not defined IRN_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "IRN_PYTHON=python"
)

if not defined IRN_PYTHON (
  echo No Python found - downloading a portable copy ^(one time^)...
  call "%DIR%setup.bat"
  if exist "%PYEMBED%" set "IRN_PYTHON=%PYEMBED%"
)

if not defined IRN_PYTHON (
  echo Could not find or set up Python.
  pause
  exit /b 1
)

set "SHOTS=%~1"
set "MODE=%~2"
if "%SHOTS%"=="" set "SHOTS=12"
if "%MODE%"=="" set "MODE=RANDOMENEMY"

REM IRN_PYTHON is exported to the PowerShell/Python children below.
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%fire.ps1" -shots %SHOTS% -mode %MODE%
echo.
echo Done. Press any key to close.
pause >nul
