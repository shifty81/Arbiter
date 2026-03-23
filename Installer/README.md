# Arbiter Installer (M8-1)

Inno Setup 6 installer that bundles the WPF HostApp, embedded Python 3.12,
ArbiterEngine backend, PythonBridge, and the Arbiter CLI into a single
Windows installer (`.exe`).

## Files

| File | Purpose |
|---|---|
| `arbiter_setup.iss` | Inno Setup 6 script — defines all installer sections |
| `build_installer.ps1` | PowerShell helper that runs all pre-build steps then invokes `iscc` |

## Quick Start

```powershell
# From the repository root (requires .NET 9 SDK, Python 3.12, Inno Setup 6)
powershell -ExecutionPolicy Bypass -File Installer\build_installer.ps1
```

The finished installer is placed at `Installer\Output\arbiter-setup-<version>.exe`.

## Prerequisites

- **.NET 9 SDK** — for `dotnet publish`
- **Python 3.12** — for downloading the embedded distribution and installing packages
- **Inno Setup 6** — `iscc` must be on `PATH` or installed to its default location
  (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`)

## Manual steps (if not using build_installer.ps1)

1. Publish the WPF app:
   ```
   dotnet publish HostApp/ArbiterHost.csproj -c Release -r win-x64 --self-contained
   ```
2. Download and extract the Python embedded zip to `Installer/python-embed/`
3. Install backend dependencies to `Installer/python-pkgs/`
4. Run `iscc Installer/arbiter_setup.iss`

