# Troubleshooting

Common problems and their solutions.

---

## Backend Won't Start

**Symptom:** WPF launcher shows "Could not start the Arbiter server automatically"

**Solutions:**

1. Install Python dependencies:
   ```bash
   pip install -r AIEngine/PythonBridge/requirements.txt
   # or for Engine:
   pip install -r AIEngine/ArbiterEngine/requirements.txt
   ```

2. Start the server manually and check for errors:
   ```bash
   python AIEngine/PythonBridge/fastapi_bridge.py
   ```

3. Check if port 8000/8001 is already in use:
   ```cmd
   netstat -ano | findstr :8000
   ```

---

## WPF App Won't Build

**Symptom:** `dotnet build` fails

**Solutions:**

1. Ensure .NET 8 SDK is installed: `dotnet --version`
2. Restore NuGet packages: `cd HostApp && dotnet restore`
3. WebView2 SDK issue: ensure `Microsoft.Web.WebView2` package is in the solution

---

## AI Chat Returns Empty or "Model not loaded"

**Solutions:**

1. Check `/model/status` endpoint: `curl http://127.0.0.1:8000/model/status`
2. Ensure a model file is present:
   - GGUF: check `ARBITER_MODEL_PATH` in `.env`
   - Ollama: run `ollama list`
3. Run `python setup_arbiter.py` to auto-detect and download the best model

---

## Chat Responses Are Very Slow

**Solutions:**

1. Use a smaller/more quantised model (Q4 or Q5 instead of Q8)
2. Enable GPU offload: set `n_gpu_layers = -1` in config
3. Reduce `max_tokens` in `config.toml`
4. Switch to Ollama backend which handles model management more efficiently

---

## Server Crashes During AI Inference

This is a known issue fixed in M13. The fix uses `asyncio.to_thread()` to prevent
the blocking LLM call from stalling the entire event loop.

Ensure you have the latest version. If still crashing:

1. Reduce `max_tokens` in `config.toml` to `1024`
2. Limit prompt history — use `/clear` to reset the conversation context
3. Check `logs/arbiter_engine/arbiter_engine.log` for the full traceback

---

## Monaco IDE Won't Load (Blank Page)

**Solutions:**

1. Check browser console for errors (`F12`)
2. Ensure the backend is running and `/gui/index.html` is accessible
3. Clear browser cache (the IDE is served from the backend)
4. If using Docker, check that port 8001 is exposed

---

## VS Extension Not Showing in Visual Studio

**Solutions:**

1. Confirm the `.vsix` was installed: **Extensions → Manage Extensions → Installed**
2. Ensure you have the **Visual Studio SDK** workload installed
3. Try **Extensions → Manage Extensions → Updates** to see if a reinstall is needed
4. Check the VS Activity Log: `%APPDATA%\Microsoft\VisualStudio\...\ActivityLog.xml`

---

## Self-Build Loop Gets Stuck

**Symptom:** Loop is running but no commits appear

**Solutions:**

1. Check `/self-build/status` for the current phase
2. Check `logs/self_build/self_build.log` for errors
3. If stuck in `generate` phase, the LLM may be timing out — increase `timeout_s` in `config.toml`
4. If stuck in `approve` phase, the approval request is waiting — use the Self-Build panel to approve/reject

---

## Logs Not Appearing in `logs/` Folder

**Solutions:**

1. Ensure the backend has write permission to the repository directory
2. Check that `roadmap.json` exists in the repo root (used to locate the repo root)
3. If running from an unusual working directory, ensure the path walking in `_find_repo_root()` can reach the repo root

---

## Git Operations Fail

**Solutions:**

1. Ensure Git is installed: `git --version`
2. Configure git identity:
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```
3. Or set in `settings.json`:
   ```json
   { "git_author_name": "You", "git_author_email": "you@example.com" }
   ```

---

## Ollama Backend Not Responding

**Solutions:**

1. Check Ollama is running: `ollama serve`
2. Verify the model is pulled: `ollama list`
3. Check `OLLAMA_HOST` in `.env` (default: `http://localhost:11434`)
4. Pull a model: `ollama pull llama3`

---

## Port Conflict (Address Already in Use)

**Solutions:**

1. Find the process: `netstat -ano | findstr :8000`
2. Kill it: `taskkill /PID <pid> /F`
3. Or change the port in `config.toml` (`[server] port = 8002`)

---

## Still Stuck?

1. Check `logs/arbiter_engine/arbiter_engine.log` for detailed errors
2. Open an issue at https://github.com/shifty81/Arbiter/issues
3. Include: OS version, Python version, .NET version, the error message, and the relevant log excerpt
