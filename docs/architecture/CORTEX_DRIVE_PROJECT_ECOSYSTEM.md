# Cortex Drive Project Ecosystem

## Goal

Cortex can attach to a development drive and treat it as a persistent project ecosystem.

The initial Windows target is `D:\Cortex`, but the implementation must support any user-selected
drive/folder.

## Provisioned library layout

```text
D:\Cortex\
├─ Projects\
│  ├─ <project-a>\
│  ├─ <project-b>\
│  └─ ...
├─ Intake\
│  ├─ _Unassigned\
│  ├─ <project-id>\
│  └─ ...
├─ Shared\
├─ Artifacts\
├─ Backups\
├─ Exports\
└─ .cortex\
   ├─ registry\
   ├─ memory\
   ├─ intake\
   ├─ transactions\
   ├─ history\
   └─ indexes\
```

Machine-local secrets and credentials remain outside the library root in the normal local
application settings location. The drive may contain project/library metadata, indexes,
transaction history, and non-secret memory.

## Attach Drive

Cortex Settings > Library provides:

- Attach Development Drive / Folder
- Provision Cortex Layout
- Scan Existing Projects
- Create Desktop Intake Shortcut
- Open Intake Folder
- Rebuild Project Index
- Detach Library (non-destructive)

If `D:\Cortex` exists, it may be offered as the preferred local library.

## Project ownership

Projects normally live under `Projects`, but Cortex may register projects elsewhere on the attached
drive without moving them.

Each registered project has:
- stable project/workspace ID;
- root path;
- adapter/profile;
- Project Control Center command authority;
- intake target;
- patch/update history;
- build/test history;
- searchable project memory.

## Intake shortcut

Cortex can create a Windows `.lnk` shortcut named:

`Cortex Intake`

pointing to:

`D:\Cortex\Intake`

The shortcut is a convenience entry point only. The real intake watcher owns processing.

## Intake watcher

Use native Windows directory change notifications (`ReadDirectoryChangesW`) with debounce/stability
checks. Never process a file while it is still being copied.

Recognized intake classes include:
- root-drop handoff ZIP;
- source/source-refresh ZIP;
- debug bundle;
- logs;
- screenshots/images;
- documents/specs;
- asset packs;
- generated images;
- arbitrary reference files.

## Project tagging priority

1. Explicit Cortex intake manifest/sidecar.
2. Project-specific intake folder: `Intake\<project-id>\`.
3. Handoff/patch manifest containing project identity.
4. Embedded project metadata.
5. Filename/path heuristic as a suggestion only.

Heuristics must never silently apply a patch to a project.

## Patch routing

A validated root-drop project handoff remains unextracted.

Flow:

```text
Cortex Intake
  -> classify
  -> resolve explicit project
  -> validate safe path + manifest + hashes
  -> create Cortex transaction record
  -> copy unchanged ZIP into target project root/update inbox
  -> target Project Control Center consumes it
  -> archive intake item
  -> link patch/build/debug events into Cortex memory
```

Cortex does not bypass the project's Project Control Center or directly spray patch files into source.

## General-file routing

Non-patch files are never automatically treated as source modifications.

Cortex may:
- attach them to a project;
- index them;
- create an artifact;
- offer them to a tool;
- create a proposed transaction;
- keep them as reference evidence.

## Safety and recovery

Every intake item receives:
- content hash;
- size;
- source path;
- receive timestamp;
- resolved project ID;
- classification;
- disposition;
- transaction ID when applicable;
- archive/quarantine path;
- optional provenance/redaction metadata.

Unknown or ambiguous patches go to quarantine/unassigned, not a project root.
