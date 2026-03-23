using System;
using System.Text.RegularExpressions;
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
    ///   - Build events: post-build error list → AI fix suggestions (M6-8, M6-10)
    ///   - Solution events: solution open/close → update active project (M6-9)
    ///
    /// M6-10: AI fix suggestions are surfaced in the VS Error List as info-level
    ///        "Messages" alongside the compiler errors that triggered them.
    /// </summary>
    internal sealed class EventHandlers : IDisposable
    {
        private readonly DTE2 _dte;
        private readonly ArbiterPackage _package;

        // DTE event sources (must be held alive to prevent GC).
        private DocumentEvents? _docEvents;
        private BuildEvents?    _buildEvents;
        private SolutionEvents? _solutionEvents;

        // ── M6-10: Error List provider — shows AI fix suggestions as Messages ──
        // One provider per EventHandlers instance; cleared before each build.
        private ErrorListProvider? _arbiterTaskProvider;

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

            // M6-10: initialise the Error List provider for AI fix suggestions
            _arbiterTaskProvider = new ErrorListProvider(_package)
            {
                ProviderName = "Arbiter AI",
                ProviderGuid = new Guid("2E6F4A3C-9D8B-4F1A-A56E-7C3D2B8E0F45"),
            };
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

        public void Dispose()
        {
            _arbiterTaskProvider?.Dispose();
            _arbiterTaskProvider = null;
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

        // ── Build events (M6-8, M6-10) ───────────────────────────────────────

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

                // M6-10: Clear previous Arbiter items from the Error List before the new build.
                if (_arbiterTaskProvider != null)
                {
                    ThreadHelper.JoinableTaskFactory.Run(async () =>
                    {
                        await ThreadHelper.JoinableTaskFactory.SwitchToMainThreadAsync();
                        _arbiterTaskProvider.Tasks.Clear();
                    });
                }

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

                    // M6-10: Surface each suggestion line as an info-level item in the Error List
                    // so developers see AI fix hints alongside the compiler errors.
                    AddFixSuggestionsToErrorList(result, errors);
                });
            }
            catch
            {
                // Non-fatal.
            }
        }

        /// <summary>
        /// M6-10: Adds AI-generated fix suggestions to the VS Error List as
        /// information-level ("Message") entries so they appear alongside compiler errors.
        /// </summary>
        private void AddFixSuggestionsToErrorList(string suggestions, string buildErrorContext)
        {
            ThreadHelper.ThrowIfNotOnUIThread();
            if (_arbiterTaskProvider == null) return;
            if (string.IsNullOrWhiteSpace(suggestions)) return;

            // Parse the file/line from the first build error for navigation hints.
            string sourceFile = "";
            int sourceLine = 0;
            var firstErrorLine = buildErrorContext.Split('\n')[0];
            var fileMatch = System.Text.RegularExpressions.Regex.Match(
                firstErrorLine, @"^([^(]+)\((\d+)\)");
            if (fileMatch.Success)
            {
                sourceFile = fileMatch.Groups[1].Value.Trim();
                int.TryParse(fileMatch.Groups[2].Value, out sourceLine);
            }

            // Add a header task so users know these are Arbiter suggestions.
            var header = new ErrorTask
            {
                Text          = "Arbiter AI — Fix suggestions for build errors (see Arbiter Output pane for details):",
                ErrorCategory = TaskErrorCategory.Message,
                Category      = TaskCategory.BuildCompile,
            };
            _arbiterTaskProvider.Tasks.Add(header);

            // Add each non-empty suggestion line as a separate task.
            int count = 0;
            foreach (var line in suggestions.Split('\n'))
            {
                var trimmed = line.TrimStart('-', ' ', '*').Trim();
                if (string.IsNullOrWhiteSpace(trimmed)) continue;
                if (count >= 10) break;   // cap at 10 items to avoid flooding the list

                var task = new ErrorTask
                {
                    Text          = $"[Arbiter] {trimmed}",
                    ErrorCategory = TaskErrorCategory.Message,
                    Category      = TaskCategory.BuildCompile,
                    Document      = sourceFile,
                    Line          = Math.Max(0, sourceLine - 1),   // 0-based in ErrorTask
                };
                _arbiterTaskProvider.Tasks.Add(task);
                count++;
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
