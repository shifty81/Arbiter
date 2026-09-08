# UPCC -> Cortex Feature Parity and Authority Matrix

Legend: **PORT** = native Cortex authority; **ADAPTER** = project/domain plugin; **EVIDENCE** = donor-only. There is no permanent CLIENT-to-separate-PCC category anymore.

| Capability | Decision | Pass | Native target |
|---|---|---:|---|
| Stable project identity / typed contract | PORT | 02 | `cortex_project` + registry |
| Typed commands, risk, cancellation, rollback, artifacts | PORT | 02 | `cortex_project` |
| Cortex self-registration / project zero | PORT | 02 | `cortex_registry` |
| Native project CLI / quality gate entry | PORT | 02/07 | `cortex_cli` + process spine |
| Hardened discovery / ownership boundaries / budgets | PORT | 03 | native discovery service |
| Durable project registry / family / lineage | PORT | 04 | SQLite registry |
| Git status/worktrees/leases | PORT | 05 | Git provider + lease service |
| Plan -> Validate -> Apply -> Verify -> Recover | PORT | 06 | transaction coordinator |
| Root-drop patch/update intake + rollback/history | PORT | 06/07 | native project operations |
| Streaming project process host | PORT | 07 | process/events spine |
| Build/test/lint/run and quality gates | PORT | 07 | typed command/gate execution |
| GREEN evidence/source fingerprint/debug bundles | PORT | 07 | evidence/artifact services |
| Audit/source refresh/handoff/packaging | PORT | 07/08 | artifact/package services |
| Environment/toolchain inventory | PORT | 08 | normalized project capability view |
| Project/fleet/graph/event APIs | PORT | 08 | application API |
| GUI Project Control Center | PORT | 08 | Cortex Desktop |
| Game/editor/domain commands | ADAPTER | integrations | Open2D/Havenwild/etc plugins |
| B003R3 PowerShell implementation | EVIDENCE | 01 | `migration/upcc_v0_6_3` |
| Historical PCC menu/UI | EVIDENCE | 01 | migration only |

## Duplication checks

Architecture certification should fail if a new independent PCC backend is introduced beside Cortex, if generic Cortex crates acquire project-name branches, if project adapters are compiled directly into generic `cortex_cli`, or if donor PowerShell becomes a hidden runtime dependency.
