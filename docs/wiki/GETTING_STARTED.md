# Getting Started

This guide covers everything you need to install, configure, and run Arbiter
for the first time.

---

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Operating System | Windows 10 (1903+) | Windows 11 recommended |
| .NET SDK | 8.0 | [Download](https://dotnet.microsoft.com/download) |
| Python | 3.10+ | [Download](https://www.python.org/downloads/) |
| WebView2 Runtime | latest | Pre-installed on Windows 11; [download](https://developer.microsoft.com/microsoft-edge/webview2/) for Windows 10 |
| GPU (optional) | 4 GB+ VRAM | For local LLM inference; CPU-only also works |
| Git | 2.x | Required for self-build and git panel features |

---

## Installation

### Option A — One-Click Setup (Recommended)

```bash
git clone https://github.com/shifty81/Arbiter
cd Arbiter
python setup_arbiter.py
```

`setup_arbiter.py` will:
1. Detect your GPU and available VRAM
2. Install Python dependencies from `requirements.txt` files
3. Download the best-fit GGUF model for your hardware
4. Create the initial `settings.json` and `config.toml` with sensible defaults

### Option B — Manual Setup

**1. Install Python dependencies:**

```bash
# PythonBridge (lightweight mode, port 8000)
pip install -r AIEngine/PythonBridge/requirements.txt

# ArbiterEngine (full agentic mode, port 8001)
pip install -r AIEngine/ArbiterEngine/requirements.txt
```

**2. (Optional) Install Ollama for best quality:**

```bash
# Visit https://ollama.com and install
ollama pull llama3
```

**3. Build the WPF application:**

```bash
cd HostApp
dotnet restore
dotnet build
```

---

## Starting Arbiter

### Start the AI Backend

Choose one mode:

```bash
# --- Lightweight mode (recommended for first run) ---
python AIEngine/PythonBridge/fastapi_bridge.py
# Chat UI  →  http://127.0.0.1:8000/
# Monaco IDE  →  http://127.0.0.1:8000/gui/

# --- Full agentic mode (self-build, 12 LLM backends, 200+ tools) ---
python AIEngine/ArbiterEngine/server.py
# API  →  http://127.0.0.1:8001/
```

### Start the WPF Application

```bash
cd HostApp
dotnet run
# OR: open Arbiter.sln in Visual Studio 2022 → press F5
```

The **Launcher** window will appear. Choose your mode:
- **ArbiterAI** — connects to port 8000 (lightweight)
- **Arbiter Engine** — connects to port 8001 (full agentic)

### Docker (Backend Only)

```bash
# Backend only
docker-compose up arbiter-engine

# Backend + Ollama
docker-compose --profile ollama up
```

The API is available at `http://localhost:8001`.

---

## First Run Walkthrough

1. **Open the Launcher** — run `dotnet run` in `HostApp/`
2. **Choose a mode** — click **ArbiterAI** for the first run
3. **Wait for server startup** — the backend starts automatically
4. **The IDE window opens** — you'll see the Monaco IDE with 40+ panels
5. **Open the Chat panel** — press `Ctrl+\`` or click the chat icon in the sidebar
6. **Send your first message** — type anything and press Enter
7. **Browse the panels** — explore File Explorer, Git, Self-Build, etc.

---

## Installing the Visual Studio Extension (Optional)

1. Open `VisualStudioExtension/ArbiterVSIX/` in Visual Studio 2022
2. Press **F5** to install in the experimental instance
3. Or download the pre-built `.vsix` from the [Releases page](https://github.com/shifty81/Arbiter/releases)
4. Double-click the `.vsix` to install

After installation, Arbiter commands appear in the Visual Studio toolbar and
under **Tools → Arbiter AI**.

---

## Directory Overview

```
Arbiter/
├── AIEngine/
│   ├── PythonBridge/       ← Lightweight backend (port 8000)
│   └── ArbiterEngine/      ← Full agentic backend (port 8001)
├── HostApp/                ← C# WPF desktop application
├── VisualStudioExtension/  ← VSIX for Visual Studio 2022
├── Memory/                 ← Conversation history, archive, snippets
├── Projects/               ← Your project workspaces
├── logs/                   ← Per-system rotating log files
├── docs/wiki/              ← This documentation
├── roadmap.json            ← Machine-readable roadmap (self-build loop)
└── setup_arbiter.py        ← One-click setup script
```

---

## Environment Variables

Arbiter reads a `.env` file at the repository root if present:

```env
# Path to the GGUF model file
ARBITER_MODEL_PATH=models/llama3.gguf

# Ollama host (if using Ollama backend)
OLLAMA_HOST=http://localhost:11434

# OpenAI API key (if using OpenAI backend)
OPENAI_API_KEY=sk-...

# Anthropic API key
ANTHROPIC_API_KEY=...
```

---

## Next Steps

- [Configuration](CONFIGURATION.md) — tune all settings
- [Chat Engine](CHAT_ENGINE.md) — explore chat features, personas, slash commands
- [Monaco IDE](MONACO_IDE.md) — discover all 40+ IDE panels
- [Self-Build Loop](SELF_BUILD.md) — let Arbiter improve itself
- [VS Extension](VS_EXTENSION.md) — use Arbiter inside Visual Studio
- [API Reference](API_REFERENCE.md) — integrate your own tools
