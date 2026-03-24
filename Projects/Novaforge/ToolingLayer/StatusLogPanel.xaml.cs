// Novaforge Tooling Layer — StatusLogPanel stub
// Displays live server status: uptime, player count, restart warnings.
// Full implementation tracked in roadmap.json → NF3-2.
using System.Windows.Controls;

namespace Novaforge.ToolingLayer
{
    public partial class StatusLogPanel : UserControl
    {
        public StatusLogPanel() => InitializeComponent();
        // TODO NF3-2: poll SteamServerAdmin REST API on 30s interval
        // TODO NF3-2: surface uptime, player count, last restart time
    }
}
