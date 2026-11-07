# Adds "superboxes" to your Start menu (current user only).
#
#     powershell -ExecutionPolicy Bypass -File scripts\add-to-start-menu.ps1
#
# The entry starts serve.py with pythonw, so there is no console window. The server keeps running in the
# background; starting the entry again just opens another app window on it.
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$root\dist\index.html")) { throw "No build yet: double-click start.bat once first." }
# Launchers that survive a Python upgrade first (py launcher, Python install manager), then PATH; never the .venv.
$pyw = @((Get-Command pyw.exe -All -ErrorAction SilentlyContinue).Source) +
       "$env:LOCALAPPDATA\Python\bin\pythonw.exe" +
       @((Get-Command pythonw.exe -All -ErrorAction SilentlyContinue).Source) |
    Where-Object { $_ -and (Test-Path $_) -and $_ -notlike "$root\*" } | Select-Object -First 1
if (-not $pyw) { throw "pythonw.exe not found on PATH." }

$lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "superboxes.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$root\serve.py`""
$s.WorkingDirectory = $root
$s.IconLocation = "$root\scripts\superboxes.ico,0"
$s.Description = "boxes.py as a local web app"
$s.Save()
"Added to the Start menu: $lnk"
