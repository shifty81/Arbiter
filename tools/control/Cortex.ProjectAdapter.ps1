Set-StrictMode -Version Latest
function Get-CortexAdapterInfo {
    param([string]$ProjectRoot)
    $cargo = Test-Path -LiteralPath (Join-Path $ProjectRoot 'Cargo.toml') -PathType Leaf
    $desktopCandidates = @('target\debug\cortex_desktop.exe','target\debug\cortex.exe','target\release\cortex_desktop.exe','target\release\cortex.exe')
    $ready = @($desktopCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $ProjectRoot $_) -PathType Leaf })
    [pscustomobject]@{ CargoWorkspace=$cargo; RunnableCount=$ready.Count; Runnables=$ready }
}
function Invoke-CortexAdapterCommand {
    param([string]$ProjectRoot,[string]$Command)
    Push-Location $ProjectRoot
    try {
        switch ($Command) {
            'metadata' { & cargo metadata --format-version 1 --no-deps; return $LASTEXITCODE }
            'fmt'      { & cargo fmt --all -- --check; return $LASTEXITCODE }
            'check'    { & cargo check --workspace --all-targets; return $LASTEXITCODE }
            'test'     { & cargo test --workspace --all-targets; return $LASTEXITCODE }
            'clippy'   { & cargo clippy --workspace --all-targets -- -D warnings; return $LASTEXITCODE }
            'build'    { & cargo build --workspace; return $LASTEXITCODE }
            'release'  { & cargo build --workspace --release; return $LASTEXITCODE }
            default { throw "Unknown Cortex adapter command: $Command" }
        }
    } finally { Pop-Location }
}
