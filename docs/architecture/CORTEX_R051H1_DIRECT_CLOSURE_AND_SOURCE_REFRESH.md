# O2D-R051H1 — Direct Closure + Source Refresh

## Why H1 exists

The 2026-08-19 20:57 Cortex checkpoint proves that the R051 support files were extracted but the R051 maintenance apply action did not modify the active Rust source:

- workspace closure remained 53/53;
- build and tests passed;
- Cortex Desktop certification remained READY;
- the source manifest increased from 4640 to 4645 files;
- the checkpoint still reported `O2D-R050H10`;
- `crates/cortex_activity/src/lib.rs` still contained `.filter_map(Result::ok)`.

R051H1 therefore makes the active-source repair explicit and installs a durable source handoff path.

## Root utility source refresh

The existing `Open2DTools.cmd` is patched in place—not replaced—with two aliases:

```text
Open2DTools.cmd source-refresh
Open2DTools.cmd source-chatgpt
```

They call:

```text
scripts/Export-Open2DSourceForChatGPT.ps1
```

The resulting archive is written under:

```text
artifacts/source-snapshots/
```

so the repository root stays clean.

The default source snapshot includes code, manifests, lockfiles, project/config/schema data, docs and development scripts while excluding build output, logs, caches, package caches, local Cortex state, archives and other generated bulk.

Binary asset files are excluded by default to keep the ChatGPT source refresh compact. They can be included explicitly with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Export-Open2DSourceForChatGPT.ps1 -RepoRoot . -IncludeAssetBinaries
```

## Required verification

After applying H1:

1. Run the Cortex checkpoint.
2. Confirm Clippy `-D warnings` passes the former `cortex_activity` location.
3. Run `Open2DTools.cmd source-refresh`.
4. Upload the generated `Open2D_Foundry_SourceRefresh_*.zip` as the refreshed project source.
