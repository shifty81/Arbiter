# Cortex / Open2D Project-Wide Consolidation

This pack freezes the architecture around a small set of canonical authorities and removes the
design pressure to create parallel implementations.

## Normalization target
1. exactly one durable owner per domain;
2. UI surfaces are projections only;
3. ProjectId, GenerationId, ArtifactId, JobId, EventId and ConversationId replace path/text identity;
4. compatibility `open2d_cortex_*` crates are frozen;
5. `cortex_task` migrates into `cortex_jobs`;
6. `cortex_observability` emits to `cortex_activity` instead of owning a duplicate timeline;
7. `cortex_protocol` is the shared contract/schema envelope authority;
8. `cortex_registry` owns Project Passport/project identity;
9. `cortex_artifacts` owns immutable lineage/generations;
10. `cortex_permissions` becomes the single policy/trust authority;
11. Learning Lab begins as one `cortex_learning` authority and reuses existing Jobs/Vault/Artifacts/
    Transactions/Execution rather than duplicating them.

## Immediate sequencing
Do not mix this structural normalization into the current H68C live responsiveness acceptance.
Finish H68C3C2 and Hello3D certification first. Then implement H68D-L using this authority model.

This pack is architecture/configuration only. It deliberately does not rewrite runtime crates.
