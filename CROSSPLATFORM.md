# Arbiter — Cross-Platform Evaluation (M8-7)

> **Status:** Evaluation complete. Recommendation: adopt **.NET MAUI** for the
> host application and keep the Python backend unchanged. See the phased plan below.

---

## Current Architecture

| Layer | Technology | Platform |
|---|---|---|
| **HostApp** (UI) | WPF, .NET 9, WebView2 | Windows only |
| **PythonBridge** | FastAPI, Uvicorn (port 8000) | Any OS |
| **ArbiterEngine** | FastAPI, Uvicorn (port 8001) | Any OS |
| **VSIX Extension** | .NET 4.7.2, VS SDK | Windows (VS 2022) |

---

## Option 1 — .NET MAUI (Recommended)

### Pros
- First-party Microsoft cross-platform UI framework (Windows, macOS, iOS, Android).
- WPF code migrates well — XAML syntax is ~80 % compatible.
- `WebView` control available on all platforms → existing Monaco IDE iframe reused as-is.
- Single project, single binary per platform.
- Microsoft actively investing in MAUI (long-term support).

### Cons
- MAUI WebView is less capable than WPF WebView2 on Windows (some Monaco keybindings need adjustment).
- macOS notarisation and codesigning add CI/CD complexity.
- No tray-icon API on non-Windows platforms (use background service + menu bar app instead).

### Migration effort: **Medium** (~2–3 weeks for a solo developer)

#### Key changes required
1. Replace `ArbiterHost.csproj` target framework from `net9.0-windows` to `net9.0`.
2. Replace `UseWPF`/`UseWindowsForms` with `UseMaui`.
3. Port WPF windows → MAUI `ContentPage` / `Shell`.
4. Replace `System.Speech` TTS with `Microsoft.CognitiveServices.Speech` (cross-platform) or
   `AVSpeechSynthesizer` (macOS/iOS) via dependency injection.
5. Replace `DarkTitleBar` P/Invoke with MAUI `Window.TitleBar` API.
6. Replace `NotifyIcon` (tray) with a macOS menu-bar agent or a system-tray NuGet package.
7. `LibGit2Sharp` already works cross-platform — no change needed.
8. `Microsoft.Web.WebView2` → `Microsoft.Maui.Controls.WebView` (MAUI built-in).

---

## Option 2 — Avalonia UI

### Pros
- Open-source, mature, WPF-compatible XAML (closest migration path from WPF).
- Strong community; actively used by JetBrains Rider and other IDEs.
- Custom rendering pipeline — pixel-perfect UI on all platforms including Linux.
- `WebViewControl` available via `Avalonia.WebView` package.

### Cons
- Requires more manual work to achieve native-looking UI per platform.
- `WebViewControl` package is newer and less mature than WPF WebView2.
- No tray-icon OOTB (use `Hardcodet.NotifyIcon.Wpf` fork or `Avalonia.Tray`).

### Migration effort: **Medium** (~3–4 weeks)

---

## Option 3 — Electron / Tauri (JS/Rust host)

Since the primary IDE UI is already Monaco (JavaScript), a JS-native shell
(Electron or Tauri) could host it directly without WPF at all.

| | Electron | Tauri |
|---|---|---|
| Language | Node.js + HTML/CSS | Rust + HTML/CSS |
| Size | ~150 MB | ~10 MB |
| Performance | Good | Excellent |
| Python side-car | Process spawn (same as now) | Process spawn |
| Tray icon | Built-in | Built-in |
| Effort | Low (2 weeks) | Medium (4 weeks, requires Rust knowledge) |

> **Note:** A Tauri or Electron wrapper could be the fastest path to Linux/macOS
> because the Monaco-based GUI (`PythonBridge/gui/`) already runs in the browser.

---

## Python Backend — No Changes Required

The ArbiterEngine and PythonBridge servers are pure Python/FastAPI and already run
unchanged on Windows, macOS, and Linux.

The CLI (`AIEngine/arbiter_cli.py`) is also fully cross-platform.

The Docker image (`Dockerfile` + `docker-compose.yml`) already provides a
one-command Linux deployment.

---

## Phase Plan (MAUI recommendation)

| Phase | Tasks | Effort |
|---|---|---|
| **P1** | Port `HostApp` to MAUI; keep all window logic intact | 2 weeks |
| **P2** | macOS code-signing + DMG packaging | 1 week |
| **P3** | Linux AppImage / Flatpak via `dotnet publish -r linux-x64` | 1 week |
| **P4** | Automated CI matrix (Windows, macOS, Ubuntu) | 3 days |

---

## CI Matrix (proposed `.github/workflows/build-multiplatform.yml`)

```yaml
strategy:
  matrix:
    os: [windows-latest, macos-14, ubuntu-latest]
    include:
      - os: windows-latest
        rid: win-x64
        artifact: ArbiterHost.exe
      - os: macos-14
        rid: osx-arm64
        artifact: ArbiterHost.app
      - os: ubuntu-latest
        rid: linux-x64
        artifact: ArbiterHost
```

---

## Conclusion

| Criterion | MAUI | Avalonia | Electron/Tauri |
|---|---|---|---|
| Migration effort | Medium | Medium | Low |
| Long-term support | High (Microsoft) | High (community) | High |
| Linux support | Good | Excellent | Excellent |
| macOS support | Good | Good | Excellent |
| WPF code reuse | ~80 % | ~85 % | ~10 % |
| WebView quality | Good | Adequate | Excellent |
| **Recommendation** | ✅ Primary | ✅ Alternative | ✅ Fastest path |

For Arbiter's use case — a developer tool with a Monaco-heavy UI — **MAUI** is
the recommended long-term path because it keeps the existing XAML investment and
has Microsoft's full backing. A **Tauri/Electron wrapper** is a viable fast-path
if Linux/macOS support is needed urgently (re-uses existing `app.js` UI directly).
