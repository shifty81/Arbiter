# O2D-R051 — Cortex Authority Normalization

## Goal

Close the R050H10 checkpoint blocker and lock the permanent authority direction before deeper crate migration.

## Authority

- `apps/cortex` — canonical standalone CLI entrypoint.
- `apps/cortex_desktop` — canonical standalone desktop application.
- `apps/open2d_cortex` — temporary compatibility launcher only.
- `cortex_*` — standalone/project-agnostic Cortex authority.
- `cortex_adapter_open2d` — explicit Open2D integration boundary.
- `open2d_runtime_bridge` / `open2d_dev_session` — Open2D-side runtime/dev integration.
- remaining `open2d_cortex_*` crates — transitional compatibility implementations to be migrated incrementally, never removed blindly.

The R051 pass deliberately does **not** mass-rename or delete compatibility crates. R050H10 already reached a healthy 53/53 workspace with successful build/tests/desktop certification, so the safe normalization strategy is to establish authority first and migrate dependency edges in later green passes.

## Immediate checkpoint repair

Rust 1.95 Clippy rejects:

```rust
.lines()
.filter_map(Result::ok)
```

for `std::io::Lines`, because repeated read errors can theoretically produce an unbounded error stream.

R051 rewrites this pattern to:

```rust
.lines()
.map_while(Result::ok)
```

across active Rust source and verifies that no occurrence remains.

## R051 normalization guards

The validator checks:

1. Cargo workspace member closure.
2. Thin CLI/compatibility entrypoints.
3. No remaining `lines().filter_map(Result::ok)` pattern.
4. No active tooling that still emits `Open2D_R020_DebugBundle`.
5. The latest Cortex checkpoint log contains no NUL bytes.
6. The authority contract parses and names the intended canonical apps/crates.
7. Transitional `open2d_cortex_*` dependencies are reported as migration debt rather than silently treated as permanent authority.

## Provider configuration

R051 does **not** bake `192.168.0.170:1234` or any other machine-specific LM Studio endpoint into source.

Provider endpoints remain settings-owned. A loopback default may exist as a portable default, but the active user-selected endpoint should come from Cortex settings.

## Follow-on migration order

After R051 is green:

1. `open2d_cortex_workspace` → merge into `cortex_workspace`.
2. protocol/RPC/HTTP primitives → generic `cortex_*`.
3. process/capture/image/providers → generic `cortex_*`.
4. ToolBroker/tool catalog authority → generic `cortex_tools`.
5. agent/core orchestration → generic `cortex_core`.
6. retire `apps/open2d_cortex` only after all external callers use the canonical Cortex app/IPC contract.

Each migration should be a small incremental pass with a green checkpoint between steps.
