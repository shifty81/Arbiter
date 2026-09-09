# Cortex Project Control Center

Current authority: `CTX-PCC-12.0`.

`PROJECT_CONTROL_CENTER.cmd` launches the Python Project Control Center at `tools/control/CortexPCC.py`. PowerShell is retained only as a thin compatibility/bootstrap layer for older callers and Windows AST validation. Git/source correctness remains isolated in `CortexGitAuthority.py`; root-patch correctness remains isolated in `CortexPatchAuthority.py`.

## Operator workflow

The root menu remains deliberately small:

1. Full Quality Gate / certify GREEN.
2. Commit current certified GREEN source.
3. Launch Cortex GUI.
4. Source / Project Control.
5. Build / Run.
6. Diagnostics / Recovery.

Startup is source-read-only: patch scan, Quick gate, and one startup evidence bundle. Pending patches are reported but never silently applied.

## Python PCC responsibilities

The Python PCC owns menu/CLI dispatch, session telemetry, subprocess execution, cancellation/timeout handling, Cargo metadata and binary discovery, Quick/Fast/Full gates, build/run workflows, patch/Git authority integration, and debug/certification bundle creation.

Every session writes both a text log and structured JSONL under `artifacts/logs/sessions` so Cortex can consume the same operational timeline later without scraping terminal text.

## Artifact and root-hygiene authority

Generated PCC evidence is contained under `artifacts/`. Session logs use `artifacts/logs/sessions`; debug bundles and latest-debug pointers use `artifacts/debug`; maintenance receipts use `artifacts/maintenance/receipts`. Startup only reports legacy generated root residue. Fast/Full or an explicit maintenance command can normalize known generated residue into artifacts. Arbitrary project files are never swept or moved.

## Patch authority

Recognized Cortex root patches require canonical `PATCH_MANIFEST.json`, a matching SHA-256 sidecar, exact payload allowlisting, per-file SHA/byte verification, safe relative destinations, operational-root rejection, replay protection, dependency validation/topological ordering, staged verification, preimage checks, transaction backups, atomic replacement, post-state verification, rollback, receipts and archive evidence. Invalid recognized patches fail the queue closed. A PCC self-update stops the queue and requires relaunch before any later patch is applied.

## Git/GREEN authority

GREEN fingerprints exclude operational data and patch/debug transport. GREEN staging uses the same exclusion semantics, including explicit unstaging of ZIP/sidecar transport after `git add -A`, while still preserving governed deletions. GREEN commit/push requires branch `main` and a source fingerprint matching the most recent successful Full Quality Gate.

## Gates

Quick validates PCC/project contracts, Python syntax, PowerShell compatibility syntax when PowerShell is available, patch authority, Git authority, Rust/Cargo availability and Cargo workspace metadata.

Fast = Quick + format check + workspace/all-target Cargo check.

Full = Quick + format + check + all-target tests + Clippy with warnings denied + workspace build + GREEN marker.

Each requested gate can create one verified evidence bundle under `artifacts/debug`. Bundles contain an embedded SHA-256 manifest and receive a `.sha256` sidecar before the artifact-local latest pointer is advanced. Failures open the debug artifact directory on Windows.

## Headless commands

`interactive`, `status`, `status-json`, `quick`, `fast`, `full`, `patch-status`, `patch-apply`, `debug-bundle`, `git-status`, `git-review`, `git-history`, `git-verify`, `git-fetch`, `git-compare`, `git-pull`, `git-setup`, `commit-green`, `commit-push-green`, `push`, `build`, `build-release`, `launch-gui`, `self-test`, `doctor`, `doctor-json`, `root-hygiene`, `root-hygiene-fix`, `artifact-status`, `artifact-prune`, `artifact-prune-apply`, `verify-latest-debug`.

Use `--yes` only with an explicitly requested headless patch apply. Startup never uses it.

See `docs/CORTEX_PCC_PYTHON_40_PASS.md` for passes 1–40 and `docs/CORTEX_PCC_PYTHON_60_PASS.md` for passes 41–60.
