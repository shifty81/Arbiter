using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.VisualStudio.Shell;

namespace ArbiterVSIX
{
    /// <summary>
    /// WPF control for the Arbiter Self-Build tool window (M7-13).
    ///
    /// Provides:
    ///   • Mode selector (Manual / Assist / SemiAuto / FullAuto)
    ///   • Task ID input (blank = auto-pick next pending task)
    ///   • Start / Stop buttons
    ///   • Approve / Reject buttons (visible when pending_approval = true)
    ///   • Live log viewer (polling /self-build/log every 2 s while running)
    ///   • Status indicator
    /// </summary>
    public sealed class SelfBuildToolWindowControl : UserControl
    {
        // ── HTTP client ────────────────────────────────────────────────────────
        private static readonly HttpClient _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(8),
        };

        // ── UI elements ────────────────────────────────────────────────────────
        private readonly ComboBox   _modeCombo;
        private readonly TextBox    _taskIdBox;
        private readonly Button     _startBtn;
        private readonly Button     _stopBtn;
        private readonly StackPanel _approvalPanel;
        private readonly Button     _approveBtn;
        private readonly Button     _rejectBtn;
        private readonly TextBox    _logBox;
        private readonly TextBlock  _statusLabel;

        // ── Polling ────────────────────────────────────────────────────────────
        private System.Threading.CancellationTokenSource? _pollCts;
        private int _lastLogLine = 0;

        // ── Constructor ────────────────────────────────────────────────────────
        public SelfBuildToolWindowControl()
        {
            // ── Root layout ───────────────────────────────────────────────────
            var root = new Grid();
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // header
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // controls
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // approval
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // log
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // status
            Content = root;

            // ── Header ────────────────────────────────────────────────────────
            var header = new TextBlock
            {
                Text = "🤖 Arbiter Self-Build Loop",
                FontWeight = FontWeights.Bold,
                FontSize = 13,
                Margin = new Thickness(8, 8, 8, 4),
            };
            Grid.SetRow(header, 0);
            root.Children.Add(header);

            // ── Controls row ──────────────────────────────────────────────────
            var ctrlPanel = new WrapPanel { Margin = new Thickness(6, 0, 6, 4) };
            Grid.SetRow(ctrlPanel, 1);
            root.Children.Add(ctrlPanel);

            // Mode selector
            var modeLabel = new TextBlock { Text = "Mode:", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 4, 0) };
            ctrlPanel.Children.Add(modeLabel);
            _modeCombo = new ComboBox { Width = 90, Margin = new Thickness(0, 0, 8, 0) };
            foreach (var m in new[] { "Manual", "Assist", "SemiAuto", "FullAuto" })
                _modeCombo.Items.Add(m);
            _modeCombo.SelectedIndex = 1; // Assist
            ctrlPanel.Children.Add(_modeCombo);

            // Task ID
            var taskLabel = new TextBlock { Text = "Task ID:", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 4, 0) };
            ctrlPanel.Children.Add(taskLabel);
            _taskIdBox = new TextBox { Width = 80, Margin = new Thickness(0, 0, 8, 0), ToolTip = "Leave blank to auto-pick next pending task" };
            ctrlPanel.Children.Add(_taskIdBox);

            // Start / Stop
            _startBtn = new Button { Content = "▶ Start", Padding = new Thickness(8, 3, 8, 3), Margin = new Thickness(0, 0, 4, 0) };
            _startBtn.Click += StartBtn_Click;
            ctrlPanel.Children.Add(_startBtn);

            _stopBtn = new Button { Content = "⏹ Stop", Padding = new Thickness(8, 3, 8, 3), IsEnabled = false };
            _stopBtn.Click += StopBtn_Click;
            ctrlPanel.Children.Add(_stopBtn);

            // ── Approval row (hidden until pending) ───────────────────────────
            _approvalPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(8, 2, 8, 4),
                Visibility = Visibility.Collapsed,
            };
            Grid.SetRow(_approvalPanel, 2);
            root.Children.Add(_approvalPanel);

            var approvalLabel = new TextBlock
            {
                Text = "⏳ Awaiting approval:",
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 8, 0),
            };
            _approvalPanel.Children.Add(approvalLabel);

            _approveBtn = new Button { Content = "✅ Approve", Padding = new Thickness(8, 3, 8, 3), Margin = new Thickness(0, 0, 4, 0) };
            _approveBtn.Click += (_, _) => _ = SendApprovalAsync(true);
            _approvalPanel.Children.Add(_approveBtn);

            _rejectBtn = new Button { Content = "✕ Reject", Padding = new Thickness(8, 3, 8, 3) };
            _rejectBtn.Click += (_, _) => _ = SendApprovalAsync(false);
            _approvalPanel.Children.Add(_rejectBtn);

            // ── Log viewer ────────────────────────────────────────────────────
            var logBorder = new Border
            {
                BorderBrush = SystemColors.ControlDarkBrush,
                BorderThickness = new Thickness(1),
                Margin = new Thickness(6, 0, 6, 0),
            };
            Grid.SetRow(logBorder, 3);
            root.Children.Add(logBorder);

            _logBox = new TextBox
            {
                IsReadOnly = true,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
                FontFamily = new FontFamily("Consolas, Courier New"),
                FontSize = 11,
                TextWrapping = TextWrapping.NoWrap,
                Background = Brushes.Black,
                Foreground = Brushes.LightGreen,
            };
            logBorder.Child = _logBox;

            // ── Status bar ────────────────────────────────────────────────────
            _statusLabel = new TextBlock
            {
                Text = "Status: idle",
                Margin = new Thickness(8, 2, 8, 4),
                FontSize = 11,
            };
            Grid.SetRow(_statusLabel, 4);
            root.Children.Add(_statusLabel);
        }

        // ── Helpers ────────────────────────────────────────────────────────────

        private string BaseUrl => ArbiterPackage.ApiClient?.BaseUrl ?? "http://127.0.0.1:8001";

        private void AppendLog(string text)
        {
            Dispatcher.BeginInvoke((Action)(() =>
            {
                _logBox.AppendText(text);
                _logBox.ScrollToEnd();
            }));
        }

        private void SetStatus(string text)
        {
            Dispatcher.BeginInvoke((Action)(() => _statusLabel.Text = $"Status: {text}"));
        }

        // ── Start ──────────────────────────────────────────────────────────────

        private async void StartBtn_Click(object sender, RoutedEventArgs e)
        {
            _logBox.Clear();
            _lastLogLine = 0;
            string mode    = (_modeCombo.SelectedItem?.ToString() ?? "Assist").ToLowerInvariant();
            string taskId  = _taskIdBox.Text.Trim();

            _startBtn.IsEnabled = false;
            _stopBtn.IsEnabled  = true;
            SetStatus("running");

            try
            {
                var body = JsonSerializer.Serialize(new { mode, task_id = taskId });
                using var content = new StringContent(body, Encoding.UTF8, "application/json");
                var resp = await _http.PostAsync($"{BaseUrl}/self-build/start", content);
                string json = await resp.Content.ReadAsStringAsync();
                AppendLog(json + "\n");

                // Start polling
                _pollCts = new System.Threading.CancellationTokenSource();
                _ = PollStatusAsync(_pollCts.Token);
            }
            catch (Exception ex)
            {
                AppendLog($"Error: {ex.Message}\n");
                SetStatus("error");
                _startBtn.IsEnabled = true;
                _stopBtn.IsEnabled  = false;
            }
        }

        // ── Stop ───────────────────────────────────────────────────────────────

        private async void StopBtn_Click(object sender, RoutedEventArgs e)
        {
            _pollCts?.Cancel();
            try
            {
                await _http.PostAsync($"{BaseUrl}/self-build/stop", null);
            }
            catch { /* ignore */ }
            SetStatus("stopped");
            _startBtn.IsEnabled = true;
            _stopBtn.IsEnabled  = false;
            _approvalPanel.Visibility = Visibility.Collapsed;
        }

        // ── Approve / Reject ───────────────────────────────────────────────────

        private async Task SendApprovalAsync(bool approved)
        {
            try
            {
                var body = JsonSerializer.Serialize(new { approved });
                using var content = new StringContent(body, Encoding.UTF8, "application/json");
                await _http.PostAsync($"{BaseUrl}/self-build/approve", content);
                Dispatcher.BeginInvoke((Action)(() =>
                    _approvalPanel.Visibility = Visibility.Collapsed));
                AppendLog(approved ? "✅ Approved.\n" : "✕ Rejected.\n");
            }
            catch (Exception ex)
            {
                AppendLog($"Approval error: {ex.Message}\n");
            }
        }

        // ── Status poller ──────────────────────────────────────────────────────

        private async Task PollStatusAsync(System.Threading.CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    // Fetch new log lines
                    var logResp = await _http.GetAsync($"{BaseUrl}/self-build/log?tail=200");
                    if (logResp.IsSuccessStatusCode)
                    {
                        string logJson = await logResp.Content.ReadAsStringAsync();
                        using var doc = JsonDocument.Parse(logJson);
                        if (doc.RootElement.TryGetProperty("lines", out var lines))
                        {
                            var arr = lines.EnumerateArray().ToList();
                            if (arr.Count > _lastLogLine)
                            {
                                for (int i = _lastLogLine; i < arr.Count; i++)
                                    AppendLog((arr[i].GetString() ?? "") + "\n");
                                _lastLogLine = arr.Count;
                            }
                        }
                    }

                    // Check status & approval
                    var statusResp = await _http.GetAsync($"{BaseUrl}/self-build/status");
                    if (statusResp.IsSuccessStatusCode)
                    {
                        string statusJson = await statusResp.Content.ReadAsStringAsync();
                        using var sdoc = JsonDocument.Parse(statusJson);
                        string status = sdoc.RootElement.TryGetProperty("status", out var s)
                            ? s.GetString() ?? "unknown" : "unknown";
                        bool pendingApproval = sdoc.RootElement.TryGetProperty("pending_approval", out var pa)
                            && pa.GetBoolean();

                        SetStatus(status);
                        Dispatcher.BeginInvoke((Action)(() =>
                            _approvalPanel.Visibility = pendingApproval
                                ? Visibility.Visible : Visibility.Collapsed));

                        if (status is "done" or "error" or "idle")
                        {
                            _pollCts?.Cancel();
                            Dispatcher.BeginInvoke((Action)(() =>
                            {
                                _startBtn.IsEnabled = true;
                                _stopBtn.IsEnabled  = false;
                            }));
                            break;
                        }
                    }
                }
                catch { /* server may be offline */ }

                await Task.Delay(2000, ct).ConfigureAwait(false);
            }
        }
    }

    // ── LINQ helper ──────────────────────────────────────────────────────────
    internal static class EnumeratorExtensions
    {
        internal static System.Collections.Generic.List<JsonElement> ToList(
            this System.Text.Json.JsonElement.ArrayEnumerator enumerator)
        {
            var list = new System.Collections.Generic.List<JsonElement>();
            foreach (var el in enumerator) list.Add(el);
            return list;
        }
    }
}
