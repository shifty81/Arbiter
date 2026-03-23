using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using EnvDTE80;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.Interop;
using Task = System.Threading.Tasks.Task;

namespace ArbiterVSIX
{
    /// <summary>
    /// ArbiterPackage — Visual Studio AsyncPackage entry point.
    ///
    /// Responsibilities:
    ///   - Register all Arbiter tool windows, commands, and settings on VS startup.
    ///   - Auto-detect and connect to the running Arbiter backend
    ///     (port 8001 → ArbiterEngine, port 8000 → PythonBridge fallback).
    ///   - Expose a package-level <see cref="ApiClient"/> singleton for all sub-components.
    ///   - Display backend status in the VS status bar.
    /// </summary>
    [PackageRegistration(UseManagedResourcesOnly = true, AllowsBackgroundLoading = true)]
    [Guid(PackageGuidString)]
    [ProvideMenuResource("Menus.ctmenu", 1)]
    [ProvideToolWindow(typeof(ChatToolWindow),
        Style = VsDockStyle.Tabbed,
        Window = "DocumentWell",
        Transient = false,
        Orientation = ToolWindowOrientation.Right)]
    [ProvideOptionPage(typeof(ArbiterSettingsPage),
        "Arbiter AI", "General", 0, 0, true)]
    [ProvideAutoLoad(UIContextGuids80.SolutionExists,
        PackageAutoLoadFlags.BackgroundLoad)]
    public sealed class ArbiterPackage : AsyncPackage
    {
        // Must match the GUID in the .vsct command-table file.
        public const string PackageGuidString = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
        public static readonly Guid PackageGuid = new Guid(PackageGuidString);

        /// <summary>Package-level singleton API client (shared by all commands and tool windows).</summary>
        internal static ArbiterApiClient? ApiClient { get; private set; }

        /// <summary>Status bar service cached at init time.</summary>
        private IVsStatusbar? _statusBar;

        /// <summary>DTE event subscriptions — kept alive to prevent GC-collection of event delegates.</summary>
        private EventHandlers? _eventHandlers;

        // ── AsyncPackage lifecycle ────────────────────────────────────────────

        protected override async Task InitializeAsync(
            CancellationToken cancellationToken,
            IProgress<ServiceProgressData> progress)
        {
            // Switch to the UI thread to access VS services.
            await JoinableTaskFactory.SwitchToMainThreadAsync(cancellationToken);

            // Cache the status bar service.
            _statusBar = await GetServiceAsync(typeof(SVsStatusbar)) as IVsStatusbar;

            // Initialise the API client and auto-detect the backend.
            ApiClient = new ArbiterApiClient();
            var settings = (ArbiterSettingsPage)GetDialogPage(typeof(ArbiterSettingsPage));
            if (!string.IsNullOrWhiteSpace(settings.BackendUrl))
                ApiClient.SetBaseUrl(settings.BackendUrl);

            // Register all commands.
            await ArbiterCommands.InitializeAsync(this);

            // Register DTE event handlers (document, build, solution events — M6-7 through M6-10).
            var dte = await GetServiceAsync(typeof(EnvDTE.DTE)) as EnvDTE80.DTE2;
            if (dte != null)
            {
                _eventHandlers = new EventHandlers(dte, this);
                _eventHandlers.Register();
            }

            // Probe backend in background — do not block VS startup.
            _ = Task.Run(async () =>
            {
                bool alive = await ApiClient.AutoDetectBackendAsync(cancellationToken)
                                            .ConfigureAwait(false);
                await JoinableTaskFactory.SwitchToMainThreadAsync(cancellationToken);
                UpdateStatusBar(alive
                    ? $"Arbiter AI: connected ({ApiClient.BaseUrl})"
                    : "Arbiter AI: backend not found — start ArbiterAI first");
            }, cancellationToken);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _eventHandlers?.Unregister();
                _eventHandlers?.Dispose();
                _eventHandlers = null;
                ApiClient?.Dispose();
                ApiClient = null;
            }
            base.Dispose(disposing);
        }

        // ── Public helpers ────────────────────────────────────────────────────

        /// <summary>Show or activate the Arbiter chat tool window.</summary>
        public async Task ShowChatWindowAsync()
        {
            await JoinableTaskFactory.SwitchToMainThreadAsync();
            var window = await FindToolWindowAsync(
                typeof(ChatToolWindow), 0, true, DisposalToken);
            if (window?.Frame is IVsWindowFrame frame)
                frame.Show();
        }

        // ── Private helpers ──────────────────────────────────────────────────

        private void UpdateStatusBar(string text)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            _statusBar?.FreezeOutput(0);
            _statusBar?.SetText(text);
        }
    }
}
