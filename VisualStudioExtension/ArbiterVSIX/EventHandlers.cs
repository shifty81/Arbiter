using System;
using EnvDTE;
using EnvDTE80;
using Microsoft.VisualStudio.Shell;

namespace ArbiterVSIX
{
    /// <summary>
    /// EventHandlers — subscribes to VS DTE events for context injection (M6-6 through M6-10).
    ///
    /// Handles:
    ///   - Document events: file open/save → update Arbiter context (M6-7)
    ///   - Build events: post-build error list → AI fix suggestions (M6-8)
    ///   - Solution events: solution open/close → update active project (M6-9)
    /// </summary>
    internal sealed class EventHandlers
    {
        private readonly DTE2 _dte;
        private readonly ArbiterPackage _package;

        // DTE event sources (must be held alive to prevent GC).
        private DocumentEvents? _docEvents;
        private BuildEvents?    _buildEvents;
        private SolutionEvents? _solutionEvents;

        public EventHandlers(DTE2 dte, ArbiterPackage package)
        {
            _dte     = dte;
            _package = package;
        }

        // ── Registration ─────────────────────────────────────────────────────

        public void Register()
        {
            ThreadHelper.ThrowIfNotOnUIThread();

            _docEvents     = _dte.Events.DocumentEvents;
            _buildEvents   = _dte.Events.BuildEvents;
            _solutionEvents = _dte.Events.SolutionEvents;

            _docEvents.DocumentOpened  += OnDocumentOpened;
            _docEvents.DocumentSaved   += OnDocumentSaved;

            _buildEvents.OnBuildDone   += OnBuildDone;

            _solutionEvents.Opened     += OnSolutionOpened;
            _solutionEvents.AfterClosing += OnSolutionClosed;
        }

        public void Unregister()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (_docEvents != null)
            {
                _docEvents.DocumentOpened -= OnDocumentOpened;
                _docEvents.DocumentSaved  -= OnDocumentSaved;
            }
            if (_buildEvents != null)
                _buildEvents.OnBuildDone -= OnBuildDone;
            if (_solutionEvents != null)
            {
                _solutionEvents.Opened       -= OnSolutionOpened;
                _solutionEvents.AfterClosing -= OnSolutionClosed;
            }
        }

        // ── Document events (M6-7) ────────────────────────────────────────────

        private void OnDocumentOpened(Document document)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            UpdateChatContext(document);
        }

        private void OnDocumentSaved(Document document)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            UpdateChatContext(document);
        }

        private void UpdateChatContext(Document document)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try
            {
                string project = document.ProjectItem?.ContainingProject?.Name ?? "default";
                string filePath = document.FullName;

                // Inject context into the chat tool window if it is open.
                if (_package.FindToolWindow(typeof(ChatToolWindow), 0, false)
                        is ChatToolWindow { Content: ChatToolWindowControl control })
                {
                    control.InjectContext(filePath, "", project);
                }

                // Update the backend's active project context via a fire-and-forget call.
                var client = ArbiterPackage.ApiClient;
                if (client == null) return;
                _ = client.ChatAsync(
                    $"[context_update] active_file={filePath} project={project}",
                    project: project);
            }
            catch
            {
                // Non-fatal; best effort.
            }
        }

        // ── Build events (M6-8) ───────────────────────────────────────────────

        private void OnBuildDone(vsBuildScope scope, vsBuildAction action)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            try
            {
                var errors = CollectBuildErrors();
                if (errors.Length == 0) return;

                var client = ArbiterPackage.ApiClient;
                if (client == null) return;

                ArbiterOutputPane.Write($"\n[Arbiter AI] Detected {errors.Length} build error(s). Requesting fix suggestions…\n");

                _ = System.Threading.Tasks.Task.Run(async () =>
                {
                    var result = await client.AiActionAsync(
                        "fix",
                        code: errors,
                        filePath: "build_errors",
                        project: "default").ConfigureAwait(false);

                    await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                    ArbiterOutputPane.Write($"[Arbiter AI — Fix Suggestions]\n{result}\n");
                    ArbiterOutputPane.ShowPane();
                });
            }
            catch
            {
                // Non-fatal.
            }
        }

        private string CollectBuildErrors()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            var sb = new System.Text.StringBuilder();
            try
            {
                var errorList = _dte.ToolWindows.ErrorList;
                for (int i = 1; i <= errorList.ErrorItems.Count && i <= 10; i++)
                {
                    var item = errorList.ErrorItems.Item(i);
                    if (item.ErrorLevel == vsBuildErrorLevel.vsBuildErrorLevelHigh)
                        sb.AppendLine($"{item.FileName}({item.Line}): error {item.Description}");
                }
            }
            catch { /* ignore */ }
            return sb.ToString();
        }

        // ── Solution events (M6-9) ────────────────────────────────────────────

        private void OnSolutionOpened()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            ArbiterOutputPane.Write($"[Arbiter AI] Solution opened: {_dte.Solution?.FullName}\n");
        }

        private void OnSolutionClosed()
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            ArbiterOutputPane.Write("[Arbiter AI] Solution closed.\n");
        }
    }
}
