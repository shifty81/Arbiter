[CmdletBinding()]
param(
    [string]$SourceRoot = (Join-Path $env:USERPROFILE 'Desktop\O2DF'),
    [string]$TargetRoot = (Join-Path $env:USERPROFILE 'Desktop\Cortex'),
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Normalize-FullPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'Path may not be empty.' }
    return [System.IO.Path]::GetFullPath($Path.Trim().Trim('"').Trim("'").Trim())
}

$source = Normalize-FullPath $SourceRoot
$target = Normalize-FullPath $TargetRoot

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Source O2DF root does not exist: $source"
}
if (-not (Test-Path -LiteralPath (Join-Path $source 'Cargo.toml') -PathType Leaf)) {
    throw "Source does not look like the expected O2DF Rust workspace: $source"
}
if (-not (Test-Path -LiteralPath (Join-Path $source 'apps\cortex\Cargo.toml') -PathType Leaf)) {
    throw "Source does not contain apps\cortex: $source"
}

New-Item -ItemType Directory -Force -Path $target | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidenceDir = Join-Path $target 'artifacts\migration'
$backupDir = Join-Path $evidenceDir "pre-import-$stamp"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$plan = [System.Collections.Generic.List[object]]::new()

function Add-Plan([string]$Action,[string]$SourceRel,[string]$TargetRel) {
    $plan.Add([ordered]@{ action=$Action; source=$SourceRel; target=$TargetRel })
}

$active = [System.Collections.Generic.List[string]]::new()
foreach ($rel in @('apps\cortex','apps\cortex_desktop','apps\cortex_model_host')) {
    if (Test-Path -LiteralPath (Join-Path $source $rel)) { $active.Add($rel) }
}

$cratesRoot = Join-Path $source 'crates'
if (Test-Path -LiteralPath $cratesRoot -PathType Container) {
    Get-ChildItem -LiteralPath $cratesRoot -Directory -Filter 'cortex_*' |
        Sort-Object Name |
        ForEach-Object {
            if ($_.Name -ne 'cortex_adapter_open2d') {
                $active.Add("crates\$($_.Name)")
            }
        }
}

foreach ($rel in @('extensions\cortex-vscode','config\cortex')) {
    if (Test-Path -LiteralPath (Join-Path $source $rel)) { $active.Add($rel) }
}

foreach ($rel in $active) { Add-Plan 'copy-active' $rel $rel }

$migrationItems = [System.Collections.Generic.List[object]]::new()
if (Test-Path -LiteralPath (Join-Path $source 'crates\cortex_adapter_open2d')) {
    $migrationItems.Add([ordered]@{
        source = 'crates\cortex_adapter_open2d'
        target = 'migration\open2d_adapter\crates\cortex_adapter_open2d'
    })
}
foreach ($dir in @('apps','crates')) {
    $dirPath = Join-Path $source $dir
    if (Test-Path -LiteralPath $dirPath -PathType Container) {
        Get-ChildItem -LiteralPath $dirPath -Directory |
            Where-Object { $_.Name -match '(?i)^open2d.*cortex|cortex.*open2d' } |
            ForEach-Object {
                $migrationItems.Add([ordered]@{
                    source = "$dir\$($_.Name)"
                    target = "migration\open2d_reference\$dir\$($_.Name)"
                })
            }
    }
}
foreach ($item in $migrationItems) { Add-Plan 'quarantine' $item.source $item.target }

foreach ($file in @('rust-toolchain.toml','rust-toolchain','rustfmt.toml','clippy.toml')) {
    if (Test-Path -LiteralPath (Join-Path $source $file) -PathType Leaf) {
        Add-Plan 'copy-root-toolchain' $file $file
    }
}

$schemaRoot = Join-Path $source 'schemas'
if (Test-Path -LiteralPath $schemaRoot -PathType Container) {
    Get-ChildItem -LiteralPath $schemaRoot -File -Filter 'cortex_*' |
        Sort-Object Name |
        ForEach-Object { Add-Plan 'copy-active' "schemas\$($_.Name)" "schemas\$($_.Name)" }
}

foreach ($docRootRel in @('docs\architecture','docs\ai')) {
    $docRoot = Join-Path $source $docRootRel
    if (Test-Path -LiteralPath $docRoot -PathType Container) {
        Get-ChildItem -LiteralPath $docRoot -File -Filter 'CORTEX_*' |
            Sort-Object Name |
            ForEach-Object { Add-Plan 'copy-doc' "$docRootRel\$($_.Name)" "$docRootRel\$($_.Name)" }
    }
}

foreach ($fixtureRoot in @('tests','fixtures')) {
    if (Test-Path -LiteralPath (Join-Path $source $fixtureRoot) -PathType Container) {
        Add-Plan 'quarantine-reference' $fixtureRoot "migration\source_$fixtureRoot"
    }
}

Add-Plan 'preserve-migration-evidence' 'Cargo.toml' 'migration\original-Cargo.toml'
if (Test-Path -LiteralPath (Join-Path $source 'Cargo.lock')) {
    Add-Plan 'preserve-migration-evidence' 'Cargo.lock' 'migration\original-Cargo.lock'
}

Write-Host ''
Write-Host '========================================================================'
Write-Host ' CORTEX STANDALONE LIVE-SOURCE IMPORT'
Write-Host '========================================================================'
Write-Host "Source : $source"
Write-Host "Target : $target"
Write-Host "Mode   : $(if ($Apply) { 'APPLY' } else { 'DRY RUN' })"
Write-Host ''
foreach ($p in $plan) {
    Write-Host ("[{0}] {1} -> {2}" -f $p.action,$p.source,$p.target)
}

if (-not $Apply) {
    Write-Host ''
    Write-Host 'DRY RUN ONLY. No project source was copied.'
    Write-Host 'Re-run with -Apply after reviewing this plan.'
    exit 0
}

$skipNames = @('.git','target','node_modules','artifacts','logs','.open2d','.cortex')
$secretPatterns = @(
    '(?i)(^|[._-])token([._-]|$)',
    '(?i)secret',
    '(?i)credential',
    '(?i)^\.env($|\.)',
    '(?i)\.(pem|pfx|p12|key)$'
)

function Is-SafeFile([System.IO.FileInfo]$File) {
    foreach ($pattern in $secretPatterns) {
        if ($File.Name -match $pattern) { return $false }
    }
    return $true
}

function Backup-IfNeeded([string]$Destination) {
    if (-not (Test-Path -LiteralPath $Destination -PathType Leaf)) { return }
    $rel = [System.IO.Path]::GetRelativePath($target,$Destination)
    $backup = Join-Path $backupDir $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
    Copy-Item -LiteralPath $Destination -Destination $backup -Force
}

function Copy-SafeTree([string]$SourceRel,[string]$TargetRel) {
    $src = Join-Path $source $SourceRel
    $dst = Join-Path $target $TargetRel
    if (-not (Test-Path -LiteralPath $src)) { return }

    if (Test-Path -LiteralPath $src -PathType Leaf) {
        $fi = Get-Item -LiteralPath $src
        if (-not (Is-SafeFile $fi)) { return }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Backup-IfNeeded $dst
        Copy-Item -LiteralPath $src -Destination $dst -Force
        return
    }

    Get-ChildItem -LiteralPath $src -Recurse -File -Force | ForEach-Object {
        if (-not (Is-SafeFile $_)) { return }

        $relativeWithin = [System.IO.Path]::GetRelativePath($src,$_.FullName)
        $segments = $relativeWithin -split '[\\/]'
        if (@($segments | Where-Object { $skipNames -contains $_ }).Count -gt 0) { return }

        $dest = Join-Path $dst $relativeWithin
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Backup-IfNeeded $dest
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
}

foreach ($p in $plan) {
    Copy-SafeTree $p.source $p.target
}

# Build a standalone workspace root using only materialized Cortex members while
# retaining inherited workspace dependency/package/profile sections from the
# source Cargo.toml. Open2D-specific dependencies that remain are intentionally
# left visible for the boundary audit rather than silently rewritten.
$memberPaths = [System.Collections.Generic.List[string]]::new()
foreach ($dir in @('apps','crates')) {
    $dirPath = Join-Path $target $dir
    if (-not (Test-Path -LiteralPath $dirPath -PathType Container)) { continue }

    Get-ChildItem -LiteralPath $dirPath -Directory | Sort-Object Name | ForEach-Object {
        $manifest = Join-Path $_.FullName 'Cargo.toml'
        if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { return }

        if ($dir -eq 'apps') {
            if ($_.Name -notin @('cortex','cortex_desktop','cortex_model_host')) { return }
        } else {
            if (-not $_.Name.StartsWith('cortex_')) { return }
            if ($_.Name -eq 'cortex_adapter_open2d') { return }
        }

        $memberPaths.Add(([System.IO.Path]::GetRelativePath($target,$_.FullName).Replace('\','/')))
    }
}

$originalCargo = Get-Content -LiteralPath (Join-Path $source 'Cargo.toml') -Raw
$workspaceMatch = [regex]::Match($originalCargo,'(?ms)^\[workspace\]\s*(.*?)(?=^\[|\z)')
$resolver = '2'
if ($workspaceMatch.Success) {
    $resolverMatch = [regex]::Match($workspaceMatch.Groups[1].Value,'(?m)^\s*resolver\s*=\s*"([^"]+)"')
    if ($resolverMatch.Success) { $resolver = $resolverMatch.Groups[1].Value }
}
$remainder = if ($workspaceMatch.Success) {
    $originalCargo.Remove($workspaceMatch.Index,$workspaceMatch.Length).TrimStart()
} else {
    $originalCargo
}

$workspaceLines = [System.Collections.Generic.List[string]]::new()
$workspaceLines.Add('[workspace]')
$workspaceLines.Add("resolver = `"$resolver`"")
$workspaceLines.Add('members = [')
foreach ($member in $memberPaths) {
    $workspaceLines.Add("    `"$member`",")
}
$workspaceLines.Add(']')
$workspaceLines.Add('')
$workspaceText = ($workspaceLines -join [Environment]::NewLine) + [Environment]::NewLine + $remainder

$cargoTarget = Join-Path $target 'Cargo.toml'
Backup-IfNeeded $cargoTarget
[System.IO.File]::WriteAllText($cargoTarget,$workspaceText,[System.Text.UTF8Encoding]::new($false))

# Never transplant the source Cargo.lock as active authority.
$activeLock = Join-Path $target 'Cargo.lock'
if (Test-Path -LiteralPath $activeLock) {
    Backup-IfNeeded $activeLock
    Remove-Item -LiteralPath $activeLock -Force
}

$files = Get-ChildItem -LiteralPath $target -Recurse -File -Force |
    Where-Object {
        $_.FullName -notmatch '[\\/](target|artifacts|logs|\.git)[\\/]'
    } |
    ForEach-Object {
        [ordered]@{
            path = [System.IO.Path]::GetRelativePath($target,$_.FullName).Replace('\','/')
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

$importManifest = [ordered]@{
    schema_version = 1
    import_id = "CORTEX-C0-IMPORT-$stamp"
    generated_local = (Get-Date).ToString('o')
    source_root = $source
    target_root = $target
    source_mutated = $false
    active_member_count = $memberPaths.Count
    active_members = @($memberPaths)
    quarantined_open2d_items = @($migrationItems)
    file_count = @($files).Count
    files = @($files)
    next = 'Run scripts\Test-CortexStandaloneBoundary.ps1 and use its blockers as the C1 dependency-detachment queue.'
}

$manifestPath = Join-Path $evidenceDir "CORTEX_IMPORT_MANIFEST_$stamp.json"
$importManifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $manifestPath -Encoding utf8

Write-Host ''
Write-Host "[PASS] Live Cortex source materialized into: $target"
Write-Host "[PASS] Active Cargo members: $($memberPaths.Count)"
Write-Host "[PASS] Import manifest: $manifestPath"
if (Test-Path -LiteralPath $backupDir) {
    $backupCount = @(Get-ChildItem -LiteralPath $backupDir -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($backupCount -gt 0) {
        Write-Host "[PASS] Pre-overwrite backups: $backupDir ($backupCount file(s))"
    } else {
        Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host ''
Write-Host 'Run the standalone boundary audit next:'
Write-Host '  pwsh -NoProfile -File .\scripts\Test-CortexStandaloneBoundary.ps1'
