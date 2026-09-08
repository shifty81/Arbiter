# Cortex Project Identity, Local Git, Vault and Observability Integration

## Authority model

Cortex treats project cataloging, registration, source history, hosted Git metadata, large-object storage, runtime/model telemetry and chat as related but distinct authorities.

- **Catalog** is read-only discovery. A confidence score never grants registration authority.
- **Registered project identity** binds one exact working tree to Cortex state/conversations/services.
- **Git** owns source/config/history and small pointer manifests.
- **Forgejo** is the default private machine-local Git/provider host.
- **Vault** owns content-addressed large objects and project pointer manifests.
- **Activity/Event history** is the persistent observability authority; GUI tabs are projections of it plus bounded native-provider log tails.

## Registration lifecycle

`scan vault` creates/refreshes the rich drive catalog and project graph. Registration requires an explicit command targeting one exact unique name, full path, or catalog id. Ambiguous names fail closed. Negative prose is never registration. Bulk high-confidence registration is review-gated so backups, snapshots, nested projects, duplicates and related versions can be classified as project families before attachment.

Unregister removes only the registry association. It refuses the active project and preserves the working tree, Git metadata/remotes, Vault data and per-project Cortex state for reattachment/recovery.

## Forgejo safety

Forgejo 15.0.7 remains loopback-only, private-by-default and registration-disabled. Actions are disabled by default. Cortex provisions its own service identity, scoped API token protected with Windows user DPAPI, and SSH key.

`git.host.backup` creates a complete Forgejo dump, copies it to the local Cortex Git backup root, verifies non-zero bytes and SHA-256, and removes the temporary container copy. Restore is deliberately not automated here: full host restore is an offline, explicit approval-gated recovery procedure.

`git.fetch.local` updates only remote-tracking refs. `git.sync.status` reports local/remote commit ids, ahead/behind counts, divergence and dirty state. `git.push.local` remains current-branch, non-force.

## Actions runner boundary

Forgejo Actions executes repository-controlled code. Cortex therefore keeps Actions disabled until a later pass can provision a repository-scoped, trust-gated, preferably ephemeral runner. A general host runner and arbitrary host Docker socket exposure are outside the default trust model.

## Observability and Chat

The native Activity rail exposes Cortex, Native Models, LM Studio compatibility, Jobs, Build, Git, Vault, System and Notifications. Native Models tails the managed llama.cpp/model-host logs in bounded windows. TextDelta events are aggregated into one bounded `Cortex · Live` card and flushed on the existing UI heartbeat rather than generating one Win32 message per token. Final persisted conversation content and verified diff/code cards remain authoritative.

Chat typography is reduced one small density step without changing application controls.

## Deferred intentionally

- Forgejo restore automation.
- Forgejo Actions runner provisioning.
- Cloud mirrors (GitHub/GitLab/Azure/other Forgejo).
- D:\ working-tree migration.
- Automatic duplicate deletion/deduplication.
- Hunk/line staging UI and destructive Git history operations.
