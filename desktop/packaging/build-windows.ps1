<#
.SYNOPSIS
    Build FlowSense.exe with PyInstaller and verify it with the built-in self-check.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File desktop\packaging\build-windows.ps1
#>
param([string]$Python = "")

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
$env:PYTHONUTF8 = "1"

# Default: the README's .venv, else a backend-only dev venv, else whatever python is on PATH.
if (-not $Python) {
    $Python = @(".venv\Scripts\python.exe", "backend\.venv\Scripts\python.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Python) { $Python = "python" }
}

& $Python -m PyInstaller desktop\packaging\flowsense.spec --distpath build\dist --workpath build\work --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = "build\dist\FlowSense\FlowSense.exe"
$size = (Get-ChildItem build\dist\FlowSense -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Built {0} ({1:N0} MB)" -f $exe, $size)

# The self-check needs PostgreSQL; it starts its own server on a spare port.
$check = Start-Process -FilePath $exe -ArgumentList "--check", "--url", "http://127.0.0.1:8099" -Wait -PassThru -NoNewWindow
if ($check.ExitCode -ne 0) { throw "Self-check failed (exit $($check.ExitCode)); see %LOCALAPPDATA%\FlowSense\logs" }
Write-Host "Install it with: powershell -ExecutionPolicy Bypass -File desktop\packaging\install-windows.ps1"
