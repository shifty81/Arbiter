# Cortex native root utility bridge — CTX-PROJOPS-02

Cortex now owns the universal Project Control Center tooling spine. The historical standalone PowerShell UPCC is donor/migration evidence only.

`PROJECT_CONTROL_CENTER.cmd` remains the standard repository-root doorway. It launches the local root bridge, which prefers the built native Cortex GUI/CLI and falls back to a small build/recovery menu only when Cortex has not been built yet.

## Normal use

Run `PROJECT_CONTROL_CENTER.cmd`.

- If `cortex_desktop.exe` exists, the native Cortex GUI opens with this repository selected.
- `-Status` prefers `cortex.exe project status`.
- `-FastGate` and `-FullGate` prefer native Cortex project gates.
- Patch intake/debug-bundle/bootstrap build functions remain available for recovery before a native binary exists.

No `PCC_HOME`, separate Universal PCC folder, or external PCC runtime is required.
