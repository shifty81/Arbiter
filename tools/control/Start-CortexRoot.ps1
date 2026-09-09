[CmdletBinding()]
param([string]$ProjectRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
& (Join-Path $PSScriptRoot 'ProjectControlCenter.ps1') -ProjectRoot $ProjectRoot
exit $LASTEXITCODE
