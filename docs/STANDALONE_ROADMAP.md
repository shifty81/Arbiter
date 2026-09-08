# Cortex Standalone Roadmap — Post-Separation

Separation itself is complete. The roadmap now starts from product health and native authority rather than detachment enforcement.

## S0 — Standalone normalization
Acceptance:
- obsolete `Standalone boundary` stage removed from active gates;
- Hxx/R051 literal-marker gates removed from primary certification;
- migration material moved to history only;
- root menu/status reports product health rather than separation state.

## S1 — Native CLI bootstrap
Acceptance:
- `cortex`/`cortex-cli` builds from the standalone workspace;
- typed status/health/build/test/certify command descriptors;
- stable JSON/JSONL output envelopes and exit codes;
- non-interactive/headless execution;
- cancellation and process lifecycle tests.

## S2 — Standalone engineering GREEN
Acceptance:
1. `cargo fmt --all -- --check`;
2. `cargo check --workspace --all-targets`;
3. `cargo test --workspace`;
4. `cargo clippy --workspace --all-targets -- -D warnings`;
5. `cargo build --workspace`;
6. CLI fixture suite;
7. schema/protocol suite;
8. transaction/recovery suite.

## S3 — Forge integration
Acceptance:
- typed Forge capability discovery;
- project identity/status/commands/events accessible to Cortex;
- no duplicate Cortex project-operation backend;
- execution leases/worktrees/transactions represented in Cortex job state;
- diagnostics/artifacts consumable by agent repair loops.

## S4 — Plugin/tool-provider SDK
Acceptance:
- versioned manifest/schema;
- capability negotiation;
- permission model;
- health/discovery;
- cancellation;
- out-of-process provider support;
- integration fixtures.

## S5 — Provider/model execution hardening
Acceptance:
- local/remote provider lifecycle contracts;
- structured tool-call normalization;
- bounded repair loops;
- durable execution evidence;
- restart/recovery behavior;
- model/runtime diagnostics.

## S6 — Cortex Desktop normalization
Acceptance:
- Chat/Projects/Workbench/Jobs/Activity/Diagnostics/Artifacts/Recovery surfaces;
- GUI actions call the same typed authorities as CLI/agent paths;
- non-blocking execution;
- durable conversation/project context;
- native project-control/Forge integration.

## S7 — Library/Vault/source intelligence
Acceptance:
- stable content/project identities;
- incremental catalog/index;
- semantic source/symbol/reference/impact services;
- provenance/license metadata;
- dry-run organization plans;
- transactional moves and rollback;
- no silent destructive organization.

## S8 — Git/worktree/recovery development loop
Acceptance:
- local Git first-class;
- isolated worktrees and execution leases;
- last-GREEN checkpoints;
- candidate change review;
- Forgejo optional, not required;
- recovery state independent of remotes.

## S9 — Release certification
Acceptance:
- clean reproducible build;
- complete test/integration/runtime smoke suites;
- package manifests/hashes/provenance;
- rollback/recovery evidence;
- installer/portable distribution validation;
- no obsolete migration enforcement in release gates.
