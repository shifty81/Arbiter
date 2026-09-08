# Cortex Plugin / Adapter SDK v2 Specification

## Why v2

The existing plugin manifest is a useful discovery start but is too small for a standalone ecosystem. It currently describes identity, permissions, tool names and workspace kinds, and also has protocol endpoints for MCP/LSP/DAP/BSP.

v2 should make compatibility, capability negotiation, schemas, health and UI contributions explicit.

## Public boundary

Use **out-of-process plugins** for project/external integrations.

Recommended protocol mapping:

- MCP 2026-07-28: AI-facing tools/resources/prompts.
- PCC JSON/JSONL contract: project operations.
- LSP: language intelligence.
- DAP: debugging.
- BSP: build-server integration where applicable.
- Cortex local RPC: tightly controlled first-party services where MCP/PCC are not the right fit.

## Manifest v2 fields

See `schemas/cortex_plugin_manifest.v2.proposed.json`.

Core sections:

```text
identity
compatibility
entrypoints
capabilities
permissions
project_kinds
schemas
subscriptions
ui_contributions
health
lifecycle
provenance
```

## Required compatibility behavior

A plugin is not enabled merely because its JSON parsed.

Cortex checks:
1. manifest schema;
2. Cortex version range;
3. protocol version;
4. executable existence/signature/hash policy;
5. project kind;
6. requested permissions;
7. capability discovery;
8. health probe;
9. user/project policy.

Failure creates a visible degraded integration, not a crash.

## Capability namespaces

Reserve:

```text
cortex.*
pcc.*
git.*
forgejo.*
open2d.*
ember.*
havenwild.*
```

Third-party plugins use reverse-domain or vendor namespaces.

## Permissions

Permissions are granular and project-scoped where possible:
- filesystem.read
- filesystem.write
- process.spawn
- network
- git.read
- git.write
- project.patch
- project.build
- project.run
- editor.read
- editor.write
- secrets.use:<provider>

A plugin requests; Cortex/PCC policy grants.

## UI contributions

Plugins may contribute descriptors, not arbitrary native GUI code:
- commands;
- context-menu actions;
- Project Home cards;
- integration status cards;
- tool categories;
- settings schema;
- artifact viewers by declared MIME/content kind.

The Cortex GUI decides final layout and security.

## Project integrations

### Open2D / Ember
The adapter belongs with Open2D because it depends on Open2D runtime/editor APIs. It exposes:
- Ember service/editor capability;
- Open2D project/editor/runtime tools;
- PIE/run/build through PCC;
- selected resource/context;
- asset transactions and artifact exchange.

### Havenwild
The adapter belongs with Havenwild and exposes:
- native editor status;
- Game Canvas PIE/Play From Here;
- content/asset validation;
- world/editor commands;
- project build/certification through PCC.

### Universal PCC
`cortex_adapter_pcc` belongs in Cortex because PCC is a general service used by every project.

### External CLI/classification project
Expose as MCP/tool-provider/PCC capability. Cortex must not copy its classifier implementation.

## No Rust ABI plugin loading

Do not make `cdylib` + Rust trait-object loading the general plugin API. Keep Rust traits for code compiled as part of Cortex itself; use process boundaries for independent projects.
