# Cortex Crate Ownership Matrix

| Crate / family | Decision | Canonical responsibility |
|---|---|---|
| cortex_protocol | KEEP / EXPAND | Shared IDs, envelopes and wire contracts |
| cortex_registry | KEEP / EXPAND | ProjectId, Project Passport, project graph and location records |
| cortex_workspace | KEEP | Canonical filesystem/path/topology/read/search authority |
| cortex_transactions | KEEP / EXPAND | Candidate mutations, checkpoint, rollback, transaction journal |
| cortex_artifacts | KEEP / EXPAND | Generation/artifact/provenance lineage |
| cortex_activity | KEEP / EXPAND | Append-only typed operational Event journal |
| cortex_execution | KEEP / EXPAND | Execution stages, deterministic remediation, certification semantics |
| cortex_jobs | KEEP / ABSORB | Sole durable Job authority; absorb cortex_task durable responsibilities |
| cortex_task | MERGE / DEPRECATE | Compatibility layer during migration to cortex_jobs |
| cortex_observability | NORMALIZE | Instrumentation/event producer; no independent timeline authority |
| cortex_permissions | KEEP / EXPAND | Policy engine, permissions, trust zones |
| cortex_review | KEEP / EXPAND | Universal ambiguity/destructive-action Review Queue |
| cortex_conversation | KEEP | Conversation/message persistence and timestamps |
| cortex_context | KEEP / EXPAND | Search/index/context freshness |
| cortex_vault | KEEP / EXPAND | D:\ catalog, FileId/content hash, storage tiers |
| cortex_provider* | KEEP | Provider/model invocation and capability evidence |
| cortex_model_host | KEEP | Local model hosting process |
| cortex_tools | KEEP / NARROW | Tool schemas/dispatch only; avoid durable-domain ownership |
| cortex_core | KEEP / NARROW | Orchestration only |
| cortex_development | KEEP / NARROW | Roadmap/developer workflow helpers, no duplicate Job/Event state |
| cortex_toolchain | KEEP | Toolchain discovery/environment evidence |
| cortex_desktop_core | KEEP / NARROW | View models and typed UI actions |
| cortex_desktop_native | KEEP / NARROW | Native rendering/input only |
| cortex_service/session/client/http/rpc | KEEP | Transport/service/session/client responsibilities |
| cortex_plugin | KEEP / EXPAND | Plugin ABI/capability registration |
| open2d_cortex_* | FREEZE / DEPRECATE | Compatibility facades only; no new logic |
| open2d_ai/open2d_editor/open2d_runtime | REMAIN EXCLUDED | Legacy prototypes |
| future cortex_learning | NEW, SINGLE DOMAIN | Episode/dataset/reward/evaluation/training/model-candidate orchestration |

## Application entrypoints
- `apps/cortex_desktop`: canonical graphical Cortex application.
- `apps/cortex`: canonical generic Cortex CLI/application entrypoint.
- `apps/open2d_cortex`: compatibility/product entrypoint; should remain thin.
- `apps/open2d_foundry` and `apps/open2d_ember`: Open2D product applications, consumers of Cortex contracts rather than owners of Cortex internals.
