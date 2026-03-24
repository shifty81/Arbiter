// Novaforge Tooling Layer — ToolingPanel stub
// Renders clickable AI action list (insert_prefab, add_script, tooling_update).
// Full implementation tracked in roadmap.json → NF1-9.
using System.Windows.Controls;

namespace Novaforge.ToolingLayer
{
    public partial class ToolingPanel : UserControl
    {
        public ToolingPanel() => InitializeComponent();
        // TODO NF1-9: bind to ArbiterAIManager.GenerateActionsAsync()
        // TODO NF1-10: wire Execute button to ArbiterAIManager.ExecuteActionAsync()
    }
}
