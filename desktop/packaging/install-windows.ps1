<#
.SYNOPSIS
    Install (or remove) the FlowSense desktop app for the current user. No admin rights needed.

.DESCRIPTION
    Copies the PyInstaller build (build\dist\FlowSense) to %LOCALAPPDATA%\Programs\FlowSense and adds
    Start Menu and Desktop shortcuts. Your data stays in PostgreSQL and your settings in
    %APPDATA%\FlowSense, so uninstalling never deletes them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File desktop\packaging\install-windows.ps1
    powershell -ExecutionPolicy Bypass -File desktop\packaging\install-windows.ps1 -Uninstall
#>
param(
    [string]$Source = (Join-Path $PSScriptRoot "..\..\build\dist\FlowSense"),
    [switch]$NoDesktopShortcut,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FlowSense"
$StartMenuLink = Join-Path ([Environment]::GetFolderPath("Programs")) "FlowSense.lnk"
$DesktopLink = Join-Path ([Environment]::GetFolderPath("Desktop")) "FlowSense.lnk"

function Remove-FlowSense {
    Get-Process FlowSense -ErrorAction SilentlyContinue | Stop-Process -Force
    foreach ($path in @($StartMenuLink, $DesktopLink)) {
        if (Test-Path $path) { Remove-Item $path -Force }
    }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
}

if ($Uninstall) {
    Remove-FlowSense
    Write-Host "FlowSense removed. Your settings remain in $env:APPDATA\FlowSense."
    exit 0
}

$exe = Join-Path $Source "FlowSense.exe"
if (-not (Test-Path $exe)) {
    throw "No build found at $Source. Build it first: powershell -ExecutionPolicy Bypass -File desktop\packaging\build-windows.ps1"
}

Remove-FlowSense  # clean upgrade: never mix files from two versions
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $Source "*") -Destination $InstallDir -Recurse -Force

$shell = New-Object -ComObject WScript.Shell
$targets = @($StartMenuLink)
if (-not $NoDesktopShortcut) { $targets += $DesktopLink }
foreach ($linkPath in $targets) {
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = Join-Path $InstallDir "FlowSense.exe"
    $link.WorkingDirectory = $InstallDir
    $link.IconLocation = (Join-Path $InstallDir "FlowSense.exe") + ",0"
    $link.Description = "FlowSense: deep work, measured"
    $link.Save()
}

Write-Host "FlowSense installed to $InstallDir"
Write-Host "Start it from the Start Menu$(if (-not $NoDesktopShortcut) { ' or the Desktop shortcut' })."
Write-Host "Check the setup any time: & '$InstallDir\FlowSense.exe' --check"
