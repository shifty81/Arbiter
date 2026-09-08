# Cortex Standalone Normalization Action Matrix

| Current item | Action | Reason |
|---|---|---|
| Full Quality `Standalone boundary` stage | DELETE from active sequence | Cortex is already standalone |
| `Test-CortexStandaloneBoundary.ps1` | ARCHIVE or DELETE | migration-only validator; currently blocks gate with `.Count` defect |
| `Cortex.ProjectAdapter.ps1` boundary command mapping | DELETE | no active command should dispatch obsolete enforcement |
| Hxx/R051 literal-marker gate calls | DELETE from active certification | historical acceptance labels are not behavior truth |
| Hxx/R051 tests that actually exercise behavior | KEEP/RENAME | useful regression coverage |
| Open2D/Havenwild ownership/name prohibition checks | DELETE | integrations are optional providers, not enforced boundaries |
| Patch intake | KEEP | current project safety/operations |
| Root cleanliness | KEEP | current project health |
| Cargo/workspace health | KEEP | current project health |
| format/check/test/clippy/build | KEEP | core engineering certification |
| schema/CLI/plugin/provider tests | KEEP/EXPAND | product contracts |
| transaction/recovery tests | KEEP/EXPAND | mutation safety |
| GUI/runtime smoke | KEEP/EXPAND | product behavior |
| Forge integration fixtures | ADD | normalized project-operations integration |
| debug bundle/artifact/provenance output | KEEP/EXPAND | repair/recovery evidence |
| separation exporter | ARCHIVE | one-time historical migration utility |
| separation migration matrix | ARCHIVE | historical evidence only |

## Root utility expected result after normalization

The root utility should proceed directly from patch/root health into native or bootstrap engineering gates. The log should no longer contain `START Standalone boundary`.
