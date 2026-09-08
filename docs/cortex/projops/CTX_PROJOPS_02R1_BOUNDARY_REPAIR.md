# CTX-PROJOPS-02R1 — Standalone Boundary Bootstrap Repair

Date: 2026-09-07

## Trigger

The first clean-install Full Quality Gate reached the local Cortex bootstrap correctly, but the standalone-boundary stage terminated with a PowerShell null-method exception before Rust compilation began.

## Root causes

1. `Test-CortexStandaloneBoundary.ps1` called `.Trim()` on Cargo stderr without guarding the empty-file/null case.
2. The validator used `System.IO.Path.GetRelativePath` without a Windows PowerShell 5.1 fallback.
3. The validator's original textual Open2D/O2DF scan was too broad for the standalone architecture. Historical configuration, project-kind detection, compatibility labels, and migration vocabulary are not runtime coupling.
4. The adapter invoked the boundary script without explicitly passing the already-resolved project root.

## Repair

- Guard empty Cargo stdout/stderr reads.
- Resolve the Cargo executable robustly from `Get-Command`.
- Add portable relative-path handling for PowerShell 7 and Windows PowerShell 5.1.
- Pass `-ProjectRoot` explicitly from the Cortex project adapter.
- Replace vocabulary blocking with semantic boundary enforcement.

The boundary now blocks only active standalone coupling such as:

- an Open2D adapter present as an active workspace member;
- active Cargo dependencies named `open2d_*` / `o2df_*`;
- active Cargo path dependencies pointing into Open2D/O2DF authorities;
- active Rust `use` / `extern crate` imports of Open2D/O2DF crates;
- missing standalone Cortex source authorities;
- failed Cargo metadata.

Historical/migration/reference vocabulary is permitted and may be reported as non-blocking evidence.

## Static result against the CTX-PROJOPS-02 rollup

- Active Open2D/O2DF Cargo dependencies: 0
- Active Open2D/O2DF Cargo path dependencies: 0
- Active Open2D/O2DF Rust imports: 0
- Workspace-level `cortex_adapter_open2d` membership: absent

Windows Full Quality Gate remains the authoritative compile/runtime certification lane.
