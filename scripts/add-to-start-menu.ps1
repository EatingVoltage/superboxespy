# Adds "superboxes" to your Start menu and makes a double-clicked .sbox open in it (current user only).
#
#     powershell -ExecutionPolicy Bypass -File scripts\add-to-start-menu.ps1
#
# The entry starts serve.py with pythonw, so there is no console window. The server keeps running in the
# background; starting the entry again just opens another app window on it. A double-clicked .sbox goes the same
# way: serve.py "<file>" opens an app window on that box (starting the server if it isn't running).
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

# .sbox: a box file. Its own extension, because Windows picks a program by the last extension only (a .box.json is
# a .json to it). Registered under HKCU\Software\Classes: nothing else claims .sbox, so a double-click opens it here.
$classes = "HKCU:\Software\Classes"
function Set-Key($path, $value, $more = @{}) {
    if (-not (Test-Path $path)) { New-Item -Path $path | Out-Null }    # never -Force: that empties an existing key
    Set-ItemProperty -Path $path -Name "(default)" -Value $value
    foreach ($k in $more.Keys) { Set-ItemProperty -Path $path -Name $k -Value $more[$k] }
}
Set-Key "$classes\.sbox" "superboxes.box" @{ "Content Type" = "application/json"; "PerceivedType" = "text" }
Set-Key "$classes\superboxes.box" "superboxes box"
Set-Key "$classes\superboxes.box\DefaultIcon" "$root\scripts\superboxes.ico,0"
Set-Key "$classes\superboxes.box\shell" "open"
Set-Key "$classes\superboxes.box\shell\open" "Open in superboxes"
Set-Key "$classes\superboxes.box\shell\open\command" "`"$pyw`" `"$root\serve.py`" `"%1`""
# tell Explorer, so the icon and the double-click work without signing out
Add-Type -Namespace SuperBoxes -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, System.IntPtr item1, System.IntPtr item2);
'@
[SuperBoxes.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)      # SHCNE_ASSOCCHANGED
"A double-clicked .sbox now opens in superboxes."
