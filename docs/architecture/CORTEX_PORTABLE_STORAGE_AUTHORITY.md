# Cortex Portable Storage Authority

## Authority rule

D: is the first-run preference only. Cortex persists a configurable local storage root plus Windows volume identity (volume GUID/serial/filesystem/mount metadata) so drive-letter changes do not silently create a second authority.

## Managed layout

`<authority>/Projects`, `Vault`, `Models`, `Backups`, `Recovery`, `RecycleBin`, `Git` (Forgejo substrate), and `.cortex/MigrationStaging` are resolved from the configured authority. Existing in-place projects may remain outside the managed root.

## Discovery

Storage scans and whole-PC scans are explicit, read-only catalog operations. Whole-PC scanning uses eligible fixed local volumes by default and prunes system/generated/cache directories during traversal. Catalog confidence does not authorize registration or migration. Project graph/lineage review remains the decision surface.

## Migration

Project migration is copy-first and verification-first. Cortex copies into destination-side MigrationStaging, rejects symlinks, verifies every regular file byte-for-byte, promotes on the destination volume, rebinds Cortex identity, preserves existing repository history, and leaves the original source untouched. The promoted copy remains `PromotedPendingValidation` until the real project quality gate passes. Cleanup/probation is a later explicit operation and ultimately uses Cortex Recycle Bin before Windows Recycle Bin.

## Offsite backup

A Google Drive for Desktop local folder (or another user-selected sync folder) can be configured outside the live authority. Cortex may certify the local copy and SHA-256 only; `cloud_upload_confirmed` remains false until a future provider API can verify remote sync. Forgejo dumps are copied and hash-verified into this target when configured.

## Deferred

Moving the already-live Cortex authority itself between volumes is intentionally not performed by STOR1. That requires a dedicated service-aware authority migration that stops/snapshots Forgejo and model services, copies/verifies state, rewrites bindings, restarts and health-checks before changing authority.
