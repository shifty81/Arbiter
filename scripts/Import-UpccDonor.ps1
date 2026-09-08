[CmdletBinding(DefaultParameterSetName='Zip')]
param(
    [Parameter(Mandatory=$true, ParameterSetName='Zip')]
    [string]$SourceZip,

    [Parameter(Mandatory=$true, ParameterSetName='Directory')]
    [string]$SourceDirectory,

    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$repo = [System.IO.Path]::GetFullPath($RepoRoot)
$migration = Join-Path $repo 'migration\upcc_v0_6_3'
$donor = Join-Path $migration 'donor'
$manifestPath = Join-Path $migration 'DONOR_MANIFEST.json'

if ((Test-Path -LiteralPath $donor) -and (Get-ChildItem -LiteralPath $donor -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    if (-not $Force) {
        throw "Donor lane is not empty: $donor. Evidence is immutable; use -Force only for an intentional re-import."
    }
    Remove-Item -LiteralPath $donor -Recurse -Force
}
New-Item -ItemType Directory -Path $donor -Force | Out-Null

$temp = $null
try {
    if ($PSCmdlet.ParameterSetName -eq 'Zip') {
        $source = [System.IO.Path]::GetFullPath($SourceZip)
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Source ZIP not found: $source" }
        $temp = Join-Path ([System.IO.Path]::GetTempPath()) ("cortex-upcc-donor-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $temp -Force | Out-Null
        Expand-Archive -LiteralPath $source -DestinationPath $temp -Force
        $copyRoot = $temp
    } else {
        $source = [System.IO.Path]::GetFullPath($SourceDirectory)
        if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Source directory not found: $source" }
        $copyRoot = $source
    }

    # Avoid preserving mutable runtime/output state as donor authority when obvious directories are present.
    $excludedNames = @('state','logs','artifacts','.project-control')
    Get-ChildItem -LiteralPath $copyRoot -Recurse -File -Force | ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($copyRoot, $_.FullName)
        $segments = $relative -split '[\\/]'
        if (@($segments | Where-Object { $excludedNames -contains $_ }).Count -gt 0) { return }
        $dest = Join-Path $donor $relative
        $destDir = Split-Path -Parent $dest
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }

    $files = @()
    Get-ChildItem -LiteralPath $donor -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        $files += [ordered]@{
            path = ([System.IO.Path]::GetRelativePath($donor, $_.FullName) -replace '\\','/')
            bytes = $_.Length
            sha256 = Get-Sha256 $_.FullName
        }
    }
    if ($files.Count -eq 0) { throw 'No donor files were imported.' }

    $manifest = [ordered]@{
        schema_version = 1
        donor_id = 'upcc-0.6.3-B003R3'
        source = $source
        imported_utc = [DateTime]::UtcNow.ToString('o')
        file_count = $files.Count
        files = $files
    }
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Write-Host "Imported immutable donor evidence: $($files.Count) file(s)"
    Write-Host "Manifest: $manifestPath"
    Write-Host "Next: python scripts/validate_upcc_donor.py"
}
finally {
    if ($temp -and (Test-Path -LiteralPath $temp)) {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
