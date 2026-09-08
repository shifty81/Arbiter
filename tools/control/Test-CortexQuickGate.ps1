[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }
function Emit([string]$kind,[string]$msg) { Write-CortexEvent $kind $msg $LogPath }

Emit 'INFO' 'START Cortex startup quick gate'
$failed = $false

$contractScript = Join-Path $PSScriptRoot 'Test-CortexControlContracts.ps1'
if (Test-Path -LiteralPath $contractScript -PathType Leaf) {
    & $contractScript -ProjectRoot $ProjectRoot -LogPath $LogPath
    if ($LASTEXITCODE -ne 0) {
        Emit 'FAIL' 'Root control contract validation failed.'
        $failed = $true
    }
} else {
    Emit 'FAIL' 'Root control contract validator is missing.'
    $failed = $true
}


if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'Cargo.toml')) { Emit 'PASS' 'Cargo workspace manifest present.' } else { Emit 'FAIL' 'Cargo.toml missing.'; $failed = $true }
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($cargo) { Emit 'PASS' ("Cargo ready: " + (& cargo --version)) } else { Emit 'FAIL' 'cargo not found on PATH.'; $failed = $true }
$rustc = Get-Command rustc -ErrorAction SilentlyContinue
if ($rustc) { Emit 'PASS' ("Rustc ready: " + (& rustc --version)) } else { Emit 'WARN' 'rustc not found on PATH.' }

if (-not $failed -and $cargo) {
    Push-Location $ProjectRoot
    try {
        $metaFile = Join-Path $env:TEMP ("cortex-metadata-{0}.json" -f [guid]::NewGuid().ToString('N'))
        & cargo metadata --no-deps --format-version 1 --quiet | Out-File -LiteralPath $metaFile -Encoding utf8
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $metaFile)) {
            $meta = Get-Content -LiteralPath $metaFile -Raw | ConvertFrom-Json
            Emit 'PASS' ("Workspace metadata valid: {0} packages." -f @($meta.packages).Count)
        } else {
            Emit 'FAIL' 'cargo metadata failed.'
            $failed = $true
        }
        Remove-Item -LiteralPath $metaFile -Force -ErrorAction SilentlyContinue
    } finally { Pop-Location }
}

$control = Join-Path $ProjectRoot 'tools\control\ProjectControlCenter.ps1'
if (Test-Path -LiteralPath $control) { Emit 'PASS' 'Root Project Control Center present.' } else { Emit 'FAIL' 'Root Project Control Center missing.'; $failed = $true }

if ($failed) {
    Emit 'FAIL' 'Cortex startup quick gate FAILED.'
    exit 1
}
Emit 'PASS' 'Cortex startup quick gate GREEN.'
exit 0
