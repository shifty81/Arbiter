namespace ArbiterHost
{
    /// <summary>
    /// Application-level configuration shared across all windows.
    /// Set by <see cref="LauncherWindow"/> before any main window is opened.
    /// </summary>
    internal static class AppConfig
    {
        /// <summary>Which mode the user launched: "ArbiterAI" or "ArbiterEngine".</summary>
        public static string Mode { get; set; } = "ArbiterAI";

        /// <summary>
        /// Base URL of the active Python backend.
        /// ArbiterAI bridge  → http://127.0.0.1:8000
        /// Arbiter Engine    → http://127.0.0.1:8001
        /// </summary>
        public static string ApiBaseUrl { get; set; } = "http://127.0.0.1:8000";

        /// <summary>Filesystem path to the AIEngine/ArbiterEngine directory.</summary>
        public static string ArbiterEnginePath { get; set; } = string.Empty;

        /// <summary>Port the Arbiter Engine bridge server should listen on.</summary>
        public static int ArbiterEnginePort { get; set; } = 8001;

        /// <summary>
        /// The Arbiter Engine subprocess (if started by the launcher).
        /// Terminated when the application exits.
        /// </summary>
        public static System.Diagnostics.Process? EngineProcess { get; set; }

        /// <summary>
        /// The ArbiterAI bridge subprocess started by MainWindow or ProjectWindow
        /// (fastapi_bridge.py on port 8000).  Stored here so App_Exit can always
        /// clean it up regardless of which window started it.
        /// </summary>
        public static System.Diagnostics.Process? BridgeProcess { get; set; }
    }
}
