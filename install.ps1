<#
.SYNOPSIS
  Install Blender Phone Control into Blender on this Windows PC.

.DESCRIPTION
  Finds blender.exe, copies the addon into Blender's user addons folder,
  enables it (with "start server when Blender opens"), and adds a Private-
  network firewall rule when run as Administrator.

  Run from a clone of the repo:
      powershell -ExecutionPolicy Bypass -File .\install.ps1
  Or without cloning (downloads the branch zip itself):
      irm https://raw.githubusercontent.com/khattak-k/khattak-k/claude/new-session-xzed82/install.ps1 | iex

.PARAMETER BlenderExe
  Path to blender.exe if auto-detection picks the wrong one.
#>
param(
    [string]$BlenderExe = "",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Branch = "claude/new-session-xzed82"
$Repo = "khattak-k/khattak-k"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- 1. locate the addon source --------------------------------------------
$src = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "blender_phone_control\__init__.py"))) {
    $src = Join-Path $PSScriptRoot "blender_phone_control"
} else {
    Write-Step "Downloading addon from GitHub ($Repo @ $Branch)"
    $tmp = Join-Path $env:TEMP "blender_phone_control_src"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    New-Item -ItemType Directory $tmp | Out-Null
    $zip = Join-Path $tmp "src.zip"
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Recurse -Directory -Filter "blender_phone_control" | Select-Object -First 1 -ExpandProperty FullName
    if (-not $src) { throw "addon folder not found in downloaded archive" }
}

# --- 2. find blender.exe ---------------------------------------------------
if (-not $BlenderExe) {
    $candidates = @()
    $cmd = Get-Command blender.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    foreach ($root in @("$env:ProgramFiles\Blender Foundation", "${env:ProgramFiles(x86)}\Blender Foundation",
                        "$env:ProgramFiles\Steam\steamapps\common\Blender",
                        "${env:ProgramFiles(x86)}\Steam\steamapps\common\Blender")) {
        if (Test-Path $root) {
            $candidates += Get-ChildItem $root -Recurse -Filter blender.exe -ErrorAction SilentlyContinue |
                           Sort-Object LastWriteTime -Descending | ForEach-Object FullName
        }
    }
    $BlenderExe = $candidates | Where-Object { $_ } | Select-Object -First 1
}
if (-not $BlenderExe -or -not (Test-Path $BlenderExe)) {
    throw "blender.exe not found. Re-run with:  .\install.ps1 -BlenderExe 'C:\path\to\blender.exe'"
}
Write-Step "Using $BlenderExe"

# --- 3. Blender version -> addons folder ------------------------------------
$verLine = (& $BlenderExe --version 2>$null | Select-String -Pattern "^Blender (\d+)\.(\d+)").Matches[0]
if (-not $verLine) { throw "could not read Blender version from '$BlenderExe --version'" }
$major = [int]$verLine.Groups[1].Value; $minor = [int]$verLine.Groups[2].Value
$ver = "$major.$minor"
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 3)) { throw "Blender $ver is too old; need 3.3 or newer" }

$addons = Join-Path $env:APPDATA "Blender Foundation\Blender\$ver\scripts\addons"
New-Item -ItemType Directory -Force $addons | Out-Null
$dest = Join-Path $addons "blender_phone_control"

# --- 4. copy ----------------------------------------------------------------
Write-Step "Installing to $dest"
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Copy-Item $src $dest -Recurse
Get-ChildItem $dest -Recurse -Include "__pycache__" -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# --- 5. enable + autostart ---------------------------------------------------
Write-Step "Enabling addon in Blender $ver (autostart on, port $Port)"
$py = @"
import bpy
bpy.ops.preferences.addon_enable(module='blender_phone_control')
p = bpy.context.preferences.addons['blender_phone_control'].preferences
p.autostart = True
p.port = $Port
bpy.ops.wm.save_userpref()
print('PHONE_CONTROL_OK')
"@
$out = (& $BlenderExe -b --python-expr $py 2>&1) | Out-String
if ($out -notmatch "PHONE_CONTROL_OK") {
    Write-Host $out -ForegroundColor Yellow
    throw "Blender did not confirm the addon was enabled (see output above)"
}

# --- 6. firewall -------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$ruleName = "Blender Phone Control"
if ($isAdmin) {
    Write-Step "Adding firewall rule (TCP $Port, Private networks)"
    Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -Action Allow | Out-Null
} else {
    Write-Host ""
    Write-Host "Not running as Administrator, so the firewall rule was NOT added." -ForegroundColor Yellow
    Write-Host "Either click 'Allow' when Windows asks the first time Blender starts the server," 
    Write-Host "or run this in an admin PowerShell:"
    Write-Host "  New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Protocol TCP -LocalPort $Port -Profile Private -Action Allow"
}

# --- 7. what next -------------------------------------------------------------
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
       ForEach-Object IPAddress
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "1. Start (or restart) Blender - the server starts automatically."
Write-Host "2. In the 3D Viewport press N > Phone tab to see the PIN."
Write-Host "3. On your phone (same Wi-Fi) open:"
foreach ($ip in $ips) { Write-Host "     http://$ip`:$Port" -ForegroundColor Green }
Write-Host "   Make sure your Wi-Fi is set to 'Private' in Windows network settings."
