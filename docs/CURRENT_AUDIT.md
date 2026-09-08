# Current Cortex Standalone Audit

## 1. Current runtime evidence

The latest root-utility run reaches:

- root incremental patch intake: PASS;
- root cleanliness audit: PASS;
- Cargo: Ready;
- workspace: Ready;
- native Cortex CLI: not built yet;
- native Cortex GUI: not built yet.

The run then fails inside the legacy `Standalone boundary` stage through `Test-CortexStandaloneBoundary.ps1` with a PowerShell scalar/collection `.Count` error.

## 2. Normalized diagnosis

The `.Count` defect is real PowerShell behavior, but the stage itself is obsolete.

Cortex is already the standalone project. Therefore the correct fix is to remove this stage from the active quality pipeline, not spend another pass hardening a migration gate.

The same rule applies to Hxx/R051 literal-marker certification. Those labels represent useful historical milestones, but their marker validators are not production engineering truth.

## 3. What remains valuable from the old Cortex work

Preserve the implemented behavior behind prior milestones, including:

- structured tool execution;
- provider/model routing;
- hard-stop/cancellation behavior;
- durable jobs/events/activity;
- transactions and recovery;
- source mutation evidence;
- project switching/context;
- Vault/Library/catalog behavior;
- Desktop/controller behavior;
- native model lifecycle;
- repair/build/test/launch loops;
- plugin/provider/tool contracts.

Normalize those into ordinary modules and behavioral tests without Hxx/R051 enforcement names where practical.

## 4. Root utility status

The current PowerShell root utility is a bootstrap/recovery bridge while the native Cortex CLI/GUI are not yet built. It should remain useful for:

- patch intake;
- root/project status;
- bootstrap dependency checks;
- build/test/certification entrypoints;
- debug bundle creation;
- logs/artifacts access;
- recovery.

It should not own obsolete migration-policy gates.

## 5. Forge relationship

Forge is the universal root/project development platform beneath Cortex-managed project operations.

Cortex should consume Forge capabilities through typed commands/events/contracts instead of copying project discovery, build orchestration, patch engines, Git/worktree operations, diagnostics, artifact history or recovery engines into a competing backend.

Cortex still owns its own product build/test/release health like any other project.

## 6. Active blocker order

After removing obsolete enforcement, the first meaningful failure encountered by the normalized Full Quality Gate becomes the next blocker. Expected near-term sequence:

1. workspace/dependency health;
2. `cargo fmt --all -- --check`;
3. `cargo check --workspace --all-targets`;
4. `cargo test --workspace`;
5. `cargo clippy --workspace --all-targets -- -D warnings`;
6. `cargo build --workspace`;
7. Cortex CLI fixtures/contracts;
8. provider/plugin/tool contracts;
9. Desktop/runtime smoke;
10. packaging/release evidence.
