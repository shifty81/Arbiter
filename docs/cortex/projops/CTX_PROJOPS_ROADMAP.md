# Cortex Project Operations Roadmap

## Architectural authority update

Cortex itself is the long-term Universal Project Control Center. The PowerShell UPCC/B003R3 tree is donor evidence. Root scripts remain, but become thin Cortex bootstrap/adapter entry points.

## CTX-PROJOPS-01 — Donor evidence + parity matrix

Status: donor lane/parity scaffolding established. Physical B003R3 donor import remains evidence-only.

## CTX-PROJOPS-02 — Typed project contracts + self-registration

Status in this patch: **implemented foundation**.

- new `cortex_project` crate;
- typed `ProjectId`, project identity/authority, capability IDs, command risk/cancellation/rollback, quality gates and artifacts;
- native `project.control.json` loader;
- registry schema v3 stores project ID, authority, capabilities and contract path;
- Cortex self-registration is attempted before arbitrary managed projects;
- native CLI gains `cortex project status|register-self|list|activate|contract|gate`;
- direct compile-time `cortex_adapter_open2d` dependency is removed from generic `cortex_cli`;
- root utility becomes native-GUI/native-CLI first with bootstrap fallback.

Acceptance pending on user machine: `cargo fmt --all -- --check`, `cargo check --workspace --all-targets`, tests, clippy and build.

## CTX-PROJOPS-03 — Hardened native discovery

Next: absorb B003R3 discovery behavior using `ignore` + `globset`, ownership boundaries, queue pruning, scan budgets/cancellation, partial-scan truth and depth-20 regression fixtures.

## CTX-PROJOPS-04 — SQLite Project Registry + lineage

Move the current JSON workspace registry into a durable SQLite project registry while preserving stable IDs, aliases/history, families/copies/forks, capability snapshots and scan observations.

## CTX-PROJOPS-05 — Git state, worktrees and execution leases

Integrate `gix` for read-heavy state; add worktree inventory, execution leases, start-HEAD/state-digest guards and isolated write worktrees.

## CTX-PROJOPS-06 — Universal transaction coordinator

Native `Plan -> Validate -> Apply -> Verify -> Recover` across project updates, source changes and provider/adapter operations.

## CTX-PROJOPS-07 — Process/events/diagnostics/GREEN evidence

Unify streaming process lifecycle, action/job/trace correlation, diagnostics, quality evidence, debug bundles and cancellation.

## CTX-PROJOPS-08 — Native GUI/API Project Control workspace

Expose project/fleet/changes/graph/events, gates, updates, Git, health, recovery, artifacts, catalog and lineage directly inside Cortex GUI and CLI. The old PowerShell menu is retired to bootstrap/recovery only.
