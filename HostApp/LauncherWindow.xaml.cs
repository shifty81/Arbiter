using System;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;

namespace ArbiterHost
{
    /// <summary>
    /// Start-up mode picker: ArbiterAI (port 8000) or Arbiter Engine (port 8001).
    /// </summary>
    public partial class LauncherWindow : Window
    {
        private Process? _engineProcess;

        public LauncherWindow()
        {
            InitializeComponent();
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            Utilities.DarkTitleBar.Apply(this);
        }

        private void Window_Loaded(object sender, RoutedEventArgs e)
        {
            LoadEnginePathFromSettings();
        }

        // ── Settings ──────────────────────────────────────────────────────────

        private static void LoadEnginePathFromSettings()
        {
            try
            {
                string settingsPath = Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory, "Config", "settings.json");
                if (!File.Exists(settingsPath)) return;

                using var doc = JsonDocument.Parse(File.ReadAllText(settingsPath));
                var root = doc.RootElement;

                if (root.TryGetProperty("arbiterEnginePath", out var pathProp))
                {
                    string raw = pathProp.GetString() ?? string.Empty;
                    AppConfig.ArbiterEnginePath = ResolvePath(raw);
                }

                if (root.TryGetProperty("arbiterEnginePort", out var portProp)
                    && portProp.TryGetInt32(out int port))
                    AppConfig.ArbiterEnginePort = port;
            }
            catch { /* best-effort */ }
        }

        private static string ResolvePath(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw)) return string.Empty;
            if (Path.IsPathRooted(raw)) return raw;
            // Resolve relative to the application base directory first,
            // then fall back to walking up the directory tree.
            string fromBase = Path.GetFullPath(
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, raw));
            if (Directory.Exists(fromBase)) return fromBase;

            // Walk up up to 6 levels to find the repo root containing the path.
            string? dir = AppDomain.CurrentDomain.BaseDirectory;
            for (int i = 0; i < 6 && dir != null; i++)
            {
                string candidate = Path.GetFullPath(Path.Combine(dir, raw));
                if (Directory.Exists(candidate)) return candidate;
                dir = Path.GetDirectoryName(dir);
            }
            return fromBase; // return best-guess even if not found yet
        }

        // ── Button handlers ───────────────────────────────────────────────────

        private void LaunchArbiterAI_Click(object sender, RoutedEventArgs e)
        {
            AppConfig.Mode = "ArbiterAI";
            AppConfig.ApiBaseUrl = "http://127.0.0.1:8000";
            OpenMainWindow();
        }

        private void LaunchArbiterEngine_Click(object sender, RoutedEventArgs e)
        {
            AppConfig.Mode = "ArbiterEngine";
            AppConfig.ApiBaseUrl = $"http://127.0.0.1:{AppConfig.ArbiterEnginePort}";

            if (!TryStartEngineServer())
            {
                var result = MessageBox.Show(
                    "Could not start the Arbiter Engine server automatically.\n\n" +
                    "Make sure Python 3.10+ is installed and run:\n" +
                    "  pip install -r AIEngine/ArbiterEngine/requirements.txt\n\n" +
                    "Then start it manually:\n" +
                    "  python AIEngine/ArbiterEngine/server.py\n\n" +
                    "Continue anyway (if the server is already running)?",
                    "Arbiter Engine",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Warning);

                if (result == MessageBoxResult.No) return;
            }

            OpenMainWindow();
        }

        // ── Engine server startup ─────────────────────────────────────────────

        private bool TryStartEngineServer()
        {
            string serverScript = string.IsNullOrWhiteSpace(AppConfig.ArbiterEnginePath)
                ? FindEngineServerScript()
                : Path.Combine(AppConfig.ArbiterEnginePath, "server.py");

            if (!File.Exists(serverScript))
            {
                return false;
            }

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = $"\"{serverScript}\"",
                    WorkingDirectory = Path.GetDirectoryName(serverScript)!,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false,
                };
                _engineProcess = Process.Start(psi);
                AppConfig.EngineProcess = _engineProcess;
                return _engineProcess != null;
            }
            catch
            {
                return false;
            }
        }

        private static string FindEngineServerScript()
        {
            // Walk up from the app directory to find AIEngine/ArbiterEngine/server.py
            string? dir = AppDomain.CurrentDomain.BaseDirectory;
            for (int i = 0; i < 6 && dir != null; i++)
            {
                string candidate = Path.Combine(dir, "AIEngine", "ArbiterEngine", "server.py");
                if (File.Exists(candidate)) return candidate;
                dir = Path.GetDirectoryName(dir);
            }
            return string.Empty;
        }

        // ── Window transition ─────────────────────────────────────────────────

        private void OpenMainWindow()
        {
            var main = new MainWindow();
            Application.Current.MainWindow = main;
            main.Show();
            Close();
        }

        protected override void OnClosed(EventArgs e)
        {
            base.OnClosed(e);
            // If user closes the launcher without picking anything, shut down.
            if (Application.Current.Windows.Count == 0)
                Application.Current.Shutdown();
        }
    }
}
