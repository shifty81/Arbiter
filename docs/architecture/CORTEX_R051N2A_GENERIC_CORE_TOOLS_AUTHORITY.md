# O2D-R051N2A — Generic Cortex Core + Tool Authority

## Goal

Move canonical agent-engine and tool-broker ownership out of the historical
Open2D-named crates without simultaneously changing adapter execution behavior.

## Canonical authorities

- `cortex_core`
- `cortex_tools`

The historical crates remain temporarily:

- `open2d_cortex_core`
- `open2d_cortex_tools`

Both are thin re-export compatibility facades only.

## CLI migration

`cortex_cli` now consumes `cortex_core` and `cortex_tools` directly.

Generic agent/chat wording no longer claims Cortex itself is Open2D Foundry or
that every active workspace is an Open2D workspace.

## Tool catalog authority

`schemas/cortex_tools.v1.json` now names:

`crates/cortex_tools::definitions`

as the canonical Rust tool catalog authority.

Tool count remains unchanged in N2A.

## Deliberate remaining debt

`cortex_tools` still carries the old conditional Open2D adapter/runtime wiring.
That is intentionally **not** normalized in the same build step as authority
migration.

R051N2B removes those direct dependencies and makes Open2D runtime tools an
adapter-provided extension while preserving compatibility tool names.

This two-stage approach gives the project a green checkpoint between:

1. ownership/type migration; and
2. behavior/dependency extraction.

## Expected checkpoint

After N1 + N2A:

- workspace members: 59
- Cortex tools: 47
- checkpoint: PASS required before N2B
