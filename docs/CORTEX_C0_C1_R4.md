# C0/C1 implementation boundary

## C0 complete when

- Cortex source exists physically outside O2DF.
- O2DF remains unchanged and is only provenance/reference.
- Root PCC launcher resolves the shared PCC runtime.
- `project.control.json` identifies Cortex as its own project.
- local Git points to `shifty81/Cortex`.
- import provenance is recorded.

## C1 complete when

- no active `cortex_*` crate has an Open2D/O2DF compile-time path dependency;
- `cortex_adapter_open2d` is not an active workspace member;
- `cargo metadata` succeeds without the O2DF tree being present;
- `cargo check --workspace --all-targets` succeeds in the standalone root;
- a fresh standalone `Cargo.lock` is generated;
- the standalone boundary audit is PASS.

## What R4 deliberately does not do

R4 does not regex-rewrite Rust imports or Cargo dependency edges. Those changes require file-by-file source-aware refactoring against the exact blocker report generated from the live source.

This prevents a repeat of the old marker-driven repair pattern where validation strings were satisfied without proving the underlying architecture.
