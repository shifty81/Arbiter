# CORTEX-R051N9 — Project-Wide Normalization Closure

R051N9 closes the normalization train structurally. It does **not** claim a
compiled release until the standard Windows Cortex checkpoint passes.

## Final ownership

Cortex is standalone and project-agnostic. Generic `cortex_*` crates own the
agent, wire protocols, tools, workspace/state, context, Vault, jobs/events,
permissions, reversible transactions, providers, process/media services,
sessions, desktop, CLI and external-client contracts.

Open2D is an integration:

```text
Cortex generic authorities
        |
        +-- cortex_adapter_open2d
                +-- open2d_runtime_bridge
```

Historical `open2d_cortex_*` crates and `open2d_dev_session` are compatibility
facades only and may not be dependencies of generic Cortex crates.

## Security closure

- workspace file resolution rejects lexical traversal and canonical link/reparse
  escapes;
- transaction writes enforce the same boundary, including nonexistent files
  under linked parents;
- process/network/tool permissions remain centralized in `cortex_permissions`;
- debug bundles strip token/secret/password/credential/private-key payloads;
- global project intelligence is stored under Cortex-owned state by default.

## Schema closure

Canonical schemas now cover permissions v2, jobs, context index, workspace
registry v2, transactions, provider descriptors and artifact lineage. Older
schemas remain migration inputs where required.

## Product identity

`config/cortex/CORTEX_VERSION.json` gives Cortex its own architecture identity.
Open2D handoff names remain only the current development transport mechanism.

## Required next action

Apply R051N0 through R051N9 in order and run the normal Cortex checkpoint. Any
compiler/test/Clippy findings are closure bugs to fix; no new feature work should
begin until the normalized tree is fully green.
