# Cortex Separation Migration Matrix

## MOVE to standalone Cortex

| Area | Decision |
|---|---|
| `apps/cortex` | MOVE |
| `apps/cortex_desktop` | MOVE |
| `apps/cortex_model_host` | MOVE |
| generic `crates/cortex_*` | MOVE |
| `extensions/cortex-vscode` | MOVE |
| generic `config/cortex/*` | MOVE then normalize |
| `schemas/cortex_*` | MOVE |
| generic Cortex docs | MOVE |
| Cortex generic tests/fixtures | MOVE |
| Cortex global project/Library/Vault state definitions | MOVE |

## MOVE but refactor during bootstrap

| Area | Decision |
|---|---|
| `cortex_cli` | MOVE; remove direct Open2D adapter dependency |
| `cortex_plugin` | MOVE; evolve manifest/protocol to v2 |
| `cortex_adapter_git` | MOVE as generic built-in/provider |
| Hxx/R051 static validators | MOVE only as migration history, replace with contract tests |
| old Open2D-named runtime wording/config | NORMALIZE |

## Keep with Open2D / convert to integration

| Area | Decision |
|---|---|
| `cortex_adapter_open2d` | OPEN2D-OWNED ADAPTER after split |
| `open2d_runtime_bridge` | KEEP OPEN2D |
| `open2d_cortex_*` compatibility crates | KEEP temporarily, then retire |
| `apps/open2d_cortex` | KEEP as compatibility launcher/client, then thin further |
| `open2d_dev_session` | KEEP OPEN2D |
| Ember runtime/editor | KEEP OPEN2D |
| Open2D asset/editor/domain tools | KEEP OPEN2D |

## Universal PCC

Do not copy PCC logic into Cortex core.

The new Cortex project should contain:
- the standardized root PCC launcher/manifest for operating **the Cortex project itself**;
- `cortex_adapter_pcc`/PCC client integration;
- optional discovery of the centrally installed PCC runtime.

The Universal PCC implementation remains its own reusable project/runtime.

## Havenwild

No Cortex source should be copied into Havenwild. Havenwild publishes:
- project.control.json;
- Havenwild Cortex integration manifest;
- editor/runtime tool provider endpoint(s).

## External CLI/classification project

Keep independent and publish capabilities. Cortex discovers and uses it.

## Compatibility transition

During migration, allow:
- old Open2D launcher -> standalone Cortex service;
- old Open2D adapter name -> external adapter;
- old CLI aliases -> new command registry;
- schema v1 -> v2 migration.

Give every compatibility surface a deprecation owner and removal milestone.
