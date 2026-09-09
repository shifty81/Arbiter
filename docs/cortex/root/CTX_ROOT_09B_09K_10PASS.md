# Cortex Root Utility — CTX-ROOT-09B through CTX-ROOT-09K

Baseline: GitHub GREEN commit `04128acb0d14b06f589dac0d88dae8505221e408`.

This cumulative batch intentionally modifies only Root Utility/control/documentation files. It does not modify Cortex Rust source.

| Pass | Change |
|---|---|
| CTX-ROOT-09B | Manifest-authoritative patch intake. `PATCH_MANIFEST.json` schema/project/patch ID, exact payload membership, per-file SHA-256 and byte counts, staged PowerShell parse validation, optional pre-image SHA checks, safe removal declarations, and post-apply verification. |
| CTX-ROOT-09C | Deterministic patch queue ordering plus optional `dependsOn` dependency enforcement against previously applied receipts and earlier queue entries. |
| CTX-ROOT-09D | Transactional backup/rollback evidence, applied/failed transport separation, success/failure/invalid JSON patch receipts, and `LATEST_PATCH_RECEIPT.json`. |
| CTX-ROOT-09E | Scan-only and validate-only patch inspection. Validation checks ZIP sidecar, exact manifested payload, staged hashes/bytes, PowerShell syntax and preconditions without applying source changes. |
| CTX-ROOT-09F | Cargo-metadata native target discovery. CLI/GUI package target names and Cargo target directory are resolved from `cargo metadata` rather than only hard-coded paths. |
| CTX-ROOT-09G | Structured Cargo run receipts for build/check/test/clippy/fmt commands under `artifacts/builds`, including exit code, timing, arguments and current Git HEAD. |
| CTX-ROOT-09H | Artifact latest pointers and explicit retention maintenance for Root session logs and debug bundles. Patch archives/receipts are not automatically pruned. |
| CTX-ROOT-09I | Expanded Project Status / Health surface with workspace package count, pending/invalid patches, resolved native target paths, Git/GREEN status and latest evidence. Writes `artifacts/status/LATEST_ROOT_STATUS.json`. |
| CTX-ROOT-09J | Explicit published-main verification: fetch `origin/main`, compare local HEAD, remote HEAD and working-tree cleanliness, then write `artifacts/status/LATEST_PUBLISHED_STATE.json`. |
| CTX-ROOT-09K | Root self-audit integrated into Full Quality. Audits required control files, PowerShell parseability, menu contracts, intake contracts and artifact roots; writes `artifacts/certification/LATEST_ROOT_SELF_AUDIT.json`. |

## Operator workflow

1. Drop a manifested `Cortex_*_RootPatch_*.zip` into the Cortex root or `updates/inbox`.
2. Launch `PROJECT_CONTROL_CENTER.cmd`.
3. Startup applies the pending queue automatically and relaunches if control files changed.
4. Startup runs the Quick Gate.
5. Operator selects **Test / Validate / Certify → FULL QUALITY GATE**.
6. If GREEN, operator selects **Source Control / Git → Commit + push if FULL GREEN matches**.
7. Published-main verification runs after a successful GREEN commit+push.

The first CTX-ROOT-09K startup also creates an operational `CTX-ROOT-09K` baseline patch receipt if the older intake applied this cumulative package before receipt authority existed. Future `dependsOn` declarations can therefore depend on `CTX-ROOT-09K`.

Full Quality and Git publication remain explicit operator actions.
