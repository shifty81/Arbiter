[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath
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

$checks = @()
function Add-Check([string]$Name,[bool]$Pass,[string]$Detail) {
    $script:checks += [pscustomobject]@{ name=$Name; pass=$Pass; detail=$Detail }
    Emit ($(if ($Pass) {'PASS'} else {'FAIL'})) "$Name - $Detail"
}

$required = @(
    'PROJECT_CONTROL_CENTER.cmd',
    'tools\control\ProjectControlCenter.ps1',
    'tools\control\InvokeRootPatchIntake.ps1',
    'tools\control\New-CortexDebugBundle.ps1',
    'tools\control\Test-CortexQuickGate.ps1',
    'tools\control\GitSourceControl.ps1',
    'tools\control\CortexGitAuthority.py',
    'tools\control\Invoke-CortexArtifactMaintenance.ps1',
    'tools\control\Test-CortexRootSelfAudit.ps1'
)
foreach ($relative in $required) {
    $path = Join-Path $ProjectRoot $relative
    Add-Check "required:$relative" (Test-Path -LiteralPath $path -PathType Leaf) $path
}

$controlRoot = Join-Path $ProjectRoot 'tools\control'
$parseFailures = @()
foreach ($file in @(Get-ChildItem -LiteralPath $controlRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in @('.ps1','.psm1') })) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors) | Out-Null
    if (@($errors).Count -gt 0) {
        $parseFailures += "$($file.Name): $($errors[0].Message)"
    }
}
Add-Check 'powershell-parse' ($parseFailures.Count -eq 0) ($(if ($parseFailures.Count -eq 0) {'all control PowerShell parses'} else {$parseFailures -join '; '}))

$controller = Join-Path $controlRoot 'ProjectControlCenter.ps1'
if (Test-Path -LiteralPath $controller) {
    $text = Get-Content -LiteralPath $controller -Raw
    foreach ($token in @(
        'Show-BuildRunMenu',
        'Show-ValidationCertificationMenu',
        'Show-SourceGitMenu',
        'Show-UpdatePatchMenu',
        'Show-ArtifactRecoveryMenu',
        'Invoke-StartupSequence',
        'Invoke-FullGate'
    )) {
        Add-Check "controller:$token" ($text.Contains($token)) $token
    }
    Add-Check 'artifact-log-authority' ($text.Contains("artifacts") -and $text.Contains("logs")) 'controller uses artifact log root'
}

$intake = Join-Path $controlRoot 'InvokeRootPatchIntake.ps1'
if (Test-Path -LiteralPath $intake) {
    $text = Get-Content -LiteralPath $intake -Raw
    foreach ($token in @(
        'cortex.root_patch.v1',
        'PATCH_MANIFEST.json',
        'Post-apply SHA-256 mismatch',
        'cortex.patch_receipt.v1',
        'dependsOn',
        'ValidateOnly'
    )) {
        Add-Check "intake:$token" ($text.Contains($token)) $token
    }
}

$artifactDirs = @(
    'artifacts\logs\sessions',
    'artifacts\debug',
    'artifacts\builds',
    'artifacts\certification',
    'artifacts\patches',
    'artifacts\recovery',
    'artifacts\status'
)
foreach ($relative in $artifactDirs) {
    $path = Join-Path $ProjectRoot $relative
    try {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
        Add-Check "artifact:$relative" $true $path
    } catch {
        Add-Check "artifact:$relative" $false $_.Exception.Message
    }
}

$failed = @($checks | Where-Object { -not $_.pass })
$status = if ($failed.Count -eq 0) { 'GREEN' } else { 'FAIL' }
$outDir = Join-Path $ProjectRoot 'artifacts\certification'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$result = [ordered]@{
    schema = 'cortex.root_self_audit.v1'
    createdUtc = (Get-Date).ToUniversalTime().ToString('o')
    status = $status
    controller = 'CTX-ROOT-09KR6'
    checks = $checks
}
$outPath = Join-Path $outDir 'LATEST_ROOT_SELF_AUDIT.json'
($result | ConvertTo-Json -Depth 8) | Set-Content -LiteralPath $outPath -Encoding UTF8

if ($failed.Count -gt 0) {
    Emit 'FAIL' "Root self-audit failed: $($failed.Count) check(s). Evidence: $outPath"
    exit 1
}
Emit 'PASS' "Root self-audit GREEN. Evidence: $outPath"
exit 0
