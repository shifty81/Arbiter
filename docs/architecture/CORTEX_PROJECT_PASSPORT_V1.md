# Project Passport v1

A Project Passport is the durable identity record for any managed project.

```text
ProjectPassport
- project_id
- display_name
- project_kind
- authoritative_roots[]
- location_records[]
- nested_projects[]
- parent_project_id?
- source_generation_id?
- last_certified_generation_id?
- adapters[]
- manifests[]
- source_roots[]
- asset_roots[]
- generated_roots[]
- protected_roots[]
- build_targets[]
- runtime_targets[]
- toolchain_requirements[]
- dependency_graph_ref?
- git_identity?
- vault_links[]
- policy_profile
- trust_zone
- schema_version
- created_at
- updated_at
```

## Rules
- ProjectId survives moves, drive migration and renamed folders.
- Filesystem path is never ProjectId.
- Multiple physical copies may be lineage candidates, not automatic merges.
- Nested projects receive their own ProjectId when independently buildable/authoritative.
- A parent project records nested relationships rather than flattening them.
- Location changes are journaled.
- Ambiguous authority enters Review Queue.
