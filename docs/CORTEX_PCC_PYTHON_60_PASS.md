# Cortex Python PCC — 60-Pass Completion Report

Version: `CTX-PCC-12.0`

CTX-PCC-12 extends the previous 40-pass Python cutover with 20 additional passes focused on artifact authority, root cleanliness, evidence integrity, retention, and concurrent-operation safety. The Project Control Center remains Python-first; PowerShell remains a compatibility/bootstrap and Windows AST-validation surface only.

## Passes 41–60

41. Move PCC session logs to the canonical `artifacts/logs/sessions` authority.
42. Detect obsolete root `LATEST_DEBUG_BUNDLE*.txt` pointers.
43. Detect root-level `Cortex_DebugBundle_*.zip` residue.
44. Transactionally normalize legacy root debug pointers into artifacts instead of deleting them silently.
45. Normalize root debug ZIPs into `artifacts/debug`.
46. Normalize recognized legacy PCC/root session logs from `logs/sessions` into `artifacts/logs/sessions`.
47. Write maintenance receipts for every root-hygiene repair.
48. Make `artifacts/debug/LATEST_DEBUG_BUNDLE.txt` and `.json` the only latest-debug authorities and write them atomically.
49. Generate a SHA-256/byte manifest for every debug bundle payload.
50. Verify the completed debug ZIP against its embedded manifest before publishing it as latest.
51. Detect post-build/tampered debug bundle content.
52. Generate a SHA-256 sidecar for every debug bundle.
53. Compute deterministic artifact-retention plans.
54. Make retention dry-run the default and non-destructive behavior.
55. Require an explicit apply action before old debug/log artifacts are deleted.
56. Add one-at-a-time PCC operation locking for gate/build workflows.
57. Reclaim stale PCC operation locks using PID liveness/age checks.
58. Add a Python PCC doctor report covering hygiene, disk availability, latest evidence and operation-lock state.
59. Expose maintenance/doctor/evidence verification as headless commands for Cortex/Forge integration.
60. Expand the executable PCC suite to 60 tests and remove the duplicate Fast-gate menu entry.

## Root cleanliness policy

Startup remains read-only. It reports generated operational residue but does not move source or operational files. An explicitly selected Fast or Full gate may normalize known generated operational residue into `artifacts/` before validation. Operators can also run the repair directly from Diagnostics or with `root-hygiene-fix`.

Known generated root residue is narrowly classified; arbitrary files are never moved. Root patch ZIPs remain patch transport and are managed by `CortexPatchAuthority.py`, not by maintenance cleanup.

## Evidence authority

A new debug bundle is not published as latest until all of the following succeed:

- the evidence tree is built;
- `MANIFEST.json` records every payload file, byte count and SHA-256;
- the ZIP is created;
- the ZIP is reopened and verified against the manifest;
- a `.sha256` sidecar is written;
- `artifacts/debug/LATEST_DEBUG_BUNDLE.json` and `.txt` are atomically updated.

No root-level latest-debug pointer is written by the Python PCC.

## Retention

Retention is explicit. `artifact-prune` is dry-run only. `artifact-prune-apply` performs deletion and emits a maintenance receipt. Interactive mode asks for confirmation before deletion.

Defaults preserve the newest 30 debug bundles and 200 PCC session-log files. These limits are intentionally conservative and can be made project-configurable later without changing the artifact authority.

## Machine commands added

- `doctor`
- `doctor-json`
- `root-hygiene`
- `root-hygiene-fix`
- `artifact-status`
- `artifact-prune`
- `artifact-prune-apply`
- `verify-latest-debug`

## Verification

The cumulative Python suite now contains 60 tests in `tools/control/tests/test_cortex_pcc.py`. All 60 passed in the build environment. The PCC self-test entrypoint also completed with exit code 0.

Windows remains authoritative for the staged PowerShell AST parse and the real Cortex Cargo Full Quality Gate.
