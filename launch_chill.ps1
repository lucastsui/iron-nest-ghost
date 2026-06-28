# One-command launch of the IRON NEST "Chill" sandbox (Contestless Engagement),
# fully via IL2CPP, then dismiss the "Chill Mode" notification by clicking CONTINUE.
#
#   powershell -File launch_chill.ps1
#
# Steps: ensure game running -> StartOperation(Tutorial, Chill) via launch_mission.py
#        -> wait for scene -> double-click the CONTINUE button (default-bearing location).
param([double]$cx = 0.533, [double]$cy = 0.555, [int]$appid = 4300500)
$ErrorActionPreference = "Stop"
$proj = $PSScriptRoot                               # this script's own folder (the project dir)
$shot = Join-Path $env:TEMP "iron_nest_launch.png"  # portable temp location for the confirmation screenshot

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class N {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,UIntPtr e);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
}
"@
[N]::SetProcessDPIAware() | Out-Null

function Get-Game { Get-Process -Name "Iron Nest Heavy Turret Simulator" -ErrorAction SilentlyContinue | Select-Object -First 1 }
function Focus-Game {
  $p = Get-Game; if (-not $p) { return $null }
  $h = $p.MainWindowHandle; $our = [N]::GetCurrentThreadId()
  $tgt = [N]::GetWindowThreadProcessId($h, [ref]([uint32]0))
  [N]::ShowWindow($h,9) | Out-Null
  [N]::AttachThreadInput($our,$tgt,$true) | Out-Null
  [N]::BringWindowToTop($h) | Out-Null; [N]::SetForegroundWindow($h) | Out-Null
  [N]::AttachThreadInput($our,$tgt,$false) | Out-Null
  Start-Sleep -Milliseconds 350; return $h
}
function Click-Frac([double]$fx,[double]$fy) {
  $vx=[N]::GetSystemMetrics(76); $vy=[N]::GetSystemMetrics(77)
  $vw=[N]::GetSystemMetrics(78); $vh=[N]::GetSystemMetrics(79)
  $x=[int]($vx+$fx*$vw); $y=[int]($vy+$fy*$vh)
  [N]::SetCursorPos($x,$y) | Out-Null; Start-Sleep -Milliseconds 200
  [N]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 60; [N]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)
}
function Save-Shot($out) {
  $vw=[N]::GetSystemMetrics(78); $vh=[N]::GetSystemMetrics(79)
  $vx=[N]::GetSystemMetrics(76); $vy=[N]::GetSystemMetrics(77)
  $bmp=New-Object System.Drawing.Bitmap($vw,$vh); $g=[System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($vx,$vy,0,0,$bmp.Size); $bmp.Save($out,[System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
}

# 1. ensure game running + at a usable state
if (-not (Get-Game)) {
  Write-Output "launching game..."
  Start-Process "steam://rungameid/$appid"
  foreach ($i in 1..40) { Start-Sleep -Seconds 2; if ((Get-Game).MainWindowHandle) { break } }
  Start-Sleep -Seconds 12
}
Focus-Game | Out-Null

# 2. launch the Chill mission via IL2CPP (works from menu OR map)
Write-Output "StartOperation(Tutorial, Chill)..."
Push-Location $proj
python launch_mission.py startop Tutorial Chill 2>&1 | Select-String "phase|scene|StartOperation"
Pop-Location

# 3. wait for scene + notification, then dismiss CONTINUE (1st click hovers, 2nd activates)
Start-Sleep -Seconds 5
Focus-Game | Out-Null
Write-Output "dismissing Chill Mode notification..."
Click-Frac $cx $cy; Start-Sleep -Milliseconds 500
Click-Frac $cx $cy; Start-Sleep -Milliseconds 700
Save-Shot $shot
Write-Output "done -> screenshot at $shot"
