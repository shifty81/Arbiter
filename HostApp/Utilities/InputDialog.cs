using System.Windows;
using System.Windows.Controls;

namespace ArbiterHost.Utilities
{
    /// <summary>
    /// Simple input dialog to replace Microsoft.VisualBasic.Interaction.InputBox.
    /// </summary>
    public static class InputDialog
    {
        public static string? Show(string prompt, string title = "Input", string defaultValue = "")
        {
            var dialog = new Window
            {
                Title = title,
                Width = 400,
                Height = 150,
                WindowStartupLocation = WindowStartupLocation.CenterOwner,
                ResizeMode = ResizeMode.NoResize
            };

            var grid = new Grid { Margin = new Thickness(10) };
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var label = new TextBlock { Text = prompt, Margin = new Thickness(0, 0, 0, 5) };
            Grid.SetRow(label, 0);

            var textBox = new TextBox { Text = defaultValue, Margin = new Thickness(0, 0, 0, 10) };
            Grid.SetRow(textBox, 1);

            var buttonPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };
            Grid.SetRow(buttonPanel, 2);

            string? result = null;

            var okButton = new Button { Content = "OK", Width = 75, Margin = new Thickness(0, 0, 5, 0), IsDefault = true };
            okButton.Click += (_, _) =>
            {
                result = textBox.Text;
                dialog.Close();
            };

            var cancelButton = new Button { Content = "Cancel", Width = 75, IsCancel = true };
            cancelButton.Click += (_, _) => dialog.Close();

            buttonPanel.Children.Add(okButton);
            buttonPanel.Children.Add(cancelButton);

            grid.Children.Add(label);
            grid.Children.Add(textBox);
            grid.Children.Add(buttonPanel);

            dialog.Content = grid;
            dialog.SourceInitialized += (_, _) => DarkTitleBar.Apply(dialog);
            dialog.ShowDialog();

            return result;
        }
    }
}
