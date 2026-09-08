# Cortex Standalone Quality Gate Contract

## Full Quality

Canonical order:

1. root/inbox transactional patch intake;
2. root cleanliness and manifest sanity;
3. toolchain/workspace/dependency health;
4. format verification;
5. Cargo check/all-target compilation;
6. unit/integration tests;
7. Clippy with warnings denied;
8. full workspace build;
9. Cortex CLI/API/schema fixtures;
10. provider/plugin/tool execution contracts;
11. transaction/recovery tests;
12. Desktop/runtime smoke where available;
13. Forge integration fixtures where available;
14. artifacts/debug summary/provenance;
15. GREEN/FAIL result with structured evidence.

## Fast Development Gate

1. patch intake;
2. workspace/dependency health;
3. format verification;
4. `cargo check`;
5. impacted/targeted tests;
6. lightweight CLI/schema contract smoke.

## Explicit exclusions

The following must not be required by either gate:

- standalone-boundary enforcement;
- Open2D/Havenwild/PCC ownership checks;
- Hxx/R051 literal-marker scans;
- migration quarantine checks;
- project-name policy scans whose purpose is only separation proof.

A static scan is acceptable only when it protects a current engineering/security invariant that cannot be better expressed as a behavioral or schema test.
