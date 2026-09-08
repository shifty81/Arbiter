# Cortex Native Desktop UX Contract — R16V6

## Purpose

Cortex is a Windows-native project/development shell, not a generic Win32 utility panel.
The visible desktop must converge on the project-first ChatGPT/Codex-style shell while retaining
native Windows behavior where native behavior is beneficial.

## Native Windows context menus

Right-click is an application-wide interaction contract.

Use native Win32 popup menus (`WM_CONTEXTMENU` + `TrackPopupMenuEx`) rather than custom-drawn popup windows.

Required contexts:

### Project row
- Open / Activate
- New Chat
- Refresh Project
- Scan / Re-index
- Open in Explorer
- Copy Project Path
- Project Settings
- Detach from Cortex

### Chat row
- Open
- Rename
- Pin / Unpin
- Duplicate / Branch
- Archive
- Copy Conversation ID

### Chat response/card
- Copy Response
- Upvote
- Downvote
- Regenerate
- Open referenced file/code in Workbench
- Copy Message ID

### Code block
- Copy Code
- Open in Workbench
- Apply / Review Diff when applicable

### File tree/list
- Open
- Open in Workbench
- Show in Explorer
- Copy Path
- Attach to Chat
- Assign / Reassign Intake Project when applicable

### Empty shell / panel space
- New Chat
- Refresh
- Command Palette
- Settings

Keyboard equivalents should later include the Windows Menu key and Shift+F10.

## Right context panel

The right side is one retained tabbed panel, never a row of unrelated utility buttons.

Primary tabs:

1. Files
2. Changes
3. Memory
4. Artifacts
5. Tasks
6. Settings

Rules:
- one compact tab strip at the top;
- icon + concise label when width permits;
- icon-only compact mode with tooltip when narrow;
- active underline/accent;
- tab state persists per project;
- right panel width and collapsed state persist;
- each tab owns only its content region, not shell chrome;
- Files uses a real tree/breadcrumb surface;
- Changes uses the shared rich diff renderer;
- Memory replaces the user-facing name "Vault";
- Settings uses nested tabs/sections inside Settings, not six permanent shell buttons.

## Chat cards and action row

Assistant cards require a consistent action row.

Order:
- Copy
- Upvote
- Downvote
- Regenerate

Up/down controls should visually read like Reddit vote arrows:
- compact outlined arrow glyph;
- selected state becomes filled/accented;
- no textual `▲ 1` / `▼ 1` utility styling;
- optional score appears between arrows only when useful;
- hover/focus states are visible.

Copy is always available for assistant responses and code blocks.

Card identity:
- Cortex assistant: dedicated Cortex glyph/avatar;
- user: simple user glyph/avatar;
- tool activity: wrench/terminal/tool glyph;
- system/status: info/status glyph;
- error: warning glyph.

Do not overuse colored avatar circles; keep the central conversation calm.

## Left project/chat navigation

Projects are top-level visual groups.

Required spacing:
- 8–12 logical px between project groups;
- 2–4 logical px between child chats;
- chats are indented below their parent project;
- active project and active chat are independently legible;
- long project/chat names ellipsize without breaking row geometry.

Project rows may expose hover actions, but permanent button clutter is prohibited.

## Composer

The composer becomes one cohesive surface:
- multiline text;
- Attach;
- Send/Stop;
- provider/model status in compact form;
- drag/drop;
- pasted images/files;
- Enter = Send;
- Shift+Enter = newline.

## Acceptance

R16V6 GUI closure requires:
- native right-click contexts;
- keyboard focus;
- 100–200% DPI;
- narrow laptop through ultrawide;
- no stock-light controls;
- no overlapping tabs;
- no raw Win32 utility-button rows;
- no context menu action that bypasses Cortex transaction/permission policy.
