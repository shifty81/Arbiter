# O2D-R051N3 — Workspace Identity + Global Cortex State

Cortex project state is now global/user-local by default under
`CORTEX_HOME/workspaces/<WorkspaceId>`.

The registry schema records a persistent WorkspaceId, current root, known
historical paths, project fingerprint and state root. Repository moves can be
reattached without making the filesystem path the long-term identity.

Legacy `.cortex` and `.open2d/cortex` directories are migration sources.
Repo-local state is available only when `CORTEX_STATE_MODE=portable`.
