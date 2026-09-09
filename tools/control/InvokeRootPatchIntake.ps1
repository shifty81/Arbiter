[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath,
    [switch]$Apply,
    [switch]$ScanOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}

$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console -PathType Leaf) { . $console }

function Emit([string]$Kind, [string]$Message) {
    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) {
        Write-CortexEvent $Kind $Message $LogPath
    } else {
        Write-Host "[$Kind] $Message"
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonPrefix = @()
if ($null -eq $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $python) { $pythonPrefix = @('-3') }
}
if ($null -eq $python) {
    throw 'Cortex patch authority requires Python, but python/py was not found.'
}

$authority = Join-Path $PSScriptRoot 'CortexPatchAuthority.py'
if (-not (Test-Path -LiteralPath $authority -PathType Leaf)) {
    throw "Cortex patch authority is missing: $authority"
}

$action = if ($ScanOnly) { 'scan' } else { 'apply' }
$global:CortexPatchBridgeExitCode = 0
$summary = $null

try {
    $lines = @(& $python.Source @pythonPrefix $authority $action '--root' $ProjectRoot 2>&1)
    $code = $LASTEXITCODE
    $global:CortexPatchBridgeExitCode = $code

    foreach ($item in $lines) {
        $line = [string]$item
        if ($line.StartsWith('PCC_RESULT_JSON=')) {
            $json = $line.Substring('PCC_RESULT_JSON='.Length)
            if (-not [string]::IsNullOrWhiteSpace($json)) {
                $summary = $json | ConvertFrom-Json
            }
            continue
        }
        if ($line -match '^\[(INFO|PASS|WARN|FAIL|DEBUG)\]\s*(.*)$') {
            Emit $Matches[1] $Matches[2]
        } elseif (-not [string]::IsNullOrWhiteSpace($line)) {
            Write-Host $line
        }
    }
} catch {
    $global:CortexPatchBridgeExitCode = 1
    Emit 'FAIL' "Patch authority crashed: $($_.Exception.Message)"
}

if ($null -eq $summary) {
    $summary = [pscustomobject]@{
        Applied = 0
        Pending = 0
        Invalid = 1
        Ignored = 0
        RestartRequired = $false
        Archives = @()
        ValidPatches = @()
        InvalidPatches = @([pscustomobject]@{
            name = '<authority>'
            path = ''
            error = 'Patch authority did not return a machine-readable result.'
        })
        IgnoredZips = @()
    }
}

Write-Output $summary
