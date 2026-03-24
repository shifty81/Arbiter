using System.Windows;

namespace ArbiterHost
{
    public partial class App : Application
    {
        private void App_Startup(object sender, StartupEventArgs e)
        {
            Exit += App_Exit;
            var launcher = new LauncherWindow();
            MainWindow = launcher;
            launcher.Show();
        }

        private static void App_Exit(object sender, ExitEventArgs e)
        {
            // Check whether any managed server processes are still running.
            bool engineRunning = AppConfig.EngineProcess != null && !AppConfig.EngineProcess.HasExited;
            bool bridgeRunning = AppConfig.BridgeProcess != null && !AppConfig.BridgeProcess.HasExited;

            if (engineRunning || bridgeRunning)
            {
                // Ask the user whether to shut servers down or leave them live for
                // remote chat access (e.g. from another machine or the web UI).
                var sb = new System.Text.StringBuilder();
                sb.AppendLine("Arbiter server(s) are still running:");
                sb.AppendLine();
                if (bridgeRunning)
                    sb.AppendLine("  •  Arbiter AI Bridge  (port 8000)");
                if (engineRunning)
                    sb.AppendLine($"  •  Arbiter Engine     (port {AppConfig.ArbiterEnginePort})");
                sb.AppendLine();
                sb.AppendLine("Shut them down now, or leave them running so you can");
                sb.AppendLine("access Arbiter chat remotely via the web UI?");
                sb.AppendLine();
                sb.Append("  Yes = Shut down all servers\n  No = Leave servers running");

                var answer = MessageBox.Show(
                    sb.ToString(),
                    "Shut Down Servers?",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question,
                    MessageBoxResult.Yes);

                if (answer == MessageBoxResult.Yes)
                {
                    // Terminate the Arbiter Engine server if we started it.
                    try
                    {
                        if (engineRunning)
                            AppConfig.EngineProcess!.Kill(entireProcessTree: true);
                    }
                    catch { /* best-effort */ }

                    // Terminate the ArbiterAI bridge server (port 8000) if we started it.
                    try
                    {
                        if (bridgeRunning)
                            AppConfig.BridgeProcess!.Kill(entireProcessTree: true);
                    }
                    catch { /* best-effort */ }
                }
                // If No: leave servers running — they are accessible via web UI.
            }
            else
            {
                // No server processes managed by this app; nothing to shut down.
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
}

