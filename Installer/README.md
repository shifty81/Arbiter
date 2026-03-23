; ─── Arbiter — Inno Setup pre-build helper (M8-1) ────────────────────────────
;
; Run this PowerShell script to prepare all installer inputs, then compile
; the .iss script with Inno Setup.
;
; Usage (from repo root):
;   powershell -ExecutionPolicy Bypass -File Installer\build_installer.ps1
;
; Requirements:
;   • .NET 9 SDK
;   • Python 3.12 (system install or embedded zip)
;   • Inno Setup 6 (iscc on PATH, or at default install path)
; ─────────────────────────────────────────────────────────────────────────────
