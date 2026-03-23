# ArbiterAI

**Arbiter** is a self-hosted, fully offline AI-powered development platform — a Monaco IDE embedded in a WPF Windows client, backed by a FastAPI Python bridge and an optional full agentic engine with 200+ tools.

---

## Vision

Arbiter is not just a chatbot — it is a controllable, self-iterating AI agent that works alongside you across the full software development lifecycle:

```
Idea → Planning → Code Generation → Edit in Monaco → Build → Run → Test → AI Review → Fix → Repeat → Working Release
```

Everything runs locally. No cloud required. Your data never leaves your machine.

---

## Architecture

```
ArbiterAI/
├── Arbiter.sln                            # Visual Studio solution
│
├── HostApp/                               # C# WPF Windows application
│   ├── App.xaml(.cs)                      # Startup — shows LauncherWindow
│   ├── AppConfig.cs                       # Static: mode, API URL, engine process
│   ├── LauncherWindow.xaml(.cs)           # Mode picker: ArbiterAI | Arbiter Engine
│   ├── MainWindow.xaml(.cs)              # Project list, chat, build controls
│   ├── ProjectWindow.xaml(.cs)           # Per-project: chat, file tree, git, TTS
│   ├── WorkspaceWindow.xaml(.cs)         # Workspace drag-and-drop manager
│   ├── PdfViewerWindow.xaml(.cs)         # Read-only PDF viewer (WebView2)
│   ├── BuildInterface/BuildManager.cs    # dotnet / npm / cargo build runner
│   ├── GitInterface/GitManager.cs        # LibGit2Sharp integration
│   ├── VoiceInterface/                   # TTS (System.Speech) + STT
│   ├── Utilities/                        # DarkTitleBar, PythonHelper, InputDialog
│   ├── Themes/DarkTheme.xaml             # VS Code-inspired dark palette
│   └── Config/settings.json             # App configuration
│
├── AIEngine/
│   ├── PythonBridge/                      # Primary backend (port 8000)
│   │   ├── fastapi_bridge.py             # 1 600-line FastAPI server
│   │   ├── llm_interface.py              # Hardware-aware LLM loading (GGUF + Ollama + stub)
│   │   ├── persona_manager.py            # Persona system (Arbiter / Coder / Teacher / Organizer)
│   │   ├── VoiceManager.py               # TTS helper
│   │   ├── model_downloader.py           # HuggingFace Hub auto-download
│   │   ├── requirements.txt
│   │   ├── static/                       # Chat-only web UI (index.html)
│   │   └── gui/                          # Monaco IDE web UI (index.html + app.js + style.css)
│   │
│   └── ArbiterEngine/                     # Full agentic backend (port 8001, optional)
│       ├── server.py                      # FastAPI server — same API contract as bridge
│       ├── setup_modules.py              # Sparse-clone 42-module toolset
│       ├── core/                          # agent, agentic_agent, config_loader, logger,
│       │                                  # module_loader, permission, plugin_loader,
│       │                                  # self_build, task_runner, tool_registry
│       ├── llm/                           # factory + 12 backends
│       │   # ollama, api, anthropic, gemini, llamacpp, lmstudio,
│       │   # local, localai, openwebui, tabby, base
│       ├── configs/config.toml           # Runtime configuration
│       ├── workspace/                     # Arbiter Engine working directory
│       │   └── roadmap.json             # Self-build task roadmap
│       ├── modules/                       # Installed tool modules
│       └── plugins/                       # Installed plugins
│
├── Memory/
│   ├── ConversationLogs/                  # Per-project SQLite chat history
│   ├── snippets.json                      # Saved code snippets
│   ├── notes.json                         # Per-project notes
│   └── Archive/                           # Archive codex (coming M3)
│       └── archive.json
│
├── Projects/                              # User project workspaces
│   └── ExampleProject/roadmap.json
│
├── roadmap.json                           # Master project roadmap
└── archive/                               # Archived predecessor code
    └── webhook-integration/
```

---

## Modes

| Mode | Port | Description |
|---|---|---|
| **ArbiterAI** | 8000 | Lightweight bridge — chat, code actions, build/run/test, Monaco IDE |
| **Arbiter Engine** | 8001 | Full agentic engine — 200+ tools, 12 LLM backends, self-build loop |

The **Launcher** lets you choose at startup. Both modes serve the same API contract so the WPF client and Monaco IDE work identically with either.

---

## Key Features

| Feature | Status | Milestone |
|---|---|---|
| ChatGPT-style web chat UI | ✅ Done | M0 |
| WPF dark-theme Windows client | ✅ Done | M0 |
| Voice output (TTS) | ✅ Done | M0 |
| Voice input (STT — Whisper + Windows Speech) | ✅ Done | M0 |
| Persona system (Arbiter / Coder / Teacher / Organizer) | ✅ Done | M0 |
| Project & workspace management | ✅ Done | M0 |
| Git integration (commit, push, pull, branch, log) | ✅ Done | M0 |
| Hardware-aware LLM loading (GGUF + Ollama + stub) | ✅ Done | M0 |
| Build / run / test loop (dotnet, npm, Python, Make) | ✅ Done | M0 |
| Automated model download (HuggingFace Hub) | ✅ Done | M0 |
| PDF viewer (WebView2, read-only) | ✅ Done | M1 |
| Startup launcher (mode picker) | ✅ Done | M1 |
| Auto-open web chat in browser on launch | ✅ Done | M1 |
| **Monaco IDE web UI** (Explorer, Editor, Git, AI Chat, Terminal, 40+ panels) | ✅ Done | M1 |
| File CRUD API (/files, read, write, delete, rename) | ✅ Done | M1 |
| AI code actions (complete, explain, fix, refactor, docstring, tests) | ✅ Done | M1 |
| WebSocket streaming (build output, terminal, PTY) | ✅ Done | M1 |
| Git API (clone, status, stage, commit, log, diff) | ✅ Done | M1 |
| Arbiter Engine — 12 LLM backends | ✅ Done | M2 |
| Arbiter Engine — agentic loop (plan → edit → diff) | ✅ Done | M2 |
| Arbiter Engine — module / plugin system | ✅ Done | M2 |
| Arbiter Engine — self-build loop | ✅ Done | M2 |
| **IdeWindow — Monaco embedded in WPF via WebView2** | 🔄 Next | M1 |
| WPF ↔ IDE native tool-call bridge | 🔄 Next | M1 |
| Archive & Library codex system | 📋 M3 | M3 |
| Background file watcher + AI indexing | 📋 M3 | M3 |
| Multi-agent orchestration | 📋 M5 | M5 |
| NSIS installer | 📋 M6 | M6 |
| VS Code extension | 📋 M6 | M6 |

---

## Quick Start

### 1 — Prerequisites

- Windows 10/11
- [.NET 8 SDK](https://dotnet.microsoft.com/download)
- Python 3.10+
- [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (usually pre-installed on Win 11)

### 2 — Install Python dependencies

```bash
cd AIEngine/PythonBridge
pip install -r requirements.txt
```

### 3 — (Optional) Install Ollama for best AI quality

```
https://ollama.com  →  ollama pull llama3
```

### 4 — Run the Python bridge manually (or let the WPF app start it)

```bash
python AIEngine/PythonBridge/fastapi_bridge.py
# Bridge starts at http://127.0.0.1:8000
# Monaco IDE available at http://127.0.0.1:8000/gui/
```

### 5 — Build and run the WPF app

```bash
cd HostApp
dotnet build
dotnet run
# OR open Arbiter.sln in Visual Studio and press F5
```

The Launcher will appear — choose **ArbiterAI** for the standard bridge or **Arbiter Engine** for the full agentic mode.

### 6 — (Optional) Install Arbiter Engine modules

```bash
python AIEngine/ArbiterEngine/setup_modules.py
```

---

## Monaco IDE

The built-in Monaco IDE (available at `/gui/`) is a full VS Code-like web editor with:

- **Activity bar** — Explorer, Search, Git, AI Backends, Code Tools, DevOps, Monitoring, Analytics, and 30+ more panels
- **Monaco Editor** — syntax highlighting, IntelliSense, diff view, multi-tab
- **AI Chat panel** — chat with Arbiter while viewing your code; context-aware completions
- **Terminal** — xterm.js PTY terminal streamed via WebSocket
- **Git panel** — staged/unstaged/untracked, commit, log
- **Build panel** — real-time streaming output
- **40+ tool panels** — Scaffold, Brainstorm, Refactor, DocGen, Snippets, Deploy, Docker, DB, Vault, Webhooks, and more

---

## Roadmap

See [`roadmap.json`](roadmap.json) for the full milestone breakdown.

| Milestone | Status |
|---|---|
| M0 — Foundation | ✅ Done |
| M1 — IDE Integration (Monaco + WebView2) | 🔄 In Progress |
| M2 — Arbiter Engine (full agentic backend) | 🔄 In Progress |
| M3 — Archive & Library (knowledge codex) | 📋 Planned |
| M4 — WPF IDE (full native client) | 📋 Planned |
| M5 — Advanced AI (RAG, multi-agent, self-build) | 📋 Planned |
| M6 — Distribution (installer, VS Code ext, CLI) | 📋 Planned |

---

## Configuration

Edit `HostApp/Config/settings.json`:

```json
{
  "arbiterEnginePath": "AIEngine/ArbiterEngine",
  "arbiterEnginePort": 8001,
  "library_paths": []
}
```

Edit `AIEngine/ArbiterEngine/configs/config.toml` for LLM backend selection, tool permissions, and agent behaviour.

---

## Contributing

This is an active solo project. Issues and PRs are welcome — please check the roadmap first to avoid duplicating in-progress work.


---

## Vision

Arbiter is not just a chatbot — it is a controllable, self-iterating AI agent that works alongside you across the full software development lifecycle:

```
Idea → Planning → Code Generation → Build → Run → Test → Report → Fix → Repeat → Working EXE
```

---

## Architecture

```
ArbiterAI/
├── Arbiter.sln                        # Visual Studio solution
│
├── HostApp/                           # C# WPF Windows application
│   ├── MainWindow.xaml(.cs)           # Launch screen
│   ├── WorkspaceWindow.xaml(.cs)      # Project list + drag-and-drop
│   ├── ProjectWindow.xaml(.cs)        # Chat, suggestions, file tree, Git, TTS
│   ├── VoiceInterface/
│   │   ├── VoiceManager.cs            # C# TTS bridge
│   │   └── VoiceManager.py            # Python TTS helper
│   ├── GitInterface/
│   │   └── GitManager.cs              # LibGit2Sharp integration
│   └── Config/
│       └── settings.json              # App configuration
│
├── AIEngine/
│   ├── LLaMA2-13B/                    # Local LLM model folder (GGUF files go here)
│   └── PythonBridge/
│       ├── fastapi_bridge.py          # FastAPI server — chat, TTS, history
│       ├── llm_interface.py           # Hardware-aware LLM loading + inference
│       ├── VoiceManager.py            # TTS (pyttsx3 / Coqui TTS)
│       └── requirements.txt           # Python dependencies
│
├── Memory/
│   └── ConversationLogs/              # Per-project SQLite chat logs
│
├── Projects/                          # User project workspaces
│   └── ExampleProject/
│       └── roadmap.json               # Phase and task tracking
│
├── Temp/                              # Temporary build/run files
│
└── archive/
    └── webhook-integration/           # Previous Jira/Azure Boards/Linear bridge (archived)
```

---

## Key Features

| Feature | Status |
|---|---|
| Chat UI (ChatGPT-style) | ✅ Phase 0 |
| Voice output (TTS) | ✅ Phase 0 |
| Voice input (STT) | ✅ Phase 0 — Windows System.Speech |
| Project & workspace management | ✅ Phase 0 |
| Drag-and-drop file workflow | ✅ Phase 0 |
| Git integration (commit, branch, push, pull, log) | ✅ Phase 0 |
| Hardware-aware LLM loading | ✅ Phase 0 |
| Code generation & approval | ✅ Phase 0 |
| Roadmap / task planning | ✅ Phase 0 |
| Automated model download | ✅ Phase 0 |
| Local LLM inference (GGUF) | ✅ Auto-discovered from model folder |
| Build + run + test loop | ✅ Phase 1 |
| **Persona system** (Arbiter / Coder / Teacher / Organizer) | ✅ **Phase 1** |
| Google Drive workspace | 📋 Phase 2 |
| Visual Studio VSIX extension | 📋 Phase 3 |
| Knowledge archive (PDF, docs) | 📋 Phase 3 |
| Image & audio generation | 📋 Phase 4 |
| Multi-agent system | 📋 Phase 5 |

---

## Prerequisites

- **Windows 10/11**
- **.NET 8 SDK** — for building the WPF host app
- **Visual Studio 2022** (Community or higher) with WPF workload
- **Python 3.11+** — for the AI engine bridge
- *(Optional)* A GGUF language model — for real LLM inference

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/shifty81/ArbiterAI.git
cd ArbiterAI
```

### 2. One-click automated setup *(recommended)*

```bash
python setup_arbiter.py
```

This single command will:
- Install all Python dependencies
- Detect your GPU / available VRAM
- Download the best-fit GGUF model automatically to `AIEngine/LLaMA2-13B/`
- Write the model path to a local `.env` file

### 3. Start the Python bridge

```bash
cd AIEngine/PythonBridge
python fastapi_bridge.py
```

The bridge starts at `http://127.0.0.1:8000`.  
If a model was downloaded in step 2 it will be loaded automatically — no environment variable needed.

### 4. Build and run the Windows app

Open `Arbiter.sln` in Visual Studio 2022, restore NuGet packages, and press **F5**.

---

### Manual model setup *(alternative)*

If you prefer to download a model yourself:

1. Download a GGUF file from [HuggingFace TheBloke](https://huggingface.co/TheBloke)
2. Place it in `AIEngine/LLaMA2-13B/`
3. *(Optional)* Set the environment variable in your `.env` file (repo root) to override auto-detection:
   ```
   ARBITER_MODEL_PATH=C:\path\to\your-model.gguf
   ```
   The `.env` file is loaded automatically on server start — no need to set a system environment variable.

See `AIEngine/LLaMA2-13B/README.md` for the full model compatibility table.

---

### Ollama *(easiest local LLM setup)*

[Ollama](https://ollama.com) provides a one-command local LLM installation that Arbiter
detects automatically — no GGUF download or environment variable required.

```bash
# 1. Install Ollama from https://ollama.com
# 2. Pull a model (Mistral is a good starting point)
ollama pull mistral
# 3. Start Arbiter — it will detect Ollama automatically
python AIEngine/PythonBridge/fastapi_bridge.py
```

To point Arbiter at a non-default Ollama host, set `OLLAMA_HOST` in your `.env` file:
```
OLLAMA_HOST=http://192.168.1.10:11434
```

---

### llama-cpp-python *(for GGUF models)*

For GGUF model inference, install `llama-cpp-python` (after `setup_arbiter.py` downloads the
model):

```bash
# CPU-only (always works):
pip install llama-cpp-python

# GPU-accelerated (CUDA — replace cu121 with your CUDA version):
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
# or on Windows:
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

---

## Python Bridge API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/status` | GET | GPU, VRAM, model, token limit info |
| `/llm/status` | GET | Active LLM backend: `gguf`, `ollama`, or `stub` |
| `/personas` | GET | List all available personas |
| `/persona/{project}` | GET | Get the active persona for a project |
| `/persona/{project}` | POST | Set the active persona for a project |
| `/chat` | POST | Send a message, get Arbiter's response + TTS |
| `/history/{project}` | GET | Retrieve conversation history for a project |
| `/models` | GET | List recommended + already-downloaded models |
| `/models/download` | POST | Start async model download (auto or explicit) |
| `/models/download/status` | GET | Poll current download progress |
| `/build` | POST | Build the project (auto-detects command) |
| `/run` | POST | Run the project entry point |
| `/test` | POST | Run the project's test suite |
| `/stt` | POST | Transcribe audio to text via Whisper |

### Chat request example

```json
POST /chat
{
  "message": "Add a docking system to my ship class",
  "project": "SpaceGame",
  "use_voice": true,
  "voice": "British_Female"
}
```

### Persona switching example

```json
POST /persona/SpaceGame
{ "persona": "Coder" }
```

Built-in personas: **Arbiter** (default), **Coder**, **Teacher**, **Organizer**.
Each persona shapes Arbiter's system prompt and response style.
The active persona is persisted per project in the project's SQLite database.

### Model download example

```json
POST /models/download
{ "auto": true }
```

Auto-selects and downloads the best model for your hardware.
Poll `GET /models/download/status` until `"running": false`.

---

## Open-Source Technology Stack

| Layer | Technology |
|---|---|
| Windows UI | C# WPF / .NET 8 |
| AI Bridge | Python FastAPI |
| LLM Inference | llama-cpp-python (GGUF) |
| TTS | pyttsx3 / Coqui TTS |
| STT | Windows System.Speech / openai-whisper |
| Git | LibGit2Sharp |
| Vector Search | Chroma / FAISS (planned) |
| Agent Framework | LangChain / AutoGen (planned) |

---

## Roadmap

```
Phase 0  — Chat + Voice + Workspace + Git                  ✅ Complete
Phase 1  — Build loop + error fix + test runner            ✅ Complete
           Persona system (Coder / Teacher / Organizer)    ✅ Complete
Phase 2  — Google Drive workspace + cloud sync
Phase 3  — Knowledge archive + PDF + VS VSIX
Phase 4  — Image / audio generation + multimodal
Phase 5  — Multi-agent system
```

---

## Archive

The previous webhook integration (Jira → Azure Boards → Linear → GitHub Copilot) has been archived to `archive/webhook-integration/` and is no longer the active development focus.

---

## License

MIT
