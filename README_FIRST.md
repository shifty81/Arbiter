# Cortex Standalone — Normalized Project Handoff

Date: 2026-09-08  
Status: Active standalone authority  
Purpose: Continue Cortex as its own project. Separation is complete; no standalone-boundary enforcement is required.

## Authority

Cortex is the authoritative standalone Cortex project.

Cortex owns its generic AI/agent/runtime/CLI/Desktop/plugin/provider/job/context/review infrastructure. External projects and tools integrate with Cortex through normal versioned contracts; they are not owners of Cortex internals and Cortex does not need policy gates proving that fact.

Forge is the universal project-development/root-operations platform consumed by Cortex for project operations. Forge is an integration dependency/service surface, not a boundary Cortex must enforce.

## Active quality philosophy

The project validates engineering health, not migration history.

Keep active checks for:
- workspace and dependency health;
- formatting, compile/check, tests, Clippy and builds;
- CLI/API/schema behavior;
- provider/model/tool execution contracts;
- plugin/tool-provider compatibility;
- cancellation/job lifecycle behavior;
- transactions, recovery and mutation safety;
- GUI/runtime smoke behavior;
- Forge integration fixtures;
- packaging, provenance and release artifacts.

Do not require:
- `Test-CortexStandaloneBoundary.ps1`;
- Hxx/R051 literal marker gates;
- Open2D/Havenwild/PCC ownership enforcement;
- project-name prohibition scans whose only purpose was migration/separation;
- static proof that Cortex is standalone.

Historical separation material is retained under `docs/history/legacy-separation/` and `scripts/history/` only as evidence.

## Immediate continuation

1. Remove obsolete standalone-boundary invocation from the root Full Quality and fast-development paths.
2. Remove Hxx/R051 policy-marker stages from active certification.
3. Build the native Cortex CLI and expose typed status/build/test/certify commands.
4. Keep the bootstrap/recovery menu only until the native CLI/GUI can own the same operations.
5. Integrate Forge through typed machine contracts; do not duplicate Forge project-operation logic in Cortex.
6. Drive Cortex to a real GREEN standalone gate: `fmt -> check -> test -> clippy -> build -> CLI/contract/runtime smoke`.
7. Continue Desktop/agent/provider development only against this normalized authority.

See `docs/CURRENT_AUDIT.md`, `docs/QUALITY_GATE_CONTRACT.md`, and `docs/NORMALIZATION_ACTION_MATRIX.md`.
