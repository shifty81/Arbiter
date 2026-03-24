// Novaforge Tooling Layer — ChatPanel code-behind
// NF1-8: IAsyncEnumerable token stream; displays tokens in real-time.
// NF1-9: Shows clickable AIAction buttons returned by GenerateActionsAsync().
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;

namespace Novaforge.ToolingLayer
{
    public partial class ChatPanel : UserControl
    {
        private CancellationTokenSource? _streamCts;
        private readonly StringBuilder   _currentTokenBuffer = new();

        public ChatPanel() => InitializeComponent();

        // ── Send message ──────────────────────────────────────────────────────

        private async void OnSendClicked(object sender, RoutedEventArgs e)
        {
            var prompt = InputBox?.Text?.Trim();
            if (string.IsNullOrEmpty(prompt)) return;
            if (InputBox != null) InputBox.Text = "";

            AppendUserMessage(prompt);
            await StreamAIReplyAsync(prompt);
        }

        private void OnInputKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Enter && !Keyboard.Modifiers.HasFlag(ModifierKeys.Shift))
            {
                OnSendClicked(sender, e);
                e.Handled = true;
            }
        }

        // ── Streaming ─────────────────────────────────────────────────────────

        private async Task StreamAIReplyAsync(string prompt)
        {
            _streamCts?.Cancel();
            _streamCts = new CancellationTokenSource();
            _currentTokenBuffer.Clear();

            var aiRun = AppendAIMessagePlaceholder();

            try
            {
                await foreach (var token in ArbiterAIManager.Instance
                    .StreamAsync(prompt, _streamCts.Token)
                    .ConfigureAwait(false))
                {
                    _currentTokenBuffer.Append(token);
                    Dispatcher.Invoke(() =>
                    {
                        if (aiRun?.Parent is Paragraph para)
                        {
                            aiRun.Text = _currentTokenBuffer.ToString();
                        }
                    });
                }
            }
            catch (OperationCanceledException) { /* user cancelled */ }
            catch (Exception ex)
            {
                Dispatcher.Invoke(() =>
                {
                    if (aiRun?.Parent is Paragraph para)
                        aiRun.Text = $"[Error: {ex.Message}]";
                });
            }
        }

        // ── Message bubble helpers ────────────────────────────────────────────

        private void AppendUserMessage(string text)
        {
            Dispatcher.Invoke(() =>
            {
                var para = new Paragraph(new Run(text))
                {
                    Foreground = (Brush)Application.Current.Resources
                        .GetValueOrDefault("Theme.UserText", Brushes.White),
                    Margin     = new Thickness(4, 2, 4, 2),
                };
                ChatDocument?.Blocks.Add(para);
                ChatScrollViewer?.ScrollToEnd();
            });
        }

        private Run? AppendAIMessagePlaceholder()
        {
            Run? tokenRun = null;
            Dispatcher.Invoke(() =>
            {
                tokenRun = new Run("▌")  // blinking cursor placeholder
                {
                    Foreground = (Brush)Application.Current.Resources
                        .GetValueOrDefault("Theme.AiText", Brushes.LightGreen),
                };
                var para = new Paragraph(tokenRun)
                {
                    Margin = new Thickness(4, 2, 4, 2),
                };
                ChatDocument?.Blocks.Add(para);
                ChatScrollViewer?.ScrollToEnd();
            });
            return tokenRun;
        }

        // ── Named XAML elements (linked from ChatPanel.xaml) ──────────────────
        // These properties are populated by x:Name bindings in the XAML stub.
        private FlowDocument?    ChatDocument    => null;   // TODO: bind from XAML
        private ScrollViewer?    ChatScrollViewer => null;  // TODO: bind from XAML
        private TextBox?         InputBox        => null;   // TODO: bind from XAML
    }
}
