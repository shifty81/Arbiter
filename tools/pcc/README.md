# Universal Project Control Center (Python)

This package is Cortex's universal **project-operations provider**. The native/PowerShell Cortex Root Project Control Center remains the authoritative top-level operations entry point during this phase. PCC reads `project.control.json` so build/test/validation command semantics are not duplicated in Python or AI prompts.

R1 guarantees:

- one typed command catalog and quality-gate model sourced from `project.control.json`;
- exact registered argv execution only (no arbitrary trailing flags);
- mutation requires explicit opt-in and remains permission-checked again by Cortex;
- quality gates reject source/external mutation and allow only bounded build/cache/artifact/log effects;
- live subprocess output plus logs under `artifacts/logs/pcc`;
- machine-readable `--json` output for the Rust `cortex_pcc` bridge;
- bounded, read-only donor/archive parity auditing;
- project discovery by `project.control.json`;
- zero required third-party Python runtime dependencies.

Patch/update application is intentionally **not** owned by Python PCC in R1. The hardened Cortex Root intake remains authoritative until the later PCC transaction/patch-engine pass proves Plan -> Validate -> Apply -> Verify -> Recover parity.

Run from a checkout without installation:

```powershell
$env:PYTHONPATH = "$PWD\tools\pcc\src"
python -B -m pcc --project-root . status
python -B -m pcc --project-root . --json catalog
python -B -m pcc --project-root . --json archive-audit tools.zip --prefix crates
python -B -m pcc --project-root . gate full
```
