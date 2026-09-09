[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$pccSource = Join-Path $ProjectRoot 'tools\pcc\src'
if (-not (Test-Path -LiteralPath (Join-Path $pccSource 'pcc\__main__.py') -PathType Leaf)) {
    throw "Universal Python PCC provider source missing: $pccSource"
}

function Test-PccPython311 {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [string[]]$Prefix = @()
    )
    try {
        $versionText = (& $Program @Prefix --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { return $false }
        if ($versionText -notmatch '(?i)Python\s+(\d+)\.(\d+)') { return $false }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        return ($major -gt 3) -or (($major -eq 3) -and ($minor -ge 11))
    } catch {
        return $false
    }
}

$python = $null
$prefix = @()
if (-not [string]::IsNullOrWhiteSpace($env:CORTEX_PCC_PYTHON)) {
    $explicit = Get-Command $env:CORTEX_PCC_PYTHON -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $explicit) {
        throw "CORTEX_PCC_PYTHON could not be resolved: $($env:CORTEX_PCC_PYTHON)"
    }
    if (-not (Test-PccPython311 -Program $explicit.Source)) {
        throw "CORTEX_PCC_PYTHON must resolve to Python 3.11+: $($explicit.Source)"
    }
    $python = $explicit.Source
} else {
    foreach ($candidate in @('python','python3','py')) {
        $resolved = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $resolved) { continue }
        $candidatePrefix = if ($candidate -eq 'py') { @('-3') } else { @() }
        if (Test-PccPython311 -Program $resolved.Source -Prefix $candidatePrefix) {
            $python = $resolved.Source
            $prefix = $candidatePrefix
            break
        }
    }
}
if (-not $python) {
    throw 'Universal Python PCC requires Python 3.11+ (python, python3, or py -3).'
}

$oldPythonPath = $env:PYTHONPATH
try {
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        $env:PYTHONPATH = $pccSource
    } else {
        $env:PYTHONPATH = "$pccSource$([IO.Path]::PathSeparator)$oldPythonPath"
    }
    $argsList = @($prefix) + @('-B','-m','pcc','--project-root',$ProjectRoot)
    if ($ForwardArgs -and $ForwardArgs.Count -gt 0) {
        $argsList += $ForwardArgs
    } else {
        $argsList += @('status')
    }
    & $python @argsList
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
