# CTX-PROJOPS-02 Native Project Spine Foundation

Source basis: the supplied `crates.zip` standalone Cortex tree.

This pass intentionally does not polish the standalone PowerShell UPCC self-test failure. That implementation is donor evidence now. Instead it ports the first authority slice into native Cortex and removes a real standalone compile-graph defect: `cortex_cli` still referenced the quarantined `cortex_adapter_open2d` crate.

## Implemented

- native typed project contract crate;
- registry v3 project metadata;
- best-effort Cortex self-registration;
- native project CLI and project quality-gate execution;
- Open2D direct CLI dependency removal;
- native-first root utility launch path;
- authority documentation normalization.

## Validation

The execution environment used to build this patch does not have `cargo`, so Rust compilation could not be run here. Apply the patch and run the root Full Quality Gate on the Windows development machine. The patch is designed so the root bootstrap can still invoke Cargo directly before the native Cortex binaries are rebuilt.
