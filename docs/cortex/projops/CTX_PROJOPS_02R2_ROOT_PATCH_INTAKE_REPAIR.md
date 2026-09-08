# CTX-PROJOPS-02R2 — Root Patch Intake Repair

Date: 2026-09-07

## Trigger

The first live application of the CTX-PROJOPS-02R1 root patch reached `InvokeRootPatchIntake.ps1` and failed before writing any payload files:

`Cannot convert argument "trimChars", with value: "\\", for "TrimStart" to type "System.Char".`

The R1 patch was therefore not applied and was moved to `updates/failed`.

## Root cause

The bootstrap patch engine derived staged relative paths using a `String.TrimStart` overload with string arguments. The first literal represented two backslash characters, while the .NET overload requires `Char` values. PowerShell overload conversion failed on Windows before the first file could be copied.

## Repair

R2 is cumulative from the CTX-PROJOPS-02 clean rollup and includes the R1 standalone-boundary repair plus the patch-engine repair.

`InvokeRootPatchIntake.ps1` now:

- derives staged relative paths without `TrimStart(char[])` overload resolution;
- validates ZIP entries before extraction;
- verifies every destination remains beneath the project root;
- uses unique millisecond snapshot paths per patch;
- cleans temporary staging in `finally`;
- preserves overwritten files under `artifacts/updates/snapshots`;
- archives successfully applied ZIPs under `updates/applied`;
- archives failed ZIPs under `updates/failed`.

The boundary validator's PowerShell 5.1 relative-path fallback was hardened the same way so it cannot hit the same separator-overload class of problem.

## Application rule

Because the patch engine itself is the failed component, this R2 package is a **one-time manual overwrite repair**. Extract it directly over the Cortex repository root with overwrite enabled. Do not feed R2 through the broken pre-R2 inbox engine.

After R2 is installed, normal unextracted `updates/inbox` patch delivery resumes.

## Expected next certification

Run `PROJECT_CONTROL_CENTER.cmd` and select `FULL QUALITY GATE`. The gate should:

1. report no pending patches (unless another patch is intentionally queued);
2. pass root cleanliness;
3. execute the repaired standalone boundary;
4. advance into Cargo metadata / fmt / check / test / clippy / build.

Windows remains the authoritative runtime/compile certification environment.
