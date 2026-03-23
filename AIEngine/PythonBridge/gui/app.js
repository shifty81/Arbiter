/**
 * Arbiter IDE — frontend application
 * Uses Monaco Editor (loaded via CDN) and the Arbiter REST + WebSocket API.
 */
(function () {
  "use strict";

  // ── Constants ───────────────────────────────────────────────────────────────
  const MAX_BUILD_OUTPUT_FOR_AI = 2000;

  // ── Code-block store — keyed by incrementing ID to avoid encoding issues ────
  const _codeStore = new Map();
  let   _codeStoreSeq = 0;

  // ── State ──────────────────────────────────────────────────────────────────
  const state = {
    openFiles: {},        // path → { content, language, modified, model }
    activeFile: null,     // currently visible path
    activeProject: "",    // currently active project path
    editor: null,         // Monaco editor instance
    editorMode: null,     // "monaco" | "fallback" | null
    ws: null,             // active WebSocket for /ws/run
    currentWsAbort: null, // AbortController for fetch-based fallback
    buildErrors: [],      // parsed error objects from last build
    lastBuildOutput: "",  // raw build output for "Fix with AI"
    contextTarget: null,  // path of the right-clicked tree item
  };

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const fileTree       = $("file-tree");
  const tabsList       = $("tabs-list");
  const outputContent  = $("output-content");
  const buildContent   = $("build-content");
  const problemsContent = $("problems-content");
  const chatMessages   = $("chat-messages");
  const chatInput      = $("chat-input");
  const statusEl       = $("status-indicator");
  const newFileDialog  = $("new-file-dialog");
  const newFilePath    = $("new-file-path");
  const llmSelect      = $("llm-backend-select");
  const contextMenu    = $("context-menu");

  // Status bar refs
  const sbFile     = $("sb-file");
  const sbCursor   = $("sb-cursor");
  const sbLanguage = $("sb-language");
  const sbAiStatus = $("sb-ai-status");

  // ── Utilities ──────────────────────────────────────────────────────────────
  function appendOutput(text) {
    outputContent.textContent += text;
    outputContent.scrollTop = outputContent.scrollHeight;
  }

  function clearOutput() {
    outputContent.textContent = "";
  }

  function setStatus(mode) {
    statusEl.className = `status-${mode}`;
    const labels = { idle: "● Idle", running: "⟳ Running…", error: "✕ Error" };
    statusEl.textContent = labels[mode] || "● Idle";
    // Also update status bar
    sbAiStatus.className = mode === "running" ? "sb-running" : mode === "error" ? "sb-error" : "sb-idle";
    sbAiStatus.textContent = mode === "running" ? "⟳ AI Running…" : mode === "error" ? "✕ AI Error" : "● AI Idle";
  }

  function appendChat(text, role) {
    const msg = document.createElement("div");
    msg.className = `chat-msg ${role}`;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return msg;
  }

  // ── Code-block rendering (Copilot-style Apply + Copy buttons) ────────────
  /** Parse ```lang\ncode``` fences and return an HTML string with action buttons. */
  function _renderCodeBlocks(rawText) {
    // Safely escape text outside code fences
    function escHtml(s) {
      return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    const parts = rawText.split(/(```[\w]*\n[\s\S]*?```)/g);
    return parts.map((part) => {
      const m = part.match(/^```([\w]*)\n([\s\S]*?)```$/);
      if (!m) return `<span class="chat-text">${escHtml(part)}</span>`;
      const lang = m[1] || "text";
      const code = m[2].trimEnd();
      const id = ++_codeStoreSeq;
      _codeStore.set(id, code);
      return (
        `<div class="code-block">` +
        `<div class="code-block-header">` +
        `<span class="code-lang">${escHtml(lang)}</span>` +
        `<div class="code-block-actions">` +
        `<button class="code-copy-btn" data-cid="${id}" title="Copy to clipboard">📋 Copy</button>` +
        `<button class="code-apply-btn" data-cid="${id}" title="Apply to active file">⬆ Apply to file</button>` +
        `</div></div>` +
        `<pre class="code-content"><code>${escHtml(code)}</code></pre>` +
        `</div>`
      );
    }).join("");
  }

  /** Wire the Copy / Apply buttons inside a rendered chat message element. */
  function _bindCodeButtons(msgEl) {
    msgEl.querySelectorAll(".code-copy-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const code = _codeStore.get(Number(btn.dataset.cid));
        if (code === undefined) return;
        navigator.clipboard.writeText(code).catch(() => appendOutput(`Code:\n${code}\n`));
        btn.textContent = "✓ Copied";
        setTimeout(() => { btn.textContent = "📋 Copy"; }, 1500);
      });
    });
    msgEl.querySelectorAll(".code-apply-btn").forEach((btn) => {
      btn.addEventListener("click", () => _applyCodeToEditor(Number(btn.dataset.cid)));
    });
  }

  /** Replace a streaming-complete agent message's textContent with rendered HTML. */
  function _finaliseAgentMessage(msgEl) {
    const raw = msgEl.textContent;
    if (!raw.includes("```")) return; // nothing to render
    msgEl.innerHTML = _renderCodeBlocks(raw);
    _bindCodeButtons(msgEl);
  }

  /** Apply a stored code snippet to the active editor file. */
  function _applyCodeToEditor(codeId) {
    const code = _codeStore.get(codeId);
    if (code === undefined) return;
    if (!state.activeFile) {
      // Prompt for a filename
      const name = prompt("No file open. Enter a workspace path to create:", "workspace/snippet.txt");
      if (!name) return;
      createNewFile(name).then(() => {
        setTimeout(() => _applyCodeToEditor(codeId), 400);
      });
      return;
    }
    if (state.editorMode === "monaco" && state.openFiles[state.activeFile]?.model) {
      state.openFiles[state.activeFile].model.setValue(code);
    } else if (state.editorMode === "fallback") {
      $("fallback-editor").value = code;
      if (state.openFiles[state.activeFile]) state.openFiles[state.activeFile].content = code;
    }
    markModified(state.activeFile);
    appendOutput(`⬆ Applied code block to ${state.activeFile}\n`);
    switchOutputTab("output");
  }

  function extToLang(path) {
    const ext = path.split(".").pop().toLowerCase();
    const map = {
      py: "python", js: "javascript", ts: "typescript",
      html: "html", css: "css", json: "json",
      md: "markdown", sh: "shell", bash: "shell",
      cpp: "cpp", c: "c", cs: "csharp", java: "java",
      rs: "rust", go: "go", lua: "lua", rb: "ruby",
      toml: "ini", yaml: "yaml", yml: "yaml",
      txt: "plaintext",
    };
    return map[ext] || "plaintext";
  }

  function langDisplayName(lang) {
    const names = {
      python: "Python", javascript: "JavaScript", typescript: "TypeScript",
      html: "HTML", css: "CSS", json: "JSON", markdown: "Markdown",
      shell: "Shell", cpp: "C++", c: "C", csharp: "C#", java: "Java",
      rust: "Rust", go: "Go", lua: "Lua", ruby: "Ruby",
      ini: "TOML", yaml: "YAML", plaintext: "Plain Text",
    };
    return names[lang] || lang;
  }

  // ── Status bar updates ────────────────────────────────────────────────────
  function updateStatusBar() {
    if (state.activeFile) {
      sbFile.textContent = state.activeFile;
      const lang = state.openFiles[state.activeFile]?.language || "plaintext";
      sbLanguage.textContent = langDisplayName(lang);
    } else {
      sbFile.textContent = "No file open";
      sbLanguage.textContent = "Plain Text";
    }
  }

  function updateCursorPosition() {
    if (state.editorMode === "monaco" && state.editor) {
      const pos = state.editor.getPosition();
      if (pos) {
        sbCursor.textContent = `Ln ${pos.lineNumber}, Col ${pos.column}`;
      }
    } else if (state.editorMode === "fallback") {
      const ta = $("fallback-editor");
      const text = ta.value.substring(0, ta.selectionStart);
      const lines = text.split("\n");
      const line = lines.length;
      const col = lines[lines.length - 1].length + 1;
      sbCursor.textContent = `Ln ${line}, Col ${col}`;
    }
  }

  // ── File tree ──────────────────────────────────────────────────────────────
  async function loadFileTree(node = null, parentEl = null) {
    const url = node ? `/files?path=${encodeURIComponent(node)}` : "/files";
    // If loading a top-level project path (not a sub-directory), track it as active project
    if (node && !parentEl) {
      state.activeProject = node;
      _roadmapCache.data = null;
    }
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderTree(data.entries, parentEl || fileTree, node || "");
    } catch (e) {
      fileTree.textContent = "⚠ " + e.message;
    }
  }

  function renderTree(entries, container, parentPath) {
    container.innerHTML = "";
    entries.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    for (const entry of entries) {
      const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
      const item = document.createElement("div");
      item.className = `tree-item ${entry.type === "dir" ? "dir" : "file"}`;
      item.dataset.path = fullPath;
      item.dataset.type = entry.type;

      const icon = document.createElement("span");
      icon.className = "icon";
      icon.textContent = entry.type === "dir" ? "📁" : fileIcon(entry.name);

      const label = document.createElement("span");
      label.textContent = entry.name;

      item.appendChild(icon);
      item.appendChild(label);
      container.appendChild(item);

      // Right-click context menu
      item.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        showContextMenu(e.pageX, e.pageY, fullPath, entry.type);
      });

      if (entry.type === "dir") {
        const children = document.createElement("div");
        children.className = "tree-children";
        children.style.display = "none";
        container.appendChild(children);

        item.addEventListener("click", async () => {
          const open = children.style.display !== "none";
          children.style.display = open ? "none" : "block";
          icon.textContent = open ? "📁" : "📂";
          if (!open && children.innerHTML === "") {
            await loadFileTree(fullPath, children);
          }
        });
      } else {
        item.addEventListener("click", () => openFile(fullPath));
      }
    }
  }

  function fileIcon(name) {
    const ext = name.split(".").pop().toLowerCase();
    const m = {
      py: "🐍", js: "📜", ts: "📘", html: "🌐", css: "🎨",
      json: "📋", md: "📝", sh: "⚙", cpp: "⚙", c: "⚙",
      cs: "⚙", java: "☕", rs: "🦀", go: "🐹", lua: "🌙",
      toml: "⚙", yaml: "⚙", yml: "⚙",
    };
    return m[ext] || "📄";
  }

  // ── Context menu ──────────────────────────────────────────────────────────
  function showContextMenu(x, y, path, type) {
    state.contextTarget = path;
    contextMenu.style.left = x + "px";
    contextMenu.style.top = y + "px";
    contextMenu.classList.remove("hidden");
  }

  function hideContextMenu() {
    contextMenu.classList.add("hidden");
    state.contextTarget = null;
  }

  document.addEventListener("click", hideContextMenu);
  document.addEventListener("contextmenu", (e) => {
    // Only show custom menu on tree items (handled above)
    if (!e.target.closest(".tree-item")) hideContextMenu();
  });

  contextMenu.addEventListener("click", async (e) => {
    const action = e.target.closest(".ctx-item")?.dataset.action;
    if (!action || !state.contextTarget) return;
    const path = state.contextTarget;
    hideContextMenu();

    switch (action) {
      case "new-file": {
        const name = prompt("New file name:", "");
        if (name) {
          const newPath = path + "/" + name;
          await createNewFile(newPath);
        }
        break;
      }
      case "new-folder": {
        const name = prompt("New folder name:", "");
        if (name) {
          // Create a .gitkeep inside the new folder to materialize it
          const newPath = path + "/" + name + "/.gitkeep";
          await createNewFile(newPath);
        }
        break;
      }
      case "rename": {
        const parts = path.split("/");
        const oldName = parts.pop();
        const newName = prompt("Rename to:", oldName);
        if (newName && newName !== oldName) {
          const newPath = parts.concat(newName).join("/");
          try {
            const res = await fetch("/files/rename", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ old_path: path, new_path: newPath }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Rename failed");
            appendOutput(`✓ Renamed ${oldName} → ${newName}\n`);
            await loadFileTree();
          } catch (e) {
            appendOutput(`Error renaming: ${e.message}\n`);
          }
        }
        break;
      }
      case "copy-path": {
        try {
          await navigator.clipboard.writeText(path);
          appendOutput(`✓ Copied path: ${path}\n`);
        } catch {
          appendOutput(`Path: ${path}\n`);
        }
        break;
      }
      case "open-split": {
        await openSplitFile(path);
        break;
      }
      case "delete": {
        if (confirm(`Delete "${path}"? This cannot be undone.`)) {
          try {
            const res = await fetch("/files/delete", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Delete failed");
            // Close tab if open
            if (state.openFiles[path]) closeTab(path);
            appendOutput(`✓ Deleted ${path}\n`);
            await loadFileTree();
          } catch (e) {
            appendOutput(`Error deleting: ${e.message}\n`);
          }
        }
        break;
      }
    }
  });

  // ── File open / tabs ───────────────────────────────────────────────────────
  async function openFile(path) {
    if (state.openFiles[path]) {
      activateTab(path);
      return;
    }
    try {
      const res = await fetch(`/files/read?path=${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const lang = extToLang(path);
      if (state.editorMode === "monaco") {
        const model = monaco.editor.createModel(data.content, lang);
        model.onDidChangeContent(() => markModified(path));
        state.openFiles[path] = { content: data.content, language: lang, modified: false, model };
      } else {
        state.openFiles[path] = { content: data.content, language: lang, modified: false, model: null };
      }
      addTab(path);
      activateTab(path);
    } catch (e) {
      appendOutput(`Error opening ${path}: ${e.message}\n`);
    }
  }

  function addTab(path) {
    const tab = document.createElement("div");
    tab.className = "tab";
    tab.dataset.path = path;

    const name = document.createElement("span");
    name.className = "tab-name";
    name.textContent = path.split("/").pop();

    const close = document.createElement("span");
    close.className = "tab-close";
    close.textContent = "✕";
    close.addEventListener("click", (e) => { e.stopPropagation(); closeTab(path); });

    tab.appendChild(name);
    tab.appendChild(close);
    tab.addEventListener("click", () => activateTab(path));
    tabsList.appendChild(tab);
  }

  function activateTab(path) {
    state.activeFile = path;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.path === path));
    document.querySelectorAll(".tree-item.file").forEach((t) => t.classList.toggle("active", t.dataset.path === path));
    document.dispatchEvent(new CustomEvent("sa:fileOpened", { detail: { path } }));
    if (state.editorMode === "monaco" && state.editor && state.openFiles[path]) {
      state.editor.setModel(state.openFiles[path].model);
      // Force layout so Monaco fills its container correctly
      requestAnimationFrame(() => state.editor.layout());
    } else if (state.editorMode === "fallback" && state.openFiles[path]) {
      $("fallback-editor").value = state.openFiles[path]?.content ?? "";
      $("fallback-editor").classList.remove("hidden");
    }
    $("editor-welcome").classList.add("hidden");
    updateStatusBar();
  }

  function closeTab(path) {
    const file = state.openFiles[path];
    if (file && file.modified) {
      if (!confirm(`${path} has unsaved changes. Close anyway?`)) return;
    }
    if (file && file.model) file.model.dispose();
    delete state.openFiles[path];
    const tab = tabsList.querySelector(`[data-path="${path}"]`);
    if (tab) tab.remove();
    if (state.activeFile === path) {
      const remaining = Object.keys(state.openFiles);
      if (remaining.length > 0) activateTab(remaining[remaining.length - 1]);
      else {
        state.activeFile = null;
        if (state.editorMode === "monaco" && state.editor) {
          state.editor.setModel(null);
          $("editor-welcome").classList.remove("hidden");
        }
        if (state.editorMode === "fallback") {
          $("fallback-editor").value = "";
          $("fallback-editor").classList.add("hidden");
          $("editor-welcome").classList.remove("hidden");
        }
        updateStatusBar();
      }
    }
  }

  function markModified(path) {
    if (state.openFiles[path]) {
      state.openFiles[path].modified = true;
      const tab = tabsList.querySelector(`[data-path="${path}"]`);
      if (tab) tab.classList.add("modified");
    }
  }

  // ── Save file ──────────────────────────────────────────────────────────────
  async function saveActiveFile() {
    const path = state.activeFile;
    if (!path) return;
    const file = state.openFiles[path];
    if (!file) return;
    const content = state.editorMode === "monaco"
      ? file.model.getValue()
      : $("fallback-editor").value;
    if (state.editorMode === "fallback") file.content = content;
    try {
      const res = await fetch("/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content }),
      });
      if (!res.ok) throw new Error(await res.text());
      file.modified = false;
      file.content = content;
      const tab = tabsList.querySelector(`[data-path="${path}"]`);
      if (tab) tab.classList.remove("modified");
      appendOutput(`✓ Saved ${path}\n`);

      // Auto-rebuild on save
      if ($("chk-auto-rebuild").checked) {
        runBuildOrTest("build");
      }
    } catch (e) {
      appendOutput(`Error saving ${path}: ${e.message}\n`);
    }
  }

  // ── Build / Test ──────────────────────────────────────────────────────────
  async function runBuildOrTest(mode) {
    const cwdRoot = $("build-cwd-select").value;
    const subdir = $("build-subdir-select").value;
    const cwd = subdir ? `${cwdRoot}/${subdir}` : cwdRoot;

    // Switch to build tab
    switchOutputTab("build");
    buildContent.textContent = "";
    state.buildErrors = [];
    state.lastBuildOutput = "";
    $("btn-fix-ai").classList.add("hidden");

    // Detect build system
    let buildInfo;
    try {
      const res = await fetch(`/build/detect?path=${encodeURIComponent(cwd)}`);
      if (!res.ok) throw new Error(await res.text());
      buildInfo = await res.json();
    } catch (e) {
      buildContent.textContent = `⚠ Build detect failed: ${e.message}\n`;
      return;
    }

    const command = mode === "test" ? buildInfo.test_command : buildInfo.build_command;
    if (!command) {
      buildContent.textContent = `⚠ No ${mode} command detected for ${buildInfo.system || "unknown"} in ${cwd}\n`;
      return;
    }

    buildContent.textContent = `▶ ${mode === "test" ? "Testing" : "Building"} (${buildInfo.system}) in ${cwd}…\n$ ${command}\n\n`;

    // Stream via WebSocket
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws/terminal`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ command, cwd }));
    };

    ws.onmessage = (ev) => {
      try {
        const pkt = JSON.parse(ev.data);
        if (pkt.type === "stdout") {
          buildContent.textContent += pkt.data;
          state.lastBuildOutput += pkt.data;
          buildContent.scrollTop = buildContent.scrollHeight;
        } else if (pkt.type === "exit") {
          const ok = pkt.code === 0;
          buildContent.textContent += `\n${ok ? "✓" : "✕"} Process exited with code ${pkt.code}\n`;
          if (!ok) {
            $("btn-fix-ai").classList.remove("hidden");
            parseBuildErrors(state.lastBuildOutput);
          }
          ws.close();
        } else if (pkt.type === "error") {
          buildContent.textContent += `\n⚠ Error: ${pkt.data}\n`;
          ws.close();
        }
      } catch { /* ignore */ }
    };

    ws.onerror = () => {
      buildContent.textContent += "\n⚠ WebSocket connection error\n";
    };
  }

  // ── Error parsing ─────────────────────────────────────────────────────────
  function parseBuildErrors(output) {
    state.buildErrors = [];
    const patterns = [
      // Python: File "path", line N
      /File "([^"]+)", line (\d+)(?:.*\n\s*(.*?))?/g,
      // GCC/Clang: path:line:col: error/warning: msg
      /^([^\s:]+):(\d+):(\d+):\s*(error|warning):\s*(.*)$/gm,
      // TypeScript/ESLint: path(line,col): error TS...
      /^([^\s(]+)\((\d+),(\d+)\):\s*(error|warning)\s+(.*)$/gm,
      // Rust: error[E...]: msg\n --> path:line:col
      /^\s*-{2}>\s+([^\s:]+):(\d+):(\d+)/gm,
      // Generic: ERROR: msg
      /^(ERROR|error|Error):\s*(.*)$/gm,
    ];

    const lines = output.split("\n");
    for (const line of lines) {
      // Python
      let m = line.match(/File "([^"]+)", line (\d+)/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), severity: "error", message: line.trim() });
        continue;
      }
      // GCC/Clang/TS
      m = line.match(/^([^\s:]+):(\d+):(\d+):\s*(error|warning):\s*(.*)$/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: m[4], message: m[5] });
        continue;
      }
      // TypeScript parens style
      m = line.match(/^([^\s(]+)\((\d+),(\d+)\):\s*(error|warning)\s+(.*)$/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: m[4], message: m[5] });
        continue;
      }
      // Rust
      m = line.match(/^\s*-{2}>\s+([^\s:]+):(\d+):(\d+)/);
      if (m) {
        state.buildErrors.push({ file: m[1], line: parseInt(m[2]), col: parseInt(m[3]), severity: "error", message: line.trim() });
      }
    }

    renderProblems();
  }

  function renderProblems() {
    problemsContent.innerHTML = "";
    if (state.buildErrors.length === 0) {
      problemsContent.innerHTML = '<div style="padding:12px;color:var(--text-dim)">No problems detected.</div>';
      return;
    }
    for (const err of state.buildErrors) {
      const row = document.createElement("div");
      row.className = "problem-row";

      const icon = document.createElement("span");
      icon.className = `problem-icon ${err.severity || "error"}`;
      icon.textContent = err.severity === "warning" ? "⚠" : "✕";

      const file = document.createElement("span");
      file.className = "problem-file";
      file.textContent = err.file || "unknown";

      const line = document.createElement("span");
      line.className = "problem-line";
      line.textContent = err.line ? `:${err.line}` : "";

      const msg = document.createElement("span");
      msg.className = "problem-msg";
      msg.textContent = err.message || "";

      row.appendChild(icon);
      row.appendChild(file);
      row.appendChild(line);
      row.appendChild(msg);

      // AI explain button (t7-5)
      const explainBtn = document.createElement("button");
      explainBtn.className = "problem-explain-btn";
      explainBtn.title = "Ask AI to explain this error and suggest a fix";
      explainBtn.textContent = "🤖 Explain";
      explainBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const errDesc = `${err.file || "unknown"}:${err.line || "?"}: ${err.severity || "error"}: ${err.message || ""}`;
        sendPrompt(`Please explain this error and suggest how to fix it:\n\n${errDesc}`);
        switchOutputTab("output");
      });
      row.appendChild(explainBtn);

      // Click row to jump to file+line
      row.addEventListener("click", async () => {
        // Try to map the file path to a workspace-relative path
        let filePath = err.file;
        if (filePath && !filePath.startsWith("workspace/") && !filePath.startsWith("projects/")) {
          filePath = "workspace/" + filePath;
        }
        try {
          await openFile(filePath);
          if (state.editor && err.line) {
            state.editor.revealLineInCenter(err.line);
            state.editor.setPosition({ lineNumber: err.line, column: err.col || 1 });
            state.editor.focus();
          }
        } catch { /* ignore */ }
      });

      problemsContent.appendChild(row);
    }
  }

  // ── Fix with AI ───────────────────────────────────────────────────────────
  function fixWithAI() {
    if (!state.lastBuildOutput) return;
    const errorSummary = state.buildErrors.map((e) =>
      `${e.file}:${e.line}: ${e.severity}: ${e.message}`
    ).join("\n");

    const prompt = `The build failed with the following errors. Please fix them:\n\n${errorSummary}\n\nFull build output:\n${state.lastBuildOutput.slice(-MAX_BUILD_OUTPUT_FOR_AI)}`;
    sendPrompt(prompt);
  }

  // ── Output tab switching ──────────────────────────────────────────────────
  function switchOutputTab(tabName) {
    document.querySelectorAll(".out-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === tabName)
    );
    document.querySelectorAll(".out-pane").forEach((p) => p.classList.remove("active"));
    const paneMap = {
      build: buildContent,
      problems: problemsContent,
      terminal: $("terminal-content"),
      roadmap: $("roadmap-content"),
    };
    const target = paneMap[tabName] || outputContent;
    target.classList.add("active");

    if (tabName === "terminal") _ensureTerminal();
    if (tabName === "roadmap") loadRoadmapPanel();
  }

  // ── Slash commands ─────────────────────────────────────────────────────────
  /** Expand /fix /explain /test /docs into a full context-aware prompt. */
  function _expandSlashCommand(raw) {
    const trimmed = raw.trim();
    if (!trimmed.startsWith("/")) return raw;

    const activeContent = (() => {
      if (!state.activeFile) return "";
      if (state.editorMode === "monaco" && state.openFiles[state.activeFile]?.model) {
        return state.openFiles[state.activeFile].model.getValue();
      }
      if (state.editorMode === "fallback") {
        return $("fallback-editor").value || state.openFiles[state.activeFile]?.content || "";
      }
      return state.openFiles[state.activeFile]?.content || "";
    })();

    const fileLine = state.activeFile ? `File: \`${state.activeFile}\`` : "";
    const fence = (c) => (c ? `\n\`\`\`\n${c}\n\`\`\`` : "");

    const [cmd, ...rest] = trimmed.split(/\s+([\s\S]*)/).filter(Boolean);
    const extra = rest.join(" ").trim();

    switch (cmd.toLowerCase()) {
      case "/fix":
        return `${fileLine}\nFix the bugs or issues in this code${extra ? `: ${extra}` : "."}${fence(activeContent)}`;
      case "/explain":
        return `${fileLine}\nExplain what this code does in clear, concise terms.${fence(activeContent)}`;
      case "/test":
        return `${fileLine}\nWrite unit tests for this code. Return only the test code in a code block.${fence(activeContent)}`;
      case "/docs":
        return `${fileLine}\nAdd docstrings/comments to every function and class in this code. Return the fully documented version.${fence(activeContent)}`;
      case "/refactor":
        return `${fileLine}\nRefactor this code to improve readability and maintainability${extra ? `: ${extra}` : "."}${fence(activeContent)}`;
      default:
        return raw;
    }
  }

  // ── Agent interaction ──────────────────────────────────────────────────────
  async function sendPrompt(promptText) {
    if (!promptText.trim()) return;

    const expandedPrompt = _expandSlashCommand(promptText);

    appendChat(promptText, "user");   // show original text in chat
    chatInput.value = "";
    setStatus("running");
    $("btn-send-prompt").disabled = true;
    $("btn-run-file").disabled = true;

    // Notify sessions manager
    document.dispatchEvent(new CustomEvent("sa:chatSent", { detail: { prompt: promptText } }));

    const agentMsg = appendChat("", "agent");
    clearOutput();

    const backend = llmSelect.value;

    // Try WebSocket streaming first; fall back to fetch
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsProto}://${location.host}/ws/run`;

    try {
      await streamViaWebSocket(wsUrl, expandedPrompt, backend, agentMsg);
    } catch {
      // WebSocket unavailable — fallback to plain fetch
      await runViaFetch(expandedPrompt, backend, agentMsg);
    }

    // Render code blocks now that the full response is available
    _finaliseAgentMessage(agentMsg);

    setStatus("idle");
    $("btn-send-prompt").disabled = false;
    $("btn-run-file").disabled = false;

    // Notify sessions manager that turn is complete
    document.dispatchEvent(new CustomEvent("sa:chatDone"));
  }

  function streamViaWebSocket(wsUrl, prompt, backend, agentMsg) {
    return new Promise((resolve, reject) => {
      let ws;
      try { ws = new WebSocket(wsUrl); }
      catch { reject(new Error("WebSocket unavailable")); return; }

      ws.onopen = () => ws.send(JSON.stringify({ prompt, llm_backend: backend, project_path: state.activeProject }));

      ws.onmessage = (ev) => {
        try {
          const pkt = JSON.parse(ev.data);
          if (pkt.type === "chunk") {
            agentMsg.textContent += pkt.data;
            appendOutput(pkt.data);
            chatMessages.scrollTop = chatMessages.scrollHeight;
          } else if (pkt.type === "done") {
            ws.close();
            resolve();
          } else if (pkt.type === "error") {
            agentMsg.className = "chat-msg error";
            agentMsg.textContent = "⚠ " + pkt.data;
            appendOutput("Error: " + pkt.data + "\n");
            ws.close();
            setStatus("error");
            resolve();
          }
        } catch { /* ignore non-JSON */ }
      };

      ws.onerror = () => { ws.close(); reject(new Error("ws error")); };
    });
  }

  async function runViaFetch(prompt, backend, agentMsg) {
    try {
      const res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, llm_backend: backend, project_path: state.activeProject }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      agentMsg.textContent = data.result;
      appendOutput(data.result + "\n");
    } catch (e) {
      agentMsg.className = "chat-msg error";
      agentMsg.textContent = "⚠ " + e.message;
      appendOutput("Error: " + e.message + "\n");
      setStatus("error");
    }
  }

  // ── "Run agent on file" ────────────────────────────────────────────────────
  // ── Agentic mode ──────────────────────────────────────────────────────────

  let _agenticMode = false;

  /** Toggle agentic mode on/off. */
  function _setAgenticMode(on) {
    _agenticMode = on;
    const btn = $("btn-agentic-toggle");
    if (!btn) return;
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.classList.toggle("active", on);
    btn.title = on
      ? "Agentic mode ON — AI will plan tasks and edit files directly"
      : "Toggle Agentic mode (AI edits files)";
  }

  /** Build the agentic thinking indicator element. */
  function _mkThinking(text) {
    const el = document.createElement("div");
    el.className = "ag-thinking";
    el.textContent = text;
    return el;
  }

  /** Render a Todo list card inside an agent message element. */
  function _renderTodos(todos, containerEl) {
    const done = todos.filter((t) => t.done).length;
    const wrapper = document.createElement("div");
    wrapper.className = "ag-todos";
    wrapper.dataset.agTodos = "1";

    wrapper.innerHTML = `
      <div class="ag-todos-header">
        <span class="ag-todos-title">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
          </svg>
          Todos (${done}/${todos.length})
        </span>
        <span class="ag-todos-badge">${todos.length - done} left</span>
      </div>
      <div class="ag-todos-list"></div>
    `;

    const list = wrapper.querySelector(".ag-todos-list");
    todos.forEach((t) => {
      const item = document.createElement("div");
      item.className = "ag-todo-item" + (t.done ? " done" : "");
      item.dataset.todoId = t.id;
      item.innerHTML = `
        <span class="ag-todo-check">${t.done ? "✓" : ""}</span>
        <span>${escHtmlSimple(t.text)}</span>
      `;
      list.appendChild(item);
    });

    // Toggle expand/collapse
    wrapper.querySelector(".ag-todos-header").addEventListener("click", () => {
      list.style.display = list.style.display === "none" ? "" : "none";
    });

    containerEl.appendChild(wrapper);
    return wrapper;
  }

  /** Update an existing todo list card with fresh state. */
  function _updateTodos(wrapper, todos) {
    if (!wrapper) return;
    const done = todos.filter((t) => t.done).length;
    const title = wrapper.querySelector(".ag-todos-title");
    if (title) title.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
      </svg>
      Todos (${done}/${todos.length})
    `;
    const badge = wrapper.querySelector(".ag-todos-badge");
    if (badge) badge.textContent = `${todos.length - done} left`;
    const list = wrapper.querySelector(".ag-todos-list");
    if (!list) return;
    todos.forEach((t) => {
      const item = list.querySelector(`[data-todo-id="${t.id}"]`);
      if (item) {
        item.classList.toggle("done", t.done);
        item.classList.toggle("active", false);
        const check = item.querySelector(".ag-todo-check");
        if (check) check.textContent = t.done ? "✓" : "";
      }
    });
  }

  /** Mark one todo item as active (in progress). */
  function _setTodoActive(wrapper, id) {
    if (!wrapper) return;
    wrapper.querySelectorAll(".ag-todo-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.todoId === id);
    });
  }

  /** Render a file-changes card inside an agent message element.
   *  Returns the wrapper so the caller can update it. */
  function _renderFileChanges(fileChanges, containerEl) {
    const totalAdd = fileChanges.reduce((s, f) => s + (f.additions || 0), 0);
    const totalDel = fileChanges.reduce((s, f) => s + (f.deletions || 0), 0);

    const wrapper = document.createElement("div");
    wrapper.className = "ag-changes";
    wrapper.dataset.agChanges = "1";

    wrapper.innerHTML = `
      <div class="ag-changes-header">
        <span class="ag-changes-title">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
          </svg>
          ${fileChanges.length} file${fileChanges.length !== 1 ? "s" : ""} changed
        </span>
        <span class="ag-changes-stats">
          <span class="ag-stat-add">+${totalAdd}</span>
          <span class="ag-stat-del">-${totalDel}</span>
        </span>
        <div class="ag-changes-actions">
          <button class="ag-btn-keep" title="Keep all changes">Keep</button>
          <button class="ag-btn-undo" title="Undo all changes — restore original files">Undo</button>
        </div>
      </div>
      <div class="ag-changes-list"></div>
    `;

    const list = wrapper.querySelector(".ag-changes-list");
    fileChanges.forEach((fc) => {
      const entry = document.createElement("div");
      entry.className = "ag-file-entry";
      entry.innerHTML = `
        <span class="ag-file-bullet">◆</span>
        <span class="ag-file-path">${escHtmlSimple(fc.path)}</span>
        <span class="ag-file-add">+${fc.additions}</span>
        <span class="ag-file-del">-${fc.deletions}</span>
      `;
      // Click to open the diff view
      entry.addEventListener("click", () => {
        if (fc.path) openFile(fc.path).catch(() => {});
      });
      list.appendChild(entry);
    });

    // Toggle expand/collapse
    wrapper.querySelector(".ag-changes-header").addEventListener("click", (e) => {
      if (e.target.closest(".ag-changes-actions")) return;
      list.style.display = list.style.display === "none" ? "" : "none";
    });

    // Keep: just disable the undo button to signal acceptance
    wrapper.querySelector(".ag-btn-keep").addEventListener("click", async () => {
      wrapper.querySelector(".ag-btn-keep").disabled = true;
      wrapper.querySelector(".ag-btn-undo").disabled = true;
      wrapper.querySelector(".ag-btn-keep").textContent = "✓ Kept";
    });

    // Undo: restore each file's original content
    wrapper.querySelector(".ag-btn-undo").addEventListener("click", async () => {
      const undoBtn = wrapper.querySelector(".ag-btn-undo");
      undoBtn.disabled = true;
      undoBtn.textContent = "Undoing…";
      let allOk = true;
      for (const fc of fileChanges) {
        try {
          const r = await fetch("/files/write", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: fc.path, content: fc.original_content }),
          });
          if (!r.ok) { allOk = false; }
        } catch { allOk = false; }
      }
      undoBtn.textContent = allOk ? "✓ Undone" : "⚠ Partial";
      wrapper.querySelector(".ag-btn-keep").disabled = true;
      // Reload the active file if it was changed
      if (state.activeFile && fileChanges.some((f) => f.path === state.activeFile)) {
        openFile(state.activeFile).catch(() => {});
      }
    });

    containerEl.appendChild(wrapper);
    return wrapper;
  }

  /**
   * Run the agentic chat flow via WebSocket, falling back to REST.
   * Returns the final AgenticChatResponse data.
   */
  async function sendAgenticPrompt(promptText) {
    if (!promptText.trim()) return;

    appendChat(promptText, "user");
    chatInput.value = "";
    setStatus("running");
    $("btn-send-prompt").disabled = true;
    $("btn-run-file").disabled = true;
    document.dispatchEvent(new CustomEvent("sa:chatSent", { detail: { prompt: promptText } }));

    // Create the agent message container
    const agentMsg = document.createElement("div");
    agentMsg.className = "chat-msg agent";
    chatMessages.appendChild(agentMsg);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const backend = llmSelect.value;
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${wsProto}://${location.host}/ws/assistant/chat/agentic`;

    let todosWrapper = null;
    let changesWrapper = null;
    let thinkingEl = null;

    function removeThinking() {
      if (thinkingEl && thinkingEl.parentNode) thinkingEl.parentNode.removeChild(thinkingEl);
      thinkingEl = null;
    }

    function handleEvent(evt) {
      if (evt.type === "thinking") {
        removeThinking();
        thinkingEl = _mkThinking(evt.text || "Thinking…");
        agentMsg.appendChild(thinkingEl);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      } else if (evt.type === "todos" && evt.todos) {
        removeThinking();
        if (todosWrapper) todosWrapper.parentNode && todosWrapper.parentNode.removeChild(todosWrapper);
        todosWrapper = _renderTodos(evt.todos, agentMsg);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      } else if (evt.type === "todo_active") {
        _setTodoActive(todosWrapper, evt.id);
      } else if (evt.type === "generating_patch") {
        removeThinking();
        thinkingEl = document.createElement("div");
        thinkingEl.className = "ag-patch-indicator";
        thinkingEl.textContent = `Generating patch for ${evt.path || "file"}…`;
        agentMsg.appendChild(thinkingEl);
        chatMessages.scrollTop = chatMessages.scrollHeight;
      } else if (evt.type === "file_edited" && evt.path) {
        removeThinking();
        appendOutput(`Edited ${evt.path} +${evt.additions} -${evt.deletions}\n`);
      } else if (evt.type === "todo_done") {
        // Individual todo marked done — update will come in the "reply" packet
      } else if (evt.type === "reply") {
        removeThinking();
        // Update todos with final state
        if (evt.todos && todosWrapper) _updateTodos(todosWrapper, evt.todos);
        else if (evt.todos && !todosWrapper) todosWrapper = _renderTodos(evt.todos, agentMsg);
        // Render file changes card
        if (evt.file_changes && evt.file_changes.length > 0) {
          changesWrapper = _renderFileChanges(evt.file_changes, agentMsg);
        }
        // Render the final text reply
        if (evt.text) {
          const replyEl = document.createElement("div");
          replyEl.className = "chat-msg agent";
          replyEl.style.marginTop = "6px";
          replyEl.innerHTML = _renderCodeBlocks(evt.text);
          _bindCodeButtons(replyEl);
          agentMsg.appendChild(replyEl);
        }
        chatMessages.scrollTop = chatMessages.scrollHeight;
      }
    }

    try {
      await _agenticStreamWS(wsUrl, promptText, backend, handleEvent);
    } catch {
      // WebSocket unavailable — use REST fallback
      await _agenticFetch(promptText, backend, agentMsg, handleEvent);
    }

    removeThinking();
    setStatus("idle");
    $("btn-send-prompt").disabled = false;
    $("btn-run-file").disabled = false;
    document.dispatchEvent(new CustomEvent("sa:chatDone"));
  }

  /** Stream agentic events via WebSocket. */
  function _agenticStreamWS(wsUrl, message, backend, onEvent) {
    return new Promise((resolve, reject) => {
      let ws;
      try { ws = new WebSocket(wsUrl); }
      catch { reject(new Error("WebSocket unavailable")); return; }

      ws.onopen = () => ws.send(JSON.stringify({
        message,
        llm_backend: backend,
        project_path: state.activeProject || "",
      }));

      ws.onmessage = (ev) => {
        try {
          const pkt = JSON.parse(ev.data);
          onEvent(pkt);
          if (pkt.type === "done") { ws.close(); resolve(); }
          else if (pkt.type === "error") { ws.close(); resolve(); }
        } catch { /* ignore non-JSON */ }
      };

      ws.onerror = () => { ws.close(); reject(new Error("ws error")); };
    });
  }

  /** Agentic fallback via REST POST. */
  async function _agenticFetch(message, backend, containerEl, onEvent) {
    onEvent({ type: "thinking", text: "Sending request…" });
    try {
      const res = await fetch("/assistant/chat/agentic", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          llm_backend: backend,
          project_path: state.activeProject || "",
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      // Simulate event stream from REST response
      if (data.todos) onEvent({ type: "todos", todos: data.todos });
      onEvent({
        type: "reply",
        text: data.reply,
        todos: data.todos,
        file_changes: data.file_changes,
      });
      onEvent({ type: "done" });
    } catch (e) {
      containerEl.innerHTML += `<div class="chat-msg error">⚠ ${escHtmlSimple(e.message)}</div>`;
    }
  }

  // ── "Run agent on file" ────────────────────────────────────────────────────
  function runAgentOnFile() {
    const path = state.activeFile;
    if (!path) {
      appendOutput("No file open.\n");
      return;
    }
    const file = state.openFiles[path];
    const content = state.editorMode === "monaco"
      ? (file?.model?.getValue() ?? "")
      : ($("fallback-editor").value || file?.content || "");
    const prompt = `Review and improve the file '${path}':\n\n${content}`;
    sendPrompt(prompt);
  }

  // ── New file dialog ────────────────────────────────────────────────────────
  async function createNewFile(path) {
    try {
      const res = await fetch("/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: "" }),
      });
      if (!res.ok) throw new Error(await res.text());
      await loadFileTree();
      if (!path.endsWith("/.gitkeep")) {
        await openFile(path);
      }
    } catch (e) {
      appendOutput(`Error creating ${path}: ${e.message}\n`);
    }
  }

  // ── Import project dialog ─────────────────────────────────────────────────
  function showImportDialog() {
    $("import-path").value = "";
    $("import-dest").value = "";
    $("import-preview").classList.add("hidden");
    $("import-preview").textContent = "";
    $("import-dialog").classList.remove("hidden");
    $("import-path").focus();
  }

  async function scanImportFolder() {
    const path = $("import-path").value.trim();
    if (!path) return;
    const preview = $("import-preview");
    preview.textContent = "Scanning…";
    preview.classList.remove("hidden");
    try {
      const res = await fetch(`/files/scan?path=${encodeURIComponent(path)}`);
      if (!res.ok) throw new Error((await res.json()).detail || "Scan failed");
      const data = await res.json();
      let text = `📁 ${path}\n`;
      text += `Type: ${(data.summary?.detected_project_types ?? []).join(", ") || "unknown"}\n`;
      text += `Files: ${data.summary?.total_files ?? 0}  Dirs: ${data.summary?.total_dirs ?? 0}\n\n`;
      if (data.entries) {
        for (const e of data.entries.slice(0, 30)) {
          text += `  ${e.type === "dir" ? "📁" : "📄"} ${e.name}\n`;
        }
        if (data.entries.length > 30) text += `  … and ${data.entries.length - 30} more\n`;
      }
      preview.textContent = text;
    } catch (e) {
      preview.textContent = `⚠ ${e.message}`;
    }
  }

  async function doImport() {
    const sourcePath = $("import-path").value.trim();
    if (!sourcePath) return;
    const destName = $("import-dest").value.trim();
    try {
      const res = await fetch("/files/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_path: sourcePath, destination_name: destName }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Import failed");
      const data = await res.json();
      $("import-dialog").classList.add("hidden");
      appendOutput(`✓ Imported project: ${data.destination || sourcePath}\n`);
      await loadFileTree();
      showInitWizard(data.destination || `workspace/${destName || sourcePath.split('/').pop()}`);
    } catch (e) {
      appendOutput(`Error importing: ${e.message}\n`);
    }
  }

  // ── Monaco init ────────────────────────────────────────────────────────────
  function initFallbackEditor() {
    state.editorMode = "fallback";
    $("editor-loading").style.display = "none";
    $("fallback-editor").classList.add("hidden");
    $("editor-welcome").classList.remove("hidden");

    // Update status-bar editor-mode badge
    const badge = $("sb-editor-mode");
    badge.textContent = "Fallback Editor";
    badge.className = "mode-fallback";
    badge.title = "Monaco CDN unavailable — using plain-text fallback. Click to reload with Monaco when online.";
    badge.style.cursor = "pointer";
    badge.addEventListener("click", () => location.reload());

    // Tab key → 4-space indent
    $("fallback-editor").addEventListener("keydown", (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const ta = $("fallback-editor");
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        ta.value = ta.value.substring(0, start) + "    " + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 4;
        if (state.activeFile) markModified(state.activeFile);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        saveActiveFile();
      }
    });

    $("fallback-editor").addEventListener("input", () => {
      if (state.activeFile) markModified(state.activeFile);
      updateCursorPosition();
    });

    $("fallback-editor").addEventListener("keyup", updateCursorPosition);
    $("fallback-editor").addEventListener("click", updateCursorPosition);

    loadFileTree();
    appendOutput(
      "⚠ Monaco Editor CDN unavailable — using plain-text fallback editor.\n" +
      "All file and agent features (slash commands, Apply buttons) still work.\n" +
      "Connect to the internet and reload the page to get the full Monaco IDE.\n"
    );
    _startPendingPushPoller();
  }

  function initMonaco() {
    let monacoLoaded = false;

    // Hard deadline: if Monaco isn't fully ready within 3 s, use the fallback.
    const fallbackTimer = setTimeout(() => {
      if (!monacoLoaded) initFallbackEditor();
    }, 3000);

    // The CDN scripts are loaded asynchronously, so the AMD require() function
    // may not exist yet when this runs.  Poll briefly (every 100 ms) until the
    // loader is ready, has failed, or the deadline fires.
    function _tryLoad() {
      if (monacoLoaded) return;

      // Loader script reported a network error → fall back immediately.
      if (window.__monacoLoaderFailed) {
        clearTimeout(fallbackTimer);
        initFallbackEditor();
        return;
      }

      // Loader not ready yet — wait a tick and try again.
      if (typeof require !== "function") {
        setTimeout(_tryLoad, 100);
        return;
      }

      // AMD require is available — ask for the full editor module.
      require(["vs/editor/editor.main"], function () {
      if (monacoLoaded) return; // guard against double-fire
      monacoLoaded = true;
      clearTimeout(fallbackTimer);

      try {

      monaco.editor.defineTheme("arbiter-dark", {
        base: "vs-dark",
        inherit: true,
        rules: [],
        colors: {
          "editor.background": "#1e1e2e",
          "editor.foreground": "#cdd6f4",
          "editorLineNumber.foreground": "#45475a",
          "editorCursor.foreground": "#f5c2e7",
          "editor.selectionBackground": "#45475a",
          "editor.lineHighlightBackground": "#2a2a3d",
          "editorIndentGuide.background": "#313244",
        },
      });

      state.editor = monaco.editor.create($("editor-container"), {
        theme: "arbiter-dark",
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        fontLigatures: true,
        lineNumbers: "on",
        minimap: { enabled: true },
        scrollBeyondLastLine: false,
        wordWrap: "off",
        automaticLayout: true,
        tabSize: 4,
        insertSpaces: true,
        renderWhitespace: "selection",
        model: null,
      });

      // Hide the loading overlay as soon as the editor instance is ready.
      // Subsequent setup (key bindings, completions, toolbars) is non-critical;
      // failures there must not leave the spinner running forever.
      state.editorMode = "monaco";
      $("editor-loading").style.display = "none";
      $("editor-welcome").classList.remove("hidden");

      // Update status-bar editor-mode badge
      const badge = $("sb-editor-mode");
      badge.textContent = "Monaco";
      badge.className = "mode-monaco";
      badge.title = "Monaco Editor (full IDE — syntax highlighting, IntelliSense, minimap)";

      // Ctrl+S to save
      state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveActiveFile);

      // Track cursor position for status bar
      state.editor.onDidChangeCursorPosition(updateCursorPosition);

      // ── Copilot-style inline completions (t7-1) ──────────────────────────
      let _completionTimer = null;
      monaco.languages.registerInlineCompletionsProvider({ pattern: "**" }, {
        provideInlineCompletions(model, position) {
          return new Promise((resolve) => {
            clearTimeout(_completionTimer);
            _completionTimer = setTimeout(async () => {
              try {
                const allText      = model.getValue();
                const cursorOffset = model.getOffsetAt(position);
                const res = await fetch("/ai/complete", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    file_content: allText,
                    cursor_offset: cursorOffset,
                    language: model.getLanguageId(),
                    path: state.activeFile || "",
                    llm_backend: llmSelect.value,
                  }),
                });
                if (!res.ok) { resolve({ items: [] }); return; }
                const data = await res.json();
                if (!data.completion) { resolve({ items: [] }); return; }
                resolve({
                  items: [{
                    insertText: data.completion,
                    range: new monaco.Range(
                      position.lineNumber, position.column,
                      position.lineNumber, position.column,
                    ),
                  }],
                });
              } catch { resolve({ items: [] }); }
            }, 700);
          });
        },
        freeInlineCompletions() {},
      });

      // ── Floating selection toolbar (t7-2) ─────────────────────────────────
      const selToolbar = $("sel-toolbar");
      const SEL_TOOLBAR_HEIGHT   = 40;  // px — toolbar height + gap above selection
      const SEL_TOOLBAR_MIN_EDGE = 4;   // px — minimum margin from viewport edge
      const SEL_TOOLBAR_EST_W    = 320; // px — approximate toolbar width for right-edge clamping

      state.editor.onDidChangeCursorSelection(() => {
        const sel = state.editor.getSelection();
        if (!sel || sel.isEmpty()) { selToolbar.classList.add("hidden"); return; }
        const selText = state.editor.getModel().getValueInRange(sel);
        if (!selText.trim()) { selToolbar.classList.add("hidden"); return; }

        const startPos = { lineNumber: sel.startLineNumber, column: sel.startColumn };
        const coords = state.editor.getScrolledVisiblePosition(startPos);
        const editorRect = $("editor-container").getBoundingClientRect();
        if (!coords) { selToolbar.classList.add("hidden"); return; }

        let x = editorRect.left + coords.left;
        let y = editorRect.top  + coords.top - SEL_TOOLBAR_HEIGHT;
        // Keep toolbar inside the viewport
        x = Math.max(SEL_TOOLBAR_MIN_EDGE, Math.min(x, window.innerWidth - SEL_TOOLBAR_EST_W));
        y = Math.max(SEL_TOOLBAR_MIN_EDGE, y);

        selToolbar.style.left = `${x}px`;
        selToolbar.style.top  = `${y}px`;
        selToolbar.dataset.selection = selText;
        selToolbar.classList.remove("hidden");
      });

      document.addEventListener("mousedown", (e) => {
        if (!selToolbar.contains(e.target)) selToolbar.classList.add("hidden");
      });

      selToolbar.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-action]");
        if (!btn) return;
        const selText = selToolbar.dataset.selection || "";
        selToolbar.classList.add("hidden");
        _sendAiAction(btn.dataset.action, selText);
      });

      // ── Monaco right-click AI context menu actions (t7-3) ─────────────────
      const _AI_CONTEXT_ACTIONS = [
        { id: "ai.explain",   label: "🤖 Explain Selection",  action: "explain"   },
        { id: "ai.refactor",  label: "🤖 Refactor Selection", action: "refactor"  },
        { id: "ai.tests",     label: "🤖 Generate Tests",     action: "tests"     },
        { id: "ai.docstring", label: "🤖 Add Docstrings",     action: "docstring" },
        { id: "ai.fix",       label: "🤖 Fix Code",           action: "fix"       },
      ];
      for (const { id, label, action } of _AI_CONTEXT_ACTIONS) {
        state.editor.addAction({
          id,
          label,
          contextMenuGroupId: "navigation",
          contextMenuOrder: 1.5,
          run(ed) {
            const s = ed.getSelection();
            const text = (s && !s.isEmpty())
              ? ed.getModel().getValueInRange(s)
              : ed.getModel().getValue();
            _sendAiAction(action, text);
          },
        });
      }

      // Propose Changes action (t7-4) in context menu
      state.editor.addAction({
        id: "ai.propose",
        label: "🤖 Propose Changes…",
        contextMenuGroupId: "navigation",
        contextMenuOrder: 1.6,
        run() { _promptAndShowDiff(); },
      });

      // Load file tree after editor is ready
      loadFileTree();
      _startPendingPushPoller();

      } catch (err) {
        // Any error during Monaco setup must not leave the loading overlay
        // spinning forever.  Fall back to the plain-text editor.
        console.error("[Arbiter] Monaco initialization error:", err);
        clearTimeout(fallbackTimer);
        initFallbackEditor();
      }
      }, function (loadErr) {
        // AMD module-load error (e.g. CDN unreachable for the main editor bundle)
        console.error("[Arbiter] Monaco module load error:", loadErr);
        clearTimeout(fallbackTimer);
        initFallbackEditor();
      }); // end require(["vs/editor/editor.main"])
  } // end _tryLoad

  _tryLoad(); // kick off the async-aware initialisation
  }

  // ── Pending-push poller (files pushed via /api/ide/push open automatically) ─
  function _startPendingPushPoller() {
    setInterval(async () => {
      try {
        const res = await fetch("/api/ide/pending");
        if (!res.ok) return;
        const { paths } = await res.json();
        for (const p of paths) {
          await openFile(p);
          appendOutput(`📥 File pushed to IDE: ${p}\n`);
        }
        if (paths.length) await loadFileTree();
      } catch { /* server may not be ready yet */ }
    }, 3000);
  }

  // ── AI action helper (t7-2 / t7-3) ────────────────────────────────────────
  async function _sendAiAction(action, selection) {
    if (!selection.trim()) { appendOutput("No code selected for AI action.\n"); return; }
    const model    = state.editor && state.editor.getModel();
    const language = model ? model.getLanguageId() : "";
    setStatus("running");
    try {
      const res = await fetch("/ai/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          selection,
          file_content: model ? model.getValue() : "",
          language,
          path: state.activeFile || "",
          llm_backend: llmSelect.value,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.result) {
        const labels = {
          explain:   "💡 Explanation",
          refactor:  "🔧 Refactored Code",
          tests:     "🧪 Generated Tests",
          fix:       "🪲 Fixed Code",
          docstring: "📝 Documented Code",
        };
        const label = labels[action] || "AI Result";
        const msgEl = appendChat(`${label}:\n\n${data.result}`, "agent");
        _finaliseAgentMessage(msgEl);
        appendOutput(`${label}:\n${data.result}\n`);
      }
    } catch (e) {
      appendOutput(`AI action error: ${e.message}\n`);
    } finally {
      setStatus("idle");
    }
  }

  // ── AI Diff Viewer (t7-4) ──────────────────────────────────────────────────
  let _diffEditor = null;
  let _proposedContent = "";

  function _promptAndShowDiff() {
    const instruction = window.prompt("Describe the changes AI should make to this file:");
    if (instruction) _showAiDiff(instruction);
  }

  async function _showAiDiff(instruction) {
    if (!state.activeFile || !state.editor) {
      appendOutput("No file open for AI proposal.\n");
      return;
    }
    const model       = state.editor.getModel();
    const fileContent = model.getValue();
    const language    = model.getLanguageId();
    setStatus("running");
    try {
      const res = await fetch("/ai/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction,
          file_content: fileContent,
          language,
          path: state.activeFile,
          llm_backend: llmSelect.value,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.error) { appendOutput(`AI propose error: ${data.error}\n`); return; }
      _proposedContent = data.proposed_content;

      const overlay = $("ai-diff-overlay");
      overlay.classList.remove("hidden");
      $("diff-title").textContent = `🤖 Proposed Changes — ${state.activeFile}`;

      // Create or update Monaco DiffEditor
      const container = $("diff-editor-container");
      if (_diffEditor) {
        _diffEditor.dispose();
        _diffEditor = null;
      }
      if (typeof monaco !== "undefined") {
        _diffEditor = monaco.editor.createDiffEditor(container, {
          theme:            "arbiter-dark",
          automaticLayout:  true,
          renderSideBySide: true,
          fontSize:         13,
          readOnly:         false,
        });
        const origModel = monaco.editor.createModel(fileContent, language);
        const modModel  = monaco.editor.createModel(_proposedContent, language);
        _diffEditor.setModel({ original: origModel, modified: modModel });
      }
    } catch (e) {
      appendOutput(`AI diff error: ${e.message}\n`);
    } finally {
      setStatus("idle");
    }
  }

  $("btn-diff-accept").addEventListener("click", async () => {
    const content = (_diffEditor)
      ? _diffEditor.getModifiedEditor().getModel().getValue()
      : _proposedContent;
    try {
      await fetch("/files/write", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: state.activeFile, content }),
      });
      if (state.editor) state.editor.getModel().setValue(content);
      appendOutput(`✓ AI changes accepted and saved to ${state.activeFile}\n`);
      state.openFiles[state.activeFile] = { ...state.openFiles[state.activeFile], modified: false };
      updateStatusBar();
    } catch (e) {
      appendOutput(`Error saving AI changes: ${e.message}\n`);
    }
    $("ai-diff-overlay").classList.add("hidden");
  });

  $("btn-diff-reject").addEventListener("click", () => {
    $("ai-diff-overlay").classList.add("hidden");
    appendOutput("AI proposal rejected.\n");
  });

  // ── Output tab wiring ─────────────────────────────────────────────────────
  document.querySelectorAll(".out-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchOutputTab(btn.dataset.tab));
  });

  // ── Event wiring ───────────────────────────────────────────────────────────
  $("btn-save").addEventListener("click", saveActiveFile);
  $("btn-run-file").addEventListener("click", runAgentOnFile);
  $("btn-clear-output").addEventListener("click", () => {
    clearOutput();
    buildContent.textContent = "";
    problemsContent.innerHTML = "";
    state.buildErrors = [];
    state.lastBuildOutput = "";
    $("btn-fix-ai").classList.add("hidden");
  });
  $("btn-clear-chat").addEventListener("click", () => {
    chatMessages.innerHTML = "";
    _sessions.clearCurrent();
  });
  $("btn-refresh-tree").addEventListener("click", () => loadFileTree());

  // ── Chat sessions management ──────────────────────────────────────────────
  const _sessions = (() => {
    const STORE_KEY = "sa_chat_sessions";
    let _list = [];
    let _current = null;

    function _save() {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(_list)); } catch {}
    }
    function _load() {
      try {
        const raw = localStorage.getItem(STORE_KEY);
        if (raw) _list = JSON.parse(raw);
      } catch { _list = []; }
    }
    function _relativeTime(iso) {
      const diff = Date.now() - new Date(iso).getTime();
      if (diff < 60000)    return "just now";
      if (diff < 3600000)  return Math.floor(diff / 60000) + " min ago";
      if (diff < 86400000) return Math.floor(diff / 3600000) + " hr ago";
      return Math.floor(diff / 86400000) + " days ago";
    }
    function render() {
      const list = $("sessions-list");
      if (!list) return;
      if (!_list.length) {
        list.innerHTML = '<div style="padding:6px 12px;font-size:11px;color:var(--text-dim)">No sessions yet</div>';
        return;
      }
      list.innerHTML = _list.slice().reverse().map((s) => `
        <div class="session-item${s.id === (_current?.id) ? " active" : ""}" data-sid="${s.id}">
          <div class="session-title">${escHtmlSimple(s.title || "New chat")}</div>
          <div class="session-meta">
            <span class="session-ts">${_relativeTime(s.created)}</span>
            <span class="session-status${s.done ? " done" : ""}">
              ${s.done ? "Completed" : "Working…"}
            </span>
          </div>
        </div>`).join("");
      list.querySelectorAll(".session-item").forEach((el) => {
        el.addEventListener("click", () => loadSession(el.dataset.sid));
      });
    }
    function newSession(firstMessage) {
      const id = `sess_${Date.now()}`;
      const s = { id, title: (firstMessage || "New chat").slice(0, 60), created: new Date().toISOString(), done: false };
      _list.push(s);
      _current = s;
      _save();
      render();
      $("cp-divider")?.classList.add("visible");
      return id;
    }
    function finishCurrent() {
      if (_current) { _current.done = true; _save(); render(); }
    }
    function clearCurrent() { _current = null; $("cp-divider")?.classList.remove("visible"); }
    function loadSession(id) {
      const s = _list.find((x) => x.id === id);
      if (!s) return;
      _current = s;
      render();
      chatMessages.innerHTML = "";
      appendChat(`Session: "${s.title}"`, "agent");
    }
    _load();
    render();
    return { newSession, finishCurrent, clearCurrent, render };
  })();

  // Wrap sendPrompt to register sessions
  const _origSendPrompt = sendPrompt;
  // Override is done inline — hook into the existing sendPrompt via the
  // session lifecycle rather than replacing it.
  $("btn-new-session")?.addEventListener("click", () => {
    chatMessages.innerHTML = "";
    _sessions.clearCurrent();
    chatInput.focus();
  });

  // ── Attach-file chip — update from active file ────────────────────────────
  function _updateAttachChip() {
    const chipName = $("ci-attached-name");
    if (!chipName) return;
    const f = state.activeFile;
    chipName.textContent = f ? f.split("/").pop() : "no file";
  }
  document.addEventListener("sa:fileOpened", _updateAttachChip);

  $("btn-attach-file")?.addEventListener("click", () => {
    if (state.activeFile) {
      chatInput.value += (chatInput.value ? "\n" : "") + `[context: ${state.activeFile}]`;
      chatInput.focus();
    }
  });

  // Register session on send
  document.addEventListener("sa:chatSent", (e) => {
    _sessions.newSession(e.detail?.prompt || "");
  });
  document.addEventListener("sa:chatDone", () => _sessions.finishCurrent());

  // Update LLM status strip when selector changes
  function _updateLlmStrip() {
    const label = $("ci-llm-label");
    if (label) label.textContent = llmSelect?.value || "—";
  }
  llmSelect?.addEventListener("change", _updateLlmStrip);
  _updateLlmStrip();

  // Fetch active persona name for status strip
  (async () => {
    try {
      const r = await fetch("/ai/persona/active");
      if (r.ok) {
        const d = await r.json();
        const el = $("ci-persona-label");
        if (el) el.textContent = d.name || "arbiter_assistant";
      }
    } catch {}
  })();

  // ── Expand chat panel ─────────────────────────────────────────────────────
  $("btn-cp-expand")?.addEventListener("click", () => {
    const panel = $("agent-panel");
    if (!panel) return;
    const expanded = panel.style.width && panel.style.width !== "var(--agent-w)";
    panel.style.width = expanded ? "" : "580px";
  });

  // ── Slash-command quick buttons ─────────────────────────────────────────
  document.querySelectorAll(".slash-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      _agenticMode ? sendAgenticPrompt(btn.dataset.cmd) : sendPrompt(btn.dataset.cmd);
    });
  });

  $("btn-send-prompt").addEventListener("click", () => {
    _agenticMode ? sendAgenticPrompt(chatInput.value) : sendPrompt(chatInput.value);
  });
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      _agenticMode ? sendAgenticPrompt(chatInput.value) : sendPrompt(chatInput.value);
    }
  });

  // ── Agentic toggle button ──────────────────────────────────────────────────
  const _agenticToggleBtn = $("btn-agentic-toggle");
  if (_agenticToggleBtn) {
    _agenticToggleBtn.addEventListener("click", () => _setAgenticMode(!_agenticMode));
  }

  $("btn-new-file").addEventListener("click", () => {
    newFilePath.value = "workspace/";
    newFileDialog.classList.remove("hidden");
    newFilePath.focus();
  });
  $("btn-new-file-ok").addEventListener("click", () => {
    const p = newFilePath.value.trim();
    if (p) { createNewFile(p); newFileDialog.classList.add("hidden"); }
  });
  $("btn-new-file-cancel").addEventListener("click", () => newFileDialog.classList.add("hidden"));
  newFilePath.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-new-file-ok").click();
    if (e.key === "Escape") newFileDialog.classList.add("hidden");
  });

  // Build & Test buttons
  $("btn-build").addEventListener("click", () => runBuildOrTest("build"));
  $("btn-test").addEventListener("click", () => runBuildOrTest("test"));

  // Fix with AI button
  $("btn-fix-ai").addEventListener("click", fixWithAI);

  // Import project button + dialog
  $("btn-import-project").addEventListener("click", showImportDialog);
  $("btn-import-scan").addEventListener("click", scanImportFolder);
  $("btn-import-ok").addEventListener("click", doImport);
  $("btn-import-cancel").addEventListener("click", () => $("import-dialog").classList.add("hidden"));
  $("import-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") scanImportFolder();
    if (e.key === "Escape") $("import-dialog").classList.add("hidden");
  });

  // Clone repo button + dialog
  $("btn-clone-repo").addEventListener("click", showCloneDialog);
  $("btn-clone-ok").addEventListener("click", doClone);
  $("btn-clone-cancel").addEventListener("click", () => $("clone-dialog").classList.add("hidden"));
  $("clone-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doClone();
    if (e.key === "Escape") $("clone-dialog").classList.add("hidden");
  });

  // Init wizard
  $("btn-init-skip").addEventListener("click", () => $("init-wizard").classList.add("hidden"));
  $("btn-init-run").addEventListener("click", runInitWizard);

  // ── Git clone ──────────────────────────────────────────────────────────────
  function showCloneDialog() {
    $("clone-url").value = "";
    $("clone-dest").value = "";
    $("clone-branch").value = "";
    const status = $("clone-status");
    status.className = "clone-status hidden";
    status.textContent = "";
    $("clone-dialog").classList.remove("hidden");
    $("clone-url").focus();
  }

  async function doClone() {
    const url = $("clone-url").value.trim();
    if (!url) return;
    const dest = $("clone-dest").value.trim();
    const branch = $("clone-branch").value.trim();
    const status = $("clone-status");
    status.className = "clone-status running";
    status.textContent = "⟳ Cloning… (this may take a moment)";
    $("btn-clone-ok").disabled = true;
    try {
      const res = await fetch("/git/clone", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, destination: dest, branch }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Clone failed");
      status.className = "clone-status success";
      status.textContent = `✓ Cloned into ${data.destination} (${data.files} files)`;
      await loadFileTree();
      await _refreshProjectSwitcher();
      appendOutput(`✓ Cloned ${url} → ${data.destination}\n`);
      setTimeout(() => {
        $("clone-dialog").classList.add("hidden");
        showInitWizard(`workspace/${data.destination}`);
      }, 1500);
    } catch (e) {
      status.className = "clone-status error";
      status.textContent = `⚠ ${e.message}`;
    } finally {
      $("btn-clone-ok").disabled = false;
    }
  }

  // ── Project Init Wizard (AI-powered) ──────────────────────────────────────
  async function showInitWizard(projectPath) {
    $("init-wizard").classList.remove("hidden");
    $("init-wizard-detect-summary").textContent = "Scanning project…";
    $("init-wizard-steps").innerHTML = '<span style="color:var(--text-dim)">⟳ Detecting project type…</span>';
    $("init-wizard-progress").classList.add("hidden");
    $("btn-init-run").disabled = true;
    $("btn-init-run").dataset.path = projectPath;

    try {
      const res = await fetch(`/project/init/detect?path=${encodeURIComponent(projectPath)}`);
      const data = await res.json();
      const lang = data.language || "unknown";
      const fw = data.framework ? ` / ${data.framework}` : "";
      const pm = data.package_manager ? ` (${data.package_manager})` : "";
      $("init-wizard-detect-summary").textContent = `Detected: ${lang}${fw}${pm}`;

      const keyFiles = (data.detected_files || []).join(", ") || "none detected";
      $("init-wizard-steps").innerHTML =
        `<div style="line-height:1.7">` +
        `<strong>Language:</strong> ${escHtmlSimple(lang)}${escHtmlSimple(fw)}<br>` +
        (data.package_manager ? `<strong>Package manager:</strong> ${escHtmlSimple(data.package_manager)}<br>` : "") +
        `<strong>Key files:</strong> ${escHtmlSimple(keyFiles)}<br>` +
        `<br><span style="color:var(--text-dim);font-size:12px">` +
        `The AI will scan all project files, understand the codebase, ` +
        `create a setup plan, and execute it using available tools ` +
        `(read files, write config files, create .gitignore, etc.)` +
        `</span></div>`;

      $("btn-init-run").disabled = false;
    } catch (e) {
      $("init-wizard-detect-summary").textContent = "Ready to analyze";
      $("init-wizard-steps").innerHTML =
        `<span style="color:var(--text-dim);font-size:12px">` +
        `The AI will scan the project and create a setup plan.</span>`;
      $("btn-init-run").disabled = false;
    }
  }

  async function runInitWizard() {
    const projectPath = $("btn-init-run").dataset.path || state.activeProject;
    $("btn-init-run").disabled = true;
    $("btn-init-skip").disabled = true;

    // Close the wizard immediately and run in the chat panel
    $("init-wizard").classList.add("hidden");
    $("btn-init-skip").disabled = false;

    // Fetch the project scan for context
    let scanContext = "";
    try {
      const scanRes = await fetch(`/project/init/scan?path=${encodeURIComponent(projectPath)}`);
      if (scanRes.ok) {
        const scanData = await scanRes.json();
        scanContext = scanData.context || "";
      }
    } catch { /* scan is best-effort */ }

    // Build a rich AI prompt
    const prompt =
      `You are an expert developer assistant. A project has just been loaded at: ${projectPath}\n\n` +
      (scanContext ? `${scanContext}\n\n` : "") +
      `Please do the following:\n` +
      `1. Use the list_directory and read_file tools to explore the project structure\n` +
      `2. Read key files (README, package.json/requirements.txt/CMakeLists.txt, main entry points)\n` +
      `3. Understand what the project does and its tech stack\n` +
      `4. Create a brief analysis: purpose, structure, how to build/run it\n` +
      `5. Identify any missing setup files (.gitignore, .editorconfig, etc.) and create them\n` +
      `6. Suggest next steps for development\n\n` +
      `Be concise and practical. Use your tools to read and write files directly.`;

    switchOutputTab("output");
    sendPrompt(prompt);
  }

  // ── Project switcher ───────────────────────────────────────────────────────
  async function _refreshProjectSwitcher() {
    const sel = $("project-switcher");
    try {
      // Collect subdirs from both workspace/ and projects/
      const [wsRes, prRes] = await Promise.all([
        fetch("/files?path=workspace"),
        fetch("/files?path=projects"),
      ]);
      const options = [{ value: "", label: "— open project —" }];
      if (wsRes.ok) {
        const data = await wsRes.json();
        for (const e of (data.entries || [])) {
          if (e.type === "dir") options.push({ value: `workspace/${e.name}`, label: `workspace/${e.name}` });
        }
      }
      if (prRes.ok) {
        const data = await prRes.json();
        for (const e of (data.entries || [])) {
          if (e.type === "dir") options.push({ value: `projects/${e.name}`, label: `projects/${e.name}` });
        }
      }
      sel.innerHTML = options.map((o) =>
        `<option value="${o.value}">${o.label}</option>`
      ).join("");
    } catch { /* ignore */ }
  }

  $("project-switcher").addEventListener("change", async (e) => {
    const path = e.target.value;
    if (!path) return;
    state.activeProject = path;
    _roadmapCache.data = null;  // invalidate roadmap cache for new project
    // Load the file tree rooted at this project dir
    await loadFileTree(path);
    e.target.value = "";  // reset so it can be re-selected
  });

  // ── PTY terminal ─────────────────────────────────────────────────────────
  const _ptyState = { term: null, fitAddon: null, ws: null, ready: false };

  function _ensureTerminal() {
    const container = $("terminal-content");
    if (_ptyState.ready) {
      if (_ptyState.fitAddon) _ptyState.fitAddon.fit();
      return;
    }
    if (window.__xtermLoaderFailed || typeof Terminal === "undefined") {
      container.innerHTML =
        '<div style="padding:16px;color:var(--text-dim)">' +
        "⚠ xterm.js CDN unavailable. Connect to the internet to use the terminal tab.<br>" +
        "You can still run commands via the Build/Test buttons." +
        "</div>";
      return;
    }
    _ptyState.ready = true;

    const term = new Terminal({
      theme: {
        background: "#1e1e2e",
        foreground: "#cdd6f4",
        cursor: "#f5c2e7",
        selectionBackground: "#45475a",
      },
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      cursorBlink: true,
      convertEol: true,
    });
    _ptyState.term = term;

    let fitAddon = null;
    if (typeof FitAddon !== "undefined") {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      _ptyState.fitAddon = fitAddon;
    }

    term.open(container);
    if (fitAddon) fitAddon.fit();

    // Resize observer to keep terminal sized correctly
    const ro = new ResizeObserver(() => { if (fitAddon) fitAddon.fit(); });
    ro.observe(container);

    _connectPty(term, fitAddon);
  }

  function _connectPty(term, fitAddon) {
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/ws/pty`);
    _ptyState.ws = ws;

    ws.onopen = () => {
      const cols = fitAddon ? term.cols : 120;
      const rows = fitAddon ? term.rows : 30;
      ws.send(JSON.stringify({ type: "init", cwd: "workspace", cols, rows }));
    };

    ws.onmessage = (ev) => {
      try {
        const pkt = JSON.parse(ev.data);
        if (pkt.type === "output") term.write(pkt.data);
        else if (pkt.type === "exit") term.write(`\r\n\x1b[33m[Process exited with code ${pkt.code}]\x1b[0m\r\n`);
        else if (pkt.type === "error") term.write(`\r\n\x1b[31m[Error: ${pkt.data}]\x1b[0m\r\n`);
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      term.write("\r\n\x1b[33m[Connection closed — click here to reconnect]\x1b[0m\r\n");
      _ptyState.ready = false;
      // Allow reconnect on click
      $("terminal-content").addEventListener("click", () => {
        if (!_ptyState.ready) {
          $("terminal-content").innerHTML = "";
          _ensureTerminal();
        }
      }, { once: true });
    };

    ws.onerror = () => ws.close();

    // Forward keyboard input to PTY
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    // Forward resize events
    term.onResize(({ cols, rows }) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });
  }

  // ── Roadmap panel ─────────────────────────────────────────────────────────
  const _roadmapCache = { data: null };

  async function loadRoadmapPanel() {
    const container = $("roadmap-content");
    try {
      const pathParam = state.activeProject ? `?path=${encodeURIComponent(state.activeProject)}` : "";
      const res = await fetch(`/roadmap${pathParam}`);
      if (!res.ok) throw new Error("Roadmap not found");
      const data = await res.json();
      _roadmapCache.data = data;
      renderRoadmapPanel(container, data);
    } catch (e) {
      container.innerHTML = `<div style="padding:16px;color:var(--danger)">⚠ ${e.message}</div>`;
    }
  }

  function renderRoadmapPanel(container, data) {
    const statusIcon = { done: "✅", in_progress: "🔄", pending: "⬜" };

    let html = `<div class="roadmap-header">
      <span>📋 ${data.project || "Roadmap"} — ${data.version || ""}</span>
      <div style="display:flex;gap:6px">
        <button id="btn-roadmap-next-task" title="Send next pending task to the AI agent">▶ Work on Next Task</button>
        <button id="btn-roadmap-auto-build" title="Autonomous self-build: LLM generates code, tests, and commits" style="background:var(--accent2,#7c3aed);color:#fff">🤖 Auto-Build Next</button>
      </div>
    </div>`;

    for (const m of (data.milestones || [])) {
      const badge = `<span class="milestone-badge badge-${m.status}">${m.status.replace("_", " ")}</span>`;
      const tasks = (m.tasks || []).map((t) => {
        const workBtn = (t.status !== "done")
          ? `<button class="task-work-btn" data-task-id="${t.id}" data-task-title="${encodeURIComponent(t.title)}" data-task-desc="${encodeURIComponent(t.description || "")}">▶ Work</button>`
          : "";
        return `<div class="task-row">
          <span class="task-status-icon">${statusIcon[t.status] || "⬜"}</span>
          <div class="task-info">
            <div class="task-title">${escHtmlSimple(t.title)}</div>
            ${t.description ? `<div class="task-desc">${escHtmlSimple(t.description)}</div>` : ""}
          </div>
          ${workBtn}
        </div>`;
      }).join("");

      html += `<div class="milestone-block">
        <div class="milestone-title" data-milestone="${m.id}">
          <span class="milestone-arrow">▶</span>
          <span class="milestone-label">${escHtmlSimple(m.title)}</span>
          ${badge}
        </div>
        <div class="milestone-tasks ${m.status !== "done" ? "open" : ""}" id="mt-${m.id}">${tasks}</div>
      </div>`;
    }

    container.innerHTML = html;

    // Collapse/expand milestones
    container.querySelectorAll(".milestone-title").forEach((el) => {
      el.addEventListener("click", () => {
        const id = el.dataset.milestone;
        const tasks = $(`mt-${id}`);
        const arrow = el.querySelector(".milestone-arrow");
        if (tasks) {
          const open = tasks.classList.toggle("open");
          if (arrow) arrow.classList.toggle("open", open);
        }
      });
    });

    // "Work" buttons on individual tasks
    container.querySelectorAll(".task-work-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const title = decodeURIComponent(btn.dataset.taskTitle || "");
        const desc = decodeURIComponent(btn.dataset.taskDesc || "");
        const taskId = btn.dataset.taskId;
        _workOnTask(taskId, title, desc);
      });
    });

    // "Work on Next Task" button
    const nextBtn = $("btn-roadmap-next-task");
    if (nextBtn) {
      nextBtn.addEventListener("click", async () => {
        try {
          const res = await fetch("/roadmap/next");
          const data = await res.json();
          if (!data.task) {
            appendOutput("🎉 All roadmap tasks are complete!\n");
            return;
          }
          _workOnTask(data.task.id, data.task.title, data.task.description || "");
        } catch (e) {
          appendOutput(`Error fetching next task: ${e.message}\n`);
        }
      });
    }

    // "Auto-Build Next" button (t13-3)
    const autoBuildBtn = $("btn-roadmap-auto-build");
    if (autoBuildBtn) {
      autoBuildBtn.addEventListener("click", () => {
        if (!confirm("Start autonomous self-build? The agent will generate code, run tests, and commit automatically.")) return;
        switchOutputTab("output");
        appendOutput("🤖 Starting autonomous self-build…\n");
        _startSelfBuild("");
      });
    }
  }

  function _workOnTask(taskId, title, description) {
    const prompt =
      `You are implementing a task from the Arbiter roadmap.\n\n` +
      `Task: ${title}\n` +
      (description ? `Description: ${description}\n\n` : "\n") +
      `Please implement this task now. Make the required code changes, ` +
      `create any new files needed, and explain what you did.`;
    sendPrompt(prompt);
    // Mark task in_progress
    const pathSuffix = state.activeProject ? `?path=${encodeURIComponent(state.activeProject)}` : "";
    fetch(`/roadmap/task/${taskId}${pathSuffix}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "in_progress" }),
    }).catch(() => {});
    switchOutputTab("output");
  }

  // ── Autonomous self-build via WebSocket (t13-3) ────────────────────────────
  let _selfBuildWs = null;

  function _startSelfBuild(taskId) {
    if (_selfBuildWs && _selfBuildWs.readyState === WebSocket.OPEN) {
      appendOutput("⚠️ Self-build already running.\n");
      return;
    }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    _selfBuildWs = new WebSocket(`${proto}://${location.host}/ws/self-build`);
    _selfBuildWs.onopen = () => {
      _selfBuildWs.send(JSON.stringify({ task_id: taskId }));
    };
    _selfBuildWs.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "log") appendOutput(msg.data);
        else if (msg.type === "done") {
          appendOutput("✅ Self-build complete.\n");
          loadRoadmapPanel();  // refresh roadmap
        } else if (msg.type === "error") {
          appendOutput(`❌ Self-build error: ${msg.data}\n`);
        }
      } catch (e) { appendOutput(ev.data); }
    };
    _selfBuildWs.onerror = () => appendOutput("❌ Self-build WebSocket error.\n");
    _selfBuildWs.onclose = () => { _selfBuildWs = null; };
  }

  // ── Model download panel (t11-7) ───────────────────────────────────────────

  async function loadModelsPanel() {
    const container = $("models-panel-content");
    if (!container) return;
    container.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px">Loading…</div>';
    try {
      const res = await fetch("/models/list");
      const data = await res.json();
      const models = data.models || [];
      let html = `<div style="padding:8px">
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:8px">
          One-click download for recommended open-source models via Ollama.
        </div>`;
      for (const m of models) {
        const badge = m.installed
          ? `<span style="color:#22c55e;font-size:11px">✓ installed</span>`
          : `<span style="color:var(--text-dim);font-size:11px">${m.size_gb} GB</span>`;
        html += `<div class="model-card" style="border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:600;font-size:13px">${escHtmlSimple(m.label)}</span>
            ${badge}
          </div>
          <div style="font-size:11px;color:var(--text-dim);margin:4px 0">${escHtmlSimple(m.description)}</div>
          <div style="display:flex;gap:6px;margin-top:4px">
            ${!m.installed ? `<button class="model-dl-btn" data-name="${escHtmlSimple(m.name)}" style="font-size:11px;padding:2px 8px">⬇ Download</button>` : ""}
            <code style="font-size:10px;color:var(--text-dim);flex:1;overflow:hidden;text-overflow:ellipsis">${escHtmlSimple(m.pull)}</code>
          </div>
          <div id="model-dl-status-${escHtmlSimple(m.name)}" style="font-size:11px;margin-top:4px"></div>
        </div>`;
      }
      html += "</div>";
      container.innerHTML = html;
      container.querySelectorAll(".model-dl-btn").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          btn.disabled = true;
          btn.textContent = "⏳ Starting…";
          const statusEl = $(`model-dl-status-${name}`);
          try {
            const r = await fetch("/models/download", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ model_name: name, backend: "ollama" }),
            });
            const d = await r.json();
            if (d.job_id) {
              btn.textContent = "⏳ Downloading…";
              _pollModelDownload(d.job_id, name, statusEl, btn);
            } else {
              if (statusEl) statusEl.textContent = "Error: " + JSON.stringify(d);
              btn.disabled = false;
              btn.textContent = "⬇ Download";
            }
          } catch (e) {
            if (statusEl) statusEl.textContent = "Error: " + e.message;
            btn.disabled = false;
            btn.textContent = "⬇ Download";
          }
        });
      });
    } catch (e) {
      container.innerHTML = `<div style="color:var(--error,#ef4444);padding:8px">Failed to load models: ${e.message}</div>`;
    }
  }

  function _pollModelDownload(jobId, modelName, statusEl, btn) {
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`/models/download/status?job_id=${encodeURIComponent(jobId)}`);
        const d = await r.json();
        const log = (d.log || []).slice(-3).join(" | ");
        if (statusEl) statusEl.textContent = log || d.status;
        if (d.status === "done") {
          clearInterval(interval);
          if (btn) { btn.textContent = "✓ Done"; btn.style.background = "#22c55e"; }
          appendOutput(`✅ Model '${modelName}' downloaded successfully.\n`);
        } else if (d.status === "error") {
          clearInterval(interval);
          if (btn) { btn.textContent = "❌ Error"; btn.disabled = false; }
        }
      } catch (e) {
        clearInterval(interval);
      }
    }, 2000);
  }

  // ── Chat history persistence (t10-5) ─────────────────────────────────────

  async function loadChatHistory(projectPath) {
    try {
      const url = projectPath ? `/chat/history?project_path=${encodeURIComponent(projectPath)}&limit=50` : "/chat/history?limit=50";
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const messages = data.messages || [];
      if (!messages.length) return;
      appendOutput(`\n── Loaded ${messages.length} messages from chat history ──\n`);
    } catch (e) {
      // silently fail — history is optional
    }
  }

  // ── Command palette ────────────────────────────────────────────────────────
  function escHtmlSimple(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const _palette = {
    visible: false,
    mode: "files",    // "files" | "commands"
    items: [],
    activeIdx: 0,
    _fileCache: null,
  };

  const _commands = [
    { icon: "💾", label: "Save File", hint: "Ctrl+S", action: () => saveActiveFile() },
    { icon: "▶", label: "Run Agent on File", hint: "", action: () => runAgentOnFile() },
    { icon: "🔨", label: "Build Project", hint: "", action: () => runBuildOrTest("build") },
    { icon: "🧪", label: "Run Tests", hint: "", action: () => runBuildOrTest("test") },
    { icon: "⬇", label: "Clone Repository", hint: "", action: () => showCloneDialog() },
    { icon: "📥", label: "Import Project", hint: "", action: () => showImportDialog() },
    { icon: "↺", label: "Refresh File Tree", hint: "", action: () => loadFileTree() },
    { icon: "📋", label: "View Roadmap", hint: "", action: () => switchOutputTab("roadmap") },
    { icon: "⬛", label: "Open Terminal", hint: "", action: () => switchOutputTab("terminal") },
    { icon: "🔍", label: "Search Files", hint: "", action: () => { /* handled by searchbox */ } },
    { icon: "✕", label: "Clear Output", hint: "", action: () => {
      clearOutput();
      buildContent.textContent = "";
      problemsContent.innerHTML = "";
    }},
  ];

  async function _paletteGetFiles() {
    if (_palette._fileCache) return _palette._fileCache;
    const results = [];
    const roots = ["workspace", "projects"];
    for (const root of roots) {
      try {
        await _walkForPalette(root, results, 4);
      } catch { /* ignore */ }
    }
    _palette._fileCache = results;
    // Cache invalidates after 30s
    setTimeout(() => { _palette._fileCache = null; }, 30000);
    return results;
  }

  async function _walkForPalette(path, results, depth) {
    if (depth <= 0 || results.length > 500) return;
    const res = await fetch(`/files?path=${encodeURIComponent(path)}`);
    if (!res.ok) return;
    const data = await res.json();
    for (const e of (data.entries || [])) {
      const fullPath = `${path}/${e.name}`;
      if (e.type === "file") results.push(fullPath);
      else if (e.type === "dir" && !e.name.startsWith(".")) await _walkForPalette(fullPath, results, depth - 1);
    }
  }

  function openPalette(mode) {
    _palette.mode = mode;
    _palette.visible = true;
    _palette._fileCache = null;
    const overlay = $("cmd-palette");
    const input = $("cmd-palette-input");
    overlay.classList.remove("hidden");
    input.value = "";
    input.placeholder = mode === "commands" ? "Type a command…" : "Type a file name…";
    input.focus();
    _renderPalette("");
  }

  function closePalette() {
    _palette.visible = false;
    $("cmd-palette").classList.add("hidden");
  }

  async function _renderPalette(query) {
    const list = $("cmd-palette-list");
    list.innerHTML = '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">Loading…</div>';
    _palette.activeIdx = 0;

    if (_palette.mode === "commands") {
      const filtered = _commands.filter((c) =>
        !query || c.label.toLowerCase().includes(query.toLowerCase())
      );
      _palette.items = filtered;
      list.innerHTML = filtered.length
        ? filtered.map((c, i) => `<div class="palette-item${i === 0 ? " active" : ""}" data-idx="${i}">
            <span class="palette-item-icon">${c.icon}</span>
            <span class="palette-item-label">${c.label}</span>
            <span class="palette-item-hint">${c.hint}</span>
          </div>`).join("")
        : '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">No commands match.</div>';
    } else {
      const files = await _paletteGetFiles();
      const lq = query.toLowerCase();
      const filtered = query
        ? files.filter((f) => f.toLowerCase().includes(lq)).slice(0, 50)
        : files.slice(0, 50);
      _palette.items = filtered;
      list.innerHTML = filtered.length
        ? filtered.map((f, i) => {
            const parts = f.split("/");
            const name = parts.pop();
            const dir = parts.join("/");
            return `<div class="palette-item${i === 0 ? " active" : ""}" data-idx="${i}">
              <span class="palette-item-icon">📄</span>
              <span class="palette-item-label">${escHtmlSimple(name)}</span>
              <span class="palette-item-hint">${escHtmlSimple(dir)}</span>
            </div>`;
          }).join("")
        : '<div style="padding:10px 16px;color:var(--text-dim);font-size:12px">No files found.</div>';
    }

    // Bind click handlers
    list.querySelectorAll(".palette-item").forEach((el) => {
      el.addEventListener("click", () => _paletteActivateIdx(Number(el.dataset.idx)));
    });
  }

  function _paletteActivateIdx(idx) {
    _palette.activeIdx = idx;
    if (_palette.mode === "commands") {
      const cmd = _palette.items[idx];
      if (cmd) { closePalette(); cmd.action(); }
    } else {
      const file = _palette.items[idx];
      if (file) { closePalette(); openFile(file); }
    }
  }

  function _paletteMove(delta) {
    const list = $("cmd-palette-list");
    const items = list.querySelectorAll(".palette-item");
    if (!items.length) return;
    items[_palette.activeIdx]?.classList.remove("active");
    _palette.activeIdx = Math.max(0, Math.min(items.length - 1, _palette.activeIdx + delta));
    items[_palette.activeIdx]?.classList.add("active");
    items[_palette.activeIdx]?.scrollIntoView({ block: "nearest" });
  }

  $("cmd-palette-input").addEventListener("input", (e) => {
    _renderPalette(e.target.value);
  });

  $("cmd-palette-input").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closePalette(); e.preventDefault(); }
    else if (e.key === "ArrowDown") { _paletteMove(1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { _paletteMove(-1); e.preventDefault(); }
    else if (e.key === "Enter") { _paletteActivateIdx(_palette.activeIdx); e.preventDefault(); }
  });

  $("cmd-palette").addEventListener("click", (e) => {
    if (e.target === $("cmd-palette")) closePalette();
  });

  // Global keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      if (_palette.visible) closePalette();
      else openPalette("commands");
    } else if (mod && !e.shiftKey && e.key.toLowerCase() === "p") {
      e.preventDefault();
      if (_palette.visible) closePalette();
      else openPalette("files");
    }
  });

  // ── Activity bar panel switching (flat icon-only bar) ────────────────────
  function activatePanel(panel) {
    // Update active icon
    document.querySelectorAll(".ab-icon[data-panel]").forEach((b) => b.classList.remove("active"));
    const activeIcon = document.querySelector(`.ab-icon[data-panel="${panel}"]`);
    if (activeIcon) activeIcon.classList.add("active");
    // Show matching sidebar panel
    document.querySelectorAll(".sb-panel").forEach((p) => p.classList.remove("active"));
    const targetPanel = document.getElementById(
      panel === "roadmap" ? "panel-roadmap-sidebar" : `panel-${panel}`
    );
    if (targetPanel) targetPanel.classList.add("active");
    // Lazy-load panel content when first shown
    if (panel === "git")        loadGitPanel();
    if (panel === "knowledge")  { loadKnowledgePanel(); loadProfilePanel(); loadRulesPanel(); }
    if (panel === "roadmap")    loadRoadmapSidebar();
    if (panel === "plugins")    loadPluginsPanel();
    if (panel === "models")     loadModelsPanel();
    if (panel === "search")     setTimeout(() => $("sb-search-input")?.focus(), 50);
    if (panel === "notes")      loadNotesPanel();
    if (panel === "aibackends") loadAIBackendsPanel();
    if (panel === "agents")     loadAgentsPanel();
    if (panel === "ci")         loadCIPanel();
    if (panel === "docker")     loadDockerPanel();
    if (panel === "deploy")     loadDeployPanel();
    if (panel === "monitor")    loadMonitorPanel();
    if (panel === "database")   loadDatabasePanel();
    if (panel === "vault")      loadVaultPanel();
    if (panel === "webhooks")   loadWebhooksPanel();
    if (panel === "ratelimit")  loadRatelimitPanel();
    if (panel === "events")     loadEventsPanel();
    if (panel === "cron")       loadCronPanel();
    if (panel === "audit")      loadAuditPanel();
    if (panel === "flags")      loadFlagsPanel();
    if (panel === "cfgprofile") loadCfgProfilePanel();
    if (panel === "notify")     loadNotifyPanel();
    if (panel === "taskqueue")  loadTaskQueuePanel();
    if (panel === "brainstorm") loadBrainstormPanel();
    if (panel === "snippets")   loadSnippetsPanel();
    if (panel === "aitimeline") loadTimelinePanel();
    if (panel === "healthdash") loadHealthPanel();
    if (panel === "testrunner") loadTestRunnerPanel();
    if (panel === "terminal")   loadTerminalPanel();
  }

  document.querySelectorAll(".ab-icon[data-panel]").forEach((btn) => {
    btn.addEventListener("click", () => activatePanel(btn.dataset.panel));
  });

  // Overflow panel menu
  const abMoreBtn = $("btn-ab-more");
  const abOverflow = $("ab-overflow-menu");
  if (abMoreBtn && abOverflow) {
    abMoreBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      abOverflow.classList.toggle("hidden");
    });
    document.addEventListener("click", () => abOverflow.classList.add("hidden"));
    abOverflow.querySelectorAll(".ab-ov-item").forEach((item) => {
      item.addEventListener("click", () => {
        const panel = item.dataset.panel;
        abOverflow.classList.add("hidden");
        activatePanel(panel);
      });
    });
  }

  // ── Search panel in sidebar ───────────────────────────────────────────────
  async function runSidebarSearch() {
    const query = $("sb-search-input").value.trim();
    if (!query) return;
    const resultsDiv = $("sb-search-results");
    resultsDiv.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Searching…</div>';
    try {
      const res = await fetch(`/search?q=${encodeURIComponent(query)}&path=workspace&max_results=30`);
      const data = await res.json();
      const results = data.results || [];
      if (!results.length) {
        resultsDiv.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">No results.</div>';
        return;
      }
      resultsDiv.innerHTML = results.map((r) => `
        <div class="search-result-item" data-path="${escHtmlSimple(r.path)}" data-line="${r.line || 1}" style="padding:3px 4px;cursor:pointer;border-radius:3px;margin-bottom:2px;">
          <div style="font-size:11px;font-family:var(--font-mono);color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escHtmlSimple(r.path)}</div>
          <div style="font-size:10px;color:var(--text-dim);font-family:var(--font-mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${r.line ? `L${r.line}: ` : ""}${escHtmlSimple(r.match || "")}</div>
        </div>
      `).join("");
      resultsDiv.querySelectorAll(".search-result-item").forEach((el) => {
        el.addEventListener("mouseenter", () => { el.style.background = "var(--surface2)"; });
        el.addEventListener("mouseleave", () => { el.style.background = ""; });
        el.addEventListener("click", () => {
          openFile(el.dataset.path);
          // Switch to explorer panel to show context
          activatePanel("explorer");
        });
      });
    } catch (e) {
      resultsDiv.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  $("btn-sb-search").addEventListener("click", runSidebarSearch);
  $("sb-search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSidebarSearch();
  });

  // ── Git panel ─────────────────────────────────────────────────────────────
  let _gitCurrentPath = "workspace";

  async function _gitPath() {
    // Use the current project switcher value or "workspace"
    const sw = $("project-switcher");
    const val = sw ? sw.value : "";
    if (val && val !== "") return val;
    const cwd = $("build-cwd-select");
    return cwd ? (cwd.value || "workspace") : "workspace";
  }

  async function loadGitPanel() {
    const path = await _gitPath();
    _gitCurrentPath = path;
    $("git-branch-info").textContent = "Loading…";
    try {
      const res = await fetch(`/git/status?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.error) {
        $("git-branch-info").textContent = "⚠ Not a git repo";
        $("git-staged-list").innerHTML = "";
        $("git-unstaged-list").innerHTML = "";
        $("git-untracked-list").innerHTML = "";
        $("git-log-list").innerHTML = "";
        return;
      }
      renderGitPanel(data);
    } catch (e) {
      $("git-branch-info").textContent = `Error: ${e.message}`;
    }
  }

  function renderGitPanel(data) {
    $("git-branch-info").textContent = `⎇ ${data.branch || "HEAD"}`;

    function makeFileItem(item, isStaged, isUntracked) {
      const div = document.createElement("div");
      div.className = "git-file-item";
      const status = isUntracked ? "?" : (item.status || " ");
      const colorClass = `git-status-${status}`;
      div.innerHTML = `
        <span class="git-status-badge ${colorClass}">${status}</span>
        <span class="git-file-name" title="${escHtmlSimple(isUntracked ? item : item.file)}">${escHtmlSimple(isUntracked ? item : item.file)}</span>
        <button class="git-file-action" title="${isStaged ? "Unstage" : "Stage"}">${isStaged ? "−" : "＋"}</button>
        <button class="git-file-action" title="View diff" data-diff="1">⊿</button>
      `;
      const fileName = isUntracked ? item : item.file;
      div.querySelectorAll(".git-file-action").forEach((btn) => {
        if (btn.dataset.diff) {
          btn.addEventListener("click", () => showGitDiff(_gitCurrentPath, fileName));
        } else {
          btn.addEventListener("click", () => {
            const files = [fileName];
            fetch("/git/stage", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path: _gitCurrentPath, files, unstage: isStaged }),
            }).then(() => loadGitPanel());
          });
        }
      });
      return div;
    }

    const staged = $("git-staged-list");
    staged.innerHTML = "";
    (data.staged || []).forEach((f) => staged.appendChild(makeFileItem(f, true, false)));
    if (!data.staged?.length) staged.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">Nothing staged</div>';

    const unstaged = $("git-unstaged-list");
    unstaged.innerHTML = "";
    (data.unstaged || []).forEach((f) => unstaged.appendChild(makeFileItem(f, false, false)));
    if (!data.unstaged?.length) unstaged.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">Nothing modified</div>';

    const untracked = $("git-untracked-list");
    untracked.innerHTML = "";
    (data.untracked || []).forEach((f) => untracked.appendChild(makeFileItem(f, false, true)));
    if (!data.untracked?.length) untracked.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">No untracked files</div>';

    const log = $("git-log-list");
    log.innerHTML = (data.commits || []).map((c) =>
      `<div class="git-log-item"><span class="git-sha">${escHtmlSimple(c.sha)}</span>${escHtmlSimple(c.message)}</div>`
    ).join("") || '<div style="font-size:11px;color:var(--text-dim);padding:2px 4px">No commits</div>';
  }

  async function showGitDiff(path, file) {
    try {
      const res = await fetch(`/git/diff?path=${encodeURIComponent(path)}&file=${encodeURIComponent(file)}`);
      const data = await res.json();
      const diffText = (data.staged_diff || "") + (data.diff || "");
      $("git-diff-title").textContent = file || "Diff";
      $("git-diff-content").textContent = diffText || "(no diff)";
      $("git-diff-area").classList.remove("hidden");
    } catch (e) {
      appendOutput(`Git diff error: ${e.message}\n`);
    }
  }

  $("btn-git-refresh").addEventListener("click", () => loadGitPanel());

  $("btn-git-stage-all").addEventListener("click", async () => {
    const path = await _gitPath();
    try {
      await fetch("/git/stage", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, files: [], unstage: false }),
      });
      loadGitPanel();
    } catch (e) {
      appendOutput(`Stage all error: ${e.message}\n`);
    }
  });

  $("btn-git-commit").addEventListener("click", async () => {
    const msg = $("git-commit-msg").value.trim();
    if (!msg) { appendOutput("⚠ Please enter a commit message.\n"); return; }
    const path = await _gitPath();
    try {
      const res = await fetch("/git/commit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, message: msg, files: [] }),
      });
      const data = await res.json();
      if (data.detail) throw new Error(data.detail);
      appendOutput(`✅ Committed: ${msg}\n`);
      $("git-commit-msg").value = "";
      loadGitPanel();
    } catch (e) {
      appendOutput(`Commit error: ${e.message}\n`);
    }
  });

  $("btn-git-diff-close").addEventListener("click", () => {
    $("git-diff-area").classList.add("hidden");
  });

  // ── Knowledge panel ────────────────────────────────────────────────────────
  function _kbProjectPath() {
    const sw = $("project-switcher");
    return (sw && sw.value) ? sw.value : "";
  }

  async function loadKnowledgePanel() {
    const path = _kbProjectPath();
    $("kb-source-list").innerHTML = '<div style="color:var(--text-dim);font-size:11px">Loading…</div>';
    try {
      const res = await fetch(`/knowledge/list?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderKbSources(data.sources || []);
    } catch (e) {
      $("kb-source-list").innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${e.message}</div>`;
    }
  }

  function renderKbSources(sources) {
    const list = $("kb-source-list");
    if (!sources.length) {
      list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;font-style:italic">No knowledge sources yet.</div>';
      return;
    }
    list.innerHTML = sources.map((s) => `
      <div class="kb-source-item">
        <span class="kb-label" title="${escHtmlSimple(s.url || s.source_id)}">${escHtmlSimple(s.label || s.url || s.source_id)}</span>
        <span style="color:var(--text-dim);font-size:10px;margin-left:auto;">${s.chunks || 0} chunks</span>
        <button data-source-id="${escHtmlSimple(s.source_id)}" title="Remove source">✕</button>
      </div>
    `).join("");
    list.querySelectorAll("button[data-source-id]").forEach((btn) => {
      btn.addEventListener("click", () => removeKbSource(btn.dataset.sourceId));
    });
  }

  async function removeKbSource(sourceId) {
    const path = _kbProjectPath();
    try {
      await fetch("/knowledge/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: sourceId, project_path: path }),
      });
      loadKnowledgePanel();
    } catch (e) {
      appendOutput(`Remove KB source error: ${e.message}\n`);
    }
  }

  $("btn-kb-add").addEventListener("click", async () => {
    const url = $("kb-add-url").value.trim();
    if (!url) return;
    const path = _kbProjectPath();
    $("btn-kb-add").textContent = "⟳";
    $("btn-kb-add").disabled = true;
    try {
      const res = await fetch("/knowledge/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, project_path: path }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      $("kb-add-url").value = "";
      appendOutput(`📚 Indexed: ${data.label || url} (${data.chunks || 0} chunks)\n`);
      loadKnowledgePanel();
    } catch (e) {
      appendOutput(`KB fetch error: ${e.message}\n`);
    } finally {
      $("btn-kb-add").textContent = "＋";
      $("btn-kb-add").disabled = false;
    }
  });

  $("kb-add-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-kb-add").click();
  });

  $("btn-kb-search").addEventListener("click", async () => {
    const query = $("kb-search-query").value.trim();
    if (!query) return;
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/knowledge/search?query=${encodeURIComponent(query)}&project_path=${encodeURIComponent(path)}&top_k=3`);
      const data = await res.json();
      const results = data.results || [];
      const div = $("kb-search-results");
      if (!results.length) {
        div.innerHTML = '<div style="color:var(--text-dim);font-size:11px">No results found.</div>';
      } else {
        div.innerHTML = results.map((r) => `
          <div class="kb-chunk">
            <div class="kb-chunk-label">${escHtmlSimple(r.source_label || "")}</div>
            <div>${escHtmlSimple((r.text || "").slice(0, 200))}${(r.text || "").length > 200 ? "…" : ""}</div>
          </div>
        `).join("");
      }
    } catch (e) {
      $("kb-search-results").innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${e.message}</div>`;
    }
  });

  $("kb-search-query").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-kb-search").click();
  });

  $("btn-kp-refresh-kb").addEventListener("click", () => loadKnowledgePanel());

  // ── Profile panel ──────────────────────────────────────────────────────────
  async function loadProfilePanel() {
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/profile?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderProfileDisplay(data);
    } catch (_) {
      // No profile yet
    }
  }

  function renderProfileDisplay(profile) {
    const div = $("profile-display");
    if (!profile || (!profile.project_name && !profile.tech_stack?.length)) {
      div.innerHTML = '<div class="profile-empty">No profile set. Click Detect or fill in fields.</div>';
      return;
    }
    const rows = [];
    if (profile.project_name) rows.push(`<div class="pf-row"><span class="pf-key">Name:</span> ${escHtmlSimple(profile.project_name)}</div>`);
    if (profile.tech_stack?.length) rows.push(`<div class="pf-row"><span class="pf-key">Stack:</span> ${escHtmlSimple(profile.tech_stack.join(", "))}</div>`);
    if (profile.llm_backend) rows.push(`<div class="pf-row"><span class="pf-key">LLM:</span> ${escHtmlSimple(profile.llm_backend)}</div>`);
    if (profile.coding_standards) rows.push(`<div class="pf-row"><span class="pf-key">Standards:</span> ${escHtmlSimple(profile.coding_standards)}</div>`);
    div.innerHTML = rows.join("");
    // Populate edit fields
    if (profile.project_name) $("profile-name").value = profile.project_name;
    if (profile.description) $("profile-desc").value = profile.description;
    if (profile.tech_stack?.length) $("profile-stack").value = profile.tech_stack.join(", ");
    if (profile.ai_persona) $("profile-persona").value = profile.ai_persona;
    if (profile.coding_standards) $("profile-standards").value = profile.coding_standards;
  }

  $("btn-profile-detect").addEventListener("click", async () => {
    const path = _kbProjectPath() || "workspace";
    $("btn-profile-detect").textContent = "⟳ Detecting…";
    try {
      const res = await fetch(`/profile/detect?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (data.detected) {
        $("profile-stack").value = (data.tech_stack || []).join(", ");
        if (data.ai_persona) $("profile-persona").value = data.ai_persona;
        appendOutput(`✅ Detected: ${(data.tech_stack || []).join(", ")}\n`);
      } else {
        appendOutput("ℹ Could not auto-detect tech stack for this path.\n");
      }
    } catch (e) {
      appendOutput(`Profile detect error: ${e.message}\n`);
    } finally {
      $("btn-profile-detect").textContent = "⚙ Detect";
    }
  });

  $("btn-profile-save").addEventListener("click", async () => {
    const path = _kbProjectPath();
    const stack = $("profile-stack").value.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const res = await fetch("/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_path: path,
          project_name: $("profile-name").value.trim(),
          description: $("profile-desc").value.trim(),
          tech_stack: stack,
          ai_persona: $("profile-persona").value.trim(),
          coding_standards: $("profile-standards").value.trim(),
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      appendOutput("✅ Profile saved.\n");
      loadProfilePanel();
    } catch (e) {
      appendOutput(`Profile save error: ${e.message}\n`);
    }
  });

  // ── Rules panel ────────────────────────────────────────────────────────────
  async function loadRulesPanel() {
    const path = _kbProjectPath();
    try {
      const res = await fetch(`/rules?project_path=${encodeURIComponent(path)}`);
      const data = await res.json();
      renderRulesList(data.rules || []);
    } catch (_) {
      $("rules-list").innerHTML = "";
    }
  }

  function renderRulesList(rules) {
    const list = $("rules-list");
    if (!rules.length) {
      list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;font-style:italic">No rules yet.</div>';
      return;
    }
    list.innerHTML = rules.map((r) => `
      <div class="rule-item">
        <span class="rule-type rule-type-${r.rule_type}">${r.rule_type.replace("_", " ")}</span>
        <span class="rule-text">${escHtmlSimple(r.rule)}</span>
        <button data-rule-id="${escHtmlSimple(r.id)}" title="Remove rule">✕</button>
      </div>
    `).join("");
    list.querySelectorAll("button[data-rule-id]").forEach((btn) => {
      btn.addEventListener("click", () => removeRule(btn.dataset.ruleId));
    });
  }

  $("btn-rules-add").addEventListener("click", async () => {
    const text = $("rules-add-text").value.trim();
    const type = $("rules-type-select").value;
    if (!text) return;
    const path = _kbProjectPath();
    try {
      await fetch("/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule: text, rule_type: type, project_path: path }),
      });
      $("rules-add-text").value = "";
      loadRulesPanel();
    } catch (e) {
      appendOutput(`Add rule error: ${e.message}\n`);
    }
  });

  $("rules-add-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-rules-add").click();
  });

  async function removeRule(ruleId) {
    const path = _kbProjectPath();
    try {
      await fetch(`/rules/${encodeURIComponent(ruleId)}?project_path=${encodeURIComponent(path)}`, { method: "DELETE" });
      loadRulesPanel();
    } catch (e) {
      appendOutput(`Remove rule error: ${e.message}\n`);
    }
  }

  // ── Roadmap sidebar panel ─────────────────────────────────────────────────
  async function loadRoadmapSidebar() {
    const container = $("roadmap-sidebar-content");
    container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Loading…</div>';
    try {
      const pathParam = state.activeProject ? `?path=${encodeURIComponent(state.activeProject)}` : "";
      const res = await fetch(`/roadmap${pathParam}`);
      const data = await res.json();
      const statusIcon = { done: "✅", in_progress: "🔄", pending: "⬜", blocked: "🚫" };
      let html = "";
      for (const m of (data.milestones || [])) {
        if (m.status === "done") continue; // hide completed milestones from sidebar
        const tasks = (m.tasks || []).filter((t) => t.status !== "done");
        if (!tasks.length) continue;
        html += `<div class="rsb-milestone">
          <div class="rsb-ms-title">${escHtmlSimple(m.title)}</div>
          ${tasks.map((t) => `
            <div class="rsb-task" data-task-id="${t.id}" data-task-title="${encodeURIComponent(t.title)}" data-task-desc="${encodeURIComponent(t.description || "")}">
              <span class="rsb-status">${statusIcon[t.status] || "⬜"}</span>
              <span class="rsb-title">${escHtmlSimple(t.title)}</span>
            </div>
          `).join("")}
        </div>`;
      }
      container.innerHTML = html || '<div style="color:var(--accent2);font-size:11px;padding:4px">🎉 All tasks complete!</div>';
      container.querySelectorAll(".rsb-task").forEach((el) => {
        el.addEventListener("click", () => {
          const title = decodeURIComponent(el.dataset.taskTitle || "");
          const desc = decodeURIComponent(el.dataset.taskDesc || "");
          _workOnTask(el.dataset.taskId, title, desc);
          switchOutputTab("output");
        });
      });
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  $("btn-roadmap-refresh-sb").addEventListener("click", () => loadRoadmapSidebar());

  $("btn-roadmap-work-next-sb").addEventListener("click", async () => {
    try {
      const res = await fetch("/roadmap/next");
      const data = await res.json();
      if (!data.task) { appendOutput("🎉 All roadmap tasks are complete!\n"); return; }
      _workOnTask(data.task.id, data.task.title, data.task.description || "");
      switchOutputTab("output");
    } catch (e) {
      appendOutput(`Error fetching next task: ${e.message}\n`);
    }
  });

  // ── Plugin browser panel ──────────────────────────────────────────────────
  async function loadPluginsPanel() {
    const list = $("plugins-list");
    list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Loading…</div>';
    try {
      const res = await fetch("/plugins");
      const data = await res.json();
      const plugins = data.plugins || [];
      if (!plugins.length) {
        list.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">No plugins installed.</div>';
        return;
      }
      list.innerHTML = plugins.map((p) => `
        <div class="plugin-item" data-name="${escHtmlSimple(p.name)}">
          <div class="plugin-item-header">
            <span class="plugin-name">${escHtmlSimple(p.name)}</span>
            <span class="plugin-version">v${escHtmlSimple(p.version)}</span>
            <button class="plugin-remove-btn" data-name="${escHtmlSimple(p.name)}" title="Remove plugin">🗑</button>
          </div>
          <div class="plugin-desc">${escHtmlSimple(p.description || "")}</div>
          ${p.author ? `<div class="plugin-author">by ${escHtmlSimple(p.author)}</div>` : ""}
        </div>
      `).join("");
      list.querySelectorAll(".plugin-remove-btn").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          const name = e.currentTarget.dataset.name;
          if (!confirm(`Remove plugin '${name}'?`)) return;
          try {
            const r = await fetch(`/plugins/${encodeURIComponent(name)}`, { method: "DELETE" });
            const d = await r.json();
            if (d.status === "removed") {
              appendOutput(`Plugin '${name}' removed.\n`);
              loadPluginsPanel();
            } else {
              appendOutput(`Error removing plugin: ${JSON.stringify(d)}\n`);
            }
          } catch (err) {
            appendOutput(`Remove plugin error: ${err.message}\n`);
          }
        });
      });
    } catch (e) {
      list.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  $("btn-plugins-reload").addEventListener("click", async () => {
    try {
      await fetch("/plugins/reload", { method: "POST" });
      loadPluginsPanel();
    } catch (e) {
      appendOutput(`Plugin reload error: ${e.message}\n`);
    }
  });

  $("btn-plugin-install").addEventListener("click", async () => {
    const url = $("plugin-install-url").value.trim();
    const status = $("plugin-install-status");
    if (!url) { status.textContent = "Please enter a URL."; return; }
    status.textContent = "Installing…";
    try {
      const res = await fetch("/plugins/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.status === "installed" || data.status === "already_installed") {
        status.style.color = "var(--accent2)";
        status.textContent = `✓ ${data.status === "already_installed" ? "Already installed" : "Installed"}: ${data.plugin}`;
        $("plugin-install-url").value = "";
        loadPluginsPanel();
      } else {
        status.style.color = "var(--danger)";
        status.textContent = `Error: ${data.detail || JSON.stringify(data)}`;
      }
    } catch (e) {
      status.style.color = "var(--danger)";
      status.textContent = `Error: ${e.message}`;
    }
  });

  $("btn-plugin-gen").addEventListener("click", async () => {
    const name = $("plugin-gen-name").value.trim();
    const desc = $("plugin-gen-desc").value.trim();
    const status = $("plugin-gen-status");
    if (!name || !desc) { status.textContent = "Name and description are required."; return; }
    status.style.color = "var(--text-dim)";
    status.textContent = "Generating…";
    try {
      const res = await fetch("/plugins/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: desc, llm_backend: state.llmBackend || "" }),
      });
      const data = await res.json();
      if (data.status === "created") {
        status.style.color = "var(--accent2)";
        status.textContent = `✓ Created plugin '${data.plugin}' (${data.tools_count} tool(s))`;
        $("plugin-gen-name").value = "";
        $("plugin-gen-desc").value = "";
        loadPluginsPanel();
        appendOutput(`Plugin '${data.plugin}' generated at ${data.path}\nFiles: ${(data.files || []).join(", ")}\n`);
      } else {
        status.style.color = "var(--danger)";
        status.textContent = `Error: ${data.error || data.detail || JSON.stringify(data)}`;
      }
    } catch (e) {
      status.style.color = "var(--danger)";
      status.textContent = `Error: ${e.message}`;
    }
  });

  // ── Scaffold panel ────────────────────────────────────────────────────────
  $("btn-scaffold-mod").addEventListener("click", async () => {
    const name = $("scaffold-mod-name").value.trim();
    const desc = $("scaffold-mod-desc").value.trim();
    const result = $("scaffold-mod-result");
    if (!name || !desc) { result.textContent = "Name and description are required."; result.style.color = "var(--danger)"; return; }
    result.style.color = "var(--text-dim)";
    result.textContent = "Generating…";
    try {
      const res = await fetch("/scaffold/module", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: desc }),
      });
      const data = await res.json();
      if (data.status === "created") {
        result.style.color = "var(--accent2)";
        result.textContent = `✓ Module '${data.module}' created (${data.tools_count} tool(s))`;
        $("scaffold-mod-name").value = "";
        $("scaffold-mod-desc").value = "";
        appendOutput(`Module '${data.module}' generated at ${data.path}\nFiles: ${(data.files || []).join(", ")}\n`);
        loadFileTree();
      } else {
        result.style.color = "var(--danger)";
        result.textContent = `Error: ${data.error || data.detail || JSON.stringify(data)}`;
      }
    } catch (e) {
      result.style.color = "var(--danger)";
      result.textContent = `Error: ${e.message}`;
    }
  });

  $("btn-scaffold-plugin").addEventListener("click", async () => {
    const name = $("scaffold-plugin-name").value.trim();
    const desc = $("scaffold-plugin-desc").value.trim();
    const result = $("scaffold-plugin-result");
    if (!name || !desc) { result.textContent = "Name and description are required."; result.style.color = "var(--danger)"; return; }
    result.style.color = "var(--text-dim)";
    result.textContent = "Generating…";
    try {
      const res = await fetch("/scaffold/plugin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: desc }),
      });
      const data = await res.json();
      if (data.status === "created") {
        result.style.color = "var(--accent2)";
        result.textContent = `✓ Plugin '${data.plugin}' created (${data.tools_count} tool(s))`;
        $("scaffold-plugin-name").value = "";
        $("scaffold-plugin-desc").value = "";
        appendOutput(`Plugin '${data.plugin}' generated at ${data.path}\nFiles: ${(data.files || []).join(", ")}\n`);
        loadPluginsPanel();
      } else {
        result.style.color = "var(--danger)";
        result.textContent = `Error: ${data.error || data.detail || JSON.stringify(data)}`;
      }
    } catch (e) {
      result.style.color = "var(--danger)";
      result.textContent = `Error: ${e.message}`;
    }
  });

  $("btn-scaffold-tests").addEventListener("click", async () => {
    const name = $("scaffold-test-name").value.trim();
    const result = $("scaffold-test-result");
    if (!name) { result.textContent = "Module/plugin name is required."; result.style.color = "var(--danger)"; return; }
    result.style.color = "var(--text-dim)";
    result.textContent = "Generating…";
    try {
      const res = await fetch("/scaffold/tests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ module_name: name }),
      });
      const data = await res.json();
      if (data.status === "created") {
        result.style.color = "var(--accent2)";
        result.textContent = `✓ Tests created: ${data.test_file} (${data.tests_count} stub(s))`;
        $("scaffold-test-name").value = "";
        appendOutput(`Tests generated: ${data.test_file}\n`);
        loadFileTree();
      } else {
        result.style.color = "var(--danger)";
        result.textContent = `Error: ${data.error || data.detail || JSON.stringify(data)}`;
      }
    } catch (e) {
      result.style.color = "var(--danger)";
      result.textContent = `Error: ${e.message}`;
    }
  });

  // ── Split editor ───────────────────────────────────────────────────────────
  let _splitEditor = null;
  let _splitFile = null;
  const _splitFiles = {}; // path → {content, language, model}

  function toggleSplitEditor() {
    const splitEl = $("editor-container-split");
    const btn = $("btn-split-editor");
    const active = !splitEl.classList.contains("hidden");
    if (active) {
      splitEl.classList.add("hidden");
      btn.classList.remove("active");
      if (_splitEditor) { _splitEditor.dispose(); _splitEditor = null; }
    } else {
      splitEl.classList.remove("hidden");
      btn.classList.add("active");
      if (state.editorMode === "monaco" && typeof monaco !== "undefined") {
        _splitEditor = monaco.editor.create($("editor-split-inner"), {
          theme: "arbiter-dark",
          fontSize: 14,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          lineNumbers: "on",
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          automaticLayout: true,
          readOnly: false,
        });
      }
      renderSplitTabs();
    }
  }

  function renderSplitTabs() {
    const list = $("split-tabs-list");
    list.innerHTML = Object.keys(_splitFiles).map((path) => `
      <div class="split-tab ${_splitFile === path ? "active" : ""}" data-path="${escHtmlSimple(path)}">
        <span>${escHtmlSimple(path.split("/").pop())}</span>
        <span style="font-size:10px;opacity:.5;cursor:pointer;" data-close="${escHtmlSimple(path)}">✕</span>
      </div>
    `).join("");
    list.querySelectorAll(".split-tab").forEach((tab) => {
      tab.addEventListener("click", (e) => {
        if (e.target.dataset.close) {
          const p = e.target.dataset.close;
          delete _splitFiles[p];
          if (_splitFile === p) { _splitFile = Object.keys(_splitFiles)[0] || null; }
          renderSplitTabs();
          if (_splitFile) openSplitFile(_splitFile);
          return;
        }
        openSplitFile(tab.dataset.path);
      });
    });
  }

  async function openSplitFile(path) {
    const splitEl = $("editor-container-split");
    if (splitEl.classList.contains("hidden")) toggleSplitEditor();
    if (!_splitFiles[path]) {
      try {
        const res = await fetch(`/files/read?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        _splitFiles[path] = { content: data.content || "", language: data.language || "plaintext" };
      } catch (e) {
        appendOutput(`Split editor error: ${e.message}\n`);
        return;
      }
    }
    _splitFile = path;
    if (_splitEditor) {
      const lang = _splitFiles[path].language;
      _splitEditor.setValue(_splitFiles[path].content || "");
      if (typeof monaco !== "undefined") {
        monaco.editor.setModelLanguage(_splitEditor.getModel(), lang);
      }
    }
    renderSplitTabs();
  }

  $("btn-split-editor").addEventListener("click", () => toggleSplitEditor());

  // ── Boot ───────────────────────────────────────────────────────────────────
  initMonaco();
  _refreshProjectSwitcher();
  loadChatHistory("");  // load recent chat history on startup (t10-5)
  appendOutput("Arbiter IDE ready. Open a file or type a prompt to get started.\n");
  appendOutput("Tip: Ctrl+P = file picker  |  Ctrl+Shift+P = command palette  |  Terminal tab = interactive shell\n");
  updateStatusBar();

  // Wire models-refresh button
  const _modelsRefreshBtn = $("btn-models-refresh");
  if (_modelsRefreshBtn) _modelsRefreshBtn.addEventListener("click", () => loadModelsPanel());

  // ── Code Quality panel (t14-1, t14-2, t14-3) ─────────────────────────────
  function _qualityOutput(msg) {
    const el = $("quality-output");
    if (el) el.textContent = msg;
  }

  const btnFmt = $("btn-format-file");
  if (btnFmt) btnFmt.onclick = async () => {
    if (!_currentFile) { _qualityOutput("No file open."); return; }
    const content = _editor ? _editor.getValue() : "";
    const lang = _currentFile.endsWith(".py") ? "python"
               : _currentFile.endsWith(".json") ? "json"
               : _currentFile.endsWith(".js") || _currentFile.endsWith(".ts") ? "javascript"
               : "other";
    _qualityOutput("Formatting…");
    try {
      const r = await fetch("/format", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, language: lang, path: _currentFile }),
      });
      const d = await r.json();
      if (!r.ok) { _qualityOutput("Error: " + (d.detail || r.status)); return; }
      if (d.changed && _editor) {
        _editor.setValue(d.formatted);
        _qualityOutput(`✅ Formatted with ${d.tool}. File updated.`);
      } else {
        _qualityOutput(`✅ Already formatted (${d.tool}). No changes.`);
      }
    } catch(e) { _qualityOutput("Error: " + e); }
  };

  const btnLint = $("btn-lint-file");
  if (btnLint) btnLint.onclick = async () => {
    if (!_currentFile) { _qualityOutput("No file open."); return; }
    const content = _editor ? _editor.getValue() : "";
    const lang = _currentFile.endsWith(".py") ? "python" : "other";
    _qualityOutput("Linting…");
    try {
      const r = await fetch("/lint", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, language: lang, path: _currentFile }),
      });
      const d = await r.json();
      if (!r.ok) { _qualityOutput("Error: " + (d.detail || r.status)); return; }
      if (d.diagnostics.length === 0) {
        _qualityOutput(`✅ No issues found (${d.tool}).`);
      } else {
        _qualityOutput(d.diagnostics.map(x => `L${x.line}:${x.col} [${x.code}] ${x.message}`).join("\n"));
      }
    } catch(e) { _qualityOutput("Error: " + e); }
  };

  const btnStats = $("btn-workspace-stats");
  if (btnStats) btnStats.onclick = async () => {
    _qualityOutput("Loading stats…");
    try {
      const r = await fetch("/stats");
      const d = await r.json();
      if (!r.ok) { _qualityOutput("Error: " + (d.detail || r.status)); return; }
      const lines = [
        `Total files : ${d.total_files}`,
        `Total lines : ${d.total_lines.toLocaleString()}`,
        "",
        "Language breakdown:",
        ...d.breakdown.map(b => `  ${b.language.padEnd(16)} ${b.files} files  ${b.lines.toLocaleString()} lines`),
      ];
      _qualityOutput(lines.join("\n"));
    } catch(e) { _qualityOutput("Error: " + e); }
  };

  // ── Templates & Toolchain panel (Phase 15) ────────────────────────────────
  let _selectedTemplate = null;

  function _tmplOut(msg) { const el = $("toolchain-output"); if (el) el.textContent = msg; }
  function _snippetOut(msg) { const el = $("snippet-output"); if (el) el.textContent = msg; }

  // Detect toolchain
  const btnToolchain = $("btn-detect-toolchain");
  if (btnToolchain) btnToolchain.onclick = async () => {
    _tmplOut("Detecting…");
    try {
      const r = await fetch("/toolchain");
      const d = await r.json();
      if (!r.ok) { _tmplOut("Error: " + (d.detail || r.status)); return; }
      if (d.toolchain.length === 0) {
        _tmplOut("No toolchains detected.");
      } else {
        _tmplOut(d.toolchain.map(t => `✅ ${t.label.padEnd(18)} ${t.version}`).join("\n"));
      }
    } catch(e) { _tmplOut("Error: " + e); }
  };

  // List templates
  async function _loadTemplates() {
    const listEl = $("templates-list");
    if (!listEl) return;
    listEl.innerHTML = '<span style="color:var(--text-muted,#888);font-size:11px">Loading…</span>';
    try {
      const r = await fetch("/templates");
      const d = await r.json();
      if (!r.ok || !d.templates.length) {
        listEl.innerHTML = '<span style="color:var(--text-muted,#888);font-size:11px">No templates found.</span>';
        return;
      }
      listEl.innerHTML = "";
      d.templates.forEach(t => {
        const row = document.createElement("div");
        row.style.cssText = "padding:4px 2px;cursor:pointer;border-radius:3px;font-size:11px";
        row.textContent = `📦 ${t.name} — ${t.description || "no description"}`;
        row.dataset.name = t.name;
        row.onclick = () => {
          document.querySelectorAll("#templates-list div").forEach(x => x.style.background = "");
          row.style.background = "var(--accent-bg,#264f78)";
          _selectedTemplate = t.name;
        };
        listEl.appendChild(row);
      });
    } catch(e) {
      listEl.innerHTML = '<span style="color:#f44">Error loading templates.</span>';
    }
  }

  const btnListTemplates = $("btn-list-templates");
  if (btnListTemplates) btnListTemplates.onclick = _loadTemplates;

  // Apply template
  const btnApplyTemplate = $("btn-apply-template");
  if (btnApplyTemplate) btnApplyTemplate.onclick = async () => {
    const dest = ($("tmpl-apply-dest") || {}).value || "";
    if (!_selectedTemplate) { _tmplOut("Select a template first."); return; }
    if (!dest.trim()) { _tmplOut("Enter a destination folder name."); return; }
    _tmplOut("Applying template…");
    try {
      const r = await fetch("/templates/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: _selectedTemplate, dest: dest.trim(), context: {} }),
      });
      const d = await r.json();
      if (!r.ok) { _tmplOut("Error: " + (d.detail || r.status)); return; }
      _tmplOut(`✅ Template '${d.template}' applied to workspace/${d.dest}\n` +
               `Files: ${d.files.join(", ") || "(none)"}`);
    } catch(e) { _tmplOut("Error: " + e); }
  };

  // Run snippet
  const btnRunSnippet = $("btn-run-snippet");
  if (btnRunSnippet) btnRunSnippet.onclick = async () => {
    const code = ($("snippet-code") || {}).value || "";
    const lang = ($("snippet-lang") || {}).value || "python";
    if (!code.trim()) { _snippetOut("Enter some code first."); return; }
    _snippetOut("Running…");
    try {
      const r = await fetch("/snippet/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language: lang, timeout: 15 }),
      });
      const d = await r.json();
      if (!r.ok) { _snippetOut("Error: " + (d.detail || r.status)); return; }
      const out = [
        d.stdout && `STDOUT:\n${d.stdout}`,
        d.stderr && `STDERR:\n${d.stderr}`,
        `Exit code: ${d.returncode}`,
      ].filter(Boolean).join("\n");
      _snippetOut(out || "(no output)");
    } catch(e) { _snippetOut("Error: " + e); }
  };

  // Auto-load templates when panel is first shown
  const abBtnTemplates = document.querySelector('[data-panel="templates"]');
  if (abBtnTemplates) {
    let _templatesLoaded = false;
    abBtnTemplates.addEventListener("click", () => {
      if (!_templatesLoaded) { _templatesLoaded = true; _loadTemplates(); }
    });
  }

  // ── Utilities panel (Phase 16) ─────────────────────────────────────────────

  async function utilPost(url, body) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return await res.json();
    } catch (e) {
      return { error: e.message };
    }
  }

  function utilOut(data) {
    const el = $("util-output");
    if (!el) return;
    el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  }

  $("btn-util-archive-pack")?.addEventListener("click", async () => {
    const src = ($("util-archive-src")?.value ?? "").trim();
    const dst = ($("util-archive-dst")?.value ?? "").trim();
    const format = $("util-archive-fmt")?.value ?? "zip";
    utilOut("Packing…");
    utilOut(await utilPost("/archive/pack", { src, dst, format }));
  });

  $("btn-util-archive-extract")?.addEventListener("click", async () => {
    const src = ($("util-extract-src")?.value ?? "").trim();
    const dst = ($("util-extract-dst")?.value ?? "").trim();
    utilOut("Extracting…");
    utilOut(await utilPost("/archive/extract", { src, dst }));
  });

  $("btn-util-doc-gen")?.addEventListener("click", async () => {
    const src = ($("util-doc-src")?.value ?? "").trim();
    const output = ($("util-doc-out")?.value ?? "").trim();
    const format = $("util-doc-fmt")?.value ?? "markdown";
    utilOut("Generating docs…");
    utilOut(await utilPost("/doc/generate", { src, output, format }));
  });

  $("btn-util-pkg-install")?.addEventListener("click", async () => {
    const name = ($("util-pkg-name")?.value ?? "").trim();
    const version = ($("util-pkg-version")?.value ?? "").trim();
    const manager = $("util-pkg-mgr")?.value ?? "pip";
    if (!name) return utilOut("Enter a package name.");
    utilOut(`Installing ${name}…`);
    utilOut(await utilPost("/packages/install", { name, version, manager }));
  });

  $("btn-util-pkg-uninstall")?.addEventListener("click", async () => {
    const name = ($("util-pkg-name")?.value ?? "").trim();
    const manager = $("util-pkg-mgr")?.value ?? "pip";
    if (!name) return utilOut("Enter a package name.");
    utilOut(`Uninstalling ${name}…`);
    utilOut(await utilPost("/packages/uninstall", { name, manager }));
  });

  $("btn-util-pkg-list")?.addEventListener("click", async () => {
    const manager = $("util-pkg-mgr")?.value ?? "pip";
    utilOut("Loading…");
    try {
      const res = await fetch(`/packages/list?manager=${manager}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  $("btn-util-img-info")?.addEventListener("click", async () => {
    const path = ($("util-img-path")?.value ?? "").trim();
    if (!path) return utilOut("Enter an image path.");
    try {
      const res = await fetch(`/image/info?path=${encodeURIComponent(path)}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  $("btn-util-img-resize")?.addEventListener("click", async () => {
    const path = ($("util-img-path")?.value ?? "").trim();
    const width = parseInt($("util-img-w")?.value ?? "0") || 0;
    const height = parseInt($("util-img-h")?.value ?? "0") || 0;
    const dst = ($("util-img-dst")?.value ?? "").trim();
    if (!path || !width || !height) return utilOut("Path, width, and height required.");
    utilOut("Resizing…");
    utilOut(await utilPost("/image/resize", { path, width, height, dst }));
  });

  $("btn-util-img-convert")?.addEventListener("click", async () => {
    const path = ($("util-img-path")?.value ?? "").trim();
    const format = ($("util-img-fmt")?.value ?? "").trim();
    const dst = ($("util-img-dst")?.value ?? "").trim();
    if (!path || !format) return utilOut("Path and format required.");
    utilOut("Converting…");
    utilOut(await utilPost("/image/convert", { path, format, dst }));
  });

  $("btn-util-audio-info")?.addEventListener("click", async () => {
    const path = ($("util-audio-src")?.value ?? "").trim();
    if (!path) return utilOut("Enter an audio path.");
    try {
      const res = await fetch(`/audio/info?path=${encodeURIComponent(path)}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  $("btn-util-audio-convert")?.addEventListener("click", async () => {
    const src = ($("util-audio-src")?.value ?? "").trim();
    const dst = ($("util-audio-dst")?.value ?? "").trim();
    const codec = ($("util-audio-codec")?.value ?? "").trim();
    if (!src || !dst) return utilOut("src and dst required.");
    utilOut("Converting audio…");
    utilOut(await utilPost("/audio/convert", { src, dst, codec }));
  });

  $("btn-util-audio-trim")?.addEventListener("click", async () => {
    const src = ($("util-audio-src")?.value ?? "").trim();
    const dst = ($("util-audio-dst")?.value ?? "").trim();
    const start_ms = parseInt($("util-audio-start")?.value ?? "0") || 0;
    const end_ms = parseInt($("util-audio-end")?.value ?? "-1") || -1;
    if (!src || !dst) return utilOut("src and dst required.");
    utilOut("Trimming audio…");
    utilOut(await utilPost("/audio/trim", { src, dst, start_ms, end_ms }));
  });

  $("btn-util-debug-process")?.addEventListener("click", async () => {
    const pid = parseInt($("util-debug-pid")?.value ?? "0") || 0;
    if (!pid) return utilOut("Enter a process ID.");
    try {
      const res = await fetch(`/debug/process?pid=${pid}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  $("btn-util-debug-memory")?.addEventListener("click", async () => {
    const pid = parseInt($("util-debug-pid")?.value ?? "0") || 0;
    if (!pid) return utilOut("Enter a process ID.");
    try {
      const res = await fetch(`/debug/memory?pid=${pid}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  $("btn-util-debug-trace")?.addEventListener("click", async () => {
    const pid = parseInt($("util-debug-pid")?.value ?? "0") || 0;
    if (!pid) return utilOut("Enter a process ID.");
    try {
      const res = await fetch(`/debug/trace?pid=${pid}`);
      utilOut(await res.json());
    } catch (e) { utilOut({ error: e.message }); }
  });

  // ── Phase 17: Notes & Task Board ─────────────────────────────────────────

  async function loadNotesPanel() {
    try {
      const [nRes, tRes] = await Promise.all([fetch("/notes"), fetch("/tasks")]);
      const { notes } = await nRes.json();
      const { tasks } = await tRes.json();
      renderNotesList(notes || []);
      renderKanban(tasks || []);
    } catch (e) {
      $("notes-list").textContent = `Error: ${e.message}`;
    }
  }

  function renderNotesList(notes) {
    const el = $("notes-list");
    if (!el) return;
    if (!notes.length) {
      el.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:2px">No notes yet.</div>';
      return;
    }
    el.innerHTML = notes.map((n) => `
      <div class="note-card" data-id="${escHtmlSimple(n.id)}">
        <div class="note-card-title">📄 ${escHtmlSimple(n.title)}</div>
        <div class="note-card-content">${escHtmlSimple(n.content || "")}</div>
        <div class="note-card-actions">
          <button class="btn-note-delete" data-id="${escHtmlSimple(n.id)}">🗑</button>
        </div>
      </div>
    `).join("");
    el.querySelectorAll(".btn-note-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/notes/${btn.dataset.id}`, { method: "DELETE" });
        loadNotesPanel();
      });
    });
  }

  function renderKanban(tasks) {
    const cols = { todo: $("tasks-col-todo"), in_progress: $("tasks-col-in_progress"), done: $("tasks-col-done") };
    Object.values(cols).forEach((c) => { if (c) c.innerHTML = ""; });
    tasks.forEach((t) => {
      const col = cols[t.status] || cols.todo;
      if (!col) return;
      const card = document.createElement("div");
      card.className = "kanban-card";
      card.innerHTML = `
        <div class="kanban-card-title">${escHtmlSimple(t.title)}</div>
        <div class="kanban-card-priority">${escHtmlSimple(t.priority || "")}</div>
        <div style="display:flex;gap:2px;margin-top:3px">
          ${t.status !== "todo" ? `<button class="btn-task-status" data-id="${escHtmlSimple(t.id)}" data-status="todo" style="font-size:9px;padding:1px 3px">←</button>` : ""}
          ${t.status !== "done" ? `<button class="btn-task-status" data-id="${escHtmlSimple(t.id)}" data-status="${t.status === "todo" ? "in_progress" : "done"}" style="font-size:9px;padding:1px 3px">→</button>` : ""}
          <button class="btn-task-delete" data-id="${escHtmlSimple(t.id)}" style="font-size:9px;padding:1px 3px;margin-left:auto">🗑</button>
        </div>
      `;
      col.appendChild(card);
    });
    document.querySelectorAll(".btn-task-status").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/tasks/${btn.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: btn.dataset.status }),
        });
        loadNotesPanel();
      });
    });
    document.querySelectorAll(".btn-task-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/tasks/${btn.dataset.id}`, { method: "DELETE" });
        loadNotesPanel();
      });
    });
  }

  $("btn-notes-add")?.addEventListener("click", async () => {
    const title = $("notes-new-title")?.value.trim();
    if (!title) return;
    await fetch("/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    $("notes-new-title").value = "";
    loadNotesPanel();
  });

  $("btn-tasks-add")?.addEventListener("click", async () => {
    const title = $("tasks-new-title")?.value.trim();
    if (!title) return;
    await fetch("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, status: "todo" }),
    });
    $("tasks-new-title").value = "";
    loadNotesPanel();
  });

  $("btn-notes-refresh")?.addEventListener("click", () => loadNotesPanel());

  // ── Phase 19: Refactor panel ─────────────────────────────────────────────

  async function runRefactorFindReplace(dryRun) {
    const find = $("refactor-find")?.value || "";
    const replace = $("refactor-replace")?.value || "";
    const glob_pattern = $("refactor-glob")?.value || "**/*";
    const is_regex = $("refactor-regex")?.checked || false;
    if (!find) return;
    try {
      const res = await fetch("/refactor/find-replace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ find, replace, glob_pattern, is_regex, dry_run: dryRun }),
      });
      const data = await res.json();
      const el = $("refactor-results");
      if (!el) return;
      if (data.detail) { el.textContent = `Error: ${data.detail}`; return; }
      const matches = data.matches || [];
      if (!matches.length) { el.textContent = "No matches found."; return; }
      el.innerHTML = matches.slice(0, 50).map((m) => `
        <div class="refactor-match">
          <span class="refactor-match-file">${escHtmlSimple(m.file)}:${m.line}</span><br>
          <span class="refactor-match-before">- ${escHtmlSimple(m.before)}</span><br>
          ${m.after !== m.before ? `<span class="refactor-match-after">+ ${escHtmlSimple(m.after)}</span>` : ""}
        </div>
      `).join("") + (matches.length > 50 ? `<div style="color:var(--text-dim)">(${matches.length - 50} more…)</div>` : "");
      if (!dryRun) el.insertAdjacentHTML("afterbegin", `<div style="color:var(--ok)">✅ Applied to ${data.files_changed} file(s)</div>`);
    } catch (e) {
      const el = $("refactor-results");
      if (el) el.textContent = `Error: ${e.message}`;
    }
  }

  $("btn-refactor-preview")?.addEventListener("click", () => runRefactorFindReplace(true));
  $("btn-refactor-apply")?.addEventListener("click", () => runRefactorFindReplace(false));

  $("btn-refactor-rename")?.addEventListener("click", async () => {
    const old_name = $("refactor-old-name")?.value.trim();
    const new_name = $("refactor-new-name")?.value.trim();
    const glob_pattern = $("refactor-rename-glob")?.value || "**/*";
    if (!old_name || !new_name) return;
    try {
      const res = await fetch("/refactor/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old_name, new_name, glob_pattern }),
      });
      const data = await res.json();
      const el = $("refactor-rename-results");
      if (!el) return;
      if (data.detail) { el.textContent = `Error: ${data.detail}`; return; }
      const changes = data.changes || [];
      if (!changes.length) { el.textContent = "No occurrences found."; return; }
      el.innerHTML = `<div style="color:var(--ok)">✅ Renamed in ${changes.length} file(s):</div>` +
        changes.map((c) => `<div>${escHtmlSimple(c.file)} (${c.count}x)</div>`).join("");
    } catch (e) {
      const el = $("refactor-rename-results");
      if (el) el.textContent = `Error: ${e.message}`;
    }
  });

  // ── AI Backends panel ────────────────────────────────────────────────────

  async function loadAIBackendsPanel() {
    const container = $("aibackends-panel-content");
    if (!container) return;
    container.innerHTML = '<div style="color:var(--text-muted,#888);font-size:11px;padding:4px">Loading…</div>';
    try {
      const res = await fetch("/ai/backends");
      const data = await res.json();
      renderAIBackendsPanel(data);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderAIBackendsPanel(data) {
    const container = $("aibackends-panel-content");
    if (!container) return;
    const active = data.active || "";
    const backends = data.backends || [];

    const LOCAL_BACKENDS = new Set(["ollama", "openwebui", "lmstudio", "llamacpp", "localai", "tabby", "local"]);
    const FREE_BACKENDS  = new Set(["gemini"]);

    const statusDot = (s) => {
      if (s === "ok") return '<span class="backend-dot backend-dot-ok"></span>';
      if (s === "no_key") return '<span class="backend-dot backend-dot-warn"></span>';
      return '<span class="backend-dot backend-dot-off"></span>';
    };

    const localBadge = (name) => LOCAL_BACKENDS.has(name)
      ? '<span class="backend-badge-local">🟢 LOCAL</span>' : "";
    const freeBadge = (name) => FREE_BACKENDS.has(name)
      ? '<span class="backend-badge-free">🔵 FREE</span>' : "";

    // Fields to configure per backend
    const configFields = (b) => {
      const hasUrl = !["anthropic", "gemini"].includes(b.name) && b.name !== "local";
      const hasKey = ["api", "openwebui", "anthropic", "gemini", "tabby", "localai"].includes(b.name);
      const hasModel = b.name !== "local";
      return `<div class="backend-configure-form" id="cfg-form-${b.name}">
        ${hasUrl ? `<label>Base URL</label><input id="cfg-url-${b.name}" placeholder="${b.base_url || "http://..."}" value="${escHtmlSimple(b.base_url || "")}" />` : ""}
        ${hasKey ? `<label>API Key</label><input id="cfg-key-${b.name}" type="password" placeholder="sk-…" />` : ""}
        ${hasModel ? `<label>Model</label><input id="cfg-model-${b.name}" placeholder="e.g. llama3, gpt-4o…" value="${escHtmlSimple(b.model || "")}" />` : ""}
        <button class="backend-configure-save" data-backend="${b.name}">💾 Save</button>
        <div id="cfg-result-${b.name}" style="font-size:10px;min-height:14px"></div>
      </div>`;
    };

    const cards = backends.map((b) => `
      <div class="backend-card${b.name === active ? " backend-card-active" : ""}">
        <div class="backend-card-header">
          ${statusDot(b.status)}
          <span class="backend-card-name">${escHtmlSimple(b.display_name)}</span>
          ${b.name === active ? '<span class="backend-active-badge">active</span>' : ""}
          ${localBadge(b.name)}${freeBadge(b.name)}
        </div>
        <div class="backend-card-meta">${escHtmlSimple(b.description)}</div>
        ${b.model ? `<div class="backend-card-model">Model: ${escHtmlSimple(b.model)}</div>` : ""}
        <div class="backend-card-actions">
          <button class="backend-btn" data-action="test"      data-backend="${escHtmlSimple(b.name)}">Test</button>
          <button class="backend-btn backend-btn-switch" data-action="switch" data-backend="${escHtmlSimple(b.name)}"${b.name === active ? " disabled" : ""}>Switch</button>
          <button class="backend-btn" data-action="configure" data-backend="${escHtmlSimple(b.name)}">⚙ Config</button>
        </div>
        <div class="backend-test-result" id="backend-result-${escHtmlSimple(b.name)}"></div>
        ${configFields(b)}
      </div>
    `).join("");

    container.innerHTML = `
      <div style="font-size:11px;margin-bottom:8px;color:var(--text-dim,#999)">
        Active: <strong style="color:var(--accent)">${escHtmlSimple(active)}</strong>
        &nbsp;·&nbsp; 🟢 = local/free &nbsp;·&nbsp; 🔵 = free tier
      </div>
      ${cards}
    `;

    // Hide all configure forms initially
    container.querySelectorAll(".backend-configure-form").forEach((f) => {
      f.style.display = "none";
    });

    // Test buttons
    container.querySelectorAll(".backend-btn[data-action='test']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.backend;
        const resultEl = $(`backend-result-${name}`);
        if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-muted);font-size:10px">Testing…</span>';
        try {
          const res = await fetch("/ai/backends/test", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ backend: name }),
          });
          const d = await res.json();
          if (resultEl) {
            const color = d.ok ? "var(--ok,#4caf50)" : "var(--danger,#f44)";
            const models = d.models && d.models.length ? `<br>${d.models.slice(0, 5).map(escHtmlSimple).join(", ")}` : "";
            resultEl.innerHTML = `<span style="color:${color};font-size:10px">${d.ok ? "✅" : "❌"} ${escHtmlSimple(d.message)}${models}</span>`;
          }
        } catch (e) {
          if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger);font-size:10px">Error: ${e.message}</span>`;
        }
      });
    });

    // Switch buttons
    container.querySelectorAll(".backend-btn[data-action='switch']").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.backend;
        try {
          const res = await fetch("/ai/backends/switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ backend: name }),
          });
          const d = await res.json();
          if (d.ok) {
            // Also update the topbar selector
            const sel = $("llm-backend-select");
            if (sel) sel.value = name;
            await loadAIBackendsPanel();
          }
        } catch (e) {
          alert(`Switch failed: ${e.message}`);
        }
      });
    });

    // Configure toggle buttons
    container.querySelectorAll(".backend-btn[data-action='configure']").forEach((btn) => {
      btn.addEventListener("click", () => {
        const name = btn.dataset.backend;
        const form = document.getElementById(`cfg-form-${name}`);
        if (form) form.style.display = form.style.display === "none" ? "flex" : "none";
      });
    });

    // Save config buttons
    container.querySelectorAll(".backend-configure-save").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.backend;
        const urlEl   = document.getElementById(`cfg-url-${name}`);
        const keyEl   = document.getElementById(`cfg-key-${name}`);
        const modelEl = document.getElementById(`cfg-model-${name}`);
        const resultEl = document.getElementById(`cfg-result-${name}`);
        const payload = {
          backend: name,
          base_url: urlEl?.value.trim() || "",
          api_key:  keyEl?.value.trim() || "",
          model:    modelEl?.value.trim() || "",
        };
        try {
          const res = await fetch("/ai/backends/configure", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const d = await res.json();
          if (resultEl) resultEl.textContent = d.ok ? "✅ Saved" : `❌ ${d.detail || "Error"}`;
          if (d.ok) setTimeout(() => loadAIBackendsPanel(), 800);
        } catch (e) {
          if (resultEl) resultEl.textContent = `❌ ${e.message}`;
        }
      });
    });
  }

  // ── Phase 22: Multi-Agent Orchestration ──────────────────────────────────

  async function loadAgentsPanel() {
    const container = $("agents-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/agents");
      const data = await res.json();
      renderAgentsPanel(data.agents || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderAgentsPanel(agents) {
    const container = $("agents-panel-content");
    if (!container) return;

    const rows = agents.map((a) => `
      <tr>
        <td style="padding:2px 4px;font-size:11px">${escHtmlSimple(a.name)}</td>
        <td style="padding:2px 4px;font-size:11px">${escHtmlSimple(a.role)}</td>
        <td style="padding:2px 4px;font-size:11px">${escHtmlSimple(a.status)}</td>
        <td style="padding:2px 4px">
          <input class="agent-task-input" data-name="${escHtmlSimple(a.name)}" style="width:80px;padding:2px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:10px" placeholder="task…" />
          <button class="btn-agent-run" data-name="${escHtmlSimple(a.name)}" style="font-size:10px;padding:1px 4px">▶</button>
          <button class="btn-agent-kill" data-name="${escHtmlSimple(a.name)}" style="font-size:10px;padding:1px 4px;margin-left:2px">✕</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">SPAWN AGENT</div>
      <div style="display:flex;flex-direction:column;gap:3px;margin-bottom:8px">
        <input id="agent-new-name"  style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="Name…" />
        <input id="agent-new-role"  style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="Role…" />
        <input id="agent-new-model" style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="Model (default)…" />
        <button id="btn-agent-spawn" style="font-size:11px;padding:3px">Spawn</button>
      </div>
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">ACTIVE AGENTS</div>
      ${agents.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Role</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Status</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Actions</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No agents yet.</div>'}
      <div id="agent-run-result" style="font-size:10px;margin-top:6px;font-family:var(--font-mono,monospace);white-space:pre-wrap;background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;min-height:20px"></div>
    `;

    $("btn-agent-spawn")?.addEventListener("click", async () => {
      const name  = $("agent-new-name")?.value.trim();
      const role  = $("agent-new-role")?.value.trim() || "assistant";
      const model = $("agent-new-model")?.value.trim() || "default";
      if (!name) return;
      await fetch("/agents/spawn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, role, model }),
      });
      if ($("agent-new-name")) $("agent-new-name").value = "";
      if ($("agent-new-role")) $("agent-new-role").value = "";
      if ($("agent-new-model")) $("agent-new-model").value = "";
      loadAgentsPanel();
    });

    container.querySelectorAll(".btn-agent-run").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const name = btn.dataset.name;
        const input = container.querySelector(`.agent-task-input[data-name="${CSS.escape(name)}"]`);
        const task = input ? input.value.trim() : "";
        if (!task) return;
        try {
          const res = await fetch(`/agents/${encodeURIComponent(name)}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task }),
          });
          const d = await res.json();
          const resultEl = $("agent-run-result");
          if (resultEl) resultEl.textContent = d.result || d.detail || "";
        } catch (e) {
          const resultEl = $("agent-run-result");
          if (resultEl) resultEl.textContent = `Error: ${e.message}`;
        }
        loadAgentsPanel();
      });
    });

    container.querySelectorAll(".btn-agent-kill").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/agents/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
        } catch (e) {
          const resultEl = $("agent-run-result");
          if (resultEl) resultEl.textContent = `Error: ${e.message}`;
        }
        loadAgentsPanel();
      });
    });
  }

  $("btn-agents-refresh")?.addEventListener("click", () => loadAgentsPanel());

  // ── Phase 23: CI/CD Pipeline Integration ─────────────────────────────────

  async function loadCIPanel() {
    const container = $("ci-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/ci/runs");
      const data = await res.json();
      renderCIPanel(data.runs || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderCIPanel(runs) {
    const container = $("ci-panel-content");
    if (!container) return;
    const last = runs.length ? runs[runs.length - 1] : null;

    const rows = runs.map((r) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(String(r.id))}</td>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100px" title="${escHtmlSimple(r.command)}">${escHtmlSimple(r.command)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${r.exit_code === 0 ? "var(--ok,#4caf50)" : "var(--danger,#f44)"}">${escHtmlSimple(String(r.exit_code))}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((r.started_at || "").slice(0, 16).replace("T", " "))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">RUN COMMAND</div>
      <div style="display:flex;gap:4px;margin-bottom:8px">
        <input id="ci-command-input" style="flex:1;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="e.g. echo hello" />
        <button id="btn-ci-run" style="font-size:11px;padding:3px 6px">Run</button>
      </div>
      <div id="ci-run-error" style="font-size:11px;color:var(--error,#ef4444);margin-bottom:4px;display:none"></div>
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">LAST OUTPUT</div>
      <pre id="ci-last-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow-y:auto;max-height:100px;white-space:pre-wrap;margin-bottom:8px">${last ? escHtmlSimple(last.output || "") : "(no runs yet)"}</pre>
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RUN HISTORY</div>
      ${runs.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Command</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Exit</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Started</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No runs yet.</div>'}
    `;

    $("btn-ci-run")?.addEventListener("click", async () => {
      const cmd = $("ci-command-input")?.value.trim();
      if (!cmd) return;
      const btn = $("btn-ci-run");
      if (btn) btn.disabled = true;
      try {
        const res = await fetch("/ci/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: cmd }),
        });
        const d = await res.json();
        const outEl = $("ci-last-output");
        if (outEl) outEl.textContent = d.output || "";
        if ($("ci-command-input")) $("ci-command-input").value = "";
        loadCIPanel();
      } catch (e) {
        const errEl = $("ci-run-error");
        if (errEl) { errEl.textContent = `Error: ${e.message}`; errEl.style.display = "block"; }
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  $("btn-ci-refresh")?.addEventListener("click", () => loadCIPanel());

  // ── Phase 24: Docker Management ──────────────────────────────────────────

  async function loadDockerPanel() {
    const container = $("docker-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/docker/containers");
      const data = await res.json();
      renderDockerPanel(data.containers || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderDockerPanel(containers) {
    const container = $("docker-panel-content");
    if (!container) return;

    const rows = containers.map((c) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(c.id.slice(0, 12))}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(c.name)}</td>
        <td style="padding:2px 4px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80px" title="${escHtmlSimple(c.image)}">${escHtmlSimple(c.image)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${c.status.startsWith("Up") ? "var(--ok,#4caf50)" : "var(--text-dim)"}">${escHtmlSimple(c.status)}</td>
        <td style="padding:2px 4px">
          <button class="btn-docker-stop" data-id="${escHtmlSimple(c.id)}" style="font-size:10px;padding:1px 4px">Stop</button>
          <button class="btn-docker-logs" data-id="${escHtmlSimple(c.id)}" style="font-size:10px;padding:1px 4px">Logs</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">BUILD IMAGE</div>
      <div style="display:flex;gap:4px;margin-bottom:4px;flex-wrap:wrap">
        <input id="docker-build-tag" style="flex:1;min-width:80px;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="image:tag" value="myapp:latest" />
        <input id="docker-build-ctx" style="flex:1;min-width:60px;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="context (e.g. .)" value="." />
        <button id="btn-docker-build" style="font-size:11px;padding:3px 6px">Build</button>
      </div>
      <div id="docker-build-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow-y:auto;max-height:60px;white-space:pre-wrap;margin-bottom:8px;display:none"></div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">RUN CONTAINER</div>
      <div style="display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap">
        <input id="docker-run-image" style="flex:1;min-width:80px;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="image" />
        <input id="docker-run-ports" style="width:80px;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="8080:80" />
        <button id="btn-docker-run" style="font-size:11px;padding:3px 6px">Run</button>
      </div>
      <div id="docker-run-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow-y:auto;max-height:40px;white-space:pre-wrap;margin-bottom:8px;display:none"></div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">CONTAINERS</div>
      ${containers.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">ID</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Image</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Status</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Actions</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No running containers.</div>'}
      <div id="docker-logs-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow-y:auto;max-height:100px;white-space:pre-wrap;margin-top:8px;display:none"></div>
    `;

    $("btn-docker-build")?.addEventListener("click", async () => {
      const tag = $("docker-build-tag")?.value.trim() || "myapp:latest";
      const ctx = $("docker-build-ctx")?.value.trim() || ".";
      const outEl = $("docker-build-output");
      if (outEl) { outEl.textContent = "Building…"; outEl.style.display = "block"; }
      try {
        const res = await fetch("/docker/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tag, context: ctx }),
        });
        const d = await res.json();
        if (outEl) outEl.textContent = d.output || "(no output)";
      } catch (e) {
        if (outEl) outEl.textContent = `Error: ${e.message}`;
      }
    });

    $("btn-docker-run")?.addEventListener("click", async () => {
      const image = $("docker-run-image")?.value.trim();
      const ports = $("docker-run-ports")?.value.trim();
      if (!image) return;
      const outEl = $("docker-run-output");
      if (outEl) { outEl.textContent = "Starting…"; outEl.style.display = "block"; }
      try {
        const res = await fetch("/docker/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image, ports, detach: true }),
        });
        const d = await res.json();
        if (outEl) outEl.textContent = d.output || d.container_id || "(done)";
        loadDockerPanel();
      } catch (e) {
        if (outEl) outEl.textContent = `Error: ${e.message}`;
      }
    });

    container.querySelectorAll(".btn-docker-stop").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/docker/stop/${encodeURIComponent(btn.dataset.id)}`, { method: "POST" });
        } catch (_) {}
        loadDockerPanel();
      });
    });

    container.querySelectorAll(".btn-docker-logs").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const logEl = $("docker-logs-output");
        if (!logEl) return;
        logEl.style.display = "block";
        logEl.textContent = "Loading…";
        try {
          const res = await fetch(`/docker/logs/${encodeURIComponent(btn.dataset.id)}`);
          const d = await res.json();
          logEl.textContent = d.output || "(no logs)";
        } catch (e) {
          logEl.textContent = `Error: ${e.message}`;
        }
      });
    });
  }

  $("btn-docker-refresh")?.addEventListener("click", () => loadDockerPanel());

  // ── Phase 25: Remote Deployment & SSH ────────────────────────────────────

  async function loadDeployPanel() {
    const container = $("deploy-panel-content");
    if (!container) return;
    try {
      const [cfgRes, histRes] = await Promise.all([
        fetch("/deploy/configs"),
        fetch("/deploy/history"),
      ]);
      const cfgData = await cfgRes.json();
      const histData = await histRes.json();
      renderDeployPanel(cfgData.configs || [], histData.history || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderDeployPanel(configs, history) {
    const container = $("deploy-panel-content");
    if (!container) return;

    const cfgOptions = configs.map((c) => `<option value="${escHtmlSimple(c.name)}">${escHtmlSimple(c.name)} (${escHtmlSimple(c.user)}@${escHtmlSimple(c.host)})</option>`).join("");
    const cfgRows = configs.map((c) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(c.name)}</td>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(c.user)}@${escHtmlSimple(c.host)}:${escHtmlSimple(String(c.port))}</td>
        <td style="padding:2px 4px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80px" title="${escHtmlSimple(c.command)}">${escHtmlSimple(c.command)}</td>
        <td style="padding:2px 4px">
          <button class="btn-deploy-run" data-name="${escHtmlSimple(c.name)}" style="font-size:10px;padding:1px 4px">▶</button>
          <button class="btn-deploy-del" data-name="${escHtmlSimple(c.name)}" style="font-size:10px;padding:1px 4px">✕</button>
        </td>
      </tr>
    `).join("");
    const histRows = history.slice().reverse().map((r) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(String(r.id))}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(r.config)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${r.exit_code === 0 ? "var(--ok,#4caf50)" : "var(--danger,#f44)"}">${escHtmlSimple(String(r.exit_code))}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((r.started_at || "").slice(0, 16).replace("T", " "))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ADD CONFIG</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-bottom:4px">
        <input id="deploy-cfg-name"    style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="config name" />
        <input id="deploy-cfg-host"    style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="hostname/IP" />
        <input id="deploy-cfg-user"    style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="user (root)" value="root" />
        <input id="deploy-cfg-port"    style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="port (22)" value="22" />
        <input id="deploy-cfg-command" style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;grid-column:span 2" placeholder="deploy command" />
      </div>
      <button id="btn-deploy-cfg-save" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Save Config</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">CONFIGS</div>
      ${configs.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Target</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Command</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)"></th>
          </tr></thead>
          <tbody>${cfgRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No configs saved.</div>'}

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">LAST OUTPUT</div>
      <pre id="deploy-last-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow-y:auto;max-height:80px;white-space:pre-wrap;margin-bottom:8px">${history.length ? escHtmlSimple(history[history.length - 1].output || "") : "(no deployments yet)"}</pre>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">HISTORY</div>
      ${history.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Config</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Exit</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Started</th>
          </tr></thead>
          <tbody>${histRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No deployments yet.</div>'}
    `;

    $("btn-deploy-cfg-save")?.addEventListener("click", async () => {
      const name    = $("deploy-cfg-name")?.value.trim();
      const host    = $("deploy-cfg-host")?.value.trim();
      const user    = $("deploy-cfg-user")?.value.trim() || "root";
      const port    = parseInt($("deploy-cfg-port")?.value.trim() || "22", 10);
      const command = $("deploy-cfg-command")?.value.trim();
      if (!name || !host || !command) return;
      try {
        await fetch("/deploy/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, host, user, port, command }),
        });
        loadDeployPanel();
      } catch (e) {
        alert(`Error: ${e.message}`);
      }
    });

    container.querySelectorAll(".btn-deploy-run").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const res = await fetch("/deploy/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config_name: btn.dataset.name }),
          });
          const d = await res.json();
          const outEl = $("deploy-last-output");
          if (outEl) outEl.textContent = d.output || "";
          loadDeployPanel();
        } catch (e) {
          alert(`Error: ${e.message}`);
        } finally {
          btn.disabled = false;
        }
      });
    });

    container.querySelectorAll(".btn-deploy-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/deploy/config/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
        } catch (_) {}
        loadDeployPanel();
      });
    });
  }

  $("btn-deploy-refresh")?.addEventListener("click", () => loadDeployPanel());

  // ── Phase 26: Monitoring & Observability panel ────────────────────────────
  async function loadMonitorPanel() {
    const container = $("monitor-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/metrics");
      const data = await res.json();
      renderMonitorPanel(data);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderMonitorPanel(metrics) {
    const container = $("monitor-panel-content");
    if (!container) return;
    const bar = (pct) => {
      const color = pct >= 90 ? "var(--danger,#f44)" : pct >= 70 ? "#f90" : "var(--ok,#4caf50)";
      return `<div style="height:6px;background:var(--bg3,#333);border-radius:3px;overflow:hidden;margin-top:2px">
        <div style="width:${Math.min(pct,100)}%;height:100%;background:${color};transition:width .3s"></div>
      </div>`;
    };
    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">SYSTEM METRICS</div>
      <div style="font-size:11px;color:var(--text-dim,#aaa);margin-bottom:2px">Updated: ${escHtmlSimple((metrics.ts||"").slice(0,19).replace("T"," "))} UTC</div>
      <div style="margin-bottom:8px">
        <div style="font-size:11px;font-weight:600;color:var(--text,#d4d4d4);margin-top:6px">CPU Load (1m avg)</div>
        <div style="font-size:10px;color:var(--text-dim,#aaa)">${escHtmlSimple(String(metrics.cpu_load_percent))}% &nbsp;|&nbsp; 1m: ${escHtmlSimple(String((metrics.cpu_load_avg||{})['1m']||0))} 5m: ${escHtmlSimple(String((metrics.cpu_load_avg||{})['5m']||0))} 15m: ${escHtmlSimple(String((metrics.cpu_load_avg||{})['15m']||0))}</div>
        ${bar(metrics.cpu_load_percent||0)}
      </div>
      <div style="margin-bottom:8px">
        <div style="font-size:11px;font-weight:600;color:var(--text,#d4d4d4)">Memory</div>
        <div style="font-size:10px;color:var(--text-dim,#aaa)">${escHtmlSimple(String(metrics.mem_percent))}% used &nbsp;|&nbsp; ${escHtmlSimple(String(Math.round((metrics.mem_used_kb||0)/1024)))} / ${escHtmlSimple(String(Math.round((metrics.mem_total_kb||0)/1024)))} MB</div>
        ${bar(metrics.mem_percent||0)}
      </div>
      <div style="margin-bottom:8px">
        <div style="font-size:11px;font-weight:600;color:var(--text,#d4d4d4)">Disk</div>
        <div style="font-size:10px;color:var(--text-dim,#aaa)">${escHtmlSimple(String(metrics.disk_percent))}% used &nbsp;|&nbsp; ${escHtmlSimple(String(Math.round((metrics.disk_used_bytes||0)/1e9*10)/10))} / ${escHtmlSimple(String(Math.round((metrics.disk_total_bytes||0)/1e9*10)/10))} GB</div>
        ${bar(metrics.disk_percent||0)}
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">SET ALERT</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;margin-bottom:4px">
        <input id="mon-alert-name"      style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;grid-column:span 1" placeholder="alert name" />
        <select id="mon-alert-metric"   style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px">
          <option value="cpu_load_percent">CPU</option>
          <option value="mem_percent">Memory</option>
          <option value="disk_percent">Disk</option>
        </select>
        <input id="mon-alert-threshold" style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="threshold %" type="number" />
      </div>
      <button id="btn-mon-alert-save" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Save Alert</button>
      <div id="mon-alerts-list"></div>
    `;

    $("btn-monitor-refresh")?.addEventListener("click", () => loadMonitorPanel());
    $("btn-mon-alert-save")?.addEventListener("click", async () => {
      const name = $("mon-alert-name")?.value.trim();
      const metric = $("mon-alert-metric")?.value;
      const threshold = parseFloat($("mon-alert-threshold")?.value || "0");
      if (!name) return;
      try {
        await fetch("/metrics/alert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, metric, threshold }),
        });
        const r2 = await fetch("/metrics/alerts");
        const d2 = await r2.json();
        const alertsList = $("mon-alerts-list");
        if (alertsList) {
          alertsList.innerHTML = (d2.alerts || []).map((a) =>
            `<div style="font-size:10px;color:var(--text-dim,#aaa);margin:1px 0">${escHtmlSimple(a.name)}: ${escHtmlSimple(a.metric)} &ge; ${escHtmlSimple(String(a.threshold))}%
              <button data-name="${escHtmlSimple(a.name)}" class="btn-mon-alert-del" style="font-size:9px;padding:1px 3px;margin-left:4px">✕</button></div>`
          ).join("");
          alertsList.querySelectorAll(".btn-mon-alert-del").forEach((btn) => {
            btn.addEventListener("click", async () => {
              await fetch(`/metrics/alert/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
              loadMonitorPanel();
            });
          });
        }
      } catch (e) {
        alert(`Error: ${e.message}`);
      }
    });
  }

  // ── Phase 27: Database Management panel ──────────────────────────────────
  async function loadDatabasePanel() {
    const container = $("database-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/db/connections");
      const data = await res.json();
      renderDatabasePanel(data.connections || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderDatabasePanel(connections) {
    const container = $("database-panel-content");
    if (!container) return;
    const connOptions = connections.map((c) =>
      `<option value="${escHtmlSimple(c.id)}">${escHtmlSimple(c.alias)} (#${escHtmlSimple(c.id)})</option>`
    ).join("");
    const connRows = connections.map((c) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(c.id)}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(c.alias)}</td>
        <td style="padding:2px 4px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80px" title="${escHtmlSimple(c.path)}">${escHtmlSimple(c.path.split('/').pop())}</td>
        <td style="padding:2px 4px">
          <button class="btn-db-schema" data-id="${escHtmlSimple(c.id)}" style="font-size:10px;padding:1px 4px">⬡</button>
          <button class="btn-db-del"    data-id="${escHtmlSimple(c.id)}" style="font-size:10px;padding:1px 4px">✕</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">CONNECT (SQLite)</div>
      <input id="db-path"  style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="path relative to workspace/ (e.g. mydb.sqlite)" />
      <input id="db-alias" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="alias (optional)" />
      <button id="btn-db-connect" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Connect</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">CONNECTIONS</div>
      ${connections.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Alias</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">File</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)"></th>
          </tr></thead>
          <tbody>${connRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No connections.</div>'}

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">QUERY</div>
      <select id="db-query-conn" style="width:100%;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px">
        <option value="">— select connection —</option>
        ${connOptions}
      </select>
      <textarea id="db-sql" style="width:100%;box-sizing:border-box;height:60px;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;font-family:var(--font-mono,monospace);resize:vertical;margin-bottom:4px" placeholder="SELECT * FROM ..."></textarea>
      <button id="btn-db-run-query" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Run Query</button>
      <div id="db-query-result" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow:auto;max-height:140px;white-space:pre"></div>
      <div id="db-schema-result" style="margin-top:8px"></div>
    `;

    $("btn-db-refresh")?.addEventListener("click", () => loadDatabasePanel());

    $("btn-db-connect")?.addEventListener("click", async () => {
      const path = $("db-path")?.value.trim();
      if (!path) return;
      const alias = $("db-alias")?.value.trim();
      try {
        const res = await fetch("/db/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, alias }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadDatabasePanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    $("btn-db-run-query")?.addEventListener("click", async () => {
      const conn_id = $("db-query-conn")?.value;
      const sql = $("db-sql")?.value.trim();
      if (!conn_id || !sql) return;
      const resultDiv = $("db-query-result");
      if (resultDiv) resultDiv.textContent = "Running…";
      try {
        const res = await fetch("/db/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ connection_id: conn_id, sql }),
        });
        const data = await res.json();
        if (!res.ok) { if (resultDiv) resultDiv.textContent = data.detail || "Error"; return; }
        if (data.columns && data.columns.length) {
          const header = data.columns.join(" | ");
          const rows = (data.rows || []).map((r) => Object.values(r).join(" | ")).join("\n");
          if (resultDiv) resultDiv.textContent = `${header}\n${"-".repeat(header.length)}\n${rows}\n(${data.row_count} rows)`;
        } else {
          if (resultDiv) resultDiv.textContent = `OK — ${data.row_count} row(s) affected`;
        }
      } catch (e) { if (resultDiv) resultDiv.textContent = `Error: ${e.message}`; }
    });

    container.querySelectorAll(".btn-db-schema").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await fetch(`/db/schema/${encodeURIComponent(btn.dataset.id)}`);
          const data = await res.json();
          const schemaDiv = $("db-schema-result");
          if (!schemaDiv) return;
          if (!data.tables || !data.tables.length) { schemaDiv.innerHTML = '<div style="font-size:11px;color:var(--text-dim)">No tables found.</div>'; return; }
          schemaDiv.innerHTML = `<div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">SCHEMA</div>` +
            data.tables.map((t) => `
              <div style="font-size:11px;font-weight:600;color:var(--text,#d4d4d4);margin-top:4px">${escHtmlSimple(t.name)} <span style="color:var(--text-dim,#aaa);font-size:10px">(${escHtmlSimple(t.type)})</span></div>
              <div style="font-size:10px;color:var(--text-dim,#aaa);padding-left:8px">${(t.columns||[]).map((c) => `${escHtmlSimple(c.name)} <span style="color:#888">${escHtmlSimple(c.type)}</span>${c.pk?" <b>PK</b>":""}${c.not_null?" NOT NULL":""}`).join(", ")}</div>
            `).join("");
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-db-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/db/connection/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
          loadDatabasePanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 28: Secret & Environment Vault panel ───────────────────────────
  async function loadVaultPanel() {
    const container = $("vault-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/vault/keys");
      const data = await res.json();
      renderVaultPanel(data.keys || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderVaultPanel(keys) {
    const container = $("vault-panel-content");
    if (!container) return;
    const keyRows = keys.map((k) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(k.key)}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim,#aaa)">${escHtmlSimple(k.description || "")}</td>
        <td style="padding:2px 4px">
          <button class="btn-vault-get" data-key="${escHtmlSimple(k.key)}" style="font-size:10px;padding:1px 4px" title="Reveal value">👁</button>
          <button class="btn-vault-del" data-key="${escHtmlSimple(k.key)}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">SET SECRET</div>
      <input id="vault-key"   style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="KEY_NAME" />
      <input id="vault-value" type="password" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="secret value" />
      <input id="vault-desc"  style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="description (optional)" />
      <button id="btn-vault-set" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Save Secret</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">STORED KEYS</div>
      ${keys.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Key</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Desc</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)"></th>
          </tr></thead>
          <tbody>${keyRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No secrets stored.</div>'}

      <div id="vault-reveal-area" style="display:none;margin-bottom:8px">
        <div style="font-size:11px;color:var(--text-muted,#888);margin-bottom:2px">Revealed value:</div>
        <code id="vault-reveal-value" style="font-size:11px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;display:block;word-break:break-all"></code>
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">EXPORT</div>
      <div style="display:flex;gap:4px;align-items:center;margin-bottom:4px">
        <select id="vault-export-format" style="padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px">
          <option value="env">.env format</option>
          <option value="json">JSON format</option>
        </select>
        <button id="btn-vault-export" style="font-size:11px;padding:3px 8px">Export</button>
      </div>
      <pre id="vault-export-output" style="font-size:10px;font-family:var(--font-mono,monospace);background:var(--bg2,#1e1e1e);border:1px solid var(--border,#444);border-radius:3px;padding:4px;overflow:auto;max-height:80px;white-space:pre-wrap;display:none"></pre>
    `;

    $("btn-vault-refresh")?.addEventListener("click", () => loadVaultPanel());

    $("btn-vault-set")?.addEventListener("click", async () => {
      const key   = $("vault-key")?.value.trim();
      const value = $("vault-value")?.value;
      const desc  = $("vault-desc")?.value.trim();
      if (!key || !value) return;
      try {
        await fetch("/vault/set", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, value, description: desc }),
        });
        loadVaultPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-vault-get").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await fetch(`/vault/get/${encodeURIComponent(btn.dataset.key)}`);
          const data = await res.json();
          const area = $("vault-reveal-area");
          const val  = $("vault-reveal-value");
          if (area && val) {
            val.textContent = data.value || "";
            area.style.display = "block";
            setTimeout(() => { area.style.display = "none"; }, 10000);
          }
        } catch (e) { alert(`Error: ${e.message}`); }
      });
    });

    container.querySelectorAll(".btn-vault-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/vault/key/${encodeURIComponent(btn.dataset.key)}`, { method: "DELETE" });
          loadVaultPanel();
        } catch (e) { /* ignore */ }
      });
    });

    $("btn-vault-export")?.addEventListener("click", async () => {
      const format = $("vault-export-format")?.value || "env";
      try {
        const res = await fetch("/vault/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format }),
        });
        const data = await res.json();
        const out = $("vault-export-output");
        if (out) {
          out.textContent = typeof data.data === "string" ? data.data : JSON.stringify(data.data, null, 2);
          out.style.display = "block";
        }
      } catch (e) { alert(`Error: ${e.message}`); }
    });
  }

  // ── Phase 29: WebHook Manager panel ──────────────────────────────────────
  async function loadWebhooksPanel() {
    const container = $("webhooks-panel-content");
    if (!container) return;
    try {
      const [whRes, dlRes] = await Promise.all([
        fetch("/webhooks"),
        fetch("/webhook/deliveries"),
      ]);
      const whData = await whRes.json();
      const dlData = await dlRes.json();
      renderWebhooksPanel(whData.webhooks || [], dlData.deliveries || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderWebhooksPanel(webhooks, deliveries) {
    const container = $("webhooks-panel-content");
    if (!container) return;

    const whRows = webhooks.map((w) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(w.id)}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(w.name)}</td>
        <td style="padding:2px 4px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80px" title="${escHtmlSimple(w.url)}">${escHtmlSimple(w.url)}</td>
        <td style="padding:2px 4px">
          <button class="btn-wh-deliver" data-id="${escHtmlSimple(w.id)}" style="font-size:10px;padding:1px 4px" title="Deliver">▶</button>
          <button class="btn-wh-del"     data-id="${escHtmlSimple(w.id)}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
        </td>
      </tr>
    `).join("");

    const dlRows = deliveries.slice().reverse().slice(0, 10).map((d) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(String(d.id))}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(d.webhook_name)}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(d.event)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${d.status_code >= 200 && d.status_code < 300 ? "var(--ok,#4caf50)" : "var(--danger,#f44)"}">${escHtmlSimple(String(d.status_code))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">REGISTER WEBHOOK</div>
      <input id="wh-name"   style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="webhook name" />
      <input id="wh-url"    style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="https://example.com/hook" />
      <input id="wh-events" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="events (comma-separated, empty=all)" />
      <button id="btn-wh-register" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Register</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">WEBHOOKS</div>
      ${webhooks.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">URL</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)"></th>
          </tr></thead>
          <tbody>${whRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No webhooks registered.</div>'}

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RECENT DELIVERIES</div>
      ${deliveries.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Hook</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Event</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Status</th>
          </tr></thead>
          <tbody>${dlRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No deliveries yet.</div>'}
    `;

    $("btn-webhooks-refresh")?.addEventListener("click", () => loadWebhooksPanel());

    $("btn-wh-register")?.addEventListener("click", async () => {
      const name   = $("wh-name")?.value.trim();
      const url    = $("wh-url")?.value.trim();
      const evts   = ($("wh-events")?.value.trim() || "").split(",").map((s) => s.trim()).filter(Boolean);
      if (!name || !url) return;
      try {
        const res = await fetch("/webhook/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, url, events: evts }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadWebhooksPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-wh-deliver").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const res = await fetch(`/webhook/deliver/${encodeURIComponent(btn.dataset.id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ event: "manual", payload: {} }),
          });
          const data = await res.json();
          if (!res.ok) { alert(data.detail || "Error"); return; }
          loadWebhooksPanel();
        } catch (e) {
          alert(`Error: ${e.message}`);
        } finally {
          btn.disabled = false;
        }
      });
    });

    container.querySelectorAll(".btn-wh-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/webhook/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
          loadWebhooksPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 30: API Rate Limiting & Quota panel ────────────────────────────
  async function loadRatelimitPanel() {
    const container = $("ratelimit-panel-content");
    if (!container) return;
    try {
      const [rulesRes, statusRes] = await Promise.all([
        fetch("/ratelimit/rules"),
        fetch("/ratelimit/status"),
      ]);
      const rulesData  = await rulesRes.json();
      const statusData = await statusRes.json();
      const statusMap  = {};
      (statusData.status || []).forEach((s) => { statusMap[s.name] = s; });
      renderRatelimitPanel(rulesData.rules || [], statusMap);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderRatelimitPanel(rules, statusMap) {
    const container = $("ratelimit-panel-content");
    if (!container) return;

    const ruleRows = rules.map((r) => {
      const s = statusMap[r.name] || {};
      const pct = r.limit > 0 ? Math.round(((s.used || 0) / r.limit) * 100) : 0;
      const color = s.throttled ? "var(--danger,#f44)" : pct >= 80 ? "var(--warn,#fc0)" : "var(--ok,#4caf50)";
      return `
        <tr>
          <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(r.name)}</td>
          <td style="padding:2px 4px;font-size:10px;color:${color}">${s.used ?? "?"} / ${r.limit}</td>
          <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${r.window_seconds}s</td>
          <td style="padding:2px 4px">
            <button class="btn-rl-check" data-name="${escHtmlSimple(r.name)}" style="font-size:10px;padding:1px 4px" title="Check (consumes 1 call)">▶</button>
            <button class="btn-rl-reset" data-name="${escHtmlSimple(r.name)}" style="font-size:10px;padding:1px 4px" title="Reset counter">↺</button>
            <button class="btn-rl-del"   data-name="${escHtmlSimple(r.name)}" style="font-size:10px;padding:1px 4px" title="Delete rule">✕</button>
          </td>
        </tr>
      `;
    }).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ADD RULE</div>
      <input id="rl-name"    style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="rule name" />
      <div style="display:flex;gap:4px;margin-bottom:4px">
        <input id="rl-limit"  type="number" min="1" value="100" style="width:50%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="limit" />
        <input id="rl-window" type="number" min="1" value="60"  style="width:50%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="window (s)" />
      </div>
      <button id="btn-rl-add" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Add Rule</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RULES</div>
      ${rules.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:4px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Rule</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Used</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Window</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)"></th>
          </tr></thead>
          <tbody>${ruleRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No rules defined.</div>'}
      <div id="rl-result" style="font-size:11px;color:var(--text-muted);min-height:18px;margin-top:4px"></div>
    `;

    $("btn-ratelimit-refresh")?.addEventListener("click", () => loadRatelimitPanel());

    $("btn-rl-add")?.addEventListener("click", async () => {
      const name   = $("rl-name")?.value.trim();
      const limit  = parseInt($("rl-limit")?.value || "100", 10);
      const window_ = parseInt($("rl-window")?.value || "60", 10);
      if (!name) return;
      try {
        const res = await fetch("/ratelimit/rule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, limit, window_seconds: window_ }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadRatelimitPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-rl-check").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res  = await fetch(`/ratelimit/check/${encodeURIComponent(btn.dataset.name)}`, { method: "POST" });
          const data = await res.json();
          const result = $("rl-result");
          if (result) result.textContent = `${data.rule}: ${data.allowed ? "✅ allowed" : "🚫 throttled"} (${data.used}/${data.used + data.remaining} used)`;
          loadRatelimitPanel();
        } catch (e) { alert(`Error: ${e.message}`); }
      });
    });

    container.querySelectorAll(".btn-rl-reset").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/ratelimit/reset/${encodeURIComponent(btn.dataset.name)}`, { method: "POST" });
          loadRatelimitPanel();
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-rl-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/ratelimit/rule/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
          loadRatelimitPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 31: Event Bus & Pub/Sub panel ──────────────────────────────────
  async function loadEventsPanel() {
    const container = $("events-panel-content");
    if (!container) return;
    try {
      const [subRes, histRes] = await Promise.all([
        fetch("/events/subscriptions"),
        fetch("/events/history"),
      ]);
      const subData  = await subRes.json();
      const histData = await histRes.json();
      renderEventsPanel(subData.subscriptions || [], histData.events || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderEventsPanel(subscriptions, events) {
    const container = $("events-panel-content");
    if (!container) return;

    const subRows = subscriptions.map((s) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(s.id)}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(s.name || "(unnamed)")}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((s.topics || []).join(", "))}</td>
        <td style="padding:2px 4px">
          <button class="btn-ev-unsub" data-id="${escHtmlSimple(s.id)}" style="font-size:10px;padding:1px 4px" title="Unsubscribe">✕</button>
        </td>
      </tr>
    `).join("");

    const evRows = events.slice().reverse().slice(0, 15).map((e) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(String(e.id))}</td>
        <td style="padding:2px 4px;font-size:10px;font-weight:600">${escHtmlSimple(e.topic)}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(e.source || "—")}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((e.ts || "").slice(11, 19))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">PUBLISH EVENT</div>
      <input id="ev-topic"   style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="topic name" />
      <input id="ev-source"  style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="source (optional)" />
      <textarea id="ev-payload" rows="2" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px;resize:vertical;font-family:var(--font-mono,monospace)" placeholder='{"key":"value"}'></textarea>
      <button id="btn-ev-publish" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Publish</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">SUBSCRIBE</div>
      <input id="ev-sub-topics" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="topics (comma-separated)" />
      <input id="ev-sub-name"   style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="subscriber name (optional)" />
      <button id="btn-ev-subscribe" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Subscribe</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">SUBSCRIPTIONS</div>
      ${subscriptions.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Topics</th>
            <th></th>
          </tr></thead>
          <tbody>${subRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No subscriptions.</div>'}

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RECENT EVENTS</div>
      ${events.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">#</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Topic</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Source</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Time</th>
          </tr></thead>
          <tbody>${evRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No events published yet.</div>'}
    `;

    $("btn-events-refresh")?.addEventListener("click", () => loadEventsPanel());

    $("btn-ev-publish")?.addEventListener("click", async () => {
      const topic   = $("ev-topic")?.value.trim();
      const source  = $("ev-source")?.value.trim();
      let payload   = {};
      try { payload = JSON.parse($("ev-payload")?.value || "{}"); } catch { payload = {}; }
      if (!topic) return;
      try {
        const res = await fetch("/events/publish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic, source, payload }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadEventsPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    $("btn-ev-subscribe")?.addEventListener("click", async () => {
      const topicsRaw = $("ev-sub-topics")?.value.trim();
      const name      = $("ev-sub-name")?.value.trim();
      const topics    = topicsRaw.split(",").map((s) => s.trim()).filter(Boolean);
      if (!topics.length) return;
      try {
        const res = await fetch("/events/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topics, name }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadEventsPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-ev-unsub").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/events/subscription/${encodeURIComponent(btn.dataset.id)}`, { method: "DELETE" });
          loadEventsPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 32: Cron Job Scheduler panel ───────────────────────────────────
  async function loadCronPanel() {
    const container = $("cron-panel-content");
    if (!container) return;
    try {
      const [jobsRes, histRes] = await Promise.all([
        fetch("/cron/jobs"),
        fetch("/cron/history"),
      ]);
      const jobsData = await jobsRes.json();
      const histData = await histRes.json();
      renderCronPanel(jobsData.jobs || [], histData.history || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderCronPanel(jobs, history) {
    const container = $("cron-panel-content");
    if (!container) return;

    const jobRows = jobs.map((j) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(j.name)}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(j.schedule)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${j.enabled ? "var(--ok,#4caf50)" : "var(--text-dim)"}">${j.enabled ? "on" : "off"}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${j.run_count ?? 0}</td>
        <td style="padding:2px 4px">
          <button class="btn-cron-run" data-name="${escHtmlSimple(j.name)}" style="font-size:10px;padding:1px 4px" title="Run now">▶</button>
          <button class="btn-cron-del" data-name="${escHtmlSimple(j.name)}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
        </td>
      </tr>
    `).join("");

    const histRows = history.slice().reverse().slice(0, 10).map((r) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(r.job)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${r.exit_code === 0 ? "var(--ok,#4caf50)" : "var(--danger,#f44)"}">${r.exit_code === 0 ? "✓" : "✗"} ${r.exit_code}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((r.started_at || "").slice(11, 19))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ADD JOB</div>
      <input id="cron-name"     style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="job name" />
      <input id="cron-schedule" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="schedule (e.g. every 60s)" />
      <input id="cron-command"  style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="command (e.g. echo hello)" />
      <button id="btn-cron-add" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Add Job</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">JOBS</div>
      ${jobs.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Schedule</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Enabled</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Runs</th>
            <th></th>
          </tr></thead>
          <tbody>${jobRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No jobs defined.</div>'}

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RECENT RUNS</div>
      ${history.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Job</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Result</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Time</th>
          </tr></thead>
          <tbody>${histRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No runs yet.</div>'}
    `;

    $("btn-cron-refresh")?.addEventListener("click", () => loadCronPanel());

    $("btn-cron-add")?.addEventListener("click", async () => {
      const name     = $("cron-name")?.value.trim();
      const schedule = $("cron-schedule")?.value.trim();
      const command  = $("cron-command")?.value.trim();
      if (!name || !command) return;
      try {
        const res = await fetch("/cron/job", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, schedule: schedule || "manual", command }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadCronPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-cron-run").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/cron/job/${encodeURIComponent(btn.dataset.name)}/run`, { method: "POST" });
          loadCronPanel();
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-cron-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/cron/job/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
          loadCronPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 33: Audit Log panel ─────────────────────────────────────────────
  async function loadAuditPanel() {
    const container = $("audit-panel-content");
    if (!container) return;
    try {
      const [logRes, statsRes] = await Promise.all([
        fetch("/audit/log?limit=30"),
        fetch("/audit/stats"),
      ]);
      const logData   = await logRes.json();
      const statsData = await statsRes.json();
      renderAuditPanel(logData.entries || [], statsData);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderAuditPanel(entries, stats) {
    const container = $("audit-panel-content");
    if (!container) return;

    const levelColor = (lv) =>
      lv === "error" ? "var(--danger,#f44)" : lv === "warn" ? "var(--warn,#fc0)" : "var(--ok,#4caf50)";

    const entryRows = entries.slice().reverse().slice(0, 20).map((e) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;color:${levelColor(e.level)}">${escHtmlSimple(e.level)}</td>
        <td style="padding:2px 4px;font-size:10px;font-weight:600">${escHtmlSimple(e.action)}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(e.actor)}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple((e.ts || "").slice(11, 19))}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">STATS</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;font-size:11px">
        <span>Total: <b>${stats.total ?? 0}</b></span>
        <span style="color:var(--ok,#4caf50)">info: ${stats.by_level?.info ?? 0}</span>
        <span style="color:var(--warn,#fc0)">warn: ${stats.by_level?.warn ?? 0}</span>
        <span style="color:var(--danger,#f44)">error: ${stats.by_level?.error ?? 0}</span>
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">MANUAL ENTRY</div>
      <input id="audit-action" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="action" />
      <div style="display:flex;gap:4px;margin-bottom:4px">
        <input id="audit-actor"  style="width:50%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" placeholder="actor" />
        <select id="audit-level" style="width:50%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px">
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
        </select>
      </div>
      <input id="audit-detail" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="detail (optional)" />
      <div style="display:flex;gap:4px;margin-bottom:8px">
        <button id="btn-audit-add"   style="font-size:11px;padding:3px 8px">Log Entry</button>
        <button id="btn-audit-clear" style="font-size:11px;padding:3px 8px;color:var(--danger,#f44)" title="Clear all audit log entries">Clear All</button>
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">RECENT ENTRIES</div>
      ${entries.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Level</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Action</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Actor</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Time</th>
          </tr></thead>
          <tbody>${entryRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No entries yet.</div>'}
    `;

    $("btn-audit-refresh")?.addEventListener("click", () => loadAuditPanel());

    $("btn-audit-add")?.addEventListener("click", async () => {
      const action = $("audit-action")?.value.trim();
      const actor  = $("audit-actor")?.value.trim() || "manual";
      const level  = $("audit-level")?.value || "info";
      const detail = $("audit-detail")?.value.trim();
      if (!action) return;
      try {
        const res = await fetch("/audit/log", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, actor, level, detail }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadAuditPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    $("btn-audit-clear")?.addEventListener("click", async () => {
      if (!confirm("Clear all audit log entries?")) return;
      try {
        await fetch("/audit/log/clear", { method: "DELETE" });
        loadAuditPanel();
      } catch (e) { /* ignore */ }
    });
  }

  // ── Phase 34: Feature Flags panel ────────────────────────────────────────
  async function loadFlagsPanel() {
    const container = $("flags-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/flags");
      const data = await res.json();
      renderFlagsPanel(data.flags || []);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderFlagsPanel(flags) {
    const container = $("flags-panel-content");
    if (!container) return;

    const flagRows = flags.map((f) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(f.name)}</td>
        <td style="padding:2px 4px;font-size:10px;color:${f.enabled ? "var(--ok,#4caf50)" : "var(--text-dim)"}">${f.enabled ? "on" : "off"}</td>
        <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${escHtmlSimple(f.variant || "")}</td>
        <td style="padding:2px 4px">
          <button class="btn-flag-toggle" data-name="${escHtmlSimple(f.name)}" style="font-size:10px;padding:1px 4px" title="Toggle">${f.enabled ? "⏸" : "▶"}</button>
          <button class="btn-flag-del"    data-name="${escHtmlSimple(f.name)}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ADD / UPDATE FLAG</div>
      <input id="flag-name"    style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="flag name" />
      <input id="flag-variant" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="variant (optional)" />
      <input id="flag-desc"    style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="description (optional)" />
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
        <label style="font-size:11px;display:flex;align-items:center;gap:4px"><input type="checkbox" id="flag-enabled" checked /> Enabled</label>
        <button id="btn-flag-add" style="font-size:11px;padding:3px 8px">Save Flag</button>
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">FLAGS</div>
      ${flags.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">State</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Variant</th>
            <th></th>
          </tr></thead>
          <tbody>${flagRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">No flags defined.</div>'}
    `;

    $("btn-flags-refresh")?.addEventListener("click", () => loadFlagsPanel());

    $("btn-flag-add")?.addEventListener("click", async () => {
      const name    = $("flag-name")?.value.trim();
      const variant = $("flag-variant")?.value.trim();
      const desc    = $("flag-desc")?.value.trim();
      const enabled = $("flag-enabled")?.checked ?? true;
      if (!name) return;
      try {
        const res = await fetch("/flags/flag", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, variant, description: desc, enabled }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadFlagsPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-flag-toggle").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/flags/flag/${encodeURIComponent(btn.dataset.name)}/toggle`, { method: "POST" });
          loadFlagsPanel();
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-flag-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/flags/flag/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
          loadFlagsPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 35: Config Profiles panel ──────────────────────────────────────
  async function loadCfgProfilePanel() {
    const container = $("cfgprofile-panel-content");
    if (!container) return;
    try {
      const [profilesRes, activeRes] = await Promise.all([
        fetch("/config/profiles"),
        fetch("/config/active"),
      ]);
      const profilesData = await profilesRes.json();
      const activeData   = await activeRes.json();
      renderCfgProfilePanel(profilesData.profiles || [], profilesData.active || "", activeData);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderCfgProfilePanel(profiles, activeProfile, activeData) {
    const container = $("cfgprofile-panel-content");
    if (!container) return;

    const profileRows = profiles.map((p) => {
      const isActive = p.name === activeProfile;
      return `
        <tr style="${isActive ? "background:rgba(33,150,243,0.1)" : ""}">
          <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(p.name)}</td>
          <td style="padding:2px 4px;font-size:10px;color:var(--text-dim)">${Object.keys(p.values || {}).length} keys</td>
          <td style="padding:2px 4px;font-size:10px;color:${isActive ? "var(--info,#2196f3)" : "var(--text-dim)"}">${isActive ? "● active" : ""}</td>
          <td style="padding:2px 4px">
            ${!isActive ? `<button class="btn-cfgprofile-activate" data-name="${escHtmlSimple(p.name)}" style="font-size:10px;padding:1px 4px" title="Activate">✓</button>` : ""}
            <button class="btn-cfgprofile-del" data-name="${escHtmlSimple(p.name)}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
          </td>
        </tr>
      `;
    }).join("");

    const activeValues = activeData?.values || {};
    const activeRows = Object.entries(activeValues).map(([k, v]) => `
      <tr>
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace);color:var(--text-dim)">${escHtmlSimple(k)}</td>
        <td style="padding:2px 4px;font-size:10px">${escHtmlSimple(v)}</td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ADD / UPDATE PROFILE</div>
      <input id="cfgprofile-name" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="profile name" />
      <textarea id="cfgprofile-values" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;height:60px;resize:vertical;margin-bottom:4px;font-family:var(--font-mono,monospace)" placeholder='key=value pairs (one per line)'></textarea>
      <button id="btn-cfgprofile-add" style="font-size:11px;padding:3px 8px;margin-bottom:8px">Save Profile</button>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">PROFILES</div>
      ${profiles.length ? `
        <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Keys</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Status</th>
            <th></th>
          </tr></thead>
          <tbody>${profileRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px;margin-bottom:8px">No profiles defined.</div>'}

      ${activeData?.active ? `
        <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">ACTIVE VALUES <span style="font-size:10px;color:var(--info,#2196f3)">(${escHtmlSimple(activeData.active)})</span></div>
        ${Object.keys(activeValues).length ? `
          <table style="width:100%;border-collapse:collapse">
            <thead><tr>
              <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Key</th>
              <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Value</th>
            </tr></thead>
            <tbody>${activeRows}</tbody>
          </table>` : '<div style="font-size:11px;color:var(--text-dim);padding:2px">Profile has no keys.</div>'}
      ` : ""}
    `;

    $("btn-cfgprofile-refresh")?.addEventListener("click", () => loadCfgProfilePanel());

    $("btn-cfgprofile-add")?.addEventListener("click", async () => {
      const name   = $("cfgprofile-name")?.value.trim();
      const rawVal = $("cfgprofile-values")?.value || "";
      if (!name) return;
      const values = {};
      for (const line of rawVal.split("\n")) {
        const idx = line.indexOf("=");
        if (idx > 0) values[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      }
      try {
        const res = await fetch("/config/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, values }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadCfgProfilePanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-cfgprofile-activate").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/config/profile/${encodeURIComponent(btn.dataset.name)}/activate`, { method: "POST" });
          loadCfgProfilePanel();
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-cfgprofile-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/config/profile/${encodeURIComponent(btn.dataset.name)}`, { method: "DELETE" });
          loadCfgProfilePanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 36: Notification Center panel ──────────────────────────────────
  async function loadNotifyPanel() {
    const container = $("notify-panel-content");
    if (!container) return;
    try {
      const res = await fetch("/notifications");
      const data = await res.json();
      renderNotifyPanel(data.notifications || [], data.unread || 0);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderNotifyPanel(notifications, unread) {
    const container = $("notify-panel-content");
    if (!container) return;

    const levelColor = { info: "var(--info,#2196f3)", warn: "var(--warn,#ff9800)", error: "var(--danger,#f44336)", success: "var(--ok,#4caf50)" };

    const rows = notifications.slice().reverse().map((n) => `
      <div style="padding:6px 4px;border-bottom:1px solid var(--border,#333);opacity:${n.read ? "0.55" : "1"}">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-size:10px;font-weight:600;color:${levelColor[n.level] || "var(--text)"}">
            [${escHtmlSimple((n.level || "info").toUpperCase())}] ${escHtmlSimple(n.title)}
          </span>
          <button class="btn-notify-del" data-id="${n.id}" style="font-size:10px;padding:0 4px;background:none;border:none;color:var(--text-dim);cursor:pointer" title="Delete">✕</button>
        </div>
        ${n.message ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px">${escHtmlSimple(n.message)}</div>` : ""}
        <div style="font-size:9px;color:var(--text-dim);margin-top:2px">${escHtmlSimple(n.created_at || "")}</div>
      </div>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">SEND NOTIFICATION</div>
      <input id="notify-title"   style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="title" />
      <input id="notify-message" style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="message (optional)" />
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
        <select id="notify-level" style="font-size:11px;padding:2px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px">
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
          <option value="success">success</option>
        </select>
        <button id="btn-notify-send" style="font-size:11px;padding:3px 8px">Send</button>
      </div>

      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:4px">
        INBOX <span style="font-size:10px;color:var(--info,#2196f3)">${unread} unread</span>
      </div>
      ${notifications.length ? rows : '<div style="font-size:11px;color:var(--text-dim)">No notifications.</div>'}
    `;

    $("btn-notify-refresh")?.addEventListener("click",   () => loadNotifyPanel());
    $("btn-notify-mark-read")?.addEventListener("click", async () => {
      await fetch("/notifications/mark-read", { method: "POST" });
      loadNotifyPanel();
    });
    $("btn-notify-clear")?.addEventListener("click", async () => {
      await fetch("/notifications/clear", { method: "DELETE" });
      loadNotifyPanel();
    });

    $("btn-notify-send")?.addEventListener("click", async () => {
      const title   = $("notify-title")?.value.trim();
      const message = $("notify-message")?.value.trim();
      const level   = $("notify-level")?.value || "info";
      if (!title) return;
      try {
        const res = await fetch("/notify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, message, level }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadNotifyPanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-notify-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/notification/${btn.dataset.id}`, { method: "DELETE" });
          loadNotifyPanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 37: Task Queue panel ────────────────────────────────────────────
  async function loadTaskQueuePanel() {
    const container = $("taskqueue-panel-content");
    if (!container) return;
    try {
      const [tasksRes, statsRes] = await Promise.all([
        fetch("/queue/tasks"),
        fetch("/queue/stats"),
      ]);
      const tasksData = await tasksRes.json();
      const statsData = await statsRes.json();
      renderTaskQueuePanel(tasksData.tasks || [], statsData);
    } catch (e) {
      container.innerHTML = `<div style="color:var(--danger);font-size:11px;padding:4px">Error: ${e.message}</div>`;
    }
  }

  function renderTaskQueuePanel(tasks, stats) {
    const container = $("taskqueue-panel-content");
    if (!container) return;

    const taskRows = tasks.map((t) => `
      <tr style="opacity:${t.status === "done" ? "0.5" : "1"}">
        <td style="padding:2px 4px;font-size:10px;font-family:var(--font-mono,monospace)">${escHtmlSimple(t.name)}</td>
        <td style="padding:2px 4px;font-size:10px;text-align:center">${t.priority}</td>
        <td style="padding:2px 4px;font-size:10px;color:${t.status === "pending" ? "var(--warn,#ff9800)" : "var(--ok,#4caf50)"}">${t.status}</td>
        <td style="padding:2px 4px">
          ${t.status === "pending" ? `<button class="btn-tq-complete" data-id="${t.id}" style="font-size:10px;padding:1px 4px" title="Mark done">✓</button>` : ""}
          <button class="btn-tq-del" data-id="${t.id}" style="font-size:10px;padding:1px 4px" title="Delete">✕</button>
        </td>
      </tr>
    `).join("");

    container.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:var(--text-muted,#888);margin-bottom:6px">ENQUEUE TASK</div>
      <input id="tq-name"    style="width:100%;box-sizing:border-box;padding:3px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px;margin-bottom:4px" placeholder="task name" />
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
        <label style="font-size:11px">Priority (1-10):</label>
        <input id="tq-priority" type="number" min="1" max="10" value="5" style="width:48px;padding:2px;background:var(--bg2,#1e1e1e);color:var(--text,#d4d4d4);border:1px solid var(--border,#444);border-radius:3px;font-size:11px" />
        <button id="btn-tq-add" style="font-size:11px;padding:3px 8px">Enqueue</button>
      </div>

      <div style="font-size:11px;color:var(--text-dim);margin-bottom:6px">
        📊 Total: <b>${stats.total || 0}</b> | Pending: <b style="color:var(--warn,#ff9800)">${stats.pending || 0}</b> | Done: <b style="color:var(--ok,#4caf50)">${stats.done || 0}</b>
      </div>

      ${tasks.length ? `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Name</th>
            <th style="font-size:10px;text-align:center;padding:2px 4px;color:var(--text-muted,#888)">Pri</th>
            <th style="font-size:10px;text-align:left;padding:2px 4px;color:var(--text-muted,#888)">Status</th>
            <th></th>
          </tr></thead>
          <tbody>${taskRows}</tbody>
        </table>` : '<div style="font-size:11px;color:var(--text-dim)">Queue is empty.</div>'}
    `;

    $("btn-taskqueue-refresh")?.addEventListener("click", () => loadTaskQueuePanel());

    $("btn-tq-add")?.addEventListener("click", async () => {
      const name     = $("tq-name")?.value.trim();
      const priority = parseInt($("tq-priority")?.value || "5", 10);
      if (!name) return;
      try {
        const res = await fetch("/queue/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, priority }),
        });
        if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
        loadTaskQueuePanel();
      } catch (e) { alert(`Error: ${e.message}`); }
    });

    container.querySelectorAll(".btn-tq-complete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/queue/task/${btn.dataset.id}/complete`, { method: "POST" });
          loadTaskQueuePanel();
        } catch (e) { /* ignore */ }
      });
    });

    container.querySelectorAll(".btn-tq-del").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await fetch(`/queue/task/${btn.dataset.id}`, { method: "DELETE" });
          loadTaskQueuePanel();
        } catch (e) { /* ignore */ }
      });
    });
  }

  // ── Phase 38: Brainstorm Mode panel ──────────────────────────────────────
  let _bsActiveSessionId = null;

  async function loadBrainstormPanel() {
    const container = $("bs-sessions-container");
    if (!container) return;
    try {
      const res  = await fetch("/brainstorm/sessions");
      const data = await res.json();
      const sessions = data.sessions || [];
      if (!sessions.length) {
        container.innerHTML = `<div style="color:var(--text-dim);font-size:11px;padding:4px">
          No sessions yet. Click <b>+</b> to start a new brainstorm.
        </div>`;
        return;
      }
      container.innerHTML = sessions.map(s => `
        <div class="bs-session-card" data-id="${s.id}"
          style="padding:8px;border-radius:5px;border:1px solid var(--border);cursor:pointer;
                 margin-bottom:6px;background:var(--surface);transition:background .15s">
          <div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:2px">${escHtmlSimple(s.title)}</div>
          <div style="font-size:10px;color:var(--text-dim)">${s.messages.length} message${s.messages.length !== 1 ? "s" : ""}
            · ${s.created_at.slice(0,10)}</div>
        </div>
      `).join("");
      container.querySelectorAll(".bs-session-card").forEach(card => {
        card.addEventListener("mouseenter", () => card.style.background = "var(--surface2)");
        card.addEventListener("mouseleave", () => card.style.background = "var(--surface)");
        card.addEventListener("click", () => openBrainstormSession(Number(card.dataset.id)));
      });
    } catch (e) {
      if (container) container.innerHTML = `<div style="color:var(--danger);font-size:11px">${e.message}</div>`;
    }
  }

  async function openBrainstormSession(id) {
    _bsActiveSessionId = id;
    try {
      const res  = await fetch(`/brainstorm/session/${id}`);
      const s    = await res.json();
      const title = $("bs-session-title");
      if (title) title.textContent = s.title;
      _renderBrainstormMessages(s.messages);
      $("bs-session-list-view")?.classList.add("hidden");
      $("bs-session-view")?.classList.remove("hidden");
      $("bs-input")?.focus();
    } catch (e) {
      appendOutput(`Brainstorm load error: ${e.message}\n`);
    }
  }

  function _renderBrainstormMessages(messages) {
    const container = $("bs-messages");
    if (!container) return;
    container.innerHTML = messages.map(m => {
      const isUser = m.role === "user";
      const bg     = isUser ? "var(--surface2)" : "rgba(124,106,247,0.1)";
      const align  = isUser ? "flex-end" : "flex-start";
      const label  = isUser ? "You" : "AI";
      const ts     = (m.timestamp || "").slice(0,16).replace("T"," ");
      return `
        <div style="display:flex;flex-direction:column;align-items:${align};gap:2px">
          <div style="font-size:9px;color:var(--text-dim);padding:0 4px">${label} · ${escHtmlSimple(ts)}</div>
          <div style="max-width:90%;background:${bg};border-radius:6px;padding:7px 10px;
                      font-size:12px;line-height:1.5;white-space:pre-wrap;word-break:break-word">
            ${escHtmlSimple(m.content)}
          </div>
        </div>`;
    }).join("");
    container.scrollTop = container.scrollHeight;
  }

  async function _bsSendMessage() {
    const input = $("bs-input");
    if (!input || !_bsActiveSessionId) return;
    const content = input.value.trim();
    if (!content) return;
    input.value = "";
    input.disabled = true;
    const sendBtn = $("btn-bs-send");
    if (sendBtn) sendBtn.disabled = true;

    // Optimistically render user message
    const msgs = $("bs-messages");
    if (msgs) {
      msgs.innerHTML += `
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px">
          <div style="font-size:9px;color:var(--text-dim);padding:0 4px">You · now</div>
          <div style="max-width:90%;background:var(--surface2);border-radius:6px;padding:7px 10px;
                      font-size:12px;line-height:1.5;white-space:pre-wrap">${escHtmlSimple(content)}</div>
        </div>
        <div id="bs-thinking" style="display:flex;align-items:flex-start;gap:2px">
          <div style="font-size:9px;color:var(--text-dim);padding:0 4px">AI</div>
          <div style="font-size:12px;color:var(--text-dim);font-style:italic;padding:7px 10px">Thinking…</div>
        </div>`;
      msgs.scrollTop = msgs.scrollHeight;
    }

    try {
      const res = await fetch(`/brainstorm/session/${_bsActiveSessionId}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "user", content }),
      });
      const data = await res.json();
      // Re-fetch the full session to render complete history
      const sRes = await fetch(`/brainstorm/session/${_bsActiveSessionId}`);
      const s    = await sRes.json();
      _renderBrainstormMessages(s.messages);
    } catch (e) {
      const thinking = $("bs-thinking");
      if (thinking) thinking.remove();
      appendOutput(`Brainstorm send error: ${e.message}\n`);
    } finally {
      input.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      input.focus();
    }
  }

  $("btn-bs-new")?.addEventListener("click", async () => {
    const title = prompt("Session title:", "New Brainstorm");
    if (!title) return;
    const desc = prompt("Short description (optional):", "") || "";
    try {
      const res  = await fetch("/brainstorm/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description: desc }),
      });
      const s = await res.json();
      await openBrainstormSession(s.id);
    } catch (e) { alert(`Error: ${e.message}`); }
  });

  $("btn-bs-refresh")?.addEventListener("click", () => {
    $("bs-session-view")?.classList.add("hidden");
    $("bs-session-list-view")?.classList.remove("hidden");
    loadBrainstormPanel();
  });

  $("btn-bs-back")?.addEventListener("click", () => {
    _bsActiveSessionId = null;
    $("bs-session-view")?.classList.add("hidden");
    $("bs-session-list-view")?.classList.remove("hidden");
    loadBrainstormPanel();
  });

  $("btn-bs-send")?.addEventListener("click", _bsSendMessage);

  $("bs-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      _bsSendMessage();
    }
  });

  $("btn-bs-export")?.addEventListener("click", async () => {
    if (!_bsActiveSessionId) return;
    try {
      const res  = await fetch(`/brainstorm/session/${_bsActiveSessionId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: "markdown" }),
      });
      const data = await res.json();
      const blob = new Blob([data.content], { type: "text/markdown" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = `brainstorm-${_bsActiveSessionId}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { alert(`Export error: ${e.message}`); }
  });

  $("btn-bs-to-project")?.addEventListener("click", async () => {
    if (!_bsActiveSessionId) return;
    const name = prompt("New project name:");
    if (!name) return;
    try {
      const res = await fetch(`/brainstorm/session/${_bsActiveSessionId}/to-project`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: name }),
      });
      if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
      const data = await res.json();
      alert(`Project created at ${data.project_path}`);
      // Refresh file tree
      loadFileTree?.();
    } catch (e) { alert(`Error: ${e.message}`); }
  });

  // ── Phase 39: Web Search panel ────────────────────────────────────────────

  async function _runWebSearch() {
    const input   = $("ws-query-input");
    const results = $("ws-results");
    if (!input || !results) return;
    const q = input.value.trim();
    if (!q) return;
    results.innerHTML = `<div style="color:var(--text-dim);font-size:11px">Searching…</div>`;
    try {
      const res  = await fetch(`/search/web?q=${encodeURIComponent(q)}&max_results=8`);
      const data = await res.json();
      if (!data.results || !data.results.length) {
        results.innerHTML = `<div style="color:var(--text-dim);font-size:11px">No results found.</div>`;
        return;
      }
      results.innerHTML = data.results.map(r => `
        <div style="padding:8px;border-radius:5px;border:1px solid var(--border);background:var(--surface);
                    display:flex;flex-direction:column;gap:3px">
          <a href="${escHtmlSimple(r.url)}" target="_blank" rel="noopener"
             style="color:var(--accent);font-size:12px;font-weight:600;
                    text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
             title="${escHtmlSimple(r.url)}">${escHtmlSimple(r.title)}</a>
          <div style="font-size:10px;color:var(--text-dim);overflow:hidden;
                      text-overflow:ellipsis;white-space:nowrap">${escHtmlSimple(r.url)}</div>
          ${r.snippet ? `<div style="font-size:11px;color:var(--text);line-height:1.4">${escHtmlSimple(r.snippet)}</div>` : ""}
        </div>
      `).join("");
    } catch (e) {
      results.innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${escHtmlSimple(e.message)}</div>`;
    }
  }

  $("btn-ws-search")?.addEventListener("click", _runWebSearch);
  $("ws-query-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") _runWebSearch();
  });

  // ── Phase 40: Code Snippet Library panel ─────────────────────────────────
  let _snipEditId = null;

  async function loadSnippetsPanel() {
    const list = $("snip-list");
    if (!list) return;
    list.innerHTML = `<div style="color:var(--text-dim);font-size:11px">Loading…</div>`;
    try {
      const res  = await fetch("/snippets");
      const data = await res.json();
      _renderSnipList(data.snippets || []);
    } catch (e) {
      list.innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${escHtmlSimple(e.message)}</div>`;
    }
  }

  function _renderSnipList(snippets) {
    const list = $("snip-list");
    if (!list) return;
    if (!snippets.length) {
      list.innerHTML = `<div style="color:var(--text-dim);font-size:11px;padding:4px">No snippets yet. Click + to add one.</div>`;
      return;
    }
    list.innerHTML = snippets.map(s => `
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:5px;padding:8px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
          <span style="font-size:12px;font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtmlSimple(s.name)}</span>
          ${s.language ? `<span style="font-size:10px;background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:1px 5px;color:var(--accent)">${escHtmlSimple(s.language)}</span>` : ""}
        </div>
        ${s.description ? `<div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">${escHtmlSimple(s.description)}</div>` : ""}
        ${s.tags.length ? `<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">${s.tags.map(t => `<span style="background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:1px 4px;margin-right:2px">${escHtmlSimple(t)}</span>`).join("")}</div>` : ""}
        <pre style="font-size:10px;font-family:var(--font-mono);background:var(--bg);border:1px solid var(--border);border-radius:3px;padding:5px;margin:0 0 6px;overflow-x:auto;max-height:80px;white-space:pre-wrap">${escHtmlSimple(s.code.slice(0, 300))}${s.code.length > 300 ? "…" : ""}</pre>
        <div style="display:flex;gap:4px">
          <button onclick="_snipCopy(${s.id})" style="font-size:11px;padding:3px 7px">📋 Copy</button>
          <button onclick="_snipEdit(${s.id})" style="font-size:11px;padding:3px 7px">✏ Edit</button>
          <button onclick="_snipDelete(${s.id})" style="font-size:11px;padding:3px 7px;color:var(--danger)">🗑 Delete</button>
        </div>
      </div>
    `).join("");
  }

  window._snipCopy = async function(id) {
    try {
      const res = await fetch(`/snippet/${id}`);
      const s = await res.json();
      await navigator.clipboard.writeText(s.code);
      _showToast?.("Snippet copied!");
    } catch (e) { alert("Copy failed: " + e.message); }
  };

  window._snipEdit = async function(id) {
    try {
      const res = await fetch(`/snippet/${id}`);
      const s = await res.json();
      _snipEditId = id;
      $("snip-name").value = s.name;
      $("snip-lang").value = s.language;
      $("snip-tags").value = s.tags.join(", ");
      $("snip-desc").value = s.description;
      $("snip-code").value = s.code;
      $("snip-form").classList.remove("hidden");
    } catch (e) { alert("Error: " + e.message); }
  };

  window._snipDelete = async function(id) {
    if (!confirm("Delete this snippet?")) return;
    try {
      await fetch(`/snippet/${id}`, { method: "DELETE" });
      loadSnippetsPanel();
    } catch (e) { alert("Error: " + e.message); }
  };

  $("btn-snip-new")?.addEventListener("click", () => {
    _snipEditId = null;
    ["snip-name","snip-lang","snip-tags","snip-desc","snip-code"].forEach(id => { const el = $(id); if (el) el.value = ""; });
    $("snip-form")?.classList.remove("hidden");
  });

  $("btn-snip-cancel")?.addEventListener("click", () => {
    _snipEditId = null;
    $("snip-form")?.classList.add("hidden");
  });

  $("btn-snip-save")?.addEventListener("click", async () => {
    const name = $("snip-name")?.value.trim();
    const code = $("snip-code")?.value.trim();
    if (!name || !code) { alert("Name and code are required."); return; }
    const body = {
      name,
      language: $("snip-lang")?.value.trim() || "",
      code: $("snip-code")?.value,
      tags: ($("snip-tags")?.value || "").split(",").map(t => t.trim()).filter(Boolean),
      description: $("snip-desc")?.value.trim() || "",
    };
    try {
      let res;
      if (_snipEditId) {
        res = await fetch(`/snippet/${_snipEditId}`, { method: "PUT", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
      } else {
        res = await fetch("/snippet", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
      }
      if (!res.ok) { const d = await res.json(); alert(d.detail || "Error"); return; }
      _snipEditId = null;
      $("snip-form")?.classList.add("hidden");
      loadSnippetsPanel();
    } catch (e) { alert("Error: " + e.message); }
  });

  $("btn-snip-refresh")?.addEventListener("click", loadSnippetsPanel);

  $("btn-snip-search")?.addEventListener("click", async () => {
    const q = $("snip-search")?.value.trim();
    const list = $("snip-list");
    if (!list) return;
    if (!q) { loadSnippetsPanel(); return; }
    try {
      const res  = await fetch(`/snippets/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      _renderSnipList(data.snippets || []);
    } catch (e) {
      list.innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${escHtmlSimple(e.message)}</div>`;
    }
  });

  $("snip-search")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("btn-snip-search")?.click();
  });

  // ── Phase 44: Environment Variables Manager panel ────────────────────────
  (function () {
    let _envCurrentFile = ".env";

    async function _envLoadFiles() {
      try {
        const r = await fetch("/env/files");
        const d = await r.json();
        const sel = $("env-file-select");
        if (!sel) return;
        const existing = sel.value;
        sel.innerHTML = d.files.length
          ? d.files.map(f => `<option value="${escHtmlSimple(f)}">${escHtmlSimple(f)}</option>`).join("")
          : `<option value=".env">.env</option>`;
        if (d.files.includes(existing)) sel.value = existing;
      } catch (_) {}
    }

    async function _envLoadVars(file) {
      _envCurrentFile = file || _envCurrentFile;
      const list = $("env-vars-list");
      if (!list) return;
      list.innerHTML = `<div style="color:var(--text-dim);font-size:11px">Loading…</div>`;
      try {
        const r = await fetch(`/env/vars?file=${encodeURIComponent(_envCurrentFile)}`);
        const d = await r.json();
        if (!d.exists || !d.vars.length) {
          list.innerHTML = `<div style="color:var(--text-dim);font-size:11px">No variables found in <code>${escHtmlSimple(_envCurrentFile)}</code>.</div>`;
          return;
        }
        list.innerHTML = d.vars.map(v => `
          <div class="env-var-row" data-key="${escHtmlSimple(v.key)}" style="display:flex;align-items:center;gap:4px;padding:5px 6px;background:var(--surface);border-radius:4px;border:1px solid var(--border)">
            <span style="font-family:var(--font-mono);font-size:11px;font-weight:bold;flex:0 0 auto;min-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtmlSimple(v.key)}">${escHtmlSimple(v.key)}</span>
            <span style="color:var(--text-dim);margin:0 2px">=</span>
            <input class="env-val-input" data-key="${escHtmlSimple(v.key)}" type="text" value="${escHtmlSimple(v.value)}"
              style="flex:1;font-family:var(--font-mono);font-size:11px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:3px;padding:3px 5px;min-width:0" />
            <button class="btn-env-save-inline" data-key="${escHtmlSimple(v.key)}" title="Save" style="font-size:10px;padding:2px 5px">✔</button>
            <button class="btn-env-del" data-key="${escHtmlSimple(v.key)}" title="Delete" style="font-size:10px;padding:2px 5px;color:var(--danger,#f44336)">🗑</button>
          </div>
        `).join("");

        list.querySelectorAll(".btn-env-save-inline").forEach(btn => {
          btn.addEventListener("click", async () => {
            const key = btn.dataset.key;
            const valInput = list.querySelector(`.env-val-input[data-key="${key}"]`);
            const val = valInput ? valInput.value : "";
            await fetch("/env/var", {
              method: "POST", headers: {"Content-Type":"application/json"},
              body: JSON.stringify({ file: _envCurrentFile, key, value: val }),
            });
            _showToast?.(`${key} saved`);
          });
        });
        list.querySelectorAll(".btn-env-del").forEach(btn => {
          btn.addEventListener("click", async () => {
            const key = btn.dataset.key;
            if (!confirm(`Delete ${key}?`)) return;
            const r2 = await fetch(`/env/var?file=${encodeURIComponent(_envCurrentFile)}&key=${encodeURIComponent(key)}`, {
              method: "DELETE",
            });
            if (r2.ok) { _showToast?.(`${key} deleted`); _envLoadVars(); }
          });
        });
      } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">${escHtmlSimple(e.message)}</div>`;
      }
    }

    document.getElementById("panel-envvars")?.addEventListener("sw-panel-shown", async () => {
      await _envLoadFiles();
      _envLoadVars();
    });

    $("btn-env-refresh")?.addEventListener("click", async () => { await _envLoadFiles(); _envLoadVars(); });
    $("env-file-select")?.addEventListener("change", e => _envLoadVars(e.target.value));

    $("btn-env-add")?.addEventListener("click", () => {
      $("env-add-form")?.classList.remove("hidden");
      $("env-new-key")?.focus();
    });
    $("btn-env-cancel-var")?.addEventListener("click", () => $("env-add-form")?.classList.add("hidden"));
    $("btn-env-save-var")?.addEventListener("click", async () => {
      const key = $("env-new-key")?.value.trim() ?? "";
      const val = $("env-new-val")?.value ?? "";
      const comment = $("env-new-comment")?.value.trim() ?? "";
      if (!key) { _showToast?.("KEY is required"); return; }
      const r = await fetch("/env/var", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ file: _envCurrentFile, key, value: val, comment }),
      });
      if (r.ok) {
        $("env-add-form")?.classList.add("hidden");
        if ($("env-new-key")) $("env-new-key").value = "";
        if ($("env-new-val")) $("env-new-val").value = "";
        if ($("env-new-comment")) $("env-new-comment").value = "";
        _showToast?.(`${key} saved`);
        _envLoadVars();
      }
    });

    $("btn-env-export")?.addEventListener("click", async () => {
      const r = await fetch(`/env/export?file=${encodeURIComponent(_envCurrentFile)}`);
      if (!r.ok) { _showToast?.("Export failed"); return; }
      const d = await r.json();
      const blob = new Blob([d.content], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = _envCurrentFile.split("/").pop() || ".env";
      a.click();
      URL.revokeObjectURL(a.href);
    });

    $("btn-env-import")?.addEventListener("click", () => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = ".env,text/plain";
      inp.onchange = async () => {
        const file = inp.files[0]; if (!file) return;
        const content = await file.text();
        const r = await fetch("/env/import", {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ file: _envCurrentFile, content }),
        });
        if (r.ok) { const d = await r.json(); _showToast?.(`Imported ${d.vars_imported} vars`); _envLoadVars(); }
      };
      inp.click();
    });
  })();

  // ── Phase 45: API Client / HTTP Playground panel ──────────────────────────
  (function () {
    let _apcColsVisible = false;

    function _apcParseHeaders(raw) {
      const h = {};
      for (const line of raw.split("\n")) {
        const idx = line.indexOf(":");
        if (idx > 0) {
          const k = line.slice(0, idx).trim();
          const v = line.slice(idx + 1).trim();
          if (k) h[k] = v;
        }
      }
      return h;
    }

    function _apcFormatResponse(d) {
      const statusColor = d.status_code < 300 ? "var(--success,#4caf50)" : d.status_code < 400 ? "#ff9800" : "var(--danger,#f44336)";
      let bodyDisplay = d.body ?? "";
      // Pretty-print JSON
      try {
        const parsed = JSON.parse(bodyDisplay);
        bodyDisplay = JSON.stringify(parsed, null, 2);
      } catch (_) {}
      return `
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-weight:bold;font-size:13px;color:${statusColor}">${d.status_code}</span>
          <span style="font-size:11px;color:var(--text-dim)">${escHtmlSimple(d.reason_phrase ?? "")}</span>
          <span style="font-size:10px;color:var(--text-dim);margin-left:auto">${d.elapsed_ms}ms</span>
        </div>
        <details style="margin-bottom:6px">
          <summary style="font-size:11px;cursor:pointer;color:var(--text-dim)">Response Headers (${Object.keys(d.headers ?? {}).length})</summary>
          <pre style="font-size:10px;font-family:var(--font-mono);background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:5px;overflow-x:auto;margin-top:4px;max-height:120px">${escHtmlSimple(Object.entries(d.headers ?? {}).map(([k,v]) => `${k}: ${v}`).join("\n"))}</pre>
        </details>
        <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">Body:</div>
        <pre style="font-size:10px;font-family:var(--font-mono);background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:5px;overflow:auto;max-height:260px;white-space:pre-wrap;word-break:break-all">${escHtmlSimple(bodyDisplay)}</pre>
        <button id="btn-apc-copy-body" style="font-size:11px;padding:3px 8px;margin-top:4px">📋 Copy Body</button>
      `;
    }

    async function _apcLoadCollections() {
      const list = $("apc-col-list");
      if (!list) return;
      try {
        const r = await fetch("/apiclient/collections");
        const d = await r.json();
        if (!d.collections.length) {
          list.innerHTML = `<div style="font-size:11px;color:var(--text-dim)">No collections yet. Click + New to create one.</div>`;
          return;
        }
        list.innerHTML = d.collections.map(c => `
          <div style="padding:5px 6px;background:var(--surface);border-radius:4px;border:1px solid var(--border)">
            <div style="display:flex;align-items:center;justify-content:space-between">
              <button class="btn-apc-col-toggle" data-col="${escHtmlSimple(c.name)}" style="font-size:11px;font-weight:bold;background:none;border:none;color:var(--text);cursor:pointer;text-align:left;padding:0">▶ ${escHtmlSimple(c.name)} <span style="font-size:10px;color:var(--text-dim)">(${c.request_count})</span></button>
              <button class="btn-apc-col-del" data-col="${escHtmlSimple(c.name)}" style="font-size:10px;padding:1px 5px;color:var(--danger,#f44336)" title="Delete collection">🗑</button>
            </div>
            <div class="apc-col-requests hidden" id="apc-col-reqs-${escHtmlSimple(c.name)}" style="margin-top:5px;display:flex;flex-direction:column;gap:3px"></div>
          </div>
        `).join("");

        list.querySelectorAll(".btn-apc-col-toggle").forEach(btn => {
          btn.addEventListener("click", async () => {
            const colName = btn.dataset.col;
            const reqs = document.getElementById(`apc-col-reqs-${colName}`);
            if (!reqs) return;
            const isHidden = reqs.classList.toggle("hidden");
            btn.textContent = `${isHidden ? "▶" : "▾"} ${colName} `;
            if (!isHidden && !reqs.children.length) {
              const r2 = await fetch(`/apiclient/collection/${encodeURIComponent(colName)}`);
              const d2 = await r2.json();
              const reqlList = Object.values(d2.requests ?? {});
              reqs.innerHTML = reqlList.length
                ? reqlList.map(req => `
                  <div style="display:flex;align-items:center;gap:4px;padding:3px 5px;border-radius:3px;background:var(--bg)">
                    <span style="font-size:10px;font-weight:bold;color:${req.method==='GET'?'#4caf50':req.method==='POST'?'#2196f3':req.method==='DELETE'?'#f44336':'#ff9800'};min-width:40px">${req.method}</span>
                    <button class="btn-apc-load-req" data-col="${escHtmlSimple(colName)}" data-req="${escHtmlSimple(req.name)}" style="flex:1;text-align:left;font-size:11px;background:none;border:none;color:var(--text);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtmlSimple(req.name)}</button>
                    <button class="btn-apc-del-req" data-col="${escHtmlSimple(colName)}" data-req="${escHtmlSimple(req.name)}" style="font-size:10px;padding:1px 4px;color:var(--danger,#f44336)">✕</button>
                  </div>
                `).join("")
                : `<div style="font-size:10px;color:var(--text-dim);padding:3px 5px">No saved requests</div>`;

              reqs.querySelectorAll(".btn-apc-load-req").forEach(rb => {
                rb.addEventListener("click", async () => {
                  const r3 = await fetch(`/apiclient/collection/${encodeURIComponent(rb.dataset.col)}`);
                  const d3 = await r3.json();
                  const saved = d3.requests[rb.dataset.req];
                  if (!saved) return;
                  const methodSel = $("apc-method");
                  if (methodSel) methodSel.value = saved.method;
                  const urlInp = $("apc-url");
                  if (urlInp) urlInp.value = saved.url;
                  const headersTA = $("apc-headers");
                  if (headersTA) headersTA.value = Object.entries(saved.headers ?? {}).map(([k,v]) => `${k}: ${v}`).join("\n");
                  const bodyTA = $("apc-body");
                  if (bodyTA) bodyTA.value = saved.body ?? "";
                  const bodyTypeSel = $("apc-body-type");
                  if (bodyTypeSel) bodyTypeSel.value = saved.body_type ?? "raw";
                  _showToast?.("Request loaded");
                });
              });

              reqs.querySelectorAll(".btn-apc-del-req").forEach(rb => {
                rb.addEventListener("click", async () => {
                  if (!confirm(`Delete request '${rb.dataset.req}'?`)) return;
                  await fetch(`/apiclient/collection/${encodeURIComponent(rb.dataset.col)}/request/${encodeURIComponent(rb.dataset.req)}`, { method: "DELETE" });
                  reqs.innerHTML = "";
                  _showToast?.("Request deleted");
                  _apcLoadCollections();
                });
              });
            }
          });
        });

        list.querySelectorAll(".btn-apc-col-del").forEach(btn => {
          btn.addEventListener("click", async () => {
            const colName = btn.dataset.col;
            if (!confirm(`Delete collection '${colName}' and all its requests?`)) return;
            await fetch(`/apiclient/collection/${encodeURIComponent(colName)}`, { method: "DELETE" });
            _showToast?.("Collection deleted");
            _apcLoadCollections();
          });
        });
      } catch (e) {
        list.innerHTML = `<div style="color:var(--danger)">${escHtmlSimple(e.message)}</div>`;
      }
    }

    // Tab switching
    document.querySelectorAll(".apc-tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".apc-tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const tab = btn.dataset.apcTab;
        $("apc-tab-headers")?.classList.toggle("hidden", tab !== "headers");
        $("apc-tab-body")?.classList.toggle("hidden", tab !== "body");
      });
    });

    // Send request
    $("btn-apc-send")?.addEventListener("click", async () => {
      const method = $("apc-method")?.value ?? "GET";
      const url = $("apc-url")?.value.trim() ?? "";
      const headersRaw = $("apc-headers")?.value ?? "";
      const body = $("apc-body")?.value ?? "";
      const bodyType = $("apc-body-type")?.value ?? "raw";
      const respEl = $("apc-response");
      if (!url) { if (respEl) respEl.innerHTML = `<div style="color:var(--danger)">URL is required</div>`; return; }
      if (respEl) respEl.innerHTML = `<div style="color:var(--text-dim)">Sending…</div>`;
      try {
        const r = await fetch("/apiclient/send", {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ method, url, headers: _apcParseHeaders(headersRaw), body, body_type: bodyType }),
        });
        const d = await r.json();
        if (!r.ok) { if (respEl) respEl.innerHTML = `<div style="color:var(--danger)">${escHtmlSimple(d.detail ?? "Error")}</div>`; return; }
        if (respEl) { respEl.innerHTML = _apcFormatResponse(d); }
        const bodyText = d.body ?? "";
        document.getElementById("btn-apc-copy-body")?.addEventListener("click", () => {
          navigator.clipboard.writeText(bodyText).then(() => _showToast?.("Body copied!"));
        });
      } catch (e) {
        if (respEl) respEl.innerHTML = `<div style="color:var(--danger)">Error: ${escHtmlSimple(e.message)}</div>`;
      }
    });

    // Toggle collections panel
    $("btn-apc-collections")?.addEventListener("click", async () => {
      _apcColsVisible = !_apcColsVisible;
      $("apc-collections-view")?.classList.toggle("hidden", !_apcColsVisible);
      if (_apcColsVisible) await _apcLoadCollections();
    });

    // New collection
    $("btn-apc-new-col")?.addEventListener("click", async () => {
      const name = prompt("Collection name:");
      if (!name?.trim()) return;
      const r = await fetch("/apiclient/collection", {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ name: name.trim() }),
      });
      if (r.ok) { _showToast?.("Collection created"); _apcLoadCollections(); }
      else { const d = await r.json(); _showToast?.(`Error: ${d.detail}`); }
    });

    // Save current request to collection
    $("btn-apc-save-req")?.addEventListener("click", async () => {
      const r0 = await fetch("/apiclient/collections");
      const d0 = await r0.json();
      if (!d0.collections.length) {
        _showToast?.("Create a collection first (click 📂)");
        return;
      }
      const colName = d0.collections.length === 1
        ? d0.collections[0].name
        : prompt(`Collection (${d0.collections.map(c => c.name).join(", ")}):`);
      if (!colName) return;
      const reqName = prompt("Request name:");
      if (!reqName?.trim()) return;
      const method = $("apc-method")?.value ?? "GET";
      const url = $("apc-url")?.value.trim() ?? "";
      const headersRaw = $("apc-headers")?.value ?? "";
      const body = $("apc-body")?.value ?? "";
      const bodyType = $("apc-body-type")?.value ?? "raw";
      const r2 = await fetch(`/apiclient/collection/${encodeURIComponent(colName)}/request`, {
        method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ name: reqName.trim(), method, url, headers: _apcParseHeaders(headersRaw), body, body_type: bodyType }),
      });
      if (r2.ok) { _showToast?.(`Saved to '${colName}'`); if (_apcColsVisible) _apcLoadCollections(); }
      else { const d2 = await r2.json(); _showToast?.(`Error: ${d2.detail}`); }
    });
  })();

  // ── Phase 41: Diff & Patch Tool panel ───────────────────────────────────
  (function () {
    function _dpSetMode(mode) {
      $("dp-diff-mode")?.classList.toggle("hidden", mode !== "diff");
      $("dp-patch-mode")?.classList.toggle("hidden", mode !== "patch");
      document.querySelectorAll(".dp-mode-btn").forEach(b => b.classList.remove("active"));
      $(mode === "diff" ? "btn-dp-mode-diff" : "btn-dp-mode-patch")?.classList.add("active");
    }
    $("btn-dp-mode-diff")?.addEventListener("click", () => _dpSetMode("diff"));
    $("btn-dp-mode-patch")?.addEventListener("click", () => _dpSetMode("patch"));

    $("btn-dp-diff")?.addEventListener("click", async () => {
      const orig     = $("dp-orig")?.value ?? "";
      const modified = $("dp-modified")?.value ?? "";
      const out      = $("dp-output");
      if (!out) return;
      out.innerHTML = `<div style="color:var(--text-dim)">Computing…</div>`;
      try {
        const res  = await fetch("/diff", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ original: orig, modified }),
        });
        const data = await res.json();
        if (!data.has_diff) {
          out.innerHTML = `<div style="color:var(--text-dim)">Files are identical.</div>`;
          return;
        }
        out.innerHTML = `
          <div style="margin-bottom:4px;font-size:11px;color:var(--text-dim)">${data.changed_lines} changed line(s)</div>
          <pre id="dp-patch-output" style="font-size:10px;font-family:var(--font-mono);background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px;overflow-x:auto;white-space:pre;max-height:300px">${escHtmlSimple(data.patch)}</pre>
          <button id="btn-dp-copy-patch" style="font-size:11px;padding:3px 8px;margin-top:4px">📋 Copy Patch</button>
        `;
        const patchText = data.patch;
        document.getElementById("btn-dp-copy-patch")?.addEventListener("click", () => {
          navigator.clipboard.writeText(patchText).then(() => _showToast?.("Patch copied!"));
        });
      } catch (e) {
        out.innerHTML = `<div style="color:var(--danger)">Error: ${escHtmlSimple(e.message)}</div>`;
      }
    });

    $("btn-dp-patch")?.addEventListener("click", async () => {
      const orig  = $("dp-patch-orig")?.value ?? "";
      const patch = $("dp-patch-text")?.value ?? "";
      const out   = $("dp-output");
      if (!out) return;
      if (!patch.trim()) { out.innerHTML = `<div style="color:var(--danger)">Patch text is empty.</div>`; return; }
      out.innerHTML = `<div style="color:var(--text-dim)">Applying…</div>`;
      try {
        const res  = await fetch("/patch", {
          method: "POST",
          headers: {"Content-Type":"application/json"},
          body: JSON.stringify({ original: orig, patch }),
        });
        const data = await res.json();
        if (!res.ok) { out.innerHTML = `<div style="color:var(--danger)">${escHtmlSimple(data.detail || "Error")}</div>`; return; }
        out.innerHTML = `
          <div style="margin-bottom:4px;font-size:11px;color:var(--success,#4caf50)">✔ Patch applied successfully</div>
          <textarea id="dp-result-text" rows="8" readonly style="width:100%;font-size:11px;font-family:var(--font-mono);background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:5px;resize:vertical">${escHtmlSimple(data.result)}</textarea>
          <button id="btn-dp-copy-result" style="font-size:11px;padding:3px 8px;margin-top:4px">📋 Copy Result</button>
        `;
        const resultText = data.result;
        document.getElementById("btn-dp-copy-result")?.addEventListener("click", () => {
          navigator.clipboard.writeText(resultText).then(() => _showToast?.("Result copied!"));
        });
      } catch (e) {
        out.innerHTML = `<div style="color:var(--danger)">Error: ${escHtmlSimple(e.message)}</div>`;
      }
    });
  })();

  // ── Phase 46: AI Suggestions Timeline panel ───────────────────────────────
  (function () {
    async function loadTimelinePanel() {
      const container = $("timeline-panel-content");
      if (!container) return;
      container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Loading…</div>';
      try {
        const res = await fetch("/ai/timeline?limit=100");
        const data = await res.json();
        const events = data.events || [];
        if (!events.length) {
          container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">No AI timeline events yet.<br>Events are logged automatically when you use AI features.</div>';
          return;
        }
        container.innerHTML = events.map(ev => {
          const accepted = ev.accepted === true ? `<span class="timeline-event-accepted">✔ Accepted</span>`
                         : ev.accepted === false ? `<span class="timeline-event-rejected">✕ Rejected</span>`
                         : `<span style="color:var(--text-dim);font-size:10px">Pending</span>`;
          const ts = ev.ts ? new Date(ev.ts).toLocaleString() : "";
          const fileEl = ev.file_path ? `<div class="timeline-event-file">📄 ${escHtmlSimple(ev.file_path)}</div>` : "";
          const detailEl = ev.detail ? `<details style="margin-top:4px"><summary style="font-size:10px;cursor:pointer;color:var(--text-dim)">View detail</summary><pre style="font-size:10px;white-space:pre-wrap;word-break:break-all;margin-top:3px;background:var(--bg);padding:5px;border-radius:3px;max-height:120px;overflow-y:auto">${escHtmlSimple(ev.detail.slice(0, 800))}</pre></details>` : "";
          return `
            <div class="timeline-event" data-id="${ev.id}" style="margin-bottom:6px">
              <div class="timeline-event-header">
                <span class="timeline-event-type">${escHtmlSimple(ev.event_type)}</span>
                <span class="timeline-event-summary">${escHtmlSimple(ev.summary)}</span>
              </div>
              ${fileEl}
              <div style="display:flex;align-items:center;justify-content:space-between;margin-top:3px">
                ${accepted}
                <span class="timeline-event-ts">${escHtmlSimple(ts)}</span>
              </div>
              ${detailEl}
              <div class="timeline-event-actions">
                <button onclick="_timelineAccept(${ev.id})" style="font-size:10px;padding:2px 6px" title="Mark accepted">✔</button>
                <button onclick="_timelineReject(${ev.id})" style="font-size:10px;padding:2px 6px;color:var(--danger)" title="Mark rejected">✕</button>
              </div>
            </div>
          `;
        }).join("");
      } catch (e) {
        container.innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${escHtmlSimple(e.message)}</div>`;
      }
    }

    window._timelineAccept = async function(id) {
      await fetch(`/ai/timeline/${id}?accepted=true`, { method: "PATCH" });
      loadTimelinePanel();
    };
    window._timelineReject = async function(id) {
      await fetch(`/ai/timeline/${id}?accepted=false`, { method: "PATCH" });
      loadTimelinePanel();
    };

    $("btn-timeline-refresh")?.addEventListener("click", loadTimelinePanel);
    $("btn-timeline-clear")?.addEventListener("click", async () => {
      if (!confirm("Clear all AI timeline events?")) return;
      await fetch("/ai/timeline/clear", { method: "DELETE" });
      loadTimelinePanel();
    });

    // Expose so panel switcher can call it
    window.loadTimelinePanel = loadTimelinePanel;

    // Auto-log AI events: intercept chat submit to record suggestions
    // (non-intrusive: wraps sendChat to record events after AI responds)
  })();

  // ── Phase 47: Project Health Dashboard panel ──────────────────────────────
  (function () {
    async function loadHealthPanel() {
      const container = $("healthdash-panel-content");
      if (!container) return;
      container.innerHTML = '<div style="color:var(--text-dim);font-size:11px;padding:4px">Loading…</div>';
      try {
        const res = await fetch("/project/health");
        const d = await res.json();
        const statusClass = `health-status-${d.status}`;
        const scoreColor = d.score >= 90 ? "#4caf50" : d.score >= 70 ? "#8bc34a" : d.score >= 50 ? "#ff9800" : "var(--danger)";

        const subsystems = [
          { name: "AI Timeline", value: `${d.ai_timeline.total_events} events · ${d.ai_timeline.acceptance_rate_pct}% accepted` },
          { name: "Task Queue", value: `${d.task_queue.pending} pending / ${d.task_queue.total} total` },
          { name: "Notifications", value: `${d.notifications.unread} unread / ${d.notifications.total} total` },
          { name: "Agents", value: `${d.agents.running} running / ${d.agents.total} total` },
          { name: "Cron Jobs", value: `${d.cron_jobs.active} active / ${d.cron_jobs.total} total` },
          { name: "Feature Flags", value: `${d.feature_flags.enabled} enabled / ${d.feature_flags.total} total` },
          { name: "Snippets", value: `${d.snippets.total} saved` },
          { name: "Brainstorm Sessions", value: `${d.brainstorm_sessions.total} sessions` },
          { name: "Audit Log", value: `${d.audit_log.total_entries} entries` },
        ];

        container.innerHTML = `
          <div class="health-score-ring">
            <div class="health-score-value" style="color:${scoreColor}">${d.score}</div>
            <div class="health-score-label ${statusClass}">/ 100 — ${d.status.replace("_", " ")}</div>
            <div style="font-size:10px;color:var(--text-dim);margin-top:4px">Updated: ${new Date(d.generated_at).toLocaleTimeString()}</div>
          </div>
          <div style="font-size:11px;font-weight:600;color:var(--text-dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px">Subsystems</div>
          ${subsystems.map(s => `
            <div class="health-subsystem">
              <span class="health-subsystem-name">${escHtmlSimple(s.name)}</span>
              <span class="health-subsystem-value">${escHtmlSimple(s.value)}</span>
            </div>
          `).join("")}
        `;
      } catch (e) {
        container.innerHTML = `<div style="color:var(--danger);font-size:11px">Error: ${escHtmlSimple(e.message)}</div>`;
      }
    }

    $("btn-health-refresh")?.addEventListener("click", loadHealthPanel);
    window.loadHealthPanel = loadHealthPanel;
  })();

  // ── Phase 48: Code Documentation Generator panel ──────────────────────────
  (function () {
    const resultEl = $("docgen-result");

    async function generateDoc() {
      const code = $("docgen-code")?.value.trim() || "";
      if (!code) { if (resultEl) resultEl.innerHTML = '<span style="color:var(--danger)">Paste some code first.</span>'; return; }
      const language = $("docgen-language")?.value || "";
      const style = $("docgen-style")?.value || "docstring";
      const context = $("docgen-context")?.value || "";
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Generating…</span>';
      try {
        const res = await fetch("/docgen/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, language, style, context }),
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Error");
        if (resultEl) resultEl.innerHTML = `
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:4px">Language: <b>${escHtmlSimple(d.language)}</b> · Style: <b>${escHtmlSimple(style)}</b></div>
          <pre style="background:var(--bg-alt,var(--bg));border:1px solid var(--border);border-radius:4px;padding:8px;font-size:11px;overflow-x:auto;white-space:pre-wrap">${escHtmlSimple(d.documentation)}</pre>
          <button id="btn-docgen-copy" style="font-size:10px;padding:2px 8px;margin-top:4px">📋 Copy</button>
        `;
        $("btn-docgen-copy")?.addEventListener("click", () => {
          navigator.clipboard.writeText(d.documentation).then(() => _showToast?.("Copied!"));
        });
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    async function showDocHistory() {
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Loading history…</span>';
      try {
        const res = await fetch("/docgen/history?limit=20");
        const d = await res.json();
        if (!d.entries || d.entries.length === 0) {
          if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">No history yet.</span>';
          return;
        }
        if (resultEl) resultEl.innerHTML = d.entries.map(e => `
          <div style="border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:4px">
            <div style="font-size:10px;color:var(--text-dim)">#${e.id} · ${escHtmlSimple(e.language)} · ${escHtmlSimple(e.style)} · ${new Date(e.generated_at).toLocaleTimeString()}</div>
            <pre style="margin:4px 0 0;font-size:10px;white-space:pre-wrap;overflow-x:auto">${escHtmlSimple(e.documentation.slice(0, 300))}${e.documentation.length > 300 ? "…" : ""}</pre>
          </div>
        `).join("");
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    $("btn-docgen-generate")?.addEventListener("click", generateDoc);
    $("btn-docgen-history")?.addEventListener("click", showDocHistory);
  })();

  // ── Phase 49: Dependency Analyzer panel ───────────────────────────────────
  (function () {
    const resultEl = $("deps-result");

    async function analyzeProject() {
      const projectPath = $("deps-project-path")?.value.trim() || "";
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Analyzing…</span>';
      try {
        const res = await fetch("/deps/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_path: projectPath }),
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Error");
        const r = d.report;
        if (!r.manifests || r.manifests.length === 0) {
          if (resultEl) resultEl.innerHTML = `<span style="color:var(--text-dim)">No dependency manifests found in <b>${escHtmlSimple(r.project_path)}</b>.</span>`;
          return;
        }
        if (resultEl) resultEl.innerHTML = `
          <div style="font-size:10px;color:var(--text-dim);margin-bottom:6px">
            Report #${r.id} · ${escHtmlSimple(r.project_path)} · ${r.total_dependencies} deps across ${r.manifest_count} file(s)
          </div>
          ${r.manifests.map(m => `
            <div style="border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:6px">
              <div style="font-size:11px;font-weight:bold;margin-bottom:4px">📄 ${escHtmlSimple(m.file)} <span style="font-weight:normal;color:var(--text-dim)">[${escHtmlSimple(m.ecosystem)}]</span></div>
              ${m.dependencies.map(dep => `
                <div style="display:flex;justify-content:space-between;font-size:10px;padding:2px 0;border-bottom:1px solid var(--border)">
                  <span>${escHtmlSimple(dep.name)}</span>
                  <span style="color:var(--text-dim)">${escHtmlSimple(dep.version || "any")}</span>
                </div>
              `).join("")}
            </div>
          `).join("")}
        `;
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    async function showReports() {
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Loading reports…</span>';
      try {
        const res = await fetch("/deps/reports?limit=10");
        const d = await res.json();
        if (!d.reports || d.reports.length === 0) {
          if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">No reports yet.</span>';
          return;
        }
        if (resultEl) resultEl.innerHTML = d.reports.map(r => `
          <div style="border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:4px;font-size:11px">
            <span style="font-weight:bold">#${r.id}</span> — ${escHtmlSimple(r.project_path)} · ${r.total_dependencies} deps · ${new Date(r.analyzed_at).toLocaleString()}
          </div>
        `).join("");
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    $("btn-deps-analyze")?.addEventListener("click", analyzeProject);
    $("btn-deps-reports")?.addEventListener("click", showReports);
  })();

  // ── Phase 52: Test Runner & Coverage Dashboard panel ─────────────────────
  (function () {
    const resultEl = $("testrunner-result");

    async function loadTestRunnerPanel() {
      if (resultEl) resultEl.innerHTML = '';
    }

    async function runTests() {
      const projectPath = $("testrunner-project-path")?.value.trim() || "";
      const framework = $("testrunner-framework")?.value || "pytest";
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Running tests…</span>';
      try {
        const res = await fetch("/testrunner/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_path: projectPath, framework }),
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || "Error");
        const r = d.report;
        const statusColor = r.status === "passed" ? "#4caf50" : r.status === "timeout" ? "#ff9800" : "var(--danger)";
        const s = r.summary;
        if (resultEl) resultEl.innerHTML = `
          <div style="border:1px solid var(--border);border-radius:4px;padding:8px;margin-top:4px">
            <div style="font-size:11px;font-weight:600;color:${statusColor};margin-bottom:4px">
              ${r.status.toUpperCase()} · exit ${r.exit_code} · ${escHtmlSimple(r.framework)}
            </div>
            <div style="font-size:10px;color:var(--text-dim);margin-bottom:6px">
              ✅ ${s.passed} passed &nbsp; ❌ ${s.failed} failed &nbsp; ⚠️ ${s.errors} errors &nbsp; ⏭ ${s.skipped} skipped
            </div>
            <details>
              <summary style="font-size:10px;cursor:pointer;color:var(--text-dim)">stdout / stderr</summary>
              <pre style="font-size:10px;white-space:pre-wrap;margin-top:4px;overflow-x:auto;max-height:200px;overflow-y:auto;background:var(--bg-3,var(--bg));padding:6px;border-radius:4px">${escHtmlSimple((r.stdout + (r.stderr ? "\n--- stderr ---\n" + r.stderr : "")).slice(0, 4000))}</pre>
            </details>
          </div>
        `;
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    async function showTestReports() {
      if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
      try {
        const res = await fetch("/testrunner/reports?limit=20");
        const d = await res.json();
        if (!d.reports || d.reports.length === 0) {
          if (resultEl) resultEl.innerHTML = '<span style="color:var(--text-dim)">No reports yet.</span>';
          return;
        }
        if (resultEl) resultEl.innerHTML = d.reports.map(r => {
          const statusColor = r.status === "passed" ? "#4caf50" : r.status === "timeout" ? "#ff9800" : "var(--danger)";
          const s = r.summary;
          return `
            <div style="border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:4px">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-size:10px;font-weight:600;color:${statusColor}">#${r.id} ${r.status.toUpperCase()}</span>
                <button data-del-report="${r.id}" style="font-size:9px;color:var(--danger);padding:1px 4px">✕</button>
              </div>
              <div style="font-size:10px;color:var(--text-dim)">${escHtmlSimple(r.framework)} · ${escHtmlSimple(r.project_path)} · ✅${s.passed} ❌${s.failed} ⏭${s.skipped}</div>
              <div style="font-size:9px;color:var(--text-dim)">${new Date(r.started_at).toLocaleString()}</div>
            </div>
          `;
        }).join("");
        resultEl.querySelectorAll("[data-del-report]").forEach(btn => {
          btn.addEventListener("click", async () => {
            await fetch(`/testrunner/report/${btn.dataset.delReport}`, { method: "DELETE" });
            showTestReports();
          });
        });
      } catch (e) {
        if (resultEl) resultEl.innerHTML = `<span style="color:var(--danger)">${escHtmlSimple(e.message)}</span>`;
      }
    }

    $("btn-testrunner-run")?.addEventListener("click", runTests);
    $("btn-testrunner-reports")?.addEventListener("click", showTestReports);
    window.loadTestRunnerPanel = loadTestRunnerPanel;
  })();

  // ── Phase 53: Terminal Manager panel ─────────────────────────────────────
  (function () {
    let _activeSessionId = null;

    async function loadTerminalPanel() {
      await refreshSessionsList();
    }

    async function refreshSessionsList() {
      const listEl = $("terminal-sessions-list");
      if (!listEl) return;
      try {
        const res = await fetch("/terminal/sessions");
        const d = await res.json();
        if (d.sessions.length === 0) {
          listEl.innerHTML = '<div style="color:var(--text-dim);font-size:11px">No sessions. Click ＋ to create one.</div>';
          return;
        }
        listEl.innerHTML = d.sessions.map(s => `
          <div style="border:1px solid var(--border);border-radius:4px;padding:6px;margin-bottom:4px;cursor:pointer;display:flex;justify-content:space-between;align-items:center"
               data-open-session="${escHtmlSimple(s.id)}">
            <div>
              <div style="font-size:11px;font-weight:600">${escHtmlSimple(s.name)}</div>
              <div style="font-size:9px;color:var(--text-dim)">${escHtmlSimple(s.id)}</div>
            </div>
            <button data-del-session="${escHtmlSimple(s.id)}" style="font-size:9px;color:var(--danger);padding:1px 4px">✕</button>
          </div>
        `).join("");
        listEl.querySelectorAll("[data-open-session]").forEach(el => {
          el.addEventListener("click", (e) => {
            if (e.target.dataset.delSession) return;
            openSession(el.dataset.openSession);
          });
        });
        listEl.querySelectorAll("[data-del-session]").forEach(btn => {
          btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            await fetch(`/terminal/session/${encodeURIComponent(btn.dataset.delSession)}`, { method: "DELETE" });
            if (_activeSessionId === btn.dataset.delSession) closeSessionView();
            await refreshSessionsList();
          });
        });
      } catch (e) {
        if (listEl) listEl.innerHTML = `<span style="color:var(--danger);font-size:11px">${escHtmlSimple(e.message)}</span>`;
      }
    }

    async function openSession(sessionId) {
      _activeSessionId = sessionId;
      const viewEl = $("terminal-session-view");
      const titleEl = $("terminal-session-title");
      if (viewEl) { viewEl.style.display = "flex"; viewEl.classList.remove("hidden"); }
      if (titleEl) titleEl.textContent = `Session: ${sessionId}`;
      await refreshSessionOutput();
      $("terminal-cmd-input")?.focus();
    }

    function closeSessionView() {
      _activeSessionId = null;
      const viewEl = $("terminal-session-view");
      if (viewEl) { viewEl.style.display = "none"; viewEl.classList.add("hidden"); }
    }

    async function refreshSessionOutput() {
      if (!_activeSessionId) return;
      const outputEl = $("terminal-output");
      if (!outputEl) return;
      try {
        const res = await fetch(`/terminal/session/${encodeURIComponent(_activeSessionId)}`);
        if (!res.ok) { closeSessionView(); return; }
        const d = await res.json();
        outputEl.innerHTML = d.history.map(h => {
          const exitColor = h.exit_code === 0 ? "#4caf50" : "var(--danger)";
          return `<div style="margin-bottom:4px">` +
            `<span style="color:var(--text-dim);user-select:none">$ </span>` +
            `<span style="color:var(--text);font-weight:600">${escHtmlSimple(h.command)}</span>` +
            (h.stdout ? `\n<span style="white-space:pre-wrap">${escHtmlSimple(h.stdout.trimEnd())}</span>` : "") +
            (h.stderr ? `\n<span style="color:${exitColor};white-space:pre-wrap">${escHtmlSimple(h.stderr.trimEnd())}</span>` : "") +
            `</div>`;
        }).join("");
        outputEl.scrollTop = outputEl.scrollHeight;
      } catch (e) { /* ignore */ }
    }

    async function execCommand() {
      if (!_activeSessionId) return;
      const input = $("terminal-cmd-input");
      const cmd = input?.value.trim();
      if (!cmd) return;
      if (input) input.value = "";
      try {
        await fetch(`/terminal/session/${encodeURIComponent(_activeSessionId)}/exec`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: cmd }),
        });
        await refreshSessionOutput();
      } catch (e) { /* ignore */ }
    }

    $("btn-terminal-new")?.addEventListener("click", async () => {
      const name = prompt("Session name (optional):") || "";
      const res = await fetch("/terminal/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const d = await res.json();
      if (d.success) { await refreshSessionsList(); openSession(d.session_id); }
    });

    $("btn-terminal-refresh")?.addEventListener("click", refreshSessionsList);
    $("btn-terminal-exec")?.addEventListener("click", execCommand);
    $("btn-terminal-close-session")?.addEventListener("click", closeSessionView);

    $("terminal-cmd-input")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") execCommand();
    });

    window.loadTerminalPanel = loadTerminalPanel;
  })();

  // ── UI: Focus Mode & Theme Toggle ────────────────────────────────────────
  (function () {
    // Focus Mode
    const btnFocus = $("btn-focus-mode");
    let _focusMode = false;
    if (btnFocus) {
      btnFocus.addEventListener("click", () => {
        _focusMode = !_focusMode;
        document.body.classList.toggle("focus-mode", _focusMode);
        btnFocus.textContent = _focusMode ? "⛶ Exit Focus" : "⛶ Focus";
        btnFocus.title = _focusMode ? "Exit Focus Mode (Ctrl+Shift+F)" : "Toggle Focus Mode (Ctrl+Shift+F)";
        // Trigger Monaco layout recalculation
        if (state.editor) state.editor.layout();
      });
    }

    // Keyboard shortcut Ctrl+Shift+F
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "F") {
        e.preventDefault();
        btnFocus?.click();
      }
    });

    // Theme Toggle
    const btnTheme = $("btn-theme-toggle");
    let _lightTheme = false;
    if (btnTheme) {
      // Restore saved preference
      if (localStorage.getItem("arbiter-theme") === "light") {
        _lightTheme = true;
        document.body.classList.add("light-theme");
        btnTheme.textContent = "☀️";
        btnTheme.title = "Switch to dark theme";
      }
      btnTheme.addEventListener("click", () => {
        _lightTheme = !_lightTheme;
        document.body.classList.toggle("light-theme", _lightTheme);
        btnTheme.textContent = _lightTheme ? "☀️" : "🌙";
        btnTheme.title = _lightTheme ? "Switch to dark theme" : "Toggle dark/light theme";
        localStorage.setItem("arbiter-theme", _lightTheme ? "light" : "dark");
        // Update Monaco theme
        if (state.editor && typeof monaco !== "undefined") {
          monaco.editor.setTheme(_lightTheme ? "vs" : "arbiter-dark");
        }
      });
    }
  })();

})();

