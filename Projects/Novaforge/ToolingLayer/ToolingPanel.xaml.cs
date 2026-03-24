// Novaforge Tooling Layer — ToolingPanel code-behind
// NF1-9: Renders clickable AI action list (insert_prefab, add_script, tooling_update).
// NF1-10: Wires Execute button to ArbiterAIManager.ExecuteActionAsync().
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Novaforge.ToolingLayer
{
    public partial class ToolingPanel : UserControl
    {
        private List<AIAction> _pendingActions = new();

        public ToolingPanel() => InitializeComponent();

        // ── Generate actions ──────────────────────────────────────────────────

        public async Task LoadActionsAsync(string goal)
        {
            _pendingActions = await ArbiterAIManager.Instance.GenerateActionsAsync(goal);
            Dispatcher.Invoke(RefreshList);
        }

        private void RefreshList()
        {
            ActionsList?.Items.Clear();
            if (ActionsList == null) return;
            foreach (var a in _pendingActions)
            {
                var item = new ListBoxItem
                {
                    Content = $"[{a.Type}] {a.Title}",
                    Tag     = a,
                    ToolTip = a.Description,
                };
                ActionsList.Items.Add(item);
            }
        }

        // ── Execute selected action ───────────────────────────────────────────

        private async void OnExecuteClicked(object sender, RoutedEventArgs e)
        {
            if (ActionsList?.SelectedItem is not ListBoxItem item) return;
            if (item.Tag is not AIAction action) return;

            var (success, message) = await ArbiterAIManager.Instance.ExecuteActionAsync(action);
            MessageBox.Show(
                $"{(success ? "✅" : "❌")} {message}",
                "Action Result",
                MessageBoxButton.OK,
                success ? MessageBoxImage.Information : MessageBoxImage.Warning);
        }

        // ── Named XAML elements ───────────────────────────────────────────────
        private ListBox? ActionsList => null;   // TODO: bind from XAML
    }
}
