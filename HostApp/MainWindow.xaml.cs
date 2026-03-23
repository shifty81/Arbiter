using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using ArbiterHost.BuildInterface;
using ArbiterHost.GitInterface;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    public partial class MainWindow : Window
    {
        // ── Project state ────────────────────────────────────────────────────
        private string? _currentProjectName;
        private string? _currentProjectPath;
        private readonly string _projectsRoot;

        // ── Managers ─────────────────────────────────────────────────────────
        private readonly GitManager _gitManager = new GitManager();
        private BuildManager? _buildManager;

        // ── Python server ─────────────────────────────────────────────────────
        private static readonly HttpClient _httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private static string PythonApiBase => AppConfig.ApiBaseUrl;
        private const int MaxServerStartupSeconds = 30;
        private const int MaxServerOutputChars = 800;
        private Process? _serverProcess;

        // ── Build output pop-out ──────────────────────────────────────────────
        private Window? _buildOutputWindow;

        public MainWindow()
        {
            InitializeComponent();
            _projectsRoot = Path.Combine(Directory.GetCurrentDirectory(), "Projects");
            Directory.CreateDirectory(_projectsRoot);
            LoadProjects();
            UpdateToolbarState();
        }

        // ── Dark title bar ────────────────────────────────────────────────────
        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            DarkTitleBar.Apply(this);
        }

        // ── Window lifetime ───────────────────────────────────────────────────
        private async void Window_Loaded(object sender, RoutedEventArgs e)
        {
            AppendConsole(AppConsoleBox, $"Arbiter started. Projects root: {_projectsRoot}");
            await CheckServerStatusAsync();
            OpenWebChat();
        }

        private void OpenWebChat()
        {
            try
            {
                Process.Start(new ProcessStartInfo(PythonApiBase) { UseShellExecute = true });
                AppendConsole(AppConsoleBox, $"Web chat opened at {PythonApiBase}");
            }
            catch (Exception ex)
            {
                AppendConsole(AppConsoleBox, $"Could not open web chat: {ex.Message}");
            }
        }

        private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            bool serverRunning = _serverProcess != null && !_serverProcess.HasExited;
            bool engineRunning = AppConfig.EngineProcess != null && !AppConfig.EngineProcess.HasExited;
            bool hasUnsent     = !string.IsNullOrWhiteSpace(ChatInput.Text);

            // Build a descriptive confirmation message
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("Are you sure you want to exit Arbiter?");

            if (serverRunning || engineRunning)
            {
                sb.AppendLine();
                sb.AppendLine("The following services will be stopped:");
                if (serverRunning)
                    sb.AppendLine("  •  Arbiter server  (port 8000)");
                if (engineRunning)
                    sb.AppendLine($"  •  Arbiter Engine  (port {AppConfig.ArbiterEnginePort})");
            }

            if (hasUnsent)
            {
                sb.AppendLine();
                sb.AppendLine("⚠  You have an unsent message in the chat input.");
            }

            var answer = MessageBox.Show(
                sb.ToString().TrimEnd(),
                "Exit Arbiter",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question,
                MessageBoxResult.No);

            if (answer != MessageBoxResult.Yes)
            {
                e.Cancel = true;
                return;
            }

            // Stop the bridge server (port 8000)
            try
            {
                if (_serverProcess != null && !_serverProcess.HasExited)
                    _serverProcess.Kill(entireProcessTree: true);
            }
            catch { /* best-effort */ }

            // Stop the Arbiter Engine server if one was started
            try
            {
                if (AppConfig.EngineProcess != null && !AppConfig.EngineProcess.HasExited)
                    AppConfig.EngineProcess.Kill(entireProcessTree: true);
            }
            catch { /* best-effort */ }
        }

        // ═════════════════════════════════════════════════════════════════════
        //  PROJECT SIDEBAR
        // ═════════════════════════════════════════════════════════════════════

        private void LoadProjects()
        {
            ProjectListBox.Items.Clear();
            if (Directory.Exists(_projectsRoot))
            {
                foreach (var dir in Directory.GetDirectories(_projectsRoot))
                    ProjectListBox.Items.Add(Path.GetFileName(dir));
            }
        }

        private void ProjectListBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (ProjectListBox.SelectedItem == null) return;
            string name = ProjectListBox.SelectedItem.ToString() ?? string.Empty;
            ActivateProject(name, Path.Combine(_projectsRoot, name));
        }

        private void CreateProject_Click(object sender, RoutedEventArgs e)
        {
            string? name = InputDialog.Show("Enter project name:", "Create Project", "NewProject");
            if (string.IsNullOrWhiteSpace(name)) return;

            name = SanitizeProjectName(name);
            if (string.IsNullOrWhiteSpace(name)) return;

            string newPath = Path.Combine(_projectsRoot, name);
            Directory.CreateDirectory(newPath);
            File.WriteAllText(Path.Combine(newPath, "roadmap.json"),
                "{ \"phases\": [], \"tasks\": [] }");
            ProjectListBox.Items.Add(name);
            ProjectListBox.SelectedItem = name;
        }

        private static string SanitizeProjectName(string raw) =>
            Regex.Replace(raw.Trim(), @"[^\w\s\-]", "").Replace(' ', '_');

        /// <summary>
        /// Loads Arbiter's own HostApp source directory as the active project so the
        /// AI can read, suggest, and (with user approval) write changes to itself.
        /// Expected build output layout: HostApp/bin/Debug/net8.0-windows/ (3 levels up = HostApp/)
        /// </summary>
        private void OpenArbiterSelf_Click(object sender, RoutedEventArgs e)
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            // bin/Debug/net8.0-windows/ → up 3 levels → HostApp/ (the source root)
            string hostAppSrc = Path.GetFullPath(Path.Combine(appDir, "..", "..", ".."));

            if (!Directory.Exists(hostAppSrc))
            {
                MessageBox.Show(
                    $"Could not locate Arbiter source at:\n{hostAppSrc}",
                    "Self-Iterate", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            ActivateProject("Arbiter (Self)", hostAppSrc, isSelfProject: true);
        }

        private void ProjectListBox_Drop(object sender, DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            string[] files = (string[])e.Data.GetData(DataFormats.FileDrop);
            foreach (var file in files)
            {
                string folderName = Path.GetFileNameWithoutExtension(file);
                string destPath = Path.Combine(_projectsRoot, folderName);
                Directory.CreateDirectory(destPath);
                File.Copy(file, Path.Combine(destPath, Path.GetFileName(file)), true);
                if (!ProjectListBox.Items.Contains(folderName))
                    ProjectListBox.Items.Add(folderName);
            }
        }

        // ═════════════════════════════════════════════════════════════════════
        //  PROJECT ACTIVATION (replaces ProjectWindow constructor)
        // ═════════════════════════════════════════════════════════════════════

        private void ActivateProject(string name, string path, bool isSelfProject = false)
        {
            _currentProjectName = name;
            _currentProjectPath = path;
            _buildManager = new BuildManager(path);

            Title = isSelfProject ? "Arbiter — Self-Iteration Mode" : $"Arbiter — {name}";
            ChatHeader.Text = isSelfProject
                ? $"Chat  [Self-Iterating: {name}]"
                : $"Chat  [{name}]";

            ChatDisplay.Items.Clear();
            SuggestionsListBox.Items.Clear();

            if (isSelfProject)
            {
                ChatDisplay.Items.Add(
                    "Arbiter: Self-iteration mode active. I can read and suggest changes to my own " +
                    "source code. Describe what you'd like me to improve, and I'll generate a suggestion. " +
                    "Use 'Approve' to apply changes and then rebuild.");
            }

            LoadProjectFiles();
            LoadPhaseSelector();
            UpdateToolbarState();
        }

        private void UpdateToolbarState()
        {
            bool hasProject = _currentProjectPath != null;
            CommitBtn.IsEnabled = hasProject;
            BranchBtn.IsEnabled = hasProject;
            PushBtn.IsEnabled   = hasProject;
            PullBtn.IsEnabled   = hasProject;
            LogBtn.IsEnabled    = hasProject;
            BuildBtn.IsEnabled  = hasProject;
            RunBtn.IsEnabled    = hasProject;
            TestBtn.IsEnabled   = hasProject;
            PhaseSelector.IsEnabled = hasProject;
            ChatInput.IsEnabled = hasProject;
        }

        // ═════════════════════════════════════════════════════════════════════
        //  PROJECT FILES + PHASE SELECTOR
        // ═════════════════════════════════════════════════════════════════════

        private void LoadProjectFiles()
        {
            ProjectFilesTree.Items.Clear();
            if (_currentProjectPath == null || !Directory.Exists(_currentProjectPath)) return;
            var root = new TreeViewItem { Header = _currentProjectName };
            PopulateTreeView(root, _currentProjectPath);
            ProjectFilesTree.Items.Add(root);
            root.IsExpanded = true;
        }

        private static void PopulateTreeView(TreeViewItem parent, string path)
        {
            try
            {
                foreach (var dir in Directory.GetDirectories(path)
                             .Where(d => !Path.GetFileName(d).StartsWith(".")))
                {
                    var item = new TreeViewItem { Header = Path.GetFileName(dir) };
                    PopulateTreeView(item, dir);
                    parent.Items.Add(item);
                }
                foreach (var file in Directory.GetFiles(path))
                    parent.Items.Add(new TreeViewItem { Header = Path.GetFileName(file) });
            }
            catch { /* skip inaccessible dirs */ }
        }

        private void LoadPhaseSelector()
        {
            PhaseSelector.Items.Clear();
            if (_currentProjectPath == null) return;
            string roadmapPath = Path.Combine(_currentProjectPath, "roadmap.json");
            if (!File.Exists(roadmapPath)) return;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(roadmapPath));
                if (!doc.RootElement.TryGetProperty("phases", out var phases)) return;
                foreach (var phase in phases.EnumerateArray())
                {
                    string name = phase.TryGetProperty("name", out var n)
                        ? n.GetString() ?? string.Empty
                        : phase.TryGetProperty("id", out var id)
                            ? $"Phase {id.GetInt32()}"
                            : "Phase";
                    PhaseSelector.Items.Add(new ComboBoxItem { Content = name });
                }
                if (PhaseSelector.Items.Count > 0) PhaseSelector.SelectedIndex = 0;
            }
            catch { /* ignore malformed roadmap */ }
        }

        private void ProjectFilesTree_Drop(object sender, DragEventArgs e)
        {
            if (_currentProjectPath == null) return;
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            foreach (var file in (string[])e.Data.GetData(DataFormats.FileDrop))
            {
                File.Copy(file, Path.Combine(_currentProjectPath, Path.GetFileName(file)), true);
            }
            LoadProjectFiles();
        }

        // ═════════════════════════════════════════════════════════════════════
        //  PYTHON SERVER
        // ═════════════════════════════════════════════════════════════════════

        private async Task CheckServerStatusAsync()
        {
            ServerStatusText.Text = "Server: checking…";
            ServerStatusDot.Fill = Brushes.Gray;
            StartServerButton.IsEnabled = false;

            bool online = false;
            try
            {
                var response = await _httpClient.GetAsync(PythonApiBase + "/health");
                online = response.IsSuccessStatusCode;
            }
            catch { online = false; }

            if (online)
            {
                ServerStatusDot.Fill = Brushes.LimeGreen;
                ServerStatusText.Text = "Server: Online";
                StartServerButton.IsEnabled = false;
            }
            else
            {
                ServerStatusDot.Fill = Brushes.Red;
                ServerStatusText.Text = "Server: Offline";
                StartServerButton.IsEnabled = true;
            }
        }

        private async void StartServer_Click(object sender, RoutedEventArgs e)
        {
            StartServerButton.IsEnabled = false;
            ServerStatusText.Text = "Server: starting…";
            ServerStatusDot.Fill = Brushes.Orange;
            AppendConsole(AppConsoleBox, "Server start requested.");

            try
            {
                string appDir = AppDomain.CurrentDomain.BaseDirectory;
                // Build output: HostApp/bin/Debug/net8.0-windows/ — 4 levels up = repo root (ArbiterAI/)
                string bridgePath = Path.GetFullPath(
                    Path.Combine(appDir, "..", "..", "..", "..", "AIEngine", "PythonBridge", "fastapi_bridge.py"));

                if (!File.Exists(bridgePath))
                {
                    string msg = $"Could not find fastapi_bridge.py at:\n{bridgePath}\n\n" +
                                 "Please start the server manually:\n  cd AIEngine/PythonBridge\n  python fastapi_bridge.py";
                    AppendConsole(ServerConsoleBox, "ERROR: " + msg);
                    AppendConsole(AppConsoleBox, "Server not found — start it manually.");
                    MessageBox.Show(msg, "Server Not Found", MessageBoxButton.OK, MessageBoxImage.Warning);
                    SetServerOffline();
                    return;
                }

                string bridgeDir = Path.GetDirectoryName(bridgePath)!;
                string python = PythonHelper.FindExecutable();
                AppendConsole(ServerConsoleBox, $"Python: {python}");
                AppendConsole(ServerConsoleBox, $"Bridge: {bridgePath}");
                AppendConsole(AppConsoleBox, $"Starting server with: {python} \"{bridgePath}\"");

                var psi = new ProcessStartInfo
                {
                    FileName = python,
                    Arguments = $"\"{bridgePath}\"",
                    WorkingDirectory = bridgeDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                _serverProcess = Process.Start(psi);
                AppConfig.BridgeProcess = _serverProcess; // register for app-level cleanup

                if (_serverProcess == null)
                {
                    string msg = $"Failed to start the Python server process using '{python}'.\n" +
                                 "Ensure Python is installed and in PATH.";
                    AppendConsole(ServerConsoleBox, "ERROR: " + msg);
                    AppendConsole(AppConsoleBox, "Server process failed to start.");
                    MessageBox.Show(msg, "Start Server Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    SetServerOffline();
                    return;
                }

                // Collect output/errors so they can be shown directly in the error dialog
                var serverOutput = new System.Text.StringBuilder();
                _serverProcess.OutputDataReceived += (_, args) =>
                {
                    if (args.Data == null) return;
                    serverOutput.AppendLine(args.Data);
                    Dispatcher.Invoke(() => AppendConsole(ServerConsoleBox, args.Data));
                };
                _serverProcess.ErrorDataReceived += (_, args) =>
                {
                    if (args.Data == null) return;
                    serverOutput.AppendLine(args.Data);
                    Dispatcher.Invoke(() => AppendConsole(ServerConsoleBox, args.Data));
                };
                _serverProcess.BeginOutputReadLine();
                _serverProcess.BeginErrorReadLine();

                // Poll health endpoint; bail early if the process already exited
                bool serverOnline = false;
                for (int i = 0; i < MaxServerStartupSeconds; i++)
                {
                    await Task.Delay(1000);

                    if (_serverProcess.HasExited)
                    {
                        await Task.Delay(500); // let remaining output lines flush
                        AppendConsole(AppConsoleBox, $"Server exited (code {_serverProcess.ExitCode}).");

                        // Include the last captured output lines in the dialog so the user
                        // can see the exact Python error without navigating to the Server tab.
                        string captured = serverOutput.ToString().Trim();
                        const int maxChars = MaxServerOutputChars;
                        if (captured.Length > maxChars)
                            captured = "…\n" + captured[^maxChars..];

                        string detail = string.IsNullOrEmpty(captured)
                            ? "No output captured — check the Console → Server tab."
                            : captured;

                        string msg = $"The Python server process exited unexpectedly " +
                                     $"(exit code {_serverProcess.ExitCode}).\n\n" +
                                     "Python output:\n" +
                                     "──────────────────────────────\n" +
                                     detail + "\n" +
                                     "──────────────────────────────\n\n" +
                                     "If packages are missing, run:\n" +
                                     "  pip install -r AIEngine/PythonBridge/requirements.txt\n\n" +
                                     "The server will attempt to install them automatically on next start.";
                        MessageBox.Show(msg, "Server Exited", MessageBoxButton.OK, MessageBoxImage.Error);
                        SetServerOffline();
                        return;
                    }

                    ServerStatusText.Text = $"Server: starting… ({i + 1}/{MaxServerStartupSeconds}s)";

                    try
                    {
                        var resp = await _httpClient.GetAsync(PythonApiBase + "/health");
                        if (resp.IsSuccessStatusCode) { serverOnline = true; break; }
                    }
                    catch { /* still starting */ }
                }

                if (serverOnline)
                {
                    ServerStatusDot.Fill = Brushes.LimeGreen;
                    ServerStatusText.Text = "Server: Online";
                    AppendConsole(ServerConsoleBox, $"Server online at {PythonApiBase}");
                    AppendConsole(AppConsoleBox, "Server is online.");
                }
                else
                {
                    string msg = "The server process is running but has not responded after " +
                                 $"{MaxServerStartupSeconds} seconds.\n" +
                                 "It may still be loading. Check Console → Server for details.";
                    AppendConsole(AppConsoleBox, "Server startup timed out.");
                    MessageBox.Show(msg, "Server Timeout", MessageBoxButton.OK, MessageBoxImage.Warning);
                    SetServerOffline();
                }
            }
            catch (Exception ex)
            {
                string msg = $"Failed to start Python server:\n{ex.Message}\n\n" +
                             "Ensure Python is installed and in PATH, then start manually:\n" +
                             "  cd AIEngine/PythonBridge\n  python fastapi_bridge.py";
                AppendConsole(ServerConsoleBox, $"Exception: {ex.Message}");
                AppendConsole(AppConsoleBox, $"Server start exception: {ex.Message}");
                MessageBox.Show(msg, "Start Server Error", MessageBoxButton.OK, MessageBoxImage.Error);
                SetServerOffline();
            }
        }

        private void SetServerOffline()
        {
            ServerStatusDot.Fill = Brushes.Red;
            ServerStatusText.Text = "Server: Offline";
            StartServerButton.IsEnabled = true;
        }

        // ── Console helpers ───────────────────────────────────────────────────

        private static void AppendConsole(TextBox box, string message)
        {
            string line = $"[{DateTime.Now:HH:mm:ss}] {message}";
            box.AppendText(line + Environment.NewLine);
            box.ScrollToEnd();
        }

        private void CopyLlmConsole_Click(object sender, RoutedEventArgs e)
        {
            if (!string.IsNullOrEmpty(LlmConsoleBox.Text))
                Clipboard.SetText(LlmConsoleBox.Text);
        }

        private void CopyAppConsole_Click(object sender, RoutedEventArgs e)
        {
            if (!string.IsNullOrEmpty(AppConsoleBox.Text))
                Clipboard.SetText(AppConsoleBox.Text);
        }

        private void CopyServerConsole_Click(object sender, RoutedEventArgs e)
        {
            if (!string.IsNullOrEmpty(ServerConsoleBox.Text))
                Clipboard.SetText(ServerConsoleBox.Text);
        }

        // ═════════════════════════════════════════════════════════════════════
        //  CHAT
        // ═════════════════════════════════════════════════════════════════════

        private async void SendButton_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectName == null) return;
            string message = ChatInput.Text.Trim();
            if (string.IsNullOrEmpty(message)) return;

            ChatDisplay.Items.Add($"You: {message}");
            ChatInput.Clear();

            string voice = (VoiceSelector.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "British_Female";

            // For self-iteration, include a note for the LLM about what it's editing
            if (_currentProjectName == "Arbiter (Self)")
                message = "[Self-iteration request] " + message;

            AppendConsole(LlmConsoleBox, $">> {message}");

            try
            {
                var payload = new
                {
                    message,
                    project = _currentProjectName,
                    use_voice = true,
                    voice
                };

                string json = JsonSerializer.Serialize(payload);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                HttpResponseMessage response = await _httpClient.PostAsync(PythonApiBase + "/chat", content);
                response.EnsureSuccessStatusCode();

                string responseString = await response.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(responseString);
                string arbiterResponse = doc.RootElement.GetProperty("response").GetString() ?? string.Empty;

                ChatDisplay.Items.Add($"Arbiter: {arbiterResponse}");
                SuggestionsListBox.Items.Add(arbiterResponse);
                ChatDisplay.ScrollIntoView(ChatDisplay.Items[ChatDisplay.Items.Count - 1]);
                AppendConsole(LlmConsoleBox, $"<< {arbiterResponse}");

                ServerStatusDot.Fill = Brushes.LimeGreen;
                ServerStatusText.Text = "Server: Online";
                StartServerButton.IsEnabled = false;
            }
            catch (HttpRequestException ex) when (
                ex.InnerException is System.Net.Sockets.SocketException se &&
                se.SocketErrorCode == System.Net.Sockets.SocketError.ConnectionRefused)
            {
                SetServerOffline();
                AppendConsole(AppConsoleBox, "Chat error: server connection refused.");
                ChatDisplay.Items.Add(
                    "Error: Python server is not running. Click 'Start Server' or run: " +
                    "cd AIEngine/PythonBridge && python fastapi_bridge.py");
            }
            catch (TaskCanceledException)
            {
                SetServerOffline();
                AppendConsole(AppConsoleBox, "Chat error: request timed out.");
                ChatDisplay.Items.Add(
                    "Error: Request timed out. The Python server may not be running.");
            }
            catch (Exception ex)
            {
                AppendConsole(AppConsoleBox, $"Chat error: {ex.Message}");
                ChatDisplay.Items.Add($"Error: {ex.Message}");
            }
        }

        private const int SpeechRecognitionTimeoutSeconds = 10;

        /// <summary>Pressing Enter (without Shift) sends the chat message.</summary>
        private void ChatInput_KeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter && !e.IsRepeat &&
                !e.KeyboardDevice.Modifiers.HasFlag(ModifierKeys.Shift))
            {
                e.Handled = true;
                SendButton_Click(sender, new RoutedEventArgs());
            }
        }

        private async void MicButton_Click(object sender, RoutedEventArgs e)
        {
            var btn = (Button)sender;
            btn.IsEnabled = false;
            btn.Content = "…";
            try
            {
                using var recognizer = new System.Speech.Recognition.SpeechRecognitionEngine(
                    new System.Globalization.CultureInfo("en-US"));
                recognizer.LoadGrammar(new System.Speech.Recognition.DictationGrammar());
                recognizer.SetInputToDefaultAudioDevice();
                var result = await Task.Run(() =>
                    recognizer.Recognize(TimeSpan.FromSeconds(SpeechRecognitionTimeoutSeconds)));
                if (result != null)
                    ChatInput.Text = result.Text;
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Voice input error: {ex.Message}", "Mic Input",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
            }
            finally
            {
                btn.IsEnabled = true;
                btn.Content = "Mic";
            }
        }

        // ═════════════════════════════════════════════════════════════════════
        //  SUGGESTIONS
        // ═════════════════════════════════════════════════════════════════════

        private void ApproveSuggestion_Click(object sender, RoutedEventArgs e)
        {
            if (SuggestionsListBox.SelectedItem == null || _currentProjectPath == null) return;
            string code = SuggestionsListBox.SelectedItem.ToString() ?? string.Empty;

            if (_currentProjectName == "Arbiter (Self)")
            {
                // Self-iteration: ask which source file to overwrite
                string? targetFile = InputDialog.Show(
                    "Enter the relative path of the source file to update (e.g. MainWindow.xaml.cs):",
                    "Self-Iterate: Apply Change",
                    "MainWindow.xaml.cs");
                if (string.IsNullOrWhiteSpace(targetFile)) return;

                // Sanitise: strip any directory component to prevent path traversal
                targetFile = Path.GetFileName(targetFile);
                string? filePath = FindSourceFile(_currentProjectPath, targetFile);
                if (filePath == null)
                {
                    MessageBox.Show(
                        $"File '{targetFile}' not found under the Arbiter source tree.",
                        "Self-Iterate", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                // Guard: ensure the resolved path is still inside _currentProjectPath
                string safeRoot = Path.GetFullPath(_currentProjectPath) + Path.DirectorySeparatorChar;
                if (!Path.GetFullPath(filePath).StartsWith(safeRoot, StringComparison.OrdinalIgnoreCase))
                {
                    MessageBox.Show("Resolved path is outside the project directory.",
                        "Self-Iterate", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                var confirm = MessageBox.Show(
                    $"Overwrite:\n{filePath}\n\nWith AI suggestion? This cannot be undone.",
                    "Self-Iterate: Confirm", MessageBoxButton.YesNo, MessageBoxImage.Warning);
                if (confirm != MessageBoxResult.Yes) return;

                File.WriteAllText(filePath, code);
                LoadProjectFiles();
                MessageBox.Show(
                    $"Applied to {filePath}\n\nRebuild Arbiter (Build button) to apply the change.",
                    "Self-Iterate: Done", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            else
            {
                string filePath = Path.Combine(_currentProjectPath, "GeneratedCode.cs");
                File.WriteAllText(filePath, code);
                LoadProjectFiles();
                MessageBox.Show($"Code saved to {filePath}", "Approved",
                    MessageBoxButton.OK, MessageBoxImage.Information);
            }
        }

        /// <summary>Recursively searches for a file by name under <paramref name="root"/>.</summary>
        private static string? FindSourceFile(string root, string fileName)
        {
            try
            {
                return Directory
                    .EnumerateFiles(root, fileName, SearchOption.AllDirectories)
                    .FirstOrDefault();
            }
            catch { return null; }
        }

        private void MoveSuggestion_Click(object sender, RoutedEventArgs e)
        {
            if (SuggestionsListBox.SelectedItem == null) return;
            string code = SuggestionsListBox.SelectedItem.ToString() ?? string.Empty;

            var otherProjects = Directory.Exists(_projectsRoot)
                ? Directory.GetDirectories(_projectsRoot)
                    .Select(d => Path.GetFileName(d))
                    .Where(p => !string.IsNullOrEmpty(p) && p != _currentProjectName)
                    .Select(p => p!)
                    .ToList()
                : new List<string>();

            if (otherProjects.Count == 0)
            {
                MessageBox.Show("No other projects available to move to.", "Move",
                    MessageBoxButton.OK, MessageBoxImage.Information);
                return;
            }

            string? targetProject = InputDialog.Show(
                $"Enter target project name ({string.Join(", ", otherProjects)}):",
                "Move Suggestion",
                otherProjects[0]);

            if (string.IsNullOrWhiteSpace(targetProject)) return;

            string targetDir = Path.Combine(_projectsRoot, targetProject);
            if (!Directory.Exists(targetDir))
            {
                MessageBox.Show($"Project '{targetProject}' does not exist.", "Move",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            File.WriteAllText(Path.Combine(targetDir, "GeneratedCode.cs"), code);
            SuggestionsListBox.Items.Remove(SuggestionsListBox.SelectedItem);
            MessageBox.Show($"Suggestion moved to project '{targetProject}'.", "Moved",
                MessageBoxButton.OK, MessageBoxImage.Information);
        }

        // ═════════════════════════════════════════════════════════════════════
        //  GIT OPERATIONS
        // ═════════════════════════════════════════════════════════════════════

        private void Commit_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectPath == null) return;
            string? message = InputDialog.Show("Enter commit message:", "Git Commit", "Arbiter: auto-commit");
            if (string.IsNullOrWhiteSpace(message)) return;
            try
            {
                _gitManager.InitRepo(_currentProjectPath);
                _gitManager.Commit(message);
                MessageBox.Show("Committed successfully.", "Git", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Commit failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Branch_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectPath == null) return;
            string? name = InputDialog.Show("Enter branch name:", "Create Branch", "feature/new-branch");
            if (string.IsNullOrWhiteSpace(name)) return;
            if (!Regex.IsMatch(name, @"^[\w\-./]+$"))
            {
                MessageBox.Show("Invalid branch name. Use only letters, numbers, dash, dot, underscore, or slash.",
                    "Invalid Input", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }
            try
            {
                _gitManager.CreateBranch(name);
                MessageBox.Show($"Branch '{name}' created.", "Git", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Branch failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Push_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectPath == null) return;
            string? remoteUrl = InputDialog.Show(
                "Enter remote URL (e.g. https://github.com/user/repo.git):\n" +
                "Tip: embed a Personal Access Token:\n  https://<token>@github.com/user/repo.git",
                "Git Push", string.Empty);
            if (string.IsNullOrWhiteSpace(remoteUrl)) return;
            try
            {
                _gitManager.InitRepo(_currentProjectPath);
                _gitManager.SetRemote(remoteUrl);
                _gitManager.Push();
                MessageBox.Show("Pushed successfully.", "Git Push", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Push failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Pull_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectPath == null) return;
            try
            {
                _gitManager.InitRepo(_currentProjectPath);
                _gitManager.Pull();
                LoadProjectFiles();
                MessageBox.Show("Pulled successfully.", "Git Pull", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Pull failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Log_Click(object sender, RoutedEventArgs e)
        {
            if (_currentProjectPath == null) return;
            try
            {
                _gitManager.InitRepo(_currentProjectPath);
                var entries = _gitManager.GetLog(20).ToList();
                string logText = entries.Count > 0
                    ? string.Join("\n", entries.Select(c =>
                        $"{c.Sha}  {c.When:yyyy-MM-dd HH:mm}  {c.Author}: {c.Message}"))
                    : "No commits yet.";
                MessageBox.Show(logText, "Git Log", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Log failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        // ═════════════════════════════════════════════════════════════════════
        //  BUILD / RUN / TEST
        // ═════════════════════════════════════════════════════════════════════

        private async void Build_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync(BuildBtn, BuildManager.BuildAction.Build, "Build");

        private async void Run_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync(RunBtn, BuildManager.BuildAction.Run, "Run");

        private async void Test_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync(TestBtn, BuildManager.BuildAction.Test, "Test");

        private const int BuildOutputTabIndex = 1;

        private async Task ExecuteBuildActionAsync(Button btn, BuildManager.BuildAction action, string label)
        {
            if (_buildManager == null) return;

            string command = _buildManager.AutoDetectCommand(action);
            if (string.IsNullOrEmpty(command))
            {
                command = InputDialog.Show(
                    $"No {label} command detected. Enter command to run in the project folder:",
                    $"Custom {label}", string.Empty) ?? string.Empty;
                if (string.IsNullOrWhiteSpace(command)) return;
            }

            btn.IsEnabled = false;
            btn.Content = "…";
            BottomTabControl.SelectedIndex = BuildOutputTabIndex;
            BuildOutputBox.Text = $"▶ {label}: {command}\n\n";

            // If build output is popped out, also update the pop-out TextBox
            TextBox? popOutBox = _buildOutputWindow?.Content as TextBox;

            try
            {
                var result = await _buildManager.RunAsync(command);
                BuildOutputBox.AppendText(result.Output);
                if (popOutBox != null) popOutBox.Text = BuildOutputBox.Text;

                string statusLine = result.Success
                    ? $"\n✅ {label} succeeded (exit 0)"
                    : $"\n❌ {label} failed (exit {result.ExitCode})";
                BuildOutputBox.AppendText(statusLine);
                if (popOutBox != null) popOutBox.AppendText(statusLine);

                if (!result.Success)
                    ChatDisplay.Items.Add($"[Build] {label} failed — see Build Output tab for details.");
            }
            catch (Exception ex)
            {
                BuildOutputBox.AppendText($"\n[Error] {ex.Message}");
                if (popOutBox != null) popOutBox.AppendText($"\n[Error] {ex.Message}");
            }
            finally
            {
                BuildOutputBox.ScrollToEnd();
                popOutBox?.ScrollToEnd();
                btn.IsEnabled = true;
                btn.Content = label;
            }
        }

        // ═════════════════════════════════════════════════════════════════════
        //  POP-OUT BUILD OUTPUT
        // ═════════════════════════════════════════════════════════════════════

        private void PopOutBuildOutput_Click(object sender, RoutedEventArgs e)
        {
            if (_buildOutputWindow != null && _buildOutputWindow.IsLoaded)
            {
                _buildOutputWindow.Focus();
                return;
            }

            var outputBox = new TextBox
            {
                IsReadOnly = true,
                TextWrapping = TextWrapping.Wrap,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
                FontFamily = new FontFamily("Courier New"),
                FontSize = 11,
                AcceptsReturn = true,
                Text = BuildOutputBox.Text,
            };

            _buildOutputWindow = new Window
            {
                Title = "Arbiter — Build Output",
                Width = 800,
                Height = 500,
                Content = outputBox,
            };
            _buildOutputWindow.SourceInitialized += (_, _) => DarkTitleBar.Apply(_buildOutputWindow);
            _buildOutputWindow.Show();
        }
    }
}
