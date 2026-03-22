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
using System.Windows.Media;
using ArbiterHost.BuildInterface;
using ArbiterHost.GitInterface;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    public partial class ProjectWindow : Window
    {
        public string ProjectName { get; private set; }
        public string CurrentProjectPath { get; private set; }
        private string _activePersona = "Arbiter";
        private bool _personaSelectorChanging = false;

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private static string PythonApiBase => AppConfig.ApiBaseUrl;
        private const int MaxServerStartupSeconds = 30;

        private readonly GitManager gitManager = new GitManager();
        private readonly BuildManager buildManager;
        private Process? _serverProcess;

        public ProjectWindow(string projectName, string projectsRoot)
        {
            InitializeComponent();
            ProjectName = projectName;
            CurrentProjectPath = Path.Combine(projectsRoot, projectName);
            Title = $"Arbiter — {projectName}";
            buildManager = new BuildManager(CurrentProjectPath);
            LoadProjectFiles();
            LoadPhaseSelector();
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            DarkTitleBar.Apply(this);
        }

        private async void Window_Loaded(object sender, RoutedEventArgs e)
        {
            AppendConsole(AppConsoleBox, $"Project '{ProjectName}' opened. Path: {CurrentProjectPath}");
            await CheckServerStatusAsync();
            await LoadPersonaSelectorAsync();
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

        /// <summary>
        /// Pings GET /health and updates the status dot and label.
        /// </summary>
        private async Task CheckServerStatusAsync()
        {
            ServerStatusText.Text = "Server: checking\u2026";
            ServerStatusDot.Fill = Brushes.Gray;
            StartServerButton.IsEnabled = false;

            bool online = false;
            try
            {
                var response = await httpClient.GetAsync(PythonApiBase + "/health");
                online = response.IsSuccessStatusCode;
            }
            catch
            {
                online = false;
            }

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
            ServerStatusText.Text = "Server: starting\u2026";
            ServerStatusDot.Fill = Brushes.Orange;
            AppendConsole(AppConsoleBox, "Server start requested.");

            try
            {
                // Locate fastapi_bridge.py relative to the application directory
                string appDir = AppDomain.CurrentDomain.BaseDirectory;
                string bridgePath = Path.GetFullPath(
                    Path.Combine(appDir, "..", "..", "..", "..", "AIEngine", "PythonBridge", "fastapi_bridge.py"));

                if (!File.Exists(bridgePath))
                {
                    string msg = $"Could not find fastapi_bridge.py at:\n{bridgePath}\n\nPlease start the Python server manually:\n  cd AIEngine/PythonBridge\n  python fastapi_bridge.py";
                    AppendConsole(ServerConsoleBox, "ERROR: " + msg);
                    AppendConsole(AppConsoleBox, "Server not found — start it manually.");
                    MessageBox.Show(msg, "Server Not Found", MessageBoxButton.OK, MessageBoxImage.Warning);
                    SetServerOffline();
                    return;
                }

                string? bridgeDir = Path.GetDirectoryName(bridgePath);
                if (string.IsNullOrEmpty(bridgeDir))
                {
                    MessageBox.Show(
                        "Could not determine the directory for fastapi_bridge.py.",
                        "Server Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    SetServerOffline();
                    return;
                }

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
                    string msg = $"Failed to start the Python server process using '{python}'. " +
                                 "Ensure Python is installed and in PATH.";
                    AppendConsole(ServerConsoleBox, "ERROR: " + msg);
                    AppendConsole(AppConsoleBox, "Server process failed to start.");
                    MessageBox.Show(msg, "Start Server Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    SetServerOffline();
                    return;
                }

                // Stream stdout and stderr to the Server console tab in real-time
                _serverProcess.OutputDataReceived += (_, args) =>
                {
                    if (args.Data != null)
                        Dispatcher.Invoke(() => AppendConsole(ServerConsoleBox, args.Data));
                };
                _serverProcess.ErrorDataReceived += (_, args) =>
                {
                    if (args.Data != null)
                        Dispatcher.Invoke(() => AppendConsole(ServerConsoleBox, args.Data));
                };
                _serverProcess.BeginOutputReadLine();
                _serverProcess.BeginErrorReadLine();

                // Wait up to MaxServerStartupSeconds for the server to become available
                bool serverOnline = false;
                for (int i = 0; i < MaxServerStartupSeconds; i++)
                {
                    await Task.Delay(1000);

                    if (_serverProcess.HasExited)
                    {
                        await Task.Delay(300); // let remaining output lines flush
                        string msg = $"The Python server process exited unexpectedly " +
                                     $"(exit code {_serverProcess.ExitCode}).\n\n" +
                                     "See the Console → Server tab for details.\n\n" +
                                     "Make sure all dependencies are installed:\n" +
                                     "  pip install -r AIEngine/PythonBridge/requirements.txt";
                        AppendConsole(AppConsoleBox, $"Server exited (code {_serverProcess.ExitCode}).");
                        MessageBox.Show(msg, "Server Exited", MessageBoxButton.OK, MessageBoxImage.Error);
                        SetServerOffline();
                        return;
                    }

                    ServerStatusText.Text = $"Server: starting… ({i + 1}/{MaxServerStartupSeconds}s)";

                    try
                    {
                        var resp = await httpClient.GetAsync(PythonApiBase + "/health");
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
                    string msg = $"The server process is running but has not responded after " +
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

        private void LoadProjectFiles()
        {
            ProjectFilesTree.Items.Clear();
            if (!Directory.Exists(CurrentProjectPath)) return;
            var root = new TreeViewItem { Header = ProjectName };
            PopulateTreeView(root, CurrentProjectPath);
            ProjectFilesTree.Items.Add(root);
            root.IsExpanded = true;
        }

        private static void PopulateTreeView(TreeViewItem parent, string path)
        {
            foreach (var dir in Directory.GetDirectories(path))
            {
                var item = new TreeViewItem { Header = Path.GetFileName(dir), Tag = dir };
                PopulateTreeView(item, dir);
                parent.Items.Add(item);
            }
            foreach (var file in Directory.GetFiles(path))
            {
                parent.Items.Add(new TreeViewItem { Header = Path.GetFileName(file), Tag = file });
            }
        }

        private void LoadPhaseSelector()
        {
            string roadmapPath = Path.Combine(CurrentProjectPath, "roadmap.json");
            if (!File.Exists(roadmapPath)) return;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(roadmapPath));
                if (!doc.RootElement.TryGetProperty("phases", out var phases)) return;
                PhaseSelector.Items.Clear();
                foreach (var phase in phases.EnumerateArray())
                {
                    string name = phase.TryGetProperty("name", out var nameProp)
                        ? nameProp.GetString() ?? string.Empty
                        : phase.TryGetProperty("id", out var idProp)
                            ? $"Phase {idProp.GetInt32()}"
                            : "Phase";
                    PhaseSelector.Items.Add(new ComboBoxItem { Content = name });
                }
                if (PhaseSelector.Items.Count > 0)
                    PhaseSelector.SelectedIndex = 0;
            }
            catch
            {
                // Silently ignore malformed roadmap
            }
        }

        // ── Persona selector ──────────────────────────────────────────────────

        /// <summary>
        /// Populates the Persona selector from GET /personas and selects the
        /// current persona for this project from GET /persona/{project}.
        /// </summary>
        private async Task LoadPersonaSelectorAsync()
        {
            try
            {
                // 1. Fetch all available personas
                var personasResp = await httpClient.GetAsync(PythonApiBase + "/personas");
                if (!personasResp.IsSuccessStatusCode) return;

                string personasJson = await personasResp.Content.ReadAsStringAsync();
                using var personasDoc = JsonDocument.Parse(personasJson);
                var personasArr = personasDoc.RootElement.GetProperty("personas");

                _personaSelectorChanging = true;
                PersonaSelector.Items.Clear();
                foreach (var p in personasArr.EnumerateArray())
                {
                    string name = p.GetProperty("name").GetString() ?? string.Empty;
                    PersonaSelector.Items.Add(new ComboBoxItem { Content = name, Tag = name });
                }

                // 2. Fetch the active persona for this project
                var activeResp = await httpClient.GetAsync(
                    PythonApiBase + "/persona/" + Uri.EscapeDataString(ProjectName));
                if (activeResp.IsSuccessStatusCode)
                {
                    string activeJson = await activeResp.Content.ReadAsStringAsync();
                    using var activeDoc = JsonDocument.Parse(activeJson);
                    _activePersona = activeDoc.RootElement.GetProperty("persona").GetString()
                                     ?? "Arbiter";
                }

                // 3. Select the matching item
                foreach (ComboBoxItem item in PersonaSelector.Items)
                {
                    if (item.Tag?.ToString() == _activePersona)
                    {
                        PersonaSelector.SelectedItem = item;
                        break;
                    }
                }
                if (PersonaSelector.SelectedItem == null && PersonaSelector.Items.Count > 0)
                    PersonaSelector.SelectedIndex = 0;

                _personaSelectorChanging = false;
                AppendConsole(AppConsoleBox, $"Persona loaded: {_activePersona}");
            }
            catch
            {
                _personaSelectorChanging = false;
                // Server may not be running yet — persona selector stays empty
            }
        }

        private async void PersonaSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (_personaSelectorChanging) return;
            if (PersonaSelector.SelectedItem is not ComboBoxItem item) return;
            string persona = item.Tag?.ToString() ?? item.Content?.ToString() ?? string.Empty;
            if (string.IsNullOrEmpty(persona) || persona == _activePersona) return;

            try
            {
                var payload = new { persona };
                string json = JsonSerializer.Serialize(payload);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var resp = await httpClient.PostAsync(
                    PythonApiBase + "/persona/" + Uri.EscapeDataString(ProjectName), content);
                if (resp.IsSuccessStatusCode)
                {
                    _activePersona = persona;
                    AppendConsole(AppConsoleBox, $"Persona switched to: {persona}");
                    ChatDisplay.Items.Add($"[System] Persona switched to '{persona}'.");
                }
            }
            catch (Exception ex)
            {
                AppendConsole(AppConsoleBox, $"Persona switch failed: {ex.Message}");
            }
        }

        private async void SendButton_Click(object sender, RoutedEventArgs e)
        {
            string message = ChatInput.Text.Trim();
            if (string.IsNullOrEmpty(message)) return;

            ChatDisplay.Items.Add($"You: {message}");
            ChatInput.Clear();

            string voice = (VoiceSelector.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "British_Female";

            AppendConsole(LlmConsoleBox, $">> {message}");

            try
            {
                var payload = new
                {
                    message,
                    project = ProjectName,
                    use_voice = true,
                    voice
                };

                string json = JsonSerializer.Serialize(payload);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                HttpResponseMessage response = await httpClient.PostAsync(PythonApiBase + "/chat", content);
                response.EnsureSuccessStatusCode();

                string responseString = await response.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(responseString);
                string arbiterResponse = doc.RootElement.GetProperty("response").GetString() ?? string.Empty;

                // Update active persona if the server reports a change
                if (doc.RootElement.TryGetProperty("persona", out var personaProp))
                {
                    string serverPersona = personaProp.GetString() ?? string.Empty;
                    if (!string.IsNullOrEmpty(serverPersona) && serverPersona != _activePersona)
                    {
                        _activePersona = serverPersona;
                        AppendConsole(AppConsoleBox, $"Persona confirmed: {serverPersona}");
                    }
                }

                ChatDisplay.Items.Add($"{_activePersona}: {arbiterResponse}");
                SuggestionsListBox.Items.Add(arbiterResponse);

                ChatDisplay.ScrollIntoView(ChatDisplay.Items[ChatDisplay.Items.Count - 1]);
                AppendConsole(LlmConsoleBox, $"<< {arbiterResponse}");

                // Ensure status reflects that server is running
                ServerStatusDot.Fill = Brushes.LimeGreen;
                ServerStatusText.Text = "Server: Online";
                StartServerButton.IsEnabled = false;
            }
            catch (HttpRequestException ex) when (
                ex.InnerException is System.Net.Sockets.SocketException se &&
                se.SocketErrorCode == System.Net.Sockets.SocketError.ConnectionRefused)
            {
                ServerStatusDot.Fill = Brushes.Red;
                ServerStatusText.Text = "Server: Offline";
                StartServerButton.IsEnabled = true;
                AppendConsole(AppConsoleBox, "Chat error: server connection refused.");
                ChatDisplay.Items.Add(
                    "Error: Python server is not running. Click 'Start Server' or run: " +
                    "cd AIEngine/PythonBridge && python fastapi_bridge.py");
            }
            catch (TaskCanceledException)
            {
                ServerStatusDot.Fill = Brushes.Red;
                ServerStatusText.Text = "Server: Offline";
                StartServerButton.IsEnabled = true;
                AppendConsole(AppConsoleBox, "Chat error: request timed out.");
                ChatDisplay.Items.Add(
                    "Error: Request timed out. The Python server may not be running. " +
                    "Click 'Start Server' or run: cd AIEngine/PythonBridge && python fastapi_bridge.py");
            }
            catch (Exception ex)
            {
                AppendConsole(AppConsoleBox, $"Chat error: {ex.Message}");
                ChatDisplay.Items.Add($"Error: {ex.Message}");
            }
        }

        private const int SpeechRecognitionTimeoutSeconds = 10;

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
                var result = await System.Threading.Tasks.Task.Run(() =>
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

        private void ApproveSuggestion_Click(object sender, RoutedEventArgs e)
        {
            if (SuggestionsListBox.SelectedItem == null) return;
            string code = SuggestionsListBox.SelectedItem.ToString() ?? string.Empty;
            string filePath = Path.Combine(CurrentProjectPath, "GeneratedCode.cs");
            File.WriteAllText(filePath, code);
            LoadProjectFiles();
            MessageBox.Show($"Code saved to {filePath}", "Approved", MessageBoxButton.OK, MessageBoxImage.Information);
        }

        private void MoveSuggestion_Click(object sender, RoutedEventArgs e)
        {
            if (SuggestionsListBox.SelectedItem == null) return;
            string code = SuggestionsListBox.SelectedItem.ToString() ?? string.Empty;

            string projectsRoot = Path.GetDirectoryName(CurrentProjectPath) ?? string.Empty;
            var otherProjects = Directory.Exists(projectsRoot)
                ? Directory.GetDirectories(projectsRoot)
                    .Select(d => Path.GetFileName(d))
                    .Where(p => !string.IsNullOrEmpty(p) && p != ProjectName)
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

            string targetDir = Path.Combine(projectsRoot, targetProject);
            if (!Directory.Exists(targetDir))
            {
                MessageBox.Show($"Project '{targetProject}' does not exist.", "Move",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            string targetPath = Path.Combine(targetDir, "GeneratedCode.cs");
            File.WriteAllText(targetPath, code);
            SuggestionsListBox.Items.Remove(SuggestionsListBox.SelectedItem);
            MessageBox.Show($"Suggestion moved to {targetPath}", "Moved",
                MessageBoxButton.OK, MessageBoxImage.Information);
        }

        private void ProjectFilesTree_Drop(object sender, DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            string[] files = (string[])e.Data.GetData(DataFormats.FileDrop);
            foreach (var file in files)
            {
                string dest = Path.Combine(CurrentProjectPath, Path.GetFileName(file));
                File.Copy(file, dest, true);
            }
            LoadProjectFiles();
        }

        private void ProjectFilesTree_MouseDoubleClick(object sender, System.Windows.Input.MouseButtonEventArgs e)
        {
            if (ProjectFilesTree.SelectedItem is not TreeViewItem item) return;
            if (item.Tag is not string filePath) return;
            if (!File.Exists(filePath)) return;

            if (filePath.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
            {
                var viewer = new PdfViewerWindow(filePath) { Owner = this };
                viewer.Show();
                e.Handled = true;
            }
        }

        private void Commit_Click(object sender, RoutedEventArgs e)
        {
            string? message = InputDialog.Show("Enter commit message:", "Git Commit", "Arbiter: auto-commit");
            if (string.IsNullOrWhiteSpace(message)) return;
            try
            {
                gitManager.InitRepo(CurrentProjectPath);
                gitManager.Commit(message);
                MessageBox.Show("Committed successfully.", "Git", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Commit failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Branch_Click(object sender, RoutedEventArgs e)
        {
            string? name = InputDialog.Show("Enter branch name:", "Create Branch", "feature/new-branch");
            if (string.IsNullOrWhiteSpace(name)) return;

            // Validate branch name: only allow alphanumeric, dash, underscore, dot, and forward slash
            if (!System.Text.RegularExpressions.Regex.IsMatch(name, @"^[\w\-./]+$"))
            {
                MessageBox.Show("Invalid branch name. Use only letters, numbers, dash, dot, underscore, or slash.",
                    "Invalid Input", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            try
            {
                gitManager.CreateBranch(name);
                MessageBox.Show($"Branch '{name}' created.", "Git", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Branch failed: {ex.Message}", "Git Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Push_Click(object sender, RoutedEventArgs e)
        {
            string? remoteUrl = InputDialog.Show(
                "Enter remote URL (e.g. https://github.com/user/repo.git):\n" +
                "Tip: embed a Personal Access Token in the URL for authentication:\n" +
                "  https://<token>@github.com/user/repo.git",
                "Git Push", string.Empty);
            if (string.IsNullOrWhiteSpace(remoteUrl)) return;
            try
            {
                gitManager.InitRepo(CurrentProjectPath);
                gitManager.SetRemote(remoteUrl);
                gitManager.Push();
                MessageBox.Show("Pushed successfully.", "Git Push",
                    MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Push failed: {ex.Message}", "Git Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Pull_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                gitManager.InitRepo(CurrentProjectPath);
                gitManager.Pull();
                LoadProjectFiles();
                MessageBox.Show("Pulled successfully.", "Git Pull",
                    MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Pull failed: {ex.Message}", "Git Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Log_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                gitManager.InitRepo(CurrentProjectPath);
                var entries = gitManager.GetLog(20).ToList();
                string logText = entries.Count > 0
                    ? string.Join("\n", entries.Select(c =>
                        $"{c.Sha}  {c.When:yyyy-MM-dd HH:mm}  {c.Author}: {c.Message}"))
                    : "No commits yet.";
                MessageBox.Show(logText, "Git Log", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Log failed: {ex.Message}", "Git Error",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private async void Build_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync((Button)sender, BuildManager.BuildAction.Build, "Build");

        private async void Run_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync((Button)sender, BuildManager.BuildAction.Run, "Run");

        private async void Test_Click(object sender, RoutedEventArgs e) =>
            await ExecuteBuildActionAsync((Button)sender, BuildManager.BuildAction.Test, "Test");

        private const int BuildOutputTabIndex = 1;

        private async System.Threading.Tasks.Task ExecuteBuildActionAsync(
            Button btn, BuildManager.BuildAction action, string label)
        {
            string command = buildManager.AutoDetectCommand(action);
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

            try
            {
                var result = await buildManager.RunAsync(command);
                BuildOutputBox.AppendText(result.Output);
                BuildOutputBox.AppendText(result.Success
                    ? $"\n✅ {label} succeeded (exit 0)"
                    : $"\n❌ {label} failed (exit {result.ExitCode})");

                if (!result.Success)
                {
                    ChatDisplay.Items.Add(
                        $"[Build] {label} failed. Review the Build Output tab for details.");
                }
            }
            catch (Exception ex)
            {
                BuildOutputBox.AppendText($"\n[Error] {ex.Message}");
            }
            finally
            {
                BuildOutputBox.ScrollToEnd();
                btn.IsEnabled = true;
                btn.Content = label;
            }
        }
    }
}
