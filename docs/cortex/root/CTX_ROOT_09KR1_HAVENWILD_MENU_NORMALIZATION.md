# CTX-ROOT-09KR1 — Havenwild Root Utility Menu Normalization

This pass restores the proven Havenwild Project Control Center interaction hierarchy to Cortex while preserving Cortex-specific native operations.

Canonical GREEN path:

1. Build & verify
2. Full quality gate

The top-level menu is normalized to:

1. Build & verify
2. Run & launch
3. Project & workspace tools
4. Project maintenance & diagnostics
5. Updates & recovery
6. Artifacts & evidence
7. Logs & help
8. Advanced / all registered commands
9. Source control (GitHub optional)
0. Exit

Cortex startup still owns automatic patch intake and relaunch before the startup Quick Gate.
The Full quality gate does not re-run intake. It certifies the exact post-intake governed source and writes the GREEN source marker used by protected commit/push.

The 09B–09K manifest, receipt, artifact, native-binary-discovery, published-state, and Root self-audit capabilities remain intact.
