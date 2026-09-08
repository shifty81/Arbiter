# Standards and Versioning Decisions

## External AI/tool integration
Target MCP revision: **2026-07-28** for new external/plugin integrations.

Why:
- stateless request model;
- per-request protocol/capability metadata;
- `server/discover`;
- formal extension model;
- tools/resources/prompts;
- progress/cancellation/error utilities.

Maintain dual-era compatibility only where an existing plugin requires an older MCP revision.

## Schemas
Use JSON Schema Draft **2020-12** as the canonical schema dialect for:
- plugin manifests;
- tool-provider manifests;
- CLI envelopes/events;
- project integration descriptors;
- PCC adapter descriptors.

Every schema gets:
- `$id`;
- `$schema`;
- semantic schema version;
- migration notes;
- compatibility tests.

## Telemetry
Use Cortex's existing observability layer but align event envelopes with OpenTelemetry concepts:
- service/project/plugin identity;
- trace ID / span ID where meaningful;
- structured severity;
- named events for lifecycle/state transitions;
- consistent error attributes.

Do not make an external collector mandatory for local use.

## Source control / Forgejo
Forgejo support is capability/version discovered. The API is versioned by major release and should be wrapped behind a Cortex/PCC provider interface.

## Rust
Migration order:
1. preserve current Rust edition/toolchain while separating;
2. get standalone GREEN;
3. then evaluate a workspace-wide Rust 2024 edition migration as its own bounded pass.

Do not combine repository separation with an edition migration.

## Version policy

Use separate versions:
- Cortex product: SemVer.
- Cortex local application API: integer/API revision plus compatibility range.
- Plugin manifest schema: schema version.
- MCP: MCP protocol date version.
- PCC client protocol: explicit protocol version.
- Integration/plugin package: SemVer.

Never overload one version number to mean all of these.
