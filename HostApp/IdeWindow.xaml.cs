using System;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using ArbiterHost.BuildInterface;
using ArbiterHost.Utilities;
using Microsoft.Web.WebView2.Core;

namespace ArbiterHost
{
    /// <summary>
    /// Full-screen Monaco IDE window hosted via WebView2.
    /// Provides a native WPF toolbar and a bidirectional postMessage bridge so
    /// Monaco JS can request native Windows actions (file pickers, notifications)
    /// without any HTTP polling.
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

        // ── Constructor ────────────────────────────────────────────────────────
        public IdeWindow()
        {
            InitializeComponent();
            _projectsRoot = Path.Combine(Directory.GetCurrentDirectory(), "Projects");
            Directory.CreateDirectory(_projectsRoot);
            ModeLabel.Text = AppConfig.Mode;
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
            // Nothing extra needed; App_Exit handles process cleanup.
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

        // ── Build/Run/Test via REST API ────────────────────────────────────────
        private async Task RunProjectActionAsync(string action, string statusMessage)
        {
            SetStatus(statusMessage);
            string project = string.IsNullOrWhiteSpace(_activeProjectPath)
                ? "default"
                : Path.GetFileName(_activeProjectPath.TrimEnd(Path.DirectorySeparatorChar));
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

        // ── Status helper ──────────────────────────────────────────────────────
        private void SetStatus(string message)
            => Dispatcher.Invoke(() => StatusLabel.Text = message);
    }
}
