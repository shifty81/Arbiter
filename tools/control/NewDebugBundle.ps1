[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ProjectRoot,[string]$Status='MANUAL')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'; $destDir=Join-Path $ProjectRoot 'artifacts\debug-bundles'; New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$stage=Join-Path ([IO.Path]::GetTempPath()) ('cortex-debug-'+[guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $stage | Out-Null
try {
  $summary=@("CORTEX DEBUG BUNDLE","Timestamp: $stamp","Status: $Status","Root: $ProjectRoot") -join [Environment]::NewLine
  Set-Content -LiteralPath (Join-Path $stage 'SUMMARY.txt') -Value $summary -Encoding UTF8
  foreach($rel in @('project.control.json','Cargo.toml','Cargo.lock','README.md','README_FIRST.md')){ $src=Join-Path $ProjectRoot $rel; if(Test-Path -LiteralPath $src -PathType Leaf){ Copy-Item $src (Join-Path $stage ([IO.Path]::GetFileName($src))) -Force } }
  foreach($rel in @('logs','docs\cortex\projops')){ $src=Join-Path $ProjectRoot $rel; if(Test-Path -LiteralPath $src -PathType Container){ Copy-Item $src (Join-Path $stage ($rel -replace '[\\/:]','_')) -Recurse -Force } }
  $zip=Join-Path $destDir ("Cortex_DebugBundle_${stamp}_${Status}.zip")
  if(Test-Path $zip){ Remove-Item $zip -Force }
  [System.IO.Compression.ZipFile]::CreateFromDirectory($stage,$zip,[System.IO.Compression.CompressionLevel]::Optimal,$false)
  Write-Host "Debug bundle: $zip"; return $zip
} finally { if(Test-Path $stage){ Remove-Item $stage -Recurse -Force } }
