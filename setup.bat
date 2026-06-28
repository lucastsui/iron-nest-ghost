@echo off
REM ============================================================
REM  Download a portable Python into .\python so the project
REM  runs with nothing installed. Needs internet, one time only.
REM ============================================================
setlocal
set "DIR=%~dp0"
set "PYDIR=%DIR%python"
if exist "%PYDIR%\python.exe" (
  echo Portable Python already present at %PYDIR%
  exit /b 0
)
echo Downloading portable Python 3.11.9 ^(~15 MB^)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $u='https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'; $z=Join-Path $env:TEMP 'inest-py-embed.zip'; Invoke-WebRequest -Uri $u -OutFile $z; if(Test-Path '%PYDIR%'){Remove-Item '%PYDIR%' -Recurse -Force}; Expand-Archive -Path $z -DestinationPath '%PYDIR%' -Force; Remove-Item $z; $p=Get-ChildItem (Join-Path '%PYDIR%' '*._pth')^|Select-Object -First 1; Add-Content -Path $p.FullName -Value '..'"
if not exist "%PYDIR%\python.exe" (
  echo Setup FAILED ^(no internet?^). Install Python 3.8+ from python.org instead.
  exit /b 1
)
echo Portable Python ready at %PYDIR%
exit /b 0
