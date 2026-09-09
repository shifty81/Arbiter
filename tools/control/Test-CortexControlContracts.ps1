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

# Console style literals are part of the control-spine contract. A menu must not
# pass startup parsing and then terminate when it renders an unsupported style.
$writeCortexText = Get-Command Write-CortexText -ErrorAction SilentlyContinue
if (-not $writeCortexText) {
    Emit 'FAIL' 'Write-CortexText is unavailable; console style contracts cannot be validated.'
    $failed = $true
} else {
    $styleParameter = $writeCortexText.Parameters['Style']
    $allowedStyles = @(
        $styleParameter.Attributes |
            Where-Object { $_ -is [System.Management.Automation.ValidateSetAttribute] } |
            ForEach-Object { $_.ValidValues }
    )

    if ($allowedStyles.Count -eq 0) {
        Emit 'FAIL' 'Write-CortexText Style has no ValidateSet contract.'
        $failed = $true
    } else {
        $styleFailures = New-Object System.Collections.Generic.List[string]

        foreach ($astEntry in $asts.GetEnumerator()) {
            $commands = @(
                $astEntry.Value.FindAll(
                    {
                        param($node)
                        $node -is [System.Management.Automation.Language.CommandAst] -and
                            $node.GetCommandName() -eq 'Write-CortexText'
                    },
                    $true
                )
            )

            foreach ($commandAst in $commands) {
                $elements = @($commandAst.CommandElements)
                $literalStyle = $null

                for ($i = 1; $i -lt $elements.Count; $i++) {
                    $element = $elements[$i]
                    if ($element -is [System.Management.Automation.Language.CommandParameterAst] -and
                        $element.ParameterName -ieq 'Style') {
                        if (($i + 1) -lt $elements.Count -and
                            $elements[$i + 1] -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
                            $literalStyle = $elements[$i + 1].Value
                        }
                        break
                    }
                }

                # The root controller normally uses positional Style as argument 2.
                if (-not $literalStyle -and
                    $elements.Count -ge 3 -and
                    $elements[2] -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
                    $literalStyle = $elements[2].Value
                }

                if ($literalStyle -and $literalStyle -notin $allowedStyles) {
                    $extent = $commandAst.Extent
                    $styleFailures.Add(
                        ("{0}:{1} unsupported Write-CortexText style '{2}'" -f
                            $astEntry.Key,
                            $extent.StartLineNumber,
                            $literalStyle)
                    ) | Out-Null
                }
            }
        }

        if ($styleFailures.Count -gt 0) {
            foreach ($failure in $styleFailures) {
                Emit 'FAIL' $failure
            }
            $failed = $true
        } else {
            Emit 'PASS' ("Cortex console style contracts valid: {0} styles allowed." -f $allowedStyles.Count)
        }
    }
}

# Only scripts actually invoked with named parameters have parameter contracts here.
# ProjectControlCenter.ps1 is intentionally launched by PROJECT_CONTROL_CENTER.cmd
# without named arguments in the recovered, known-good baseline.
$contracts = @(
    @{ File='InvokeRootPatchIntake.ps1'; Required=@('ProjectRoot','LogPath','Apply','ScanOnly') },
    @{ File='Test-CortexQuickGate.ps1'; Required=@('ProjectRoot','LogPath') },
    @{ File='New-CortexDebugBundle.ps1'; Required=@('ProjectRoot','Reason','FailedStage','ExitCode','LogPath','OpenFolder') },
    @{ File='Test-CortexRootSelfAudit.ps1'; Required=@('ProjectRoot','LogPath','ControllerVersion') },
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


# Source formatting is a deliberate mutation and must never be hidden inside a
# validation gate. Keep the command registered so Python PCC/Cortex can expose
# it later through typed command metadata without weakening gate semantics.
$projectControlPath = Join-Path $ProjectRoot 'project.control.json'
if (-not (Test-Path -LiteralPath $projectControlPath -PathType Leaf)) {
    Emit 'FAIL' 'project.control.json is missing; fmt.apply contract cannot be validated.'
    $failed = $true
} else {
    try {
        $projectControl = Get-Content -LiteralPath $projectControlPath -Raw | ConvertFrom-Json
        $fmtApply = @($projectControl.commands | Where-Object { [string]$_.key -eq 'fmt.apply' })
        if ($fmtApply.Count -ne 1) {
            Emit 'FAIL' 'project.control.json must contain exactly one fmt.apply command.'
            $failed = $true
        } else {
            $command = $fmtApply[0]
            $args = @($command.args | ForEach-Object { [string]$_ })
            $sideEffects = @($command.side_effects | ForEach-Object { [string]$_ })
            if ([string]$command.risk -ne 'local_mutation') {
                Emit 'FAIL' 'fmt.apply must remain risk=local_mutation.'
                $failed = $true
            } elseif (($args -join ' ') -ne 'fmt --all') {
                Emit 'FAIL' 'fmt.apply must remain the exact command: cargo fmt --all.'
                $failed = $true
            } elseif ('source_files' -notin $sideEffects) {
                Emit 'FAIL' 'fmt.apply must declare source_files side effects.'
                $failed = $true
            } else {
                $gateStages = @(
                    $projectControl.quality_gates |
                        ForEach-Object { @($_.stages) } |
                        ForEach-Object { [string]$_ }
                )
                if ('fmt.apply' -in $gateStages) {
                    Emit 'FAIL' 'fmt.apply must not appear in Fast or Full quality gates.'
                    $failed = $true
                } else {
                    Emit 'PASS' 'Explicit Rust formatting contract valid: fmt.apply is registered and outside quality gates.'
                }
            }
        }
    } catch {
        Emit 'FAIL' ("project.control.json fmt.apply contract failed: {0}" -f $_.Exception.Message)
        $failed = $true
    }
}


# Debug bundles must preserve exact, bounded source evidence for compiler failures.
$debugBundlePath = Join-Path $PSScriptRoot 'New-CortexDebugBundle.ps1'
if (-not (Test-Path -LiteralPath $debugBundlePath -PathType Leaf)) {
    Emit 'FAIL' 'New-CortexDebugBundle.ps1 is missing.'
    $failed = $true
} else {
    $debugBundleText = Get-Content -LiteralPath $debugBundlePath -Raw
    foreach ($requiredToken in @(
        'cortex.diagnostic_source_manifest.v1',
        'LATEST_CARGO_DIAGNOSTICS.log',
        'diagnostic-source',
        '$diagnosticFileLimit = 12',
        '$diagnosticTotalLimit = 4194304',
        '\x1B\[',
        'New-ProjectedArtifactStatus',
        'Post-bundle artifact status refresh failed'
    )) {
        if (-not $debugBundleText.Contains($requiredToken)) {
            Emit 'FAIL' ("Debug bundle diagnostic-source contract missing token: {0}" -f $requiredToken)
            $failed = $true
        }
    }
    if (-not $failed) {
        Emit 'PASS' 'Bounded Cargo diagnostic-source evidence contract valid.'
    }
}


# Root certification must never hard-code a stale controller version.
$selfAuditPath = Join-Path $PSScriptRoot 'Test-CortexRootSelfAudit.ps1'
if (Test-Path -LiteralPath $selfAuditPath -PathType Leaf) {
    $selfAuditText = Get-Content -LiteralPath $selfAuditPath -Raw
    if (-not $selfAuditText.Contains('controller = $resolvedControllerVersion') -or
        $selfAuditText.Contains("controller = 'CTX-ROOT-")) {
        Emit 'FAIL' 'Root self-audit controller identity must be dynamically resolved.'
        $failed = $true
    } else {
        Emit 'PASS' 'Root self-audit controller identity is dynamic.'
    }
}

# Every source-control mutation/sync path that can change publication state must
# refresh LATEST_PUBLISHED_STATE.json through Test-CortexPublishedMain.
$controllerPath = Join-Path $PSScriptRoot 'ProjectControlCenter.ps1'
if (Test-Path -LiteralPath $controllerPath -PathType Leaf) {
    $controllerText = Get-Content -LiteralPath $controllerPath -Raw
    foreach ($token in @(
        '$committedGreen = Invoke-CortexGitAction',
        '$pushed = Invoke-CortexGitAction',
        '$pulled = Invoke-CortexGitAction',
        '$setup = Invoke-CortexGitAction',
        '$manualCommitted = Invoke-CortexGitAction'
    )) {
        if (-not $controllerText.Contains($token)) {
            Emit 'FAIL' ("Published-state refresh contract missing Git path token: {0}" -f $token)
            $failed = $true
        }
    }
    if (-not $controllerText.Contains('Test-CortexPublishedMain')) {
        Emit 'FAIL' 'Published-state refresh function is missing from controller.'
        $failed = $true
    } elseif (-not $failed) {
        Emit 'PASS' 'Git publication-state refresh contract valid.'
    }
}

if ($failed) {
    Emit 'FAIL' 'Cortex root control contracts FAILED.'
    exit 1
}

Emit 'PASS' ("Cortex root control contracts valid: {0} PowerShell files parsed." -f $controlScripts.Count)
exit 0
