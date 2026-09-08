# Cortex Root Control Center + Git baseline

## Decision

The standalone Cortex repository is a first-class managed project under the Universal Project Control Center (PCC).

Cortex does **not** fork or reimplement PCC. The repository contains only:

- `PROJECT_CONTROL_CENTER.cmd` — stable project-root launcher;
- `tools/control/Invoke-UniversalPCC.ps1` — resolver/forwarder to the shared PCC runtime;
- `project.control.json` — Cortex-specific project command/gate declarations;
- `.gitignore` / `.gitattributes` — repository policy;
- `scripts/Initialize-CortexGit.ps1` — explicit local Git bootstrap helper.

The shared PCC runtime remains the authority for project discovery, command registry, streaming process execution, run-scoped logs/action history, health, Git/remote operations, transactional patch intake/rollback, diagnostics, artifacts, handoffs and GREEN certification.

## Root launch behavior

Opening `PROJECT_CONTROL_CENTER.cmd` must:

1. resolve the Cortex project root from the launcher location;
2. resolve the shared PCC runtime (`PCC_HOME` / `PROJECT_CONTROL_CENTER_HOME` preferred);
3. invoke PCC with Cortex as the explicit project;
4. allow PCC to inspect the root/update inbox before the interactive menu;
5. preserve errors on screen instead of silently closing.

No project-specific PowerShell menu should compete with the universal runtime.

## Patch/update intake

Cortex uses the normalized PCC transaction model:

- recognize governed incremental patch **and handoff** ZIPs;
- validate manifest/hashes/path safety/preimages before writing;
- create pre-patch recovery evidence;
- apply transactionally;
- archive applied/failed/superseded packages;
- invalidate prior certification whenever source changes;
- continue into the requested quality gate only after a successful intake;
- retain run-scoped logs and exact transaction IDs.

The root `updates/inbox/` folder is source-controlled only through `.gitkeep`; ZIP payloads are ignored.

## Git authority

Local Git is mandatory infrastructure for Cortex development; a remote is optional.

PCC owns project-level mutations:

- status;
- init/connect;
- diff/review;
- commit last GREEN source;
- commit + push last GREEN source;
- push;
- fast-forward-only pull;
- remote/Forgejo/GitHub status;
- recovery/history evidence.

Cortex GUI may expose these operations, but it must call the PCC/headless contract instead of implementing a second Git engine.

## GREEN source-control rule

A GREEN record is bound to the exact certified source state. At minimum the fingerprint covers:

- Git HEAD;
- tracked working-tree changes;
- staged changes;
- untracked non-ignored file hashes;
- quality-gate identity/result;
- source fingerprint.

A protected commit/push is allowed only while that evidence still matches. After the certified source is committed, the GREEN record is refreshed to the resulting commit identity without pretending a different source was certified.

Manual commits remain possible through an explicitly advanced/unprotected path and must be labeled accordingly.

## First repository bootstrap

After the real standalone source tree is exported:

```powershell
pwsh -File .\scripts\Initialize-CortexGit.ps1
```

To configure a remote explicitly:

```powershell
pwsh -File .\scripts\Initialize-CortexGit.ps1 -RemoteUrl <forgejo-or-github-url>
```

The helper does not commit or push. Run the Root Project Control Center, pass the standalone Full Quality Gate, then use its GREEN-protected source-control command.

## Cortex initial gates

Fast:

```text
cargo fmt --all -- --check
cargo check --workspace --all-targets
```

Full:

```text
cargo metadata --format-version 1 --no-deps
cargo fmt --all -- --check
cargo check --workspace --all-targets
cargo test --workspace --all-targets
cargo clippy --workspace --all-targets -- -D warnings
cargo build --workspace
```

Later standalone certification extends the full gate with CLI/PCC/plugin/Desktop fixture and smoke suites.
