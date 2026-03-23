# ─── Arbiter — Installer build helper (M8-1) ────────────────────────────────
#
# Prepares all installer inputs then invokes Inno Setup's `iscc` compiler to
# produce  Installer/Output/arbiter-setup-<version>.exe
#
# Requirements
#   • .NET 9 SDK  (dotnet on PATH)
#   • Python 3.12 (python on PATH — for pip-installing backend deps)
#   • Inno Setup 6 (iscc on PATH, or installed to default location)
#
# Usage (run from the repository root):
#   powershell -ExecutionPolicy Bypass -File Installer\build_installer.ps1
# ─────────────────────────────────────────────────────────────────────────────
param(
    [string]$Version = "0.5.0",
    [string]$PythonEmbedUrl = "https://www.python.org/ftp/python/3.12.3/python-3.12.3-embed-amd64.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo      = Split-Path -Parent $PSScriptRoot
$Installer = Join-Path $Repo "Installer"
$WpfProj   = Join-Path $Repo "HostApp\ArbiterHost.csproj"
$Publish   = Join-Path $Repo "HostApp\bin\Release\net9.0-windows\win-x64\publish"
$PyEmbed   = Join-Path $Installer "python-embed"
$PyPkgs    = Join-Path $Installer "python-pkgs"

Write-Host "=== Arbiter Installer Build ($Version) ===" -ForegroundColor Cyan

# ── Step 1: Publish WPF app (self-contained) ─────────────────────────────────
Write-Host "`n[1/4] Publishing WPF HostApp..." -ForegroundColor Yellow
dotnet publish $WpfProj `
    -c Release `
    -r win-x64 `
    --self-contained `
    -p:PublishSingleFile=false `
    -p:Version=$Version | Write-Host

if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }

# ── Step 2: Download & extract embedded Python ───────────────────────────────
if (-not (Test-Path $PyEmbed)) {
    Write-Host "`n[2/4] Downloading embedded Python..." -ForegroundColor Yellow
    $ZipPath = Join-Path $Installer "python-embed.zip"
    Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $ZipPath
    Expand-Archive -Path $ZipPath -DestinationPath $PyEmbed -Force
    Remove-Item $ZipPath

    # Patch python312._pth to enable site-packages
    $PthFile = Join-Path $PyEmbed "python312._pth"
    if (Test-Path $PthFile) {
        (Get-Content $PthFile) -replace "#import site", "import site" |
            Set-Content $PthFile
    }

    # Bootstrap pip in the embedded distribution
    $GetPip = Join-Path $Installer "get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
    & (Join-Path $PyEmbed "python.exe") $GetPip
    Remove-Item $GetPip
} else {
    Write-Host "`n[2/4] Embedded Python already present, skipping download." -ForegroundColor Green
}

# ── Step 3: Install Python dependencies ──────────────────────────────────────
Write-Host "`n[3/4] Installing Python backend dependencies..." -ForegroundColor Yellow
$PythonExe = Join-Path $PyEmbed "python.exe"
& $PythonExe -m pip install `
    --target $PyPkgs `
    -r (Join-Path $Repo "AIEngine\ArbiterEngine\requirements.txt") `
    -r (Join-Path $Repo "AIEngine\PythonBridge\requirements.txt") `
    --no-cache-dir `
    --quiet

if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ── Step 4: Compile the installer ────────────────────────────────────────────
Write-Host "`n[4/4] Compiling Inno Setup installer..." -ForegroundColor Yellow
$Iscc = "iscc"
# Try default Inno Setup install locations if not on PATH
if (-not (Get-Command $Iscc -ErrorAction SilentlyContinue)) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $Iscc = $c; break }
    }
}

& $Iscc /DMyAppVersion=$Version (Join-Path $Installer "arbiter_setup.iss")

if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }

$Output = Join-Path $Installer "Output\arbiter-setup-$Version.exe"
Write-Host "`n✅ Installer built: $Output" -ForegroundColor Green
