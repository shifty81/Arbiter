# UPCC v0.6.3/B003R3 donor evidence index

## Release identity

- Product: Universal Project Control Center
- Version: 0.6.3
- Build: B003R3
- Static release checks reported: 38/38 PASS
- Patch payloads reported: 21
- Clean rollup files reported: 90
- Runtime state bundled: no

## Hardened behaviors represented by the donor

### Discovery

- Prune archive/backup/snapshot/history and dependency/vendor branches **before descendants are queued**.
- Treat known workspace descendants as components of an owning project rather than unrelated primary projects.
- Permit deliberate manual registration even when automatic discovery suppresses a path.
- Canonicalize scan roots and avoid protected/system traversal.
- Enforce configurable per-root budgets and report partial/budget-stopped scans honestly.

Known B003R3 budget defaults:

```text
discoveryOwnedTraversalDepth    = 4
discoveryMaxDirectoriesPerRoot = 200000
discoveryMaxSecondsPerRoot     = 1800
discoveryMaxQueueLength        = 50000
```

### Cortex-facing machine state

Documented B003R3 surfaces include:

- discovery policy
- coherent project state
- non-executing action plan
- fleet state
- project graph
- durable export
- Git worktree state

The coherent state includes stable identity, root/type/adapter/capabilities, Git/worktree state, dependency-store binding, catalog/update/handoff/gate evidence, warnings, and a state digest.

### Project-control operational capabilities

The broader UPCC line also represents:

- one root launcher and central registry;
- streaming process/log host;
- root-drop transactional patch intake;
- backup/rollback/history;
- quality-gate records and automatic failure debug bundles;
- clean project audit package;
- source manifests/hashes/exclusion reports;
- source refresh packaging;
- incremental handoff generation;
- Git/remote source-control operations;
- environment/toolchain inventory;
- legacy control-center detection/normalization.

These capabilities must be classified by ownership before reuse. See `UPCC_FEATURE_PARITY_MATRIX.md`.
