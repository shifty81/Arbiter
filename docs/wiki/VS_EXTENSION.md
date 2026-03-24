# Visual Studio Extension

The Arbiter VS Extension brings the full Arbiter AI experience inside
Visual Studio 2022 as a native dockable panel and 9 AI-powered commands.

---

## Installation

### Option A — From VSIX File

1. Download `ArbiterAI.vsix` from the [Releases page](https://github.com/shifty81/Arbiter/releases)
2. Close Visual Studio
3. Double-click the `.vsix` file
4. Follow the installer prompts
5. Reopen Visual Studio

### Option B — Build from Source

1. Open `VisualStudioExtension/ArbiterVSIX/` in Visual Studio 2022
2. Ensure **Visual Studio SDK** workload is installed
3. Press **F5** — this builds the extension and opens a new VS instance with it installed

---

## Configuration

Go to **Tools → Options → Arbiter AI** to configure:

| Setting | Default | Description |
|---------|---------|-------------|
| Backend URL | `http://127.0.0.1:8001` | Arbiter Engine or PythonBridge URL |
| Auto-detect backend | `true` | Probe ports 8000 and 8001 on startup |
| Inline trigger | `// Arbiter:` | Prefix that activates inline completions |
| Max response tokens | `2048` | Token budget for inline completions |
| Auto-open chat panel | `false` | Open chat panel when a solution loads |

---

## AI Commands

All commands appear in the VS toolbar and under **Tools → Arbiter AI**.

| Command | Shortcut | Description |
|---------|----------|-------------|
| **Ask Arbiter About Selection** | `Ctrl+Shift+A` | Send selected code to the chat panel for explanation/discussion |
| **Explain This Code** | `Ctrl+Shift+E` | AI explains the selected code block |
| **Fix This Error** | `Ctrl+Shift+F` | AI fixes the selected error or code issue |
| **Refactor With Arbiter** | `Ctrl+Shift+R` | AI refactors the selected code |
| **Generate Unit Tests** | `Ctrl+Shift+T` | AI generates unit tests for the selection |
| **Add Documentation** | `Ctrl+Shift+D` | AI writes XML docs / docstrings |
| **Review This File** | `Ctrl+Shift+V` | AI performs a full code review of the active file |
| **Open Arbiter Chat Panel** | `Ctrl+Alt+A` | Toggle the dockable Arbiter chat tool window |

---

## Chat Tool Window

Open with `Ctrl+Alt+A` or **View → Other Windows → Arbiter Chat**.

The chat panel is a WebView2-hosted instance of Arbiter's web chat UI.
It automatically injects the active file path and selected text as context
with every message.

---

## Inline Completions

Arbiter provides inline AI completions via Roslyn.

**How to trigger:**

1. Type `// Arbiter:` followed by a description on any line:
   ```csharp
   // Arbiter: implement bubble sort for a List<int>
   ```
2. Wait ~1 second for the ghost text completion to appear
3. Press `Tab` to accept, or `Escape` to dismiss

---

## Self-Build Panel

Open with **View → Other Windows → Arbiter Self-Build**.

The Self-Build panel shows:
- Current task from `roadmap.json`
- Phase indicator (Plan / Identify / Generate / Validate / Apply / Test / Commit)
- Live plan text
- Diff preview with syntax highlighting
- **Approve** / **Reject** buttons for Assist/SemiAuto mode
- Session log

---

## Status Bar

When a solution is open, the VS status bar shows the active LLM backend name.
Click it to open the backend picker.

---

## Error List Integration

When a build fails, Arbiter adds AI fix suggestions to each entry in the
**Error List** panel. Click **AI Fix** next to any error to send it to chat
with the surrounding code context.

---

## Output Window

Arbiter writes its own entries to the **Output** panel under the
**"Arbiter AI"** source:

- Backend connection status
- Inline completion requests
- Self-build progress

---

## Event Handlers

The extension listens to VS events and uses them to enrich AI context:

| Event | Action |
|-------|--------|
| Document saved | Update active file context in chat |
| Selection changed | Update selection context |
| Build started | Log build start to Arbiter output pane |
| Build finished (failure) | Offer AI fix suggestions for each error |
| Solution opened | Load project context into Arbiter memory |
| Solution closed | Clear active project context |

---

## Troubleshooting

**Chat panel shows "Cannot connect to Arbiter backend":**
- Ensure the Arbiter backend is running (start it with `python server.py`)
- Check the Backend URL in **Tools → Options → Arbiter AI**
- Try enabling **Auto-detect backend** and restarting VS

**Inline completions not appearing:**
- Ensure the Arbiter backend is running
- Check that you typed `// Arbiter:` exactly (case-sensitive)
- Some Roslyn extensions can conflict — try disabling other completion providers

**Self-build panel is empty:**
- The self-build loop must be started from within the WPF app or via the REST API
- Check `/self-build/status` to see if the loop is active
