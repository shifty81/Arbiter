# Universal Project Control Center Root CLI Standard

## One authority, three surfaces

The Universal Project Control Center is one runtime with three ways to use it:

1. **Root embedded launcher**
   - `PROJECT_CONTROL_CENTER.cmd`
   - tiny, stable bootstrap only;
   - locates/invokes the universal runtime;
   - project behavior comes from `project.control.json`.

2. **Hub CLI**
   - central project registry and scan roots;
   - can operate any registered project.

3. **Headless client contract**
   - used by Cortex and future GUIs;
   - JSON/JSONL, stable exit codes, no prompts.

There must not be a different PCC implementation in every project.

## Bootstrap state machine

```text
Start
  -> ResolveRuntime
  -> ResolveProject
  -> ResolveState
  -> InitializeEncoding
  -> InitializeLogging
  -> LoadRegistry
  -> LoadManifestAndAdapters
  -> BuildCommandRegistry
  -> Ready
```

If any step fails, emit exactly one typed bootstrap error plus diagnostic context.

Logging before `InitializeLogging` uses an in-memory/pre-bootstrap sink and is flushed after the sink is ready.

## Root resolution precedence

1. explicit `--project`/`-Project`;
2. project ID in central registry;
3. launcher-relative project root in embedded mode;
4. safe upward discovery from current path;
5. explicit NotFound failure.

Never invoke `Get-ChildItem`/filesystem health logic with an unresolved root.

## Standard command contract

```text
pcc version
pcc project list
pcc project show
pcc project health
pcc command list
pcc run <command-key>
pcc gate run <gate-key>
pcc patch status
pcc patch apply
pcc patch history
pcc artifact list
pcc logs latest
pcc debug bundle
pcc source-refresh create
pcc handoff create
pcc git status
pcc forgejo status
```

PowerShell compatibility commands can map to the same backend.

## Output

All headless commands support:
- `--format json`
- `--format jsonl`
- `--non-interactive`
- `--no-color`

Long-running operations emit structured events with:
- schema_version;
- event;
- event_id;
- action_id;
- project_id;
- timestamp;
- stage;
- status;
- message;
- data;
- optional trace/span IDs.

## project.control.json

This is the project adapter declaration, not executable code injected into the universal core.

It defines:
- project identity/kind;
- command descriptors;
- quality gates;
- environment/tool requirements;
- diagnostics hook;
- artifact declarations;
- optional runtime/editor/server capabilities.

## Cortex integration

Cortex never scrapes the interactive menu.

It uses:
- version/discovery;
- command list;
- health;
- run command;
- job/event stream;
- cancellation;
- artifacts/logs;
- patch/rollback;
- Git/Forgejo.

The GUI renders these results as Project Operations.

## Patch/update standard

Keep:
- unextracted root-drop ZIP;
- manifest validation;
- hashes;
- path safety;
- preimage assertions;
- transactional application;
- rollback;
- consumed archive;
- deferred self-update;
- stale update supersession;
- post-state assertions.

Add:
- pre-patch source snapshot;
- certified post-GREEN source snapshot;
- artifact index;
- exact update transaction ID emitted to Cortex.

## Quality gate standard

A quality gate is data:
- stages;
- commands;
- dependencies;
- timeout policy;
- stop-on-failure policy;
- evidence requirements.

A GREEN marker is valid only while its source fingerprint remains unchanged.

## Forgejo

PCC owns project-level repository operations. Cortex owns the high-level UX/agent interaction and talks to PCC/Forgejo providers.

Use Forgejo's versioned API and record the Forgejo server major version/capabilities so upgrades can be handled explicitly.

## Required fixtures

Golden fixture projects:
- Rust/Cargo;
- CMake/C++;
- Gradle/Java;
- Node;
- generic source;
- no Git;
- Git + Forgejo;
- UNC/NAS project;
- path with spaces/non-ASCII;
- moved project;
- legacy project with multiple old control centers.
