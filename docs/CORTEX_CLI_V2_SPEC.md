# Cortex CLI v2 Normalization Specification

## Goal

Make `cortex` a stable human CLI, automation CLI and agent-facing control surface without project-specific branches.

## Command tree

```text
cortex
  status
  doctor
  version

  project
    list
    add
    remove
    show
    activate
    discover
    rescan
    health
    home
    roadmap
    artifacts

  chat
    send
    list
    show
    new
    export
    archive

  agent
    inspect
    plan
    apply
    repair
    certify
    stop
    resume
    status

  job
    list
    show
    watch
    cancel
    retry

  task
    list
    show
    approve
    reject

  tool
    list
    describe
    call
    doctor

  plugin
    list
    discover
    show
    enable
    disable
    permissions
    doctor

  provider
    list
    show
    set
    doctor
    models

  pcc
    status
    commands
    run
    health
    gate
    patch
    artifacts
    logs

  git
    status
    diff
    history

  forgejo
    status
    repos
    sync
    issues
    pull-requests
    releases

  vault
    status
    scan
    search
    classify
    duplicates
    review

  tx
    list
    show
    diff
    commit
    rollback

  service
    status
    start
    stop
    restart

  config
    show
    get
    set
    validate

  completion
    powershell
    bash
    zsh
```

## Global options

Standardize:

```text
--project <id|path>
--format text|json|jsonl
--non-interactive
--yes
--dry-run
--timeout <duration>
--trace-id <id>
--no-color
--quiet
--verbose
```

Legacy `--json` and `--jsonl` can remain aliases during migration.

## Machine-readable output contract

### Final JSON
Every command supporting automation returns an envelope:

```json
{
  "schema_version": 2,
  "ok": true,
  "command": "pcc.health",
  "request_id": "...",
  "project_id": "...",
  "result": {},
  "warnings": [],
  "error": null
}
```

### Streaming JSONL
Long operations emit one event per line using the proposed `cortex_cli_event.v2` schema.

Required event concepts:
- command.started
- command.output
- command.progress
- tool.started/completed/failed
- job.state
- approval.required/resolved
- artifact.created
- transaction.changed
- command.completed/failed/cancelled

## Stable exit codes

Proposed baseline:

- 0 success
- 2 usage/arguments
- 3 configuration
- 4 project/workspace not found
- 5 permission/approval denied
- 6 dependency/tool unavailable
- 7 validation/quality failure
- 8 execution/process failure
- 9 protocol/plugin incompatibility
- 10 cancelled/interrupted
- 11 partial/degraded success
- 20 internal Cortex failure

Project/PCC adapter-specific failures are represented in structured result data, not by inventing random top-level exit codes.

## Cancellation

Replace string-driven cancellation state with a typed outcome:

```text
CancellationOutcome
  NotRunning
  CooperativeRequested
  HardInterrupted
  ExternalProviderDetached
  PendingRequestCancelled
  CompletedBeforeCancel
  Failed
```

CLI, Desktop, provider workers, jobs and PCC subprocesses must map to this one contract.

## Command registry

Do not maintain parallel command lists in:
- CLI parser;
- GUI command palette;
- tool registry;
- help text.

Create one typed command descriptor registry. Surfaces filter/format the same authority.

Descriptor fields:
- key
- aliases
- category
- description
- arguments schema
- output schema
- permissions
- interactive policy
- project requirement
- streaming support
- cancellation support
- origin/plugin
- stability/deprecation metadata

## External tool-provider contract

Independently upgraded CLI projects can expose capabilities without becoming Cortex dependencies.

Preferred order:
1. MCP server when the tool is AI-facing and naturally maps to tools/resources.
2. Native `tool-provider.json` + JSON/JSONL executable contract.
3. Legacy command wrapper adapter only when necessary.

Cortex records executable version and capability fingerprint before running a provider.

## Shell ergonomics

Add:
- PowerShell/Bash/Zsh completion;
- deterministic help;
- `cortex <noun> --help`;
- no ANSI when redirected or `--no-color`;
- stdout for machine result, stderr for diagnostics;
- TTY-aware progress;
- Unicode/UTF-8 initialization on Windows;
- no prompts in `--non-interactive`.

## Security

Every mutation command declares permissions. No plugin receives blanket filesystem/process/network access because it is installed.

Project path resolution must remain canonical and traversal-safe.

## CLI tests

Create golden fixture tests covering:
- text output;
- JSON output;
- JSONL event ordering;
- exit codes;
- cancellation;
- missing project;
- invalid schema input;
- plugin version mismatch;
- PCC unavailable;
- paths with spaces and UNC paths;
- UTF-8;
- redirected output.
