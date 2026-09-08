# CTX-NORM-02 — Post-Separation Authority + Gate Repair

This root patch is intentionally cumulative.

The 2026-09-08 intake log showed the normalized handoff applied first and the older
separation handoff applied second. Because both packages contain overlapping authority
and roadmap files, the older package could restore stale migration/separation wording.

CTX-NORM-02 therefore reapplies the normalized Cortex Standalone authority as the
last-write state and retires the remaining standalone-boundary validator through a
compatibility no-op shim.

## Authority

- Cortex is already standalone.
- No standalone-boundary enforcement is required.
- No Open2D/Havenwild/PCC ownership enforcement is required.
- No Hxx/R051 literal-marker gates are required as primary certification.
- Forge is an external/universal project-operations platform consumed through normal
  integration contracts, not a boundary that Cortex must police.

## Temporary compatibility

`tools/control/Cortex.ProjectAdapter.ps1` may still dispatch `standalone-boundary`.
Until the live adapter source is captured and normalized, the replacement
`scripts/Test-CortexStandaloneBoundary.ps1` returns success without performing policy
checks. Once the adapter is updated, remove the dispatch and archive/delete the shim.
