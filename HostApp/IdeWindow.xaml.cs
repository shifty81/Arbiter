using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using ArbiterHost.BuildInterface;
using ArbiterHost.Utilities;
using Microsoft.Web.WebView2.Core;

namespace ArbiterHost
{
    /// <summary>
    /// Full-screen Monaco IDE window hosted via WebView2.
    /// Provides a native WPF menu bar, toolbar and status bar, and a
    /// bidirectional postMessage bridge so Monaco JS can request native Windows
    /// actions (file pickers, notifications) without any HTTP polling.
    ///
    /// M4-6:  Settings dialog (SettingsWindow)
    /// M4-7:  Build progress via WebSocket streaming from /ws/run
    /// M4-8:  Global keyboard shortcuts (Ctrl+B, F5, Ctrl+Shift+P, Ctrl+T)
    /// M4-9:  Chat side panel toggled via View menu / toolbar
    /// M4-10: System tray icon for background mode
    /// </summary>
    public partial class IdeWindow : Window
    {
        // ── Constants ──────────────────────────────────────────────────────────
        private static string IdeUrl => $"{AppConfig.ApiBaseUrl}/gui/index.html";

        // ── State ──────────────────────────────────────────────────────────────
        private readonly string _projectsRoot;
        private string? _activeProjectPath;
        private BuildManager? _buildManager;
        private static readonly HttpClient _http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };

        // ── M4-7: Build WebSocket ──────────────────────────────────────────────
        private CancellationTokenSource? _buildWsCts;

        // ── M4-10: System Tray icon ────────────────────────────────────────────
        private System.Windows.Forms.NotifyIcon? _trayIcon;

        // ── Constructor ────────────────────────────────────────────────────────
        public IdeWindow()
        {
            InitializeComponent();
            _projectsRoot = Path.Combine(Directory.GetCurrentDirectory(), "Projects");
            Directory.CreateDirectory(_projectsRoot);
            ModeLabel.Text = AppConfig.Mode;
            SetupKeyboardShortcuts();  // M4-8
            SetupTrayIcon();           // M4-10
            _ = PollLlmBackendAsync();
        }

        // ── Dark title bar ─────────────────────────────────────────────────────
        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            DarkTitleBar.Apply(this);
        }

        // ── Window lifetime ────────────────────────────────────────────────────
        private async void Window_Loaded(object sender, RoutedEventArgs e)
        {
            PopulateProjectSelector();
            await InitWebViewAsync();
            _ = PollServerStatusAsync();
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            // Cancel any in-flight build WebSocket before closing.
            _buildWsCts?.Cancel();
        }

        // ── M4-8: Global keyboard shortcuts ───────────────────────────────────
        private void SetupKeyboardShortcuts()
        {
            // Ctrl+B → Build
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => Build_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.B, ModifierKeys.Control)));

            // F5 → Run
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => Run_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.F5)));

            // Ctrl+T → Test
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => Test_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.T, ModifierKeys.Control)));

            // Ctrl+Shift+P → Command palette
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => MenuCommandPalette_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.P, ModifierKeys.Control | ModifierKeys.Shift)));

            // Ctrl+O → Open file
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => OpenFile_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.O, ModifierKeys.Control)));

            // Ctrl+S → Save
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => Save_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.S, ModifierKeys.Control)));

            // Ctrl+` → Toggle chat panel
            InputBindings.Add(new KeyBinding(
                new RelayCommand(_ => MenuToggleChat_Click(this, new RoutedEventArgs())),
                new KeyGesture(Key.OemTilde, ModifierKeys.Control)));
        }

        // ── M4-10: System tray icon setup ─────────────────────────────────────
        private void SetupTrayIcon()
        {
            try
            {
                _trayIcon = new System.Windows.Forms.NotifyIcon
                {
                    Text = "Arbiter IDE",
                    Icon = System.Drawing.SystemIcons.Application,
                    Visible = false,
                };
                var menu = new System.Windows.Forms.ContextMenuStrip();
                menu.Items.Add("Show Arbiter IDE", null, (_, _) => RestoreFromTray());
                menu.Items.Add(new System.Windows.Forms.ToolStripSeparator());
                menu.Items.Add("Exit", null, (_, _) => Application.Current.Shutdown());
                _trayIcon.ContextMenuStrip = menu;
                _trayIcon.DoubleClick += (_, _) => RestoreFromTray();
            }
            catch
            {
                // Non-fatal: tray icon may not be available in all environments.
            }
        }

        private void MinimizeToTray()
        {
            if (_trayIcon != null)
            {
                _trayIcon.Visible = true;
                Hide();
                _trayIcon.ShowBalloonTip(
                    2000, "Arbiter IDE",
                    "Arbiter is running in the background. Double-click to restore.",
                    System.Windows.Forms.ToolTipIcon.Info);
            }
            else
            {
                WindowState = WindowState.Minimized;
            }
        }

        private void RestoreFromTray()
        {
            Show();
            WindowState = WindowState.Normal;
            Activate();
            if (_trayIcon != null)
                _trayIcon.Visible = false;
        }

        protected override void OnStateChanged(EventArgs e)
        {
            // Intercept minimise to send to tray instead (only when tray icon is available).
            if (WindowState == WindowState.Minimized && _trayIcon != null)
            {
                // Delay slightly to let WPF finish the state transition before hiding.
                Dispatcher.BeginInvoke(MinimizeToTray, System.Windows.Threading.DispatcherPriority.Background);
            }
            base.OnStateChanged(e);
        }

        // ── WebView2 initialisation ────────────────────────────────────────────
        private async Task InitWebViewAsync()
        {
            try
            {
                await IdeWebView.EnsureCoreWebView2Async();

                // Allow the IDE to call the local FastAPI bridge
                IdeWebView.CoreWebView2.Settings.IsWebMessageEnabled = true;
                IdeWebView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                IdeWebView.CoreWebView2.Settings.AreDevToolsEnabled = true; // keep for dev

                // ── Bridge: JS → WPF ──────────────────────────────────────────
                IdeWebView.CoreWebView2.WebMessageReceived += OnWebMessageReceived;

                // ── Navigate to Monaco IDE ─────────────────────────────────────
                IdeWebView.CoreWebView2.Navigate(IdeUrl);
                SetStatus("IDE loading…");
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    $"Could not initialise WebView2:\n{ex.Message}\n\n" +
                    "Please install the Microsoft Edge WebView2 Runtime.",
                    "WebView2 Error",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        //  Native Tool-Call Bridge   (JS → WPF via postMessage)
        // ═══════════════════════════════════════════════════════════════════════
        //
        //  Monaco JS calls: window.chrome.webview.postMessage({ type, payload })
        //  IdeWindow.xaml.cs handles the request and replies via
        //  PostWebMessageAsJson({ type, result, ... })
        // -----------------------------------------------------------------------

        private void OnWebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            string raw = e.TryGetWebMessageAsString() ?? string.Empty;
            try
            {
                using var doc = JsonDocument.Parse(raw);
                var root = doc.RootElement;
                string type = root.TryGetProperty("type", out var t) ? t.GetString() ?? "" : "";

                switch (type)
                {
                    case "open_file_picker":
                        DispatchOpenFilePicker(root);
                        break;
                    case "save_file_picker":
                        DispatchSaveFilePicker(root);
                        break;
                    case "open_folder_picker":
                        DispatchOpenFolderPicker(root);
                        break;
                    case "show_notification":
                        DispatchNotification(root);
                        break;
                    case "ide_ready":
                        Dispatcher.Invoke(() =>
                        {
                            SetStatus("IDE ready");
                            // Inject active project path on startup
                            if (!string.IsNullOrWhiteSpace(_activeProjectPath))
                                PostToIde("set_workspace", new { path = _activeProjectPath });
                        });
                        break;
                    case "cursor_position":
                        // Monaco reports { line, column } so we can update the status bar
                        if (root.TryGetProperty("payload", out var cp))
                        {
                            int line = cp.TryGetProperty("line", out var l) ? l.GetInt32() : 0;
                            int col  = cp.TryGetProperty("column", out var c) ? c.GetInt32() : 0;
                            Dispatcher.Invoke(() => LineColLabel.Text = $"Ln {line}, Col {col}");
                        }
                        break;
                    case "file_opened":
                        if (root.TryGetProperty("payload", out var fo) &&
                            fo.TryGetProperty("path", out var fp))
                        {
                            string fname = Path.GetFileName(fp.GetString() ?? "");
                            Dispatcher.Invoke(() => FileLabel.Text = fname);
                        }
                        break;
                    default:
                        // Unknown message types are silently ignored
                        break;
                }
            }
            catch
            {
                // Malformed JSON from IDE — ignore
            }
        }

        // ── open_file_picker ───────────────────────────────────────────────────
        private void DispatchOpenFilePicker(JsonElement root)
        {
            Dispatcher.Invoke(() =>
            {
                string filter = "All Files|*.*";
                if (root.TryGetProperty("payload", out var p) &&
                    p.TryGetProperty("filter", out var f))
                    filter = f.GetString() ?? filter;

                var dlg = new Microsoft.Win32.OpenFileDialog { Filter = filter, Multiselect = false };
                if (dlg.ShowDialog() == true)
                    PostToIde("file_picker_result", new { path = dlg.FileName });
                else
                    PostToIde("file_picker_result", new { path = (string?)null, cancelled = true });
            });
        }

        // ── save_file_picker ───────────────────────────────────────────────────
        private void DispatchSaveFilePicker(JsonElement root)
        {
            Dispatcher.Invoke(() =>
            {
                string filter = "All Files|*.*";
                string defaultName = "untitled";
                if (root.TryGetProperty("payload", out var p))
                {
                    if (p.TryGetProperty("filter", out var f)) filter = f.GetString() ?? filter;
                    if (p.TryGetProperty("default_name", out var dn)) defaultName = dn.GetString() ?? defaultName;
                }

                var dlg = new Microsoft.Win32.SaveFileDialog
                {
                    Filter = defaultName.Contains('.') ? $"File|*{Path.GetExtension(defaultName)}|All Files|*.*" : filter,
                    FileName = defaultName,
                };
                if (dlg.ShowDialog() == true)
                    PostToIde("save_picker_result", new { path = dlg.FileName });
                else
                    PostToIde("save_picker_result", new { path = (string?)null, cancelled = true });
            });
        }

        // ── open_folder_picker ─────────────────────────────────────────────────
        private void DispatchOpenFolderPicker(JsonElement root)
        {
            Dispatcher.Invoke(() =>
            {
                var dlg = new Microsoft.Win32.OpenFolderDialog
                {
                    Title = "Select Project Folder",
                    Multiselect = false,
                };
                if (dlg.ShowDialog() == true)
                {
                    _activeProjectPath = dlg.FolderName;
                    _buildManager = new BuildManager(_activeProjectPath);
                    UpdateProjectSelectorFromPath(_activeProjectPath);
                    PostToIde("folder_picker_result", new { path = dlg.FolderName });
                }
                else
                {
                    PostToIde("folder_picker_result", new { path = (string?)null, cancelled = true });
                }
            });
        }

        // ── show_notification ──────────────────────────────────────────────────
        private void DispatchNotification(JsonElement root)
        {
            Dispatcher.Invoke(() =>
            {
                string message = "";
                string title = "Arbiter";
                if (root.TryGetProperty("payload", out var p))
                {
                    if (p.TryGetProperty("message", out var m)) message = m.GetString() ?? "";
                    if (p.TryGetProperty("title", out var t2)) title = t2.GetString() ?? title;
                }
                if (!string.IsNullOrWhiteSpace(message))
                    MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information);
            });
        }

        // ── PostWebMessage helper ──────────────────────────────────────────────
        private void PostToIde(string type, object payload)
        {
            try
            {
                var msg = JsonSerializer.Serialize(new { type, payload });
                IdeWebView.CoreWebView2.PostWebMessageAsJson(msg);
            }
            catch { /* WebView2 may not be ready yet */ }
        }

        // ═══════════════════════════════════════════════════════════════════════
        //  Toolbar button handlers
        // ═══════════════════════════════════════════════════════════════════════

        private void OpenFolder_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "Select Project Folder",
                Multiselect = false,
            };
            if (dlg.ShowDialog() != true) return;
            _activeProjectPath = dlg.FolderName;
            _buildManager = new BuildManager(_activeProjectPath);
            UpdateProjectSelectorFromPath(_activeProjectPath);
            PostToIde("set_workspace", new { path = dlg.FolderName });
            SetStatus($"Project: {Path.GetFileName(dlg.FolderName)}");
        }

        private void OpenFile_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new Microsoft.Win32.OpenFileDialog { Filter = "All Files|*.*", Multiselect = false };
            if (dlg.ShowDialog() != true) return;
            PostToIde("open_file", new { path = dlg.FileName });
            SetStatus($"Opened: {Path.GetFileName(dlg.FileName)}");
            FileLabel.Text = Path.GetFileName(dlg.FileName);
        }

        private void Save_Click(object sender, RoutedEventArgs e)
        {
            PostToIde("request_save", new { });
            SetStatus("Save requested");
        }

        private async void Build_Click(object sender, RoutedEventArgs e)
            => await RunProjectActionAsync("build", "Building…");

        private async void Run_Click(object sender, RoutedEventArgs e)
            => await RunProjectActionAsync("run", "Running…");

        private async void Test_Click(object sender, RoutedEventArgs e)
            => await RunProjectActionAsync("test", "Running tests…");

        // ── Build/Run/Test via WebSocket streaming (M4-7) ────────────────────
        private async Task RunProjectActionAsync(string action, string statusMessage)
        {
            SetStatus(statusMessage);
            string project = string.IsNullOrWhiteSpace(_activeProjectPath)
                ? "default"
                : Path.GetFileName(_activeProjectPath.TrimEnd(Path.DirectorySeparatorChar));

            // Cancel any previous build WebSocket
            _buildWsCts?.Cancel();
            _buildWsCts = new CancellationTokenSource();
            var cts = _buildWsCts;

            // Try WebSocket streaming from /ws/run first; fall back to REST.
            bool wsOk = false;
            try
            {
                string wsBase = AppConfig.ApiBaseUrl
                    .Replace("https://", "wss://")
                    .Replace("http://", "ws://");
                var wsUri = new Uri($"{wsBase}/ws/run");

                using var ws = new ClientWebSocket();
                await ws.ConnectAsync(wsUri, cts.Token);

                // Send the start command
                string startMsg = JsonSerializer.Serialize(new { action, project });
                await ws.SendAsync(
                    new ArraySegment<byte>(Encoding.UTF8.GetBytes(startMsg)),
                    WebSocketMessageType.Text, true, cts.Token);

                // Stream chunks to the IDE
                var buf = new byte[4096];
                bool success = true;
                var outputBuilder = new System.Text.StringBuilder();
                while (!cts.IsCancellationRequested)
                {
                    var recv = await ws.ReceiveAsync(new ArraySegment<byte>(buf), cts.Token);
                    if (recv.MessageType == WebSocketMessageType.Close) break;
                    string chunk = Encoding.UTF8.GetString(buf, 0, recv.Count);
                    try
                    {
                        using var doc = JsonDocument.Parse(chunk);
                        string msgType = doc.RootElement.TryGetProperty("type", out var t)
                            ? t.GetString() ?? "" : "";
                        if (msgType == "output" || msgType == "log")
                        {
                            string line = doc.RootElement.TryGetProperty("data", out var d)
                                ? d.GetString() ?? "" : chunk;
                            outputBuilder.Append(line);
                            PostToIde("build_chunk", new { action, line });
                        }
                        else if (msgType == "done")
                        {
                            success = doc.RootElement.TryGetProperty("success", out var s)
                                      ? s.GetBoolean() : true;
                            break;
                        }
                        else if (msgType == "error")
                        {
                            success = false;
                            string err = doc.RootElement.TryGetProperty("data", out var er)
                                ? er.GetString() ?? chunk : chunk;
                            PostToIde("build_chunk", new { action, line = err });
                            break;
                        }
                    }
                    catch
                    {
                        // Non-JSON chunk → treat as plain text output
                        outputBuilder.Append(chunk);
                        PostToIde("build_chunk", new { action, line = chunk });
                    }
                }
                PostToIde("build_output", new { action, success, output = outputBuilder.ToString() });
                SetStatus(success ? $"{action} succeeded" : $"{action} failed");
                wsOk = true;
            }
            catch (OperationCanceledException) { return; }
            catch
            {
                // WebSocket unavailable — fall through to REST fallback
            }

            if (wsOk) return;

            // ── REST fallback ─────────────────────────────────────────────────
            try
            {
                var body = JsonSerializer.Serialize(new { project, command = "" });
                using var content = new System.Net.Http.StringContent(
                    body, System.Text.Encoding.UTF8, "application/json");
                var resp = await _http.PostAsync($"{AppConfig.ApiBaseUrl}/{action}", content);
                string json = await resp.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);
                string output = doc.RootElement.TryGetProperty("output", out var o) ? o.GetString() ?? "" : json;
                bool success = !doc.RootElement.TryGetProperty("success", out var s) || s.GetBoolean();
                SetStatus(success ? $"{action} succeeded" : $"{action} failed");
                PostToIde("build_output", new { action, success, output });
            }
            catch (Exception ex)
            {
                SetStatus($"{action} error: {ex.Message}");
                PostToIde("build_output", new { action, success = false, output = ex.Message });
            }
        }

        // ═══════════════════════════════════════════════════════════════════════
        //  Menu bar handlers  (M4-5)
        // ═══════════════════════════════════════════════════════════════════════

        // ── File menu ─────────────────────────────────────────────────────────
        private void MenuSettings_Click(object sender, RoutedEventArgs e)
        {
            // M4-6: Open native settings dialog instead of routing to Monaco panel
            var dlg = new SettingsWindow { Owner = this };
            if (dlg.ShowDialog() == true)
            {
                // Reload the IDE URL in case the port changed
                IdeWebView.CoreWebView2?.Navigate($"{AppConfig.ApiBaseUrl}/gui/index.html");
                SetStatus("Settings saved. IDE reloaded.");
            }
        }

        private void MenuExit_Click(object sender, RoutedEventArgs e)
            => Application.Current.Shutdown();

        // ── Edit menu ─────────────────────────────────────────────────────────
        private void MenuUndo_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "undo" });

        private void MenuRedo_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "redo" });

        private void MenuCut_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "cut" });

        private void MenuCopy_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "copy" });

        private void MenuPaste_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "paste" });

        private void MenuFind_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "find" });

        private void MenuReplace_Click(object sender, RoutedEventArgs e)
            => PostToIde("editor_command", new { command = "replace" });

        // ── View menu ─────────────────────────────────────────────────────────
        private void MenuCommandPalette_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_command_palette", new { });

        private void MenuOpenCodex_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_panel", new { panel = "codex" });

        private void MenuOpenRoadmap_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_panel", new { panel = "roadmap" });

        private void MenuOpenAgents_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_panel", new { panel = "agents" });

        /// <summary>M4-9: Toggle the docked chat panel inside IdeWindow.</summary>
        private void MenuToggleChat_Click(object sender, RoutedEventArgs e)
            => PostToIde("toggle_chat_panel", new { });

        private void MenuToggleSelfBuild_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_panel", new { panel = "selfbuild" });

        // ── Git menu ──────────────────────────────────────────────────────────
        private void MenuGitRefresh_Click(object sender, RoutedEventArgs e)
            => PostToIde("git_action", new { action = "refresh" });

        private void MenuGitStageAll_Click(object sender, RoutedEventArgs e)
            => PostToIde("git_action", new { action = "stage_all" });

        private void MenuGitCommit_Click(object sender, RoutedEventArgs e)
        {
            string? msg = InputDialog.Show("Git Commit", "Commit message:");
            if (!string.IsNullOrWhiteSpace(msg))
                PostToIde("git_action", new { action = "commit", message = msg });
        }

        private void MenuGitPush_Click(object sender, RoutedEventArgs e)
            => PostToIde("git_action", new { action = "push" });

        private void MenuGitPull_Click(object sender, RoutedEventArgs e)
            => PostToIde("git_action", new { action = "pull" });

        private void MenuGitClone_Click(object sender, RoutedEventArgs e)
        {
            string? url = InputDialog.Show("Clone Repository", "Repository URL:");
            if (!string.IsNullOrWhiteSpace(url))
                PostToIde("git_action", new { action = "clone", url });
        }

        // ── AI menu ───────────────────────────────────────────────────────────
        private void MenuAutoBuild_Click(object sender, RoutedEventArgs e)
            => PostToIde("self_build_start", new { });

        private void MenuOpenChat_Click(object sender, RoutedEventArgs e)
            => PostToIde("open_chat", new { });

        private void MenuAgentFile_Click(object sender, RoutedEventArgs e)
            => PostToIde("agent_on_file", new { });

        private async void MenuRebuildArchive_Click(object sender, RoutedEventArgs e)
        {
            SetStatus("Rebuilding archive…");
            try
            {
                await _http.PostAsync($"{AppConfig.ApiBaseUrl}/archive/rebuild", null);
                SetStatus("Archive rebuild triggered.");
            }
            catch (Exception ex)
            {
                SetStatus($"Archive rebuild failed: {ex.Message}");
            }
        }

        // ── Help menu ─────────────────────────────────────────────────────────
        private void MenuOpenDocs_Click(object sender, RoutedEventArgs e)
        {
            try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                { FileName = "https://github.com/shifty81/Arbiter", UseShellExecute = true }); }
            catch { /* ignore */ }
        }

        private void MenuOpenRoadmapTab_Click(object sender, RoutedEventArgs e)
            => PostToIde("switch_output_tab", new { tab = "roadmap" });

        private void MenuAbout_Click(object sender, RoutedEventArgs e)
            => MessageBox.Show(
                "Arbiter IDE\nSelf-hosted AI-powered development platform.\n\n" +
                $"Mode: {AppConfig.Mode}\nAPI: {AppConfig.ApiBaseUrl}\nRuntime: .NET 9 / WPF",
                "About Arbiter",
                MessageBoxButton.OK,
                MessageBoxImage.Information);

        // ═══════════════════════════════════════════════════════════════════════
        //  Project selector
        // ═══════════════════════════════════════════════════════════════════════

        private void PopulateProjectSelector()
        {
            ProjectSelector.Items.Clear();
            ProjectSelector.Items.Add("(none)");
            if (Directory.Exists(_projectsRoot))
            {
                foreach (var dir in Directory.GetDirectories(_projectsRoot).OrderBy(d => d))
                    ProjectSelector.Items.Add(Path.GetFileName(dir));
            }
            ProjectSelector.SelectedIndex = 0;
        }

        private void ProjectSelector_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
        {
            string? selected = ProjectSelector.SelectedItem?.ToString();
            if (string.IsNullOrEmpty(selected) || selected == "(none)")
            {
                _activeProjectPath = null;
                _buildManager = null;
                return;
            }
            _activeProjectPath = Path.Combine(_projectsRoot, selected);
            _buildManager = new BuildManager(_activeProjectPath);
            PostToIde("set_workspace", new { path = _activeProjectPath });
            SetStatus($"Project: {selected}");
        }

        private void UpdateProjectSelectorFromPath(string path)
        {
            string name = Path.GetFileName(path.TrimEnd(Path.DirectorySeparatorChar));
            // Add to dropdown if not already present
            if (!ProjectSelector.Items.Contains(name))
                ProjectSelector.Items.Add(name);
            ProjectSelector.SelectedItem = name;
        }

        // ═══════════════════════════════════════════════════════════════════════
        //  Server health polling
        // ═══════════════════════════════════════════════════════════════════════

        private async Task PollServerStatusAsync()
        {
            while (IsLoaded)
            {
                try
                {
                    var resp = await _http.GetAsync($"{AppConfig.ApiBaseUrl}/health");
                    bool ok = resp.IsSuccessStatusCode;
                    Dispatcher.Invoke(() =>
                    {
                        ServerDot.Fill = ok ? new SolidColorBrush(Color.FromRgb(0x4e, 0xc9, 0x50))
                                            : new SolidColorBrush(Color.FromRgb(0xf4, 0x43, 0x36));
                        ServerLabel.Text = ok ? "Server: online" : "Server: offline";
                    });
                }
                catch
                {
                    Dispatcher.Invoke(() =>
                    {
                        ServerDot.Fill = new SolidColorBrush(Color.FromRgb(0xf4, 0x43, 0x36));
                        ServerLabel.Text = "Server: offline";
                    });
                }
                await Task.Delay(5000);
            }
        }

        // ── LLM backend polling (M4-4) ─────────────────────────────────────────
        private async Task PollLlmBackendAsync()
        {
            while (true)
            {
                try
                {
                    var resp = await _http.GetAsync($"{AppConfig.ApiBaseUrl}/status");
                    if (resp.IsSuccessStatusCode)
                    {
                        string json = await resp.Content.ReadAsStringAsync();
                        using var doc = JsonDocument.Parse(json);
                        string backend = doc.RootElement.TryGetProperty("llm_backend", out var b)
                            ? b.GetString() ?? ""
                            : doc.RootElement.TryGetProperty("active_backend", out var ab)
                                ? ab.GetString() ?? ""
                                : "";
                        if (!string.IsNullOrEmpty(backend))
                            Dispatcher.Invoke(() => LlmLabel.Text = $"LLM: {backend}");
                    }
                }
                catch { /* server may not be up yet */ }
                await Task.Delay(30_000); // refresh every 30 seconds
            }
        }

        // ── Status helper ──────────────────────────────────────────────────────
        private void SetStatus(string message)
            => Dispatcher.Invoke(() => StatusLabel.Text = message);
    }

    // ── M4-8: RelayCommand helper ────────────────────────────────────────────
    /// <summary>
    /// Minimal ICommand implementation used to bind keyboard shortcuts to
    /// anonymous delegates without requiring full MVVM infrastructure.
    /// </summary>
    internal sealed class RelayCommand : ICommand
    {
        private readonly Action<object?> _execute;
        private readonly Func<object?, bool>? _canExecute;

        public RelayCommand(Action<object?> execute, Func<object?, bool>? canExecute = null)
        {
            _execute    = execute;
            _canExecute = canExecute;
        }

        public event EventHandler? CanExecuteChanged
        {
            add    => CommandManager.RequerySuggested += value;
            remove => CommandManager.RequerySuggested -= value;
        }

        public bool CanExecute(object? parameter) => _canExecute?.Invoke(parameter) ?? true;
        public void Execute(object? parameter)    => _execute(parameter);
    }
}
