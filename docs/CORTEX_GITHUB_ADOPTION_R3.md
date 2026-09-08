# Cortex GitHub adoption + Root PCC launcher repair (R3)

## Permanent remote

The permanent GitHub remote for standalone Cortex is:

`https://github.com/shifty81/Cortex.git`

The repository's prior Arbiter-era contents and Git history are not part of the new Cortex authority and do not need to be preserved.

## Launcher repair

R2 passed `%~dp0` directly as a quoted native argument while it still ended in `\`.
On Windows, that can reach PowerShell as a malformed value such as:

`C:\Users\Shifty\Desktop\Cortex" `

R3 fixes the problem twice:

1. `PROJECT_CONTROL_CENTER.cmd` removes the trailing slash before native invocation.
2. `Invoke-UniversalPCC.ps1` defensively strips malformed quote/whitespace and can recover the project root from its own script location.

This makes root resolution fail-safe instead of depending on one fragile native argv representation.

## Git initialization

Run:

```powershell
pwsh -File .\scripts\Initialize-CortexGit.ps1 -ReplaceRemote
```

This:

- initializes local Git on `main` if needed;
- normalizes the branch to `main`;
- sets `origin` to `https://github.com/shifty81/Cortex.git`;
- does **not** commit;
- does **not** push;
- does **not** destroy the current remote by itself.

## One-time replacement policy

Because the existing remote is intentionally disposable, the first certified standalone Cortex baseline may establish an unrelated clean history on GitHub `main`.

That operation is a **one-time repository-adoption transaction** and belongs in Universal PCC. Its safety contract is:

1. standalone Cortex Full Quality Gate is GREEN;
2. GREEN source fingerprint still matches the exact working tree;
3. local branch is `main`;
4. `origin` is exactly `https://github.com/shifty81/Cortex.git`;
5. the user explicitly selects/approves **Replace remote main with certified Cortex baseline**;
6. PCC records the old remote head SHA as recovery/provenance evidence even though it is not retained as an archive branch;
7. PCC performs the force replacement;
8. PCC verifies remote `main` resolves to the new certified commit;
9. PCC records the adoption transaction;
10. force replacement is disabled for normal future source-control flow.

Normal Cortex development then uses ordinary GREEN-protected commit/push, fast-forward pull, Forgejo/GitHub status, and transactional recovery through PCC.

## No duplicate Git engine

Cortex Desktop and Cortex CLI may expose Git/Forgejo operations, but project-level mutations route through the PCC contract. Cortex does not implement a competing project Git authority.
