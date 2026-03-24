// Novaforge Tooling Layer — MainWindow code-behind
// NF1-1: Wire up theme system, ArbiterAIManager, VS integration bridge,
//        and server status polling.
using System;
using System.Windows;

namespace Novaforge.ToolingLayer
{
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();

            // NF1-2/NF1-3: Apply default dark theme
            GUIThemeManager.Instance.Apply(GUIThemes.Dark);
            GUIThemeManager.Instance.OnThemeChanged += (_, theme) =>
            {
                // Panels re-bind to dynamic resources automatically via the
                // ResourceDictionary swap — no explicit panel refresh needed.
            };

            // NF1-12: Start VS integration bridge (Tooling Layer ↔ VSIX)
            _ = VSIntegrationBridge.Instance.StartAsync();
        }

        protected override void OnClosed(EventArgs e)
        {
            VSIntegrationBridge.Instance.Stop();
            ArbiterAIManager.Instance.Dispose();
            base.OnClosed(e);
        }
    }
}

