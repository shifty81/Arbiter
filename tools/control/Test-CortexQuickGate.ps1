[CmdletBinding()]
param([string]$ProjectRoot,[string]$LogPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = @()
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue; if ($null -ne $python) { $prefix = @('-3') } }
if ($null -eq $python) { Write-Error 'Python 3 is required by Cortex PCC.'; exit 1 }
& $python.Source @prefix (Join-Path $PSScriptRoot 'CortexPCC.py') quick '--root' $ProjectRoot '--no-evidence'
exit $LASTEXITCODE
