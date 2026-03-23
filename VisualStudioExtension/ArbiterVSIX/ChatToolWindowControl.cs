using System;
using System.Windows;
using System.Windows.Controls;
using Microsoft.VisualStudio.Shell;

namespace ArbiterVSIX
{
    /// <summary>
    /// WPF control that hosts the Arbiter chat web UI inside the
    /// <see cref="ChatToolWindow"/>.
    ///
    /// The control embeds a WebView2 <see cref="System.Windows.Controls.WebBrowser"/>
    /// (or Microsoft.Web.WebView2 when available) and navigates to the backend's
    /// <c>/gui/</c> path.  It also bridges native VS context (active document,
    /// selection) into the web UI via PostMessage / <c>window.arbiterContext</c>.
    ///
    /// Build note: replace <see cref="WebBrowser"/> with the
    /// <c>Microsoft.Web.WebView2.Wpf.WebView2</c> control for full Chromium
    /// rendering.  The WebBrowser fallback is used here to keep the csproj
    /// free of additional NuGet references; swap it when packaging the extension.
    /// </summary>
    public sealed class ChatToolWindowControl : UserControl
    {
        private readonly WebBrowser _browser;

        public ChatToolWindowControl()
        {
            // Layout: stretch the browser to fill the tool window.
            var grid = new Grid();
            _browser = new WebBrowser();
            grid.Children.Add(_browser);
            Content = grid;

            Loaded += OnLoaded;
        }

        // ── Lifecycle ─────────────────────────────────────────────────────────

        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            NavigateToChat();
        }

        // ── Navigation ────────────────────────────────────────────────────────

        /// <summary>
        /// Navigate the embedded browser to the Arbiter chat/IDE UI.
        /// Prefers the full Monaco IDE at <c>/gui/</c>; falls back to the
        /// lightweight chat at <c>/</c>.
        /// </summary>
        public void NavigateToChat()
        {
            var baseUrl = ArbiterPackage.ApiClient?.BaseUrl ?? "http://127.0.0.1:8001";
            var uri = new Uri(baseUrl + "/gui/");
            _browser.Navigate(uri);
        }

        /// <summary>
        /// Inject the current VS document context into the web UI so that the
        /// chat can include it in AI requests automatically.
        /// </summary>
        /// <param name="filePath">Active document path.</param>
        /// <param name="selectedText">Currently selected text (may be empty).</param>
        /// <param name="project">Active VS project name.</param>
        public void InjectContext(string filePath, string selectedText, string project)
        {
            // Build a JS snippet that sets window.arbiterContext.
            // The web UI's chat handler reads this before sending each message.
            var script = $@"
(function() {{
    window.arbiterContext = {{
        filePath: {JsonEscape(filePath)},
        selection: {JsonEscape(selectedText)},
        project: {JsonEscape(project)}
    }};
    // Notify the UI if it exposes a listener.
    if (typeof window.onArbiterContextUpdate === 'function') {{
        window.onArbiterContextUpdate(window.arbiterContext);
    }}
}})();";
            try
            {
                _browser.InvokeScript("eval", script);
            }
            catch
            {
                // Browser may not be ready yet; context will be picked up next time.
            }
        }

        // ── Helpers ───────────────────────────────────────────────────────────

        private static string JsonEscape(string s)
        {
            if (s == null) return "null";
            s = s.Replace("\\", "\\\\")
                 .Replace("\"", "\\\"")
                 .Replace("\r", "\\r")
                 .Replace("\n", "\\n")
                 .Replace("\t", "\\t");
            return $"\"{s}\"";
        }
    }
}
