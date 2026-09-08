# Cortex Single-Owner Rules

A durable concept may have many views, but exactly one authority.

## Rules
- Chat is a conversation view, not an execution/event database.
- Activity is the operational event journal view.
- Jobs is a JobStore view.
- Build is a filtered build/certification projection.
- Git is the Git/review authority projection.
- Notifications is a notification/review projection.
- Desktop/native code never becomes the durable source of domain truth.
- `cortex_core` orchestrates; it does not duplicate persistence owned by another crate.
- `cortex_tools` adapts tool calls; it does not become a second project registry, policy store or job database.
- Paths locate projects; ProjectId identifies them.
- Content hashes identify bytes; ArtifactId/GenerationId identify semantic lineage.
- An EventId is immutable. Human-readable summaries may be regenerated from the event.
- Compatibility facades forward to canonical authorities only.

## Conflict resolution
When two components appear to own the same data:
1. identify the canonical domain authority;
2. migrate durable state to it;
3. convert the other component to a projection/cache/facade;
4. add a regression test preventing reintroduction;
5. remove fallback-to-unrelated-data behavior.
