# IRON NEST - one-click: launch the game (if needed), enter the "Chill" sandbox,
# dismiss the Chill Mode popup, then make BOTH turrets start firing on their own.
#
#   double-click  fire.bat
#   or:           powershell -ExecutionPolicy Bypass -File fire.ps1 [-shots N] [-mode RANDOMENEMY|ARTILLERY]
#
# Everything is path-independent (uses $PSScriptRoot), so the folder can live anywhere.
param([int]$shots = 12, [string]$mode = "RANDOMENEMY")
$ErrorActionPreference = "Stop"
$proj = $PSScriptRoot
# Python to use: the bundled/selected one from fire.bat, else a system "python".
$py = if ($env:IRN_PYTHON) { $env:IRN_PYTHON } else { "python" }

Write-Host "=== IRON NEST one-click fire: $shots shots, target mode $mode ===" -ForegroundColor Cyan

# 1) Launch the game if needed, jump straight into the Chill sandbox, dismiss the notification.
& (Join-Path $proj "launch_chill.ps1")

# 2) Run the autoloader: both guns pre-stage and fire round-robin at live targets,
#    auto-reloading, auto-reselecting AP/HE per target, auto-resealing steam valves.
Push-Location $proj
$env:IRN_TARGET_MODE = $mode
& $py -u ironnest_parallel_rr.py $shots
Pop-Location

Write-Host "=== firing run complete ===" -ForegroundColor Cyan
