# Cortex Root Project Control Center contract

Cortex is now the universal project-operations authority. The historical PowerShell Universal PCC is migration/donor evidence, not a permanent parallel runtime.

Every normalized project keeps the familiar root `PROJECT_CONTROL_CENTER.cmd`, but the root utility is a thin bootstrap/adapter into Cortex native project operations. It must never require a separate PCC installation.

## Cortex repository behavior

- `PROJECT_CONTROL_CENTER.cmd` resolves `tools/control/ProjectControlCenter.ps1`.
- The PowerShell bridge prefers the built native Cortex CLI/GUI.
- Interactive launch opens `cortex_desktop.exe` with the repository selected.
- `-FullGate` / `-FastGate` prefer `cortex.exe project gate ...`.
- Before native binaries exist, the small bootstrap lane may build/validate Cortex directly so a fresh clone can reach its first native build.
- Once Cortex is built, ordinary project operations belong to Cortex Rust services, not PowerShell.

## Cortex is project zero

The native registry automatically attempts to register the Cortex checkout itself before attaching an arbitrary managed project. A standard Cortex development launch therefore begins with Cortex known as the system project.

## Authority split

- Cortex native Rust project spine: identity, registry, discovery, command/gate contracts, execution, Git, updates, recovery, evidence, catalog, lineage, packaging and GUI/CLI APIs.
- Root script: bootstrap, handoff and recovery doorway only.
- Project adapter/plugin: project/domain-specific commands and validation.
- UPCC v0.6.3/B003R3: immutable donor/reference evidence until parity is certified.
