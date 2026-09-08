[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$Reason = 'MANUAL',
    [string]$LogPath,
    [switch]$OpenFolder
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) { . $console }
function Emit([string]$kind,[string]$msg) { Write-CortexEvent $kind $msg $LogPath }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $ProjectRoot 'artifacts\debug'
$stage = Join-Path $ProjectRoot (".project_control\debug-stage\{0}-{1}" -f $stamp,[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $outDir,$stage | Out-Null
$zipName = "Cortex_DebugBundle_{0}_{1}.zip" -f $stamp,($Reason -replace '[^A-Za-z0-9_-]','_')
$zipPath = Join-Path $outDir $zipName

try {
    $summary = New-Object System.Collections.Generic.List[string]
    $summary.Add('========================================================================')
    $summary.Add(' CORTEX DEBUG / HANDOFF BUNDLE')
    $summary.Add('========================================================================')
    $summary.Add("Created     : $(Get-Date -Format o)")
    $summary.Add("Reason      : $Reason")
    $summary.Add("Repository  : $ProjectRoot")
    $summary.Add("PowerShell  : $($PSVersionTable.PSVersion)")
    $summary.Add("OS          : $([Environment]::OSVersion.VersionString)")
    try { $summary.Add("Cargo       : $(& cargo --version 2>&1)") } catch { $summary.Add('Cargo       : unavailable') }
    try { $summary.Add("Rustc       : $(& rustc --version 2>&1)") } catch { $summary.Add('Rustc       : unavailable') }
    try {
        if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
            Push-Location $ProjectRoot
            $summary.Add("Git branch  : $(& git branch --show-current 2>&1)")
            $summary.Add('Git status  :')
            foreach ($line in @(& git status --short 2>&1)) { $summary.Add("  $line") }
            Pop-Location
        } else { $summary.Add('Git         : Not a repository') }
    } catch { try { Pop-Location } catch {} }
    $summary.Add("Active log  : $LogPath")
    $summary | Set-Content -LiteralPath (Join-Path $stage 'DEBUG_SUMMARY.txt') -Encoding UTF8

    $gitEvidence = New-Object System.Collections.Generic.List[string]
    $gitEvidence.Add('========================================================================')
    $gitEvidence.Add(' CORTEX GIT EVIDENCE')
    $gitEvidence.Add('========================================================================')
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')) {
        try {
            $gitEvidence.Add("Branch=$(git -C $ProjectRoot branch --show-current 2>&1)")
            $gitEvidence.Add("Head=$(git -C $ProjectRoot rev-parse HEAD 2>&1)")
            $gitEvidence.Add("Origin=$(git -C $ProjectRoot remote get-url origin 2>&1)")
            $gitEvidence.Add("Upstream=$(git -C $ProjectRoot rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>&1)")
            $gitEvidence.Add('Status:')
            foreach ($line in @(git -C $ProjectRoot status --porcelain=v1 -uall 2>&1)) {
                $gitEvidence.Add($line)
            }
            $gitEvidence.Add('Ignored operational examples:')
            foreach ($line in @(git -C $ProjectRoot status --porcelain=v1 --ignored --untracked-files=all 2>&1 |
                Where-Object { $_ -like '!! *' } |
                Select-Object -First 80)) {
                $gitEvidence.Add($line)
            }
        } catch {
            $gitEvidence.Add("Git evidence collection failed: $($_.Exception.Message)")
        }
    } else {
        $gitEvidence.Add('Git=Not a repository')
    }
    $gitEvidence | Set-Content -LiteralPath (Join-Path $stage 'GIT_STATUS.txt') -Encoding UTF8

    $sourceDir = Join-Path $stage 'control-source'
    New-Item -ItemType Directory -Force -Path $sourceDir | Out-Null
    $copyFiles = @(
        'Cargo.toml','Cargo.lock','rust-toolchain','rust-toolchain.toml',
        'project.control.json','cortex.integration.json','.gitignore','.gitattributes'
    )
    foreach ($name in $copyFiles) {
        $src = Join-Path $ProjectRoot $name
        if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $sourceDir -Force }
    }
    Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.cmd' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $sourceDir -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $sourceDir -Force -ErrorAction SilentlyContinue

    $ctl = Join-Path $ProjectRoot 'tools\control'
    if (Test-Path -LiteralPath $ctl) {
        $dest = Join-Path $sourceDir 'tools-control'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Get-ChildItem -LiteralPath $ctl -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
        Get-ChildItem -LiteralPath $ctl -Filter '*.py' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    }
    $scripts = Join-Path $ProjectRoot 'scripts'
    if (Test-Path -LiteralPath $scripts) {
        $dest = Join-Path $sourceDir 'scripts'
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Get-ChildItem -LiteralPath $scripts -Filter '*.ps1' -File -ErrorAction SilentlyContinue | Copy-Item -Destination $dest -Force
    }

    $logsDest = Join-Path $stage 'logs'
    New-Item -ItemType Directory -Force -Path $logsDest | Out-Null
    $logsRoot = Join-Path $ProjectRoot 'logs\sessions'
    if (Test-Path -LiteralPath $logsRoot) {
        Get-ChildItem -LiteralPath $logsRoot -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 12 |
            Copy-Item -Destination $logsDest -Force -ErrorAction SilentlyContinue
    }

    $latest = Join-Path $outDir 'LATEST_DEBUG_BUNDLE.txt'
    @(
        "Created=$(Get-Date -Format o)",
        "Reason=$Reason",
        "Bundle=$zipPath",
        "ActiveLog=$LogPath"
    ) | Set-Content -LiteralPath $latest -Encoding UTF8

    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal
    Emit 'PASS' "Debug handoff bundle: $zipPath"
    Write-CortexText " HANDOFF ZIP : $zipPath" 'Accent'

    if ($OpenFolder) {
        try { Start-Process explorer.exe -ArgumentList "`"$outDir`"" | Out-Null } catch { Emit 'WARN' "Could not open debug folder: $($_.Exception.Message)" }
    }
    Write-Output $zipPath
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
}
