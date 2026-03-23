using System;
using System.IO;
using System.Windows;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    /// <summary>
    /// Read-only PDF viewer backed by the Edge WebView2 runtime.
    /// </summary>
    public partial class PdfViewerWindow : Window
    {
        private readonly string _filePath;

        public PdfViewerWindow(string filePath)
        {
            InitializeComponent();
            _filePath = filePath;
            Title = $"PDF — {Path.GetFileName(filePath)}";
            FileNameLabel.Text = Path.GetFileName(filePath);
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            DarkTitleBar.Apply(this);
        }

        private async void Window_Loaded(object sender, RoutedEventArgs e)
        {
            try
            {
                await PdfWebView.EnsureCoreWebView2Async();

                // Disable context menus and dev-tools so the viewer stays read-only.
                PdfWebView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
                PdfWebView.CoreWebView2.Settings.AreDevToolsEnabled = false;

                // Navigate using the file:// URI scheme so Edge can render the PDF.
                string uri = new Uri(_filePath).AbsoluteUri;
                PdfWebView.CoreWebView2.Navigate(uri);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    $"Could not open PDF:\n{ex.Message}\n\n" +
                    "Make sure the Microsoft Edge WebView2 Runtime is installed.",
                    "PDF Viewer Error",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
                Close();
            }
        }
    }
}
