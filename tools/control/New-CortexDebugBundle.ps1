[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$Reason = 'MANUAL',
    [string]$LogPath,
    [string]$FailedStage = '',
    [int]$ExitCode = 0,
    [switch]$OpenFolder
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$python = Get-Command python -ErrorAction SilentlyContinue
$prefix = @()
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue; if ($null -ne $python) { $prefix = @('-3') } }
if ($null -eq $python) { throw 'Python 3 is required by Cortex PCC.' }
$argsList = @((Join-Path $PSScriptRoot 'CortexPCC.py'),'debug-bundle','--root',$ProjectRoot,'--reason',$Reason,'--failed-stage',$FailedStage,'--exit-code',[string]$ExitCode)
if ($OpenFolder) { $argsList += '--open-folder' }
& $python.Source @prefix @argsList
exit $LASTEXITCODE
