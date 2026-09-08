# Cortex Vault Pointer v1

A pointer manifest is Git-trackable metadata stored below:
`.cortex-vault/pointers/`

Required data:
- schema_version = 1
- authority = cortex_vault_pointer
- logical_path
- sha256
- bytes
- vault_object

Optional provenance:
- source_path_at_ingest
- source_url
- license
- ingested_unix_ms

Vault payload identity is SHA-256 and stored under:
`<VaultRoot>/objects/sha256/<first-two-hex>/<full-sha256>`

Materialization verifies SHA-256 before replacing/creating the project payload.
