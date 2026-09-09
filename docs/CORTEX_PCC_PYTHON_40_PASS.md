# Cortex Python PCC — 40-Pass Hardening Report

Version: `CTX-PCC-11.0`

This pass moves the Project Control Center authority from the large PowerShell controller into `tools/control/CortexPCC.py`. PowerShell remains only as a compatibility/bootstrap surface for existing integrations and for Windows PowerShell AST validation.

## 40 executed Python PCC checks

1. Explicit project-root normalization.
2. Machine-readable authority result parsing.
3. Dual text + JSONL session telemetry.
4. Successful streamed subprocess execution.
5. Non-zero subprocess result propagation.
6. Timeout/process-tree termination.
7. Normalized PCC path model.
8. Debug/release binary resolution.
9. Python PCC entrypoint AST compilation.
10. Patch relative-path normalization.
11. Patch traversal rejection.
12. Operational-destination rejection.
13. Valid manifest + sidecar acceptance.
14. Mandatory sidecar enforcement.
15. Sidecar hash mismatch rejection.
16. Undeclared ZIP payload rejection.
17. Payload SHA mismatch rejection.
18. Case-insensitive duplicate ZIP-entry rejection.
19. Patch-ID format enforcement.
20. Self-dependency rejection.
21. Missing dependency fail-closed scan.
22. Topological dependency ordering.
23. Dependency-cycle fail-closed behavior.
24. Transactional patch write + receipt.
25. Transactional file removal.
26. Preimage mismatch preserves live source.
27. Replay protection by applied receipt.
28. PCC-control update restart detection.
29. Debug/non-patch ZIP ignore behavior.
30. Stale patch-intake lock reclamation.
31. GREEN fingerprint operational/ZIP exclusion.
32. GREEN marker matches unchanged source.
33. GREEN marker becomes stale after source change.
34. GREEN staging excludes root ZIP transport.
35. GREEN staging includes governed deletions.
36. GREEN commit rejects non-main branch.
37. Git machine-status contract.
38. Manual governed-source commit excludes transport ZIPs.
39. Atomic GREEN marker JSON validity.
40. Python PCC self-test command registration.

All 40 tests passed in the build environment. They are shipped in `tools/control/tests/test_cortex_pcc.py` and can be rerun with:

`python tools/control/CortexPCC.py self-test --root <CortexRoot>`

## Additional hardening included

- Python is now the top-level PCC authority launched by `PROJECT_CONTROL_CENTER.cmd`.
- The legacy PowerShell `ProjectControlCenter.ps1` is a thin bridge into the Python PCC.
- Quick/Fast/Full gate orchestration is owned by Python.
- Debug/certification bundle generation is owned by Python.
- Session telemetry is persisted as human-readable log plus structured JSONL.
- Child processes stream live output, expose elapsed time, propagate exit status, support timeouts, and terminate process trees on cancellation.
- Patch intake adds canonical patch IDs, ZIP file/size/decompression budgets, non-regular-entry rejection, canonical manifest naming, topological dependency ordering, cycle detection, PID-aware stale-lock recovery, and a second preimage check immediately before the live mutation phase.
- Git staging is aligned with the GREEN fingerprint: excluded ZIPs/sidecars/operational files are explicitly unstaged even after `git add -A`, while governed deletions remain staged.
- GREEN commit and push require local `main`.
- GREEN marker writes are atomic.

## Windows authority still required

The supplied patch is structurally and Python-tested here, but this environment cannot execute the Windows PowerShell AST parser or the real Cortex Rust workspace quality gate. The existing staged root-intake PowerShell parser must approve the compatibility scripts on Windows, followed by the normal Cortex Full Quality Gate.
