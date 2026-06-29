@echo off
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

title IRON NEST Freezer
echo ============================================================
echo  IRON NEST - Timer + Requisition freezer
echo  - Leave this window open while playing.
echo  - It waits for the game, then locks the timer and sets
echo    requisition to 999999 and freezes it.
echo  - Close this window (or press Ctrl+C) to stop freezing.
echo ============================================================
echo.
"%IRN_PYTHON%" "%DIR%ironnest_freezer.py" set=999999
pause
