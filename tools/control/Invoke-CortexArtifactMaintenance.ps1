[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath,
    [int]$KeepSessionPairs = 40,
    [int]$KeepDebugBundles = 24,
    [switch]$Prune
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)

$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }

function Emit([string]$kind,[string]$message) {
    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) {
        Write-CortexEvent $kind $message $LogPath
    } else {
        Write-Host "[$kind] $message"
    }
}

$artifacts = Join-Path $ProjectRoot 'artifacts'
$logs = Join-Path $artifacts 'logs\sessions'
$debug = Join-Path $artifacts 'debug'
$builds = Join-Path $artifacts 'builds'
$status = Join-Path $artifacts 'status'
$cert = Join-Path $artifacts 'certification'
$patches = Join-Path $artifacts 'patches'
$recovery = Join-Path $artifacts 'recovery'
New-Item -ItemType Directory -Force -Path @($artifacts,$logs,$debug,$builds,$status,$cert,$patches,$recovery) | Out-Null

$summary = [ordered]@{
    schema = 'cortex.artifact_maintenance.v1'
    createdUtc = (Get-Date).ToUniversalTime().ToString('o')
    projectRoot = $ProjectRoot
    pruneRequested = [bool]$Prune
    removedSessionLogs = 0
    removedDebugBundles = 0
    sessionLogCount = 0
    debugBundleCount = 0
    latestSessionLog = $null
    latestDebugBundle = $null
}

$sessionFiles = @(Get-ChildItem -LiteralPath $logs -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne 'LATEST_ROOT_SESSION.txt' } | Sort-Object LastWriteTime -Descending)
$debugFiles = @(Get-ChildItem -LiteralPath $debug -Filter 'Cortex_DebugBundle_*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)

$summary.sessionLogCount = $sessionFiles.Count
$summary.debugBundleCount = $debugFiles.Count
if ($sessionFiles.Count -gt 0) { $summary.latestSessionLog = $sessionFiles[0].FullName }
if ($debugFiles.Count -gt 0) { $summary.latestDebugBundle = $debugFiles[0].FullName }

if ($Prune) {
    if ($KeepSessionPairs -lt 4) { $KeepSessionPairs = 4 }
    if ($KeepDebugBundles -lt 4) { $KeepDebugBundles = 4 }

    # Session files are log/transcript pairs, so retain twice the requested pair count.
    $keepSessionFiles = $KeepSessionPairs * 2
    foreach ($file in @($sessionFiles | Select-Object -Skip $keepSessionFiles)) {
        try {
            Remove-Item -LiteralPath $file.FullName -Force
            $summary.removedSessionLogs++
        } catch {
            Emit 'WARN' "Could not prune session log $($file.Name): $($_.Exception.Message)"
        }
    }

    foreach ($file in @($debugFiles | Select-Object -Skip $KeepDebugBundles)) {
        try {
            Remove-Item -LiteralPath $file.FullName -Force
            $summary.removedDebugBundles++
        } catch {
            Emit 'WARN' "Could not prune debug bundle $($file.Name): $($_.Exception.Message)"
        }
    }
}

$latestSessionPointer = Join-Path $logs 'LATEST_ROOT_SESSION.txt'
@(
    "Created=$(Get-Date -Format o)",
    "Latest=$($summary.latestSessionLog)"
) | Set-Content -LiteralPath $latestSessionPointer -Encoding UTF8

$latestArtifactStatus = Join-Path $status 'LATEST_ARTIFACT_STATUS.json'
($summary | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $latestArtifactStatus -Encoding UTF8

Emit 'PASS' "Artifact maintenance status written: $latestArtifactStatus"
if ($Prune) {
    Emit 'PASS' ("Artifact pruning complete: {0} session logs, {1} debug bundles removed." -f $summary.removedSessionLogs,$summary.removedDebugBundles)
}
return [pscustomobject]$summary
