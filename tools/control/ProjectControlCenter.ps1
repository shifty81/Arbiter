[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$Command,
    [string]$LogPath,
    [switch]$NonInteractive
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}
$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = @()
if ($null -eq $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $python) { $prefix = @('-3') }
}
if ($null -eq $python) { throw 'Cortex PCC requires Python 3, but python/py was not found.' }
$pcc = Join-Path $PSScriptRoot 'CortexPCC.py'
if (-not (Test-Path -LiteralPath $pcc -PathType Leaf)) { throw "Cortex Python PCC is missing: $pcc" }
$action = if ([string]::IsNullOrWhiteSpace($Command)) { 'interactive' } else { $Command.Trim().ToLowerInvariant() }
$map = @{
    'status'='status'; 'quick'='quick'; 'fast'='fast'; 'full'='full';
    'patch-status'='patch-status'; 'patch-apply'='patch-apply'; 'debug-bundle'='debug-bundle';
    'git-status'='git-status'; 'git-verify'='git-verify'; 'build'='build';
    'build-release'='build-release'; 'launch-gui'='launch-gui'; 'self-test'='self-test';
    'doctor'='doctor'; 'doctor-json'='doctor-json'; 'root-hygiene'='root-hygiene';
    'root-hygiene-fix'='root-hygiene-fix'; 'artifact-status'='artifact-status';
    'artifact-prune'='artifact-prune'; 'artifact-prune-apply'='artifact-prune-apply';
    'verify-latest-debug'='verify-latest-debug'
}
if ($action -ne 'interactive' -and -not $map.ContainsKey($action)) { throw "Unknown headless PCC command: $Command" }
if ($map.ContainsKey($action)) { $action = $map[$action] }
& $python.Source @prefix $pcc $action '--root' $ProjectRoot
exit $LASTEXITCODE
