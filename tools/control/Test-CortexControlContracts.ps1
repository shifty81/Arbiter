[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$LogPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
} else {
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
}

$console = Join-Path $PSScriptRoot 'Cortex.Console.ps1'
if (Test-Path -LiteralPath $console) {
    . $console
}

function Emit {
    param([string]$Kind, [string]$Message)

    if (Get-Command Write-CortexEvent -ErrorAction SilentlyContinue) {
        Write-CortexEvent $Kind $Message $LogPath
    } else {
        Write-Host "[$Kind] $Message"
    }
}

function Get-ScriptParameterNames {
    param([Parameter(Mandatory=$true)]$Ast)

    if ($null -eq $Ast.ParamBlock) {
        return @()
    }

    return @(
        $Ast.ParamBlock.Parameters |
            ForEach-Object { $_.Name.VariablePath.UserPath }
    )
}

$failed = $false
$asts = @{}

# Every control PowerShell file must parse. This is the primary control-spine truth gate.
$controlScripts = @(
    Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Extension -in @('.ps1', '.psm1') } |
        Sort-Object FullName
)

foreach ($file in $controlScripts) {
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )

    if (@($parseErrors).Count -gt 0) {
        Emit 'FAIL' ("PowerShell parse failure in {0}: {1}" -f $file.Name, $parseErrors[0].Message)
        $failed = $true
        continue
    }

    $asts[$file.Name] = $ast
}

# Only scripts actually invoked with named parameters have parameter contracts here.
# ProjectControlCenter.ps1 is intentionally launched by PROJECT_CONTROL_CENTER.cmd
# without named arguments in the recovered, known-good baseline.
$contracts = @(
    @{ File='InvokeRootPatchIntake.ps1'; Required=@('ProjectRoot','LogPath','Apply','ScanOnly') },
    @{ File='Test-CortexQuickGate.ps1'; Required=@('ProjectRoot','LogPath') },
    @{ File='New-CortexDebugBundle.ps1'; Required=@('ProjectRoot','Reason','LogPath','OpenFolder') },
    @{ File='Start-CortexRoot.ps1'; Required=@('ProjectRoot','Command') }
)

foreach ($contract in $contracts) {
    $path = Join-Path $PSScriptRoot $contract.File

    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Emit 'FAIL' ("Control contract file missing: {0}" -f $contract.File)
        $failed = $true
        continue
    }

    if (-not $asts.ContainsKey($contract.File)) {
        # A parse failure was already reported above.
        $failed = $true
        continue
    }

    $parameterNames = @(Get-ScriptParameterNames -Ast $asts[$contract.File])

    foreach ($required in $contract.Required) {
        if ($required -notin $parameterNames) {
            Emit 'FAIL' ("Parameter contract mismatch: {0} missing -{1}" -f $contract.File, $required)
            $failed = $true
        }
    }
}

if ($failed) {
    Emit 'FAIL' 'Cortex root control contracts FAILED.'
    exit 1
}

Emit 'PASS' ("Cortex root control contracts valid: {0} PowerShell files parsed." -f $controlScripts.Count)
exit 0
