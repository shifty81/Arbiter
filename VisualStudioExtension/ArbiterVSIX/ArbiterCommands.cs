using System;
using System.ComponentModel.Design;
using System.Threading.Tasks;
using System.Windows;
using Microsoft.VisualStudio.Shell;
using Microsoft.VisualStudio.Shell.Interop;
using Task = System.Threading.Tasks.Task;

namespace ArbiterVSIX
{
    /// <summary>
    /// ArbiterCommands — registers all Arbiter AI commands in the VS command table.
    ///
    /// Commands and keyboard shortcuts (M6-5, M6-14 through M6-21):
    ///
    ///   Ctrl+Shift+A  — Ask Arbiter About Selection
    ///   Ctrl+Shift+E  — Explain This Code
    ///   Ctrl+Shift+F  — Fix This Error
    ///   Ctrl+Shift+R  — Refactor With Arbiter
    ///   Ctrl+Shift+T  — Generate Unit Tests
    ///   Ctrl+Shift+D  — Add Documentation
    ///   Ctrl+Shift+V  — Review This File
    ///   Ctrl+Shift+I  — Insert Code From Chat
    ///   Ctrl+Alt+A    — Open Arbiter Chat Panel
    ///
    /// All commands call <see cref="ArbiterApiClient.AiActionAsync"/> with the
    /// appropriate action name and the active editor's selected text + file context.
    /// </summary>
    internal sealed class ArbiterCommands
    {
        // ── GUIDs & IDs ───────────────────────────────────────────────────────

        public static readonly Guid CommandSetGuid =
            new Guid("c3d4e5f6-a7b8-9012-cdef-234567890123");

        // Command IDs — must match the .vsct file entries.
        public const int CmdIdAskAboutSelection  = 0x0101;
        public const int CmdIdExplainCode        = 0x0102;
        public const int CmdIdFixError           = 0x0103;
        public const int CmdIdRefactor           = 0x0104;
        public const int CmdIdGenerateTests      = 0x0105;
        public const int CmdIdAddDocs            = 0x0106;
        public const int CmdIdReviewFile         = 0x0107;
        public const int CmdIdInsertFromChat     = 0x0108;
        public const int CmdIdOpenChatPanel      = 0x0109;
        public const int CmdIdOpenSelfBuildPanel = 0x010A;  // M7-13

        // ── Fields ────────────────────────────────────────────────────────────

        private readonly ArbiterPackage _package;

        private ArbiterCommands(ArbiterPackage package)
        {
            _package = package;
        }

        // ── Initialisation ────────────────────────────────────────────────────

        public static async Task InitializeAsync(ArbiterPackage package)
        {
            await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();

            var commandService = await package.GetServiceAsync(typeof(IMenuCommandService))
                                     as OleMenuCommandService;
            if (commandService == null) return;

            var instance = new ArbiterCommands(package);

            Register(commandService, CmdIdAskAboutSelection,  instance.OnAskAboutSelection);
            Register(commandService, CmdIdExplainCode,        instance.OnExplainCode);
            Register(commandService, CmdIdFixError,           instance.OnFixError);
            Register(commandService, CmdIdRefactor,           instance.OnRefactor);
            Register(commandService, CmdIdGenerateTests,      instance.OnGenerateTests);
            Register(commandService, CmdIdAddDocs,            instance.OnAddDocs);
            Register(commandService, CmdIdReviewFile,         instance.OnReviewFile);
            Register(commandService, CmdIdInsertFromChat,     instance.OnInsertFromChat);
            Register(commandService, CmdIdOpenChatPanel,      instance.OnOpenChatPanel);
            Register(commandService, CmdIdOpenSelfBuildPanel, instance.OnOpenSelfBuildPanel);
        }

        private static void Register(
            OleMenuCommandService svc,
            int cmdId,
            EventHandler handler)
        {
            var id = new CommandID(CommandSetGuid, cmdId);
            var cmd = new OleMenuCommand(handler, id);
            svc.AddCommand(cmd);
        }

        // ── Command handlers ──────────────────────────────────────────────────

        private void OnAskAboutSelection(object sender, EventArgs e)
            => ExecuteAiAction("ask", "Ask Arbiter…");

        private void OnExplainCode(object sender, EventArgs e)
            => ExecuteAiAction("explain", "Explain Code");

        private void OnFixError(object sender, EventArgs e)
            => ExecuteAiAction("fix", "Fix Error");

        private void OnRefactor(object sender, EventArgs e)
            => ExecuteAiAction("refactor", "Refactor");

        private void OnGenerateTests(object sender, EventArgs e)
            => ExecuteAiAction("generate_tests", "Generate Tests");

        private void OnAddDocs(object sender, EventArgs e)
            => ExecuteAiAction("add_docs", "Add Documentation");

        private void OnReviewFile(object sender, EventArgs e)
            => ExecuteAiAction("review", "Review File", useWholeFile: true);

        private void OnInsertFromChat(object sender, EventArgs e)
            => ExecuteAiAction("insert", "Insert Code From Chat");

        private void OnOpenChatPanel(object sender, EventArgs e)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            _ = _package.ShowChatWindowAsync();
        }

        private void OnOpenSelfBuildPanel(object sender, EventArgs e)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            _ = _package.ShowSelfBuildWindowAsync();
        }

        // ── Core execution helper ─────────────────────────────────────────────

        /// <summary>
        /// Retrieve editor context, call the AI backend, and display the result
        /// in the output window.  Long-running — runs on a background thread.
        /// </summary>
        private void ExecuteAiAction(
            string action,
            string displayName,
            bool useWholeFile = false)
        {
            ThreadHelper.ThrowIfNotOnUIThread();

            var ctx = EditorContext.Capture(useWholeFile);
            if (ctx == null)
            {
                MessageBox.Show(
                    "No active document. Open a file in the editor first.",
                    "Arbiter AI",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
                return;
            }

            var client = ArbiterPackage.ApiClient;
            if (client == null)
            {
                MessageBox.Show(
                    "Arbiter backend not initialised. Check that the Arbiter server is running.",
                    "Arbiter AI",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
                return;
            }

            _ = Task.Run(async () =>
            {
                try
                {
                    var result = await client.AiActionAsync(
                        action,
                        ctx.SelectedText,
                        ctx.FilePath,
                        ctx.Project).ConfigureAwait(false);

                    await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                    ArbiterOutputPane.Write($"=== {displayName} ===\n{result}\n");

                    // Also inject result into the chat panel if it's open.
                    ArbiterOutputPane.ShowPane();
                }
                catch (Exception ex)
                {
                    await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                    ArbiterOutputPane.Write($"[Arbiter AI error] {ex.Message}\n");
                }
            });
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    /// <summary>
    /// Captures the current VS editor context (file path, selection, project name).
    /// </summary>
    internal sealed class EditorContext
    {
        public string FilePath    { get; private set; } = "";
        public string SelectedText { get; private set; } = "";
        public string Project     { get; private set; } = "default";

        private EditorContext() { }

        /// <summary>
        /// Capture the current active document context.
        /// Returns <c>null</c> if no document is open.
        /// </summary>
        public static EditorContext? Capture(bool useWholeFile = false)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try
            {
                var dte = (EnvDTE.DTE?)Microsoft.VisualStudio.Shell.Package.GetGlobalService(
                    typeof(EnvDTE.DTE));
                if (dte?.ActiveDocument == null) return null;

                var doc = dte.ActiveDocument;
                var ctx = new EditorContext { FilePath = doc.FullName };

                if (doc.ProjectItem?.ContainingProject != null)
                    ctx.Project = doc.ProjectItem.ContainingProject.Name;

                var sel = (EnvDTE.TextSelection)doc.Selection;
                ctx.SelectedText = useWholeFile
                    ? ((EnvDTE.TextDocument)doc.Object("TextDocument")).CreateEditPoint()
                                        .GetText(int.MaxValue)
                    : sel.Text;

                return ctx;
            }
            catch
            {
                return null;
            }
        }
    }

    /// <summary>
    /// Writes messages to a dedicated "Arbiter AI" output pane (M6-12).
    /// </summary>
    internal static class ArbiterOutputPane
    {
        private static readonly Guid _paneGuid = new Guid("d4e5f6a7-b8c9-0123-def0-345678901234");
        private static IVsOutputWindowPane? _pane;

        public static void Write(string message)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            EnsurePane();
            _pane?.OutputString(message);
        }

        public static void ShowPane()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            EnsurePane();
            _pane?.Activate();
        }

        private static void EnsurePane()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (_pane != null) return;
            var outputWindow = Microsoft.VisualStudio.Shell.Package.GetGlobalService(
                typeof(SVsOutputWindow)) as IVsOutputWindow;
            if (outputWindow == null) return;
            outputWindow.GetPane(ref _paneGuid, out _pane);
            if (_pane == null)
            {
                outputWindow.CreatePane(ref _paneGuid, "Arbiter AI", fInitVisible: 1, fClearWithSolution: 0);
                outputWindow.GetPane(ref _paneGuid, out _pane);
            }
        }
    }
}
