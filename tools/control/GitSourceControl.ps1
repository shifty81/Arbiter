# Canonical Cortex Git bridge.
# Deliberately avoids a rigid param(...) block so current and legacy Root Utility
# argument shapes cannot break source control through PowerShell parameter binding.
$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$action = 'Status'
$message = ''
$remote = 'https://github.com/shifty81/Cortex.git'
$positionals = New-Object System.Collections.Generic.List[string]

for ($i = 0; $i -lt $args.Count; $i++) {
    $raw = [string]$args[$i]
    $key = $raw.TrimStart('-').ToLowerInvariant()

    if ($key -in @('root','projectroot','repositoryroot') -and ($i + 1) -lt $args.Count) {
        $root = [string]$args[++$i]
        continue
    }
    if ($key -eq 'action' -and ($i + 1) -lt $args.Count) {
        $action = [string]$args[++$i]
        continue
    }
    if ($key -in @('message','commitmessage') -and ($i + 1) -lt $args.Count) {
        $message = [string]$args[++$i]
        continue
    }
    if ($key -in @('remote','remoteurl','url') -and ($i + 1) -lt $args.Count) {
        $remote = [string]$args[++$i]
        continue
    }
    if (-not $raw.StartsWith('-')) {
        $positionals.Add($raw)
    }
}

if ($positionals.Count -gt 0 -and (Test-Path -LiteralPath $positionals[0])) {
    $root = $positionals[0]
}

$known = @(
    'Status',
    'SummaryJson',
    'Setup',
    'Repair',
    'Review',
    'MarkGreen',
    'CommitGreen',
    'CommitPushGreen',
    'Push',
    'Fetch',
    'Compare',
    'History',
    'Verify',
    'Pull',
    'CommitManual',
    'ManualCommit'
)

foreach ($value in $positionals) {
    if ($known -contains $value) {
        $action = $value
        break
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonArgsPrefix = @()
if ($null -eq $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $pythonArgsPrefix = @('-3')
    }
}
if ($null -eq $python) {
    throw 'Cortex Git authority requires Python, but python/py was not found.'
}

$authority = Join-Path $PSScriptRoot 'CortexGitAuthority.py'
if (-not (Test-Path -LiteralPath $authority -PathType Leaf)) {
    throw "Cortex Git authority is missing: $authority"
}

$normalized = $action.Trim().ToLowerInvariant().Replace('-','').Replace('_','')
$authorityAction = switch ($normalized) {
    'status'          { 'status' }
    'summaryjson'     { 'summary-json' }
    'setup'           { 'setup' }
    'repair'          { 'repair' }
    'review'          { 'review' }
    'markgreen'       { 'mark-green' }
    'commitgreen'     { 'commit-green' }
    'commitpushgreen' { 'commit-push-green' }
    'push'            { 'push' }
    'fetch'           { 'fetch' }
    'compare'         { 'compare' }
    'history'         { 'history' }
    'verify'          { 'verify' }
    'pull'            { 'pull' }
    'commitmanual'    { 'manual-commit' }
    'manualcommit'    { 'manual-commit' }
    default { throw "Unknown Cortex Git action: $action" }
}

$callArgs = @($authority,$authorityAction,'--root',$root,'--remote',$remote)
if (-not [string]::IsNullOrWhiteSpace($message)) {
    $callArgs += @('--message',$message)
}

$global:CortexGitBridgeExitCode = 0
& $python.Source @pythonArgsPrefix @callArgs
$global:CortexGitBridgeExitCode = $LASTEXITCODE
return
