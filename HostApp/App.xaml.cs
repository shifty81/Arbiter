using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    public partial class App : Application
    {
        private void App_Startup(object sender, StartupEventArgs e)
        {
            Exit += App_Exit;

            // Load persisted engine path/port before opening any window
            LoadEnginePathFromSettings();

            // Open the workspace directly — no launcher
            var workspace = new MainWindow();
            MainWindow = workspace;
            workspace.Show();

            // Fire-and-forget background tasks
            _ = CheckForUpdateAsync();
            _ = TryAutoStartEngineAsync();
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
                {
                    AppConfig.ArbiterEnginePort = port;
                    AppConfig.ApiBaseUrl = $"http://127.0.0.1:{port}";
                }
            }
            catch { /* best-effort */ }
        }

        private static string ResolvePath(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw)) return string.Empty;
            if (Path.IsPathRooted(raw)) return raw;
            string fromBase = Path.GetFullPath(
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, raw));
            if (Directory.Exists(fromBase)) return fromBase;
            string? dir = AppDomain.CurrentDomain.BaseDirectory;
            for (int i = 0; i < 6 && dir != null; i++)
            {
                string candidate = Path.GetFullPath(Path.Combine(dir, raw));
                if (Directory.Exists(candidate)) return candidate;
                dir = Path.GetDirectoryName(dir);
            }
            return fromBase;
        }

        // ── Auto-update check ─────────────────────────────────────────────────

        private static async Task CheckForUpdateAsync()
        {
            try
            {
                var info = await Updater.CheckForUpdateAsync().ConfigureAwait(false);
                if (!info.UpdateAvailable || !string.IsNullOrEmpty(info.Error))
                    return;

                await Current.Dispatcher.InvokeAsync(() =>
                {
                    var result = MessageBox.Show(
                        $"A new version of Arbiter is available!\n\n" +
                        $"Current : {Updater.CurrentVersion}\n" +
                        $"Latest  : {info.LatestVersion}\n\n" +
                        $"{info.ReleaseNotes.Split('\n')[0]}\n\n" +
                        "Open the GitHub release page to download?",
                        "Arbiter Update Available",
                        MessageBoxButton.YesNo,
                        MessageBoxImage.Information);

                    if (result == MessageBoxResult.Yes && !string.IsNullOrEmpty(info.ReleaseUrl))
                        Process.Start(new ProcessStartInfo(info.ReleaseUrl) { UseShellExecute = true });
                });
            }
            catch { /* best-effort */ }
        }

        // ── Auto-start Arbiter Engine ─────────────────────────────────────────

        /// <summary>
        /// Attempt to start the ArbiterEngine server in the background on launch.
        /// MainWindow's status dot will reflect the result when it polls /health.
        /// </summary>
        private static async Task TryAutoStartEngineAsync()
        {
            // Small delay so the window can finish rendering before any dialog appears
            await Task.Delay(1200).ConfigureAwait(false);

            string serverScript = FindEngineServerScript();
            if (!File.Exists(serverScript)) return;  // not found — user can start manually

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = PythonHelper.FindExecutable(),
                    Arguments = $"\"{serverScript}\"",
                    WorkingDirectory = Path.GetDirectoryName(serverScript)!,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false,
                };
                var proc = Process.Start(psi);
                if (proc != null)
                    AppConfig.EngineProcess = proc;
            }
            catch { /* best-effort; MainWindow will show "Offline" and the user can retry */ }
        }

        private static string FindEngineServerScript()
        {
            // Prefer explicit path from settings
            if (!string.IsNullOrWhiteSpace(AppConfig.ArbiterEnginePath))
            {
                string configuredPath = Path.Combine(AppConfig.ArbiterEnginePath, "server.py");
                if (File.Exists(configuredPath)) return configuredPath;
            }

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

        // ── Exit cleanup ──────────────────────────────────────────────────────

        private static void App_Exit(object sender, ExitEventArgs e)
        {
            bool engineRunning = AppConfig.EngineProcess != null && !AppConfig.EngineProcess.HasExited;
            bool bridgeRunning = AppConfig.BridgeProcess != null && !AppConfig.BridgeProcess.HasExited;

            if (engineRunning || bridgeRunning)
            {
                var sb = new System.Text.StringBuilder();
                sb.AppendLine("Arbiter server(s) are still running:");
                sb.AppendLine();
                if (engineRunning)
                    sb.AppendLine($"  •  Arbiter Engine  (port {AppConfig.ArbiterEnginePort})");
                if (bridgeRunning)
                    sb.AppendLine("  •  Arbiter AI Bridge  (port 8000)");
                sb.AppendLine();
                sb.AppendLine("Shut them down now, or leave them running for remote access?");
                sb.AppendLine();
                sb.AppendLine("  Yes = Shut down all servers");
                sb.Append("  No  = Leave servers running");

                var answer = MessageBox.Show(
                    sb.ToString(),
                    "Shut Down Servers?",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question,
                    MessageBoxResult.Yes);

                if (answer == MessageBoxResult.Yes)
                    KillServerProcesses();
            }
            else
            {
                KillServerProcesses();
            }
        }

        private static void KillServerProcesses()
        {
            try
            {
                if (AppConfig.EngineProcess != null && !AppConfig.EngineProcess.HasExited)
                    AppConfig.EngineProcess.Kill(entireProcessTree: true);
            }
            catch { /* best-effort */ }

            try
            {
                if (AppConfig.BridgeProcess != null && !AppConfig.BridgeProcess.HasExited)
                    AppConfig.BridgeProcess.Kill(entireProcessTree: true);
            }
            catch { /* best-effort */ }
        }
    }
}

