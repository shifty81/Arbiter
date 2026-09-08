# CORTEX-R051N — Project-Wide Normalization Lock

## Scope

This milestone applies to the **entire standalone Cortex product**.

It is not an indexing refactor and it is not an Open2D feature pass.

The certified R051C baseline is the normalization checkpoint:

- 54 / 54 Cargo workspace closure
- 47 Cortex tools
- build PASS
- workspace tests PASS
- Cortex Desktop certification READY
- Clippy `-D warnings` PASS

Feature expansion pauses at this baseline while Cortex authority is normalized.

## Product boundary

Cortex is a standalone, local-first, project-agnostic AI/agent application.

Open2D Foundry is one project/integration target.

Permanent direction:

```text
Cortex
├─ generic core/services
├─ generic workspace/context/vault
├─ generic tools/jobs/permissions/transactions
├─ generic providers/protocol/RPC
├─ generic desktop/CLI/client/plugin surfaces
└─ adapters
   ├─ Open2D
   ├─ Git
   └─ future integrations

Open2D
├─ cortex_adapter_open2d
├─ open2d_runtime_bridge
└─ open2d_dev_session
```

Open2D may not own Cortex protocol, agent core, provider, tools, memory,
workspace, process, RPC, image or capture authority long-term.

## Current concrete migration debt

The source audit found generic crates that still depend directly on transitional
Open2D-named Cortex implementations:

```text
cortex_cli
├─ open2d_cortex_core
├─ open2d_cortex_provider_comfyui
├─ open2d_cortex_provider_lmstudio
├─ open2d_cortex_protocol
├─ open2d_cortex_rpc
└─ open2d_cortex_tools

cortex_client
├─ open2d_cortex_protocol
└─ open2d_cortex_rpc

cortex_vault
├─ open2d_cortex_memory
└─ open2d_cortex_protocol
```

Those edges are temporary migration debt, not permanent architecture.

The generic CLI also still contains Open2D-branded command usage, agent prompt
wording, certification labels, and Open2D development-session behavior that
must either become generic or move behind the Open2D adapter.

## Project-wide normalization domains

The machine-readable authority file defines eighteen domains:

1. executable/product identity
2. crate authority and dependency direction
3. workspace identity and state ownership
4. jobs and event stream
5. context/Vault/memory responsibility split
6. tools/permissions/execution
7. providers/model routing
8. protocol/RPC/service/client
9. desktop shell
10. CLI/VS Code/external clients
11. transactions/review/rollback
12. logs/diagnostics/artifacts/recovery
13. plugins/adapters
14. configuration/schema migrations
15. testing/certification
16. security/privacy
17. build/packaging/distribution
18. cross-project audit/assimilation readiness

## Key structural changes before more feature growth

### Generic protocol first

Protocol, HTTP and RPC are low-level dependency roots. Normalize these first so
higher Cortex crates can migrate without creating circular authority.

### Generic tools/core second

`cortex_tools` and `cortex_core` must become the generic agent/tool authorities.
Open2D-specific tools are injected by `cortex_adapter_open2d`.

### Global state and stable WorkspaceId

Cortex-owned project intelligence should normally live under Cortex global
state, keyed by a persistent workspace UUID. Filesystem path is a location, not
project identity. Repo-local `.cortex` remains an explicit portable-state mode,
not the mandatory default.

### One job/event system

Indexing, builds, tests, Vault operations, provider operations and future
cross-project audits must use one cancellable background-job authority and one
event stream. Desktop, CLI and agents observe the same operation state.

### Split workspace / context / Vault / memory

`cortex_workspace`:
safe paths, detection, enumeration, project profile.

`cortex_context`:
fingerprints, incremental change detection, languages, symbols, dependencies,
context snapshots.

`cortex_vault`:
chunking, retrieval, lexical search, embeddings, provenance.

`cortex_memory`:
only durable memory concepts that are genuinely distinct from context/Vault.

### One permission and transaction policy

Every operation declares capabilities. Risky writes/process/network/system
operations pass through the same permission and transaction/review policy,
regardless of whether they originated from chat, CLI, desktop, RPC or plugin.

## Feature freeze

R051D should **not** be applied in its current form.

Its incremental-index concepts remain valid, but it will be rebased after
`cortex_context` and `cortex_jobs` exist so we do not immediately refactor the
same feature again.

Bug fixes and green-checkpoint repairs remain allowed during R051N.

## Execution plan

```text
R051N0  project-wide normalization lock
R051N1  protocol/http/rpc generic dependency roots
R051N2  tools/core generic authority + Open2D adapter extraction
R051N3  WorkspaceId + global state migration framework
R051N4  cortex_jobs + Cortex event stream
R051N5  cortex_context + Vault/memory responsibility split
R051N6  permissions + execution + transactions/review
R051N7  providers/process/image/capture genericization
R051N8  desktop/CLI/client/VS Code convergence
R051N9  logs/artifacts/schemas/security/certification closure

R051D-R  incremental context indexer rebased onto normalized architecture
R051E    project capability audit
R051F    cross-project comparison and deliberate assimilation
```

Every implementation pass must return to a green Cortex checkpoint before the
next authority boundary moves.
