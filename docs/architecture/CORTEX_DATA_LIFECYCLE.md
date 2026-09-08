# Cortex Data Lifecycle

```text
User / UI / Automation / Plugin
        -> Command
        -> Policy decision
        -> Job
        -> Execution
        -> Events
        -> Transaction candidates
        -> Verification / Certification
        -> Artifacts / Generations
        -> Promotion or Rollback
        -> Context/Vault indexing
        -> UI projections
```

## Immutable vs mutable
Immutable:
- Event records
- Artifact hashes
- Certification evidence
- released Generation metadata
- training/evaluation evidence

Mutable:
- Job current state
- Project location records
- Review item state
- UI projection/filter state
- caches/indexes

Mutable summaries must always be reconstructable from durable authority or explicitly marked as caches.
