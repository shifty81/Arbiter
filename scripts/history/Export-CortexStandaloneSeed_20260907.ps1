[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$SourceRoot = (Get-Location).Path,

    [string]$OutputDirectory,

    [switch]$KeepStage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-FullPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path may not be empty."
    }
    return [System.IO.Path]::GetFullPath($Path)
}

$SourceRoot = Resolve-FullPath $SourceRoot
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Source root does not exist: $SourceRoot"
}

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $SourceRoot 'artifacts\cortex-detachment'
}
$OutputDirectory = Resolve-FullPath $OutputDirectory
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stage = Join-Path $OutputDirectory ("Cortex_StandaloneSeed_STAGE_" + $stamp)
$zipPath = Join-Path $OutputDirectory ("Cortex_StandaloneSeed_" + $stamp + ".zip")
$manifestPath = Join-Path $OutputDirectory ("Cortex_StandaloneSeed_" + $stamp + ".manifest.json")
$shaPath = $zipPath + '.sha256'

New-Item -ItemType Directory -Path $stage -Force | Out-Null

$excludedNamePatterns = @(
    '*.token*','*secret*','*credential*','*.key','*.pem','*.pfx','*.p12'
)

function Test-SafeSourceFile([System.IO.FileInfo]$File) {
    foreach ($pattern in $excludedNamePatterns) {
        if ($File.Name -like $pattern) { return $false }
    }
    return $true
}

function Copy-RelativeTree([string]$Relative, [string]$DestinationRelative = $Relative) {
    $src = Join-Path $SourceRoot $Relative
    if (-not (Test-Path -LiteralPath $src)) { return }
    $dst = Join-Path $stage $DestinationRelative
    if (Test-Path -LiteralPath $src -PathType Leaf) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
        return
    }

    Get-ChildItem -LiteralPath $src -Recurse -File -Force | ForEach-Object {
        if (-not (Test-SafeSourceFile $_)) { return }
        $rel = [System.IO.Path]::GetRelativePath($src, $_.FullName)
        if ($rel -match '(^|[\\/])(target|node_modules|artifacts|logs|\.git|\.open2d|\.cortex)([\\/]|$)') { return }
        $target = Join-Path $dst $rel
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $target -Force
    }
}

# Standalone applications.
foreach ($app in @('apps\cortex','apps\cortex_desktop','apps\cortex_model_host')) {
    Copy-RelativeTree $app
}

# Generic Cortex crates. The Open2D adapter is deliberately quarantined as migration evidence.
$cratesRoot = Join-Path $SourceRoot 'crates'
if (Test-Path -LiteralPath $cratesRoot) {
    Get-ChildItem -LiteralPath $cratesRoot -Directory -Filter 'cortex_*' | ForEach-Object {
        if ($_.Name -eq 'cortex_adapter_open2d') {
            Copy-RelativeTree ("crates\" + $_.Name) ("migration\open2d_adapter\crates\" + $_.Name)
        } else {
            Copy-RelativeTree ("crates\" + $_.Name)
        }
    }
}

Copy-RelativeTree 'extensions\cortex-vscode'
Copy-RelativeTree 'config\cortex'

# Schemas and docs are selected by Cortex naming so unrelated Open2D material does not migrate.
$schemaRoot = Join-Path $SourceRoot 'schemas'
if (Test-Path -LiteralPath $schemaRoot) {
    Get-ChildItem -LiteralPath $schemaRoot -File -Filter 'cortex_*' | ForEach-Object {
        Copy-RelativeTree ("schemas\" + $_.Name)
    }
}
foreach ($docRootRel in @('docs\architecture','docs\ai')) {
    $docRoot = Join-Path $SourceRoot $docRootRel
    if (Test-Path -LiteralPath $docRoot) {
        Get-ChildItem -LiteralPath $docRoot -File -Filter 'CORTEX_*' | ForEach-Object {
            Copy-RelativeTree (Join-Path $docRootRel $_.Name)
        }
    }
}

# Current Cortex scripts are useful migration evidence but should not automatically become
# standalone authority until their Open2D assumptions are audited.
$scriptsRoot = Join-Path $SourceRoot 'scripts'
if (Test-Path -LiteralPath $scriptsRoot) {
    Get-ChildItem -LiteralPath $scriptsRoot -File | Where-Object {
        $_.Name -match 'Cortex'
    } | ForEach-Object {
        Copy-RelativeTree ("scripts\" + $_.Name) ("migration\open2d_scripts\" + $_.Name)
    }
}

# Preserve original root Cargo metadata only as migration evidence; the standalone workspace
# must generate a new Cargo.lock after project-specific dependencies are removed.
foreach ($file in @('Cargo.toml','Cargo.lock')) {
    if (Test-Path -LiteralPath (Join-Path $SourceRoot $file)) {
        Copy-RelativeTree $file ("migration\original-" + $file)
    }
}

# Dependency-edge audit. This is intentionally conservative and only reports.
$edges = @()
Get-ChildItem -LiteralPath $stage -Recurse -File -Filter 'Cargo.toml' | ForEach-Object {
    $cargoPath = $_.FullName
    $text = Get-Content -LiteralPath $cargoPath -Raw
    $matches = [regex]::Matches(
        $text,
        '(?m)^\s*([A-Za-z0-9_-]+)\s*=\s*\{[^\r\n}]*path\s*=\s*"([^"]+)"[^\r\n}]*\}'
    )
    foreach ($m in $matches) {
        $dep = $m.Groups[1].Value
        $path = $m.Groups[2].Value
        if (-not $dep.StartsWith('cortex_')) {
            $edges += [ordered]@{
                cargo = [System.IO.Path]::GetRelativePath($stage, $cargoPath)
                dependency = $dep
                path = $path
                classification = 'non-cortex-path-dependency'
            }
        }
    }
}

# Also detect direct textual Open2D coupling in active Cortex source.
$open2dRefs = @()
Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/]migration[\\/]'
    $_.Extension -in @('.rs','.toml','.json','.md','.ts')
} | ForEach-Object {
    $hits = Select-String -LiteralPath $_.FullName -Pattern 'open2d_' -SimpleMatch -ErrorAction SilentlyContinue
    if ($hits) {
        $open2dRefs += [ordered]@{
            file = [System.IO.Path]::GetRelativePath($stage, $_.FullName)
            matches = @($hits).Count
        }
    }
}

# File manifest.
$files = Get-ChildItem -LiteralPath $stage -Recurse -File | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    [ordered]@{
        path = [System.IO.Path]::GetRelativePath($stage, $_.FullName).Replace('\','/')
        bytes = $_.Length
        sha256 = $hash.Hash.ToLowerInvariant()
    }
}

$seedManifest = [ordered]@{
    schema_version = 1
    purpose = 'Cortex standalone live-source detachment seed'
    generated_local = (Get-Date).ToString('o')
    source_root = $SourceRoot
    source_mutated = $false
    file_count = @($files).Count
    files = @($files)
    migration_blockers = [ordered]@{
        non_cortex_path_dependencies = @($edges)
        active_open2d_text_references = @($open2dRefs)
    }
    notes = @(
        'cortex_adapter_open2d is quarantined under migration/open2d_adapter and is not standalone core authority.',
        'original Cargo.toml/Cargo.lock are migration evidence only.',
        'generate a fresh standalone workspace and Cargo.lock after dependency normalization.'
    )
}
$seedManifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $stage 'CORTEX_STANDALONE_SEED_MANIFEST.json') -Encoding utf8NoBOM

if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zipPath -CompressionLevel Optimal

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$external = [ordered]@{
    schema_version = 1
    artifact = $zipPath
    sha256 = $zipHash
    generated_local = (Get-Date).ToString('o')
    source_root = $SourceRoot
    file_count = @($files).Count
    non_cortex_path_dependency_count = @($edges).Count
    active_open2d_reference_file_count = @($open2dRefs).Count
}
$external | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM
("$zipHash  " + [System.IO.Path]::GetFileName($zipPath)) | Set-Content -LiteralPath $shaPath -Encoding ascii

Write-Host ""
Write-Host "Cortex standalone seed created:"
Write-Host "  ZIP      : $zipPath"
Write-Host "  SHA-256  : $zipHash"
Write-Host "  Manifest : $manifestPath"
Write-Host "  Blockers : $(@($edges).Count) non-Cortex path dependency edge(s), $(@($open2dRefs).Count) active file(s) containing open2d_ references"

if (-not $KeepStage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
