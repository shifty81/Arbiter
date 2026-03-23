using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.VisualStudio.Language.Intellisense.AsyncCompletion;
using Microsoft.VisualStudio.Language.Intellisense.AsyncCompletion.Data;
using Microsoft.VisualStudio.Text;
using Microsoft.VisualStudio.Text.Editor;
using Microsoft.VisualStudio.Utilities;
using System.ComponentModel.Composition;

namespace ArbiterVSIX
{
    /// <summary>
    /// InlineSuggestionProvider — Roslyn-based inline AI completions (M6-4).
    ///
    /// Trigger: typing a line that starts with the configured prefix
    /// (default: <c>// Arbiter:</c>) causes Arbiter to fetch an AI completion
    /// and inject it as a VS IntelliSense completion item.
    ///
    /// The comment is parsed as a natural-language instruction:
    ///
    ///   <code>
    ///     // Arbiter: write a binary search function
    ///   </code>
    ///
    /// The completion replaces the comment with the generated code.
    ///
    /// MEF export — automatically discovered by the VS MEF host.
    /// </summary>
    [Export(typeof(IAsyncCompletionSourceProvider))]
    [ContentType("CSharp")]
    [ContentType("Python")]
    [ContentType("JavaScript")]
    [ContentType("TypeScript")]
    [Name("ArbiterInlineSuggestion")]
    internal sealed class InlineSuggestionProvider : IAsyncCompletionSourceProvider
    {
        public IAsyncCompletionSource? GetOrCreate(ITextView textView)
            => new ArbiterCompletionSource(textView);
    }

    internal sealed class ArbiterCompletionSource : IAsyncCompletionSource
    {
        private readonly ITextView _textView;
        // Regex: captures the instruction text following the trigger prefix.
        private static readonly Regex _triggerRegex =
            new Regex(@"^\s*\/\/\s*Arbiter:\s*(.+)$", RegexOptions.Compiled | RegexOptions.IgnoreCase);

        public ArbiterCompletionSource(ITextView textView)
        {
            _textView = textView;
        }

        public async Task<CompletionContext> GetCompletionContextAsync(
            IAsyncCompletionSession session,
            CompletionTrigger trigger,
            SnapshotPoint triggerLocation,
            SnapshotSpan applicableToSpan,
            CancellationToken token)
        {
            // Read the current line up to the trigger point.
            var line = triggerLocation.GetContainingLine();
            var lineText = line.GetText();

            var match = _triggerRegex.Match(lineText);
            if (!match.Success)
                return CompletionContext.Empty;

            var instruction = match.Groups[1].Value.Trim();
            if (string.IsNullOrWhiteSpace(instruction))
                return CompletionContext.Empty;

            var client = ArbiterPackage.ApiClient;
            if (client == null) return CompletionContext.Empty;

            // Gather surrounding code as context (up to 20 lines before the trigger).
            var snapshot = triggerLocation.Snapshot;
            int startLine = Math.Max(0, line.LineNumber - 20);
            var contextText = snapshot.GetText(
                snapshot.GetLineFromLineNumber(startLine).Start,
                line.End - snapshot.GetLineFromLineNumber(startLine).Start);

            string? suggestion;
            try
            {
                suggestion = await client.AiActionAsync(
                    "complete",
                    contextText,
                    filePath: "",
                    project: "default",
                    ct: token).ConfigureAwait(false);
            }
            catch
            {
                return CompletionContext.Empty;
            }

            if (string.IsNullOrWhiteSpace(suggestion))
                return CompletionContext.Empty;

            var item = new CompletionItem(
                displayText: $"Arbiter: {instruction}",
                source: this,
                icon: default,
                filters: ImmutableArray<CompletionFilter>.Empty,
                suffix: "",
                insertText: suggestion,
                sortText: "\x0000",    // sort to top
                filterText: instruction,
                automationText: suggestion,
                attributeIcons: ImmutableArray<ImageElement>.Empty);

            return new CompletionContext(ImmutableArray.Create(item));
        }

        public Task<object?> GetDescriptionAsync(
            IAsyncCompletionSession session,
            CompletionItem item,
            CancellationToken token)
            => Task.FromResult<object?>("AI-generated code from Arbiter.");

        public CompletionStartData InitializeCompletion(
            CompletionTrigger trigger,
            SnapshotPoint triggerLocation,
            CancellationToken token)
        {
            var line = triggerLocation.GetContainingLine();
            var lineText = line.GetText();
            if (_triggerRegex.IsMatch(lineText))
                return new CompletionStartData(CompletionParticipation.ProvidesItems, new SnapshotSpan(line.Start, line.End));
            return CompletionStartData.DoesNotParticipateInCompletion;
        }
    }
}
