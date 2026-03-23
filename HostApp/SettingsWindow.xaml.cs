using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Windows;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    /// <summary>
    /// Settings dialog for Arbiter IDE (M4-6).
    ///
    /// Reads / writes <c>Config/settings.json</c> relative to the application
    /// base directory.  Exposes:
    ///   • Server ports (PythonBridge port 8000, ArbiterEngine port 8001)
    ///   • LLM backend URL and default model
    ///   • Voice profile and TTS on/off
    ///   • Git author identity
    ///   • Library paths for the Archive
    ///   • Chat logging toggle
    /// </summary>
    public partial class SettingsWindow : Window
    {
        // ── Settings file path ────────────────────────────────────────────────
        private static string SettingsPath
        {
            get
            {
                // Walk up from the executable to find the repo root Config folder.
                string dir = AppDomain.CurrentDomain.BaseDirectory;
                for (int i = 0; i < 6; i++)
                {
                    var candidate = Path.Combine(dir, "Config", "settings.json");
                    if (File.Exists(candidate)) return candidate;
                    var parent = Directory.GetParent(dir);
                    if (parent == null) break;
                    dir = parent.FullName;
                }
                // Fallback: executable dir
                return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "Config", "settings.json");
            }
        }

        // ── Current raw settings dict (preserved across saves) ────────────────
        private Dictionary<string, JsonElement> _raw = new();

        // ── Constructor ────────────────────────────────────────────────────────
        public SettingsWindow()
        {
            InitializeComponent();
            DarkTitleBar.Apply(this);
            LoadSettings();
        }

        // ── Load ──────────────────────────────────────────────────────────────
        private void LoadSettings()
        {
            try
            {
                if (!File.Exists(SettingsPath)) return;
                string json = File.ReadAllText(SettingsPath);
                using var doc = JsonDocument.Parse(json);
                // Copy all properties into the raw dictionary for round-trip preservation.
                foreach (var prop in doc.RootElement.EnumerateObject())
                    _raw[prop.Name] = prop.Value.Clone();

                // Ports
                BridgePortBox.Text  = GetStr("python_bridge_url", "http://127.0.0.1:8000")
                    .Replace("http://127.0.0.1:", "").Replace("http://localhost:", "");
                EnginePortBox.Text  = GetInt("arbiterEnginePort", 8001).ToString();

                // LLM
                LlmUrlBox.Text      = GetStr("llm_backend_url", "http://localhost:11434");
                LlmModelBox.Text    = GetStr("llm_model", "auto");

                // Voice
                string voice = GetStr("default_voice", "British_Female");
                foreach (System.Windows.Controls.ComboBoxItem item in VoiceCombo.Items)
                    if (item.Content?.ToString() == voice) { VoiceCombo.SelectedItem = item; break; }
                TtsEnabledCheck.IsChecked = GetBool("tts_enabled", true);

                // Git
                GitNameBox.Text   = GetStr("git_author_name", "ArbiterUser");
                GitEmailBox.Text  = GetStr("git_author_email", "arbiter@local");

                // Library paths
                if (_raw.TryGetValue("library_paths", out var lp) && lp.ValueKind == JsonValueKind.Array)
                {
                    var paths = new System.Text.StringBuilder();
                    foreach (var el in lp.EnumerateArray())
                        paths.AppendLine(el.GetString() ?? "");
                    LibraryPathsBox.Text = paths.ToString().TrimEnd();
                }

                // Misc
                ChatLoggingCheck.IsChecked = GetBool("chat_logging", true);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Could not load settings:\n{ex.Message}", "Settings",
                    MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        // ── Save ──────────────────────────────────────────────────────────────
        private void Save_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                // Parse port fields
                string bridgePort = BridgePortBox.Text.Trim();
                string enginePort = EnginePortBox.Text.Trim();
                if (!int.TryParse(enginePort, out int enginePortNum))
                    enginePortNum = 8001;

                // Build bridge URL from port or keep full URL
                string bridgeUrl = bridgePort.StartsWith("http", StringComparison.OrdinalIgnoreCase)
                    ? bridgePort
                    : $"http://127.0.0.1:{(int.TryParse(bridgePort, out int bp) ? bp : 8000)}";

                // Collect library paths (non-empty lines)
                var libraryPaths = new List<string>();
                foreach (var line in LibraryPathsBox.Text.Split('\n'))
                {
                    string trimmed = line.Trim();
                    if (!string.IsNullOrWhiteSpace(trimmed))
                        libraryPaths.Add(trimmed);
                }

                // Build settings object, preserving unknown keys
                var dict = new Dictionary<string, object?>();
                // Copy unknown preserved keys first
                foreach (var kv in _raw)
                {
                    if (!IsKnownKey(kv.Key))
                        dict[kv.Key] = kv.Value;
                }
                // Override with form values
                dict["python_bridge_url"]  = bridgeUrl;
                dict["arbiterEnginePort"]  = enginePortNum;
                dict["llm_backend_url"]    = LlmUrlBox.Text.Trim();
                dict["llm_model"]          = LlmModelBox.Text.Trim();
                dict["default_voice"]      = (VoiceCombo.SelectedItem as System.Windows.Controls.ComboBoxItem)?.Content?.ToString() ?? "British_Female";
                dict["tts_enabled"]        = TtsEnabledCheck.IsChecked == true;
                dict["git_author_name"]    = GitNameBox.Text.Trim();
                dict["git_author_email"]   = GitEmailBox.Text.Trim();
                dict["library_paths"]      = libraryPaths;
                dict["chat_logging"]       = ChatLoggingCheck.IsChecked == true;
                // Keep preserved fields that aren't in our form
                foreach (var kv in _raw)
                {
                    if (!dict.ContainsKey(kv.Key))
                        dict[kv.Key] = kv.Value;
                }

                string json = JsonSerializer.Serialize(dict, new JsonSerializerOptions { WriteIndented = true });
                string dir = Path.GetDirectoryName(SettingsPath)!;
                Directory.CreateDirectory(dir);
                File.WriteAllText(SettingsPath, json);

                // Apply immediately to AppConfig
                AppConfig.ApiBaseUrl = bridgeUrl;
                AppConfig.ArbiterEnginePort = enginePortNum;

                DialogResult = true;
                Close();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Could not save settings:\n{ex.Message}", "Settings",
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void Cancel_Click(object sender, RoutedEventArgs e) => Close();

        // ── Library path helpers ───────────────────────────────────────────────
        private void AddLibraryPath_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "Select Library Path",
                Multiselect = false,
            };
            if (dlg.ShowDialog() != true) return;
            string current = LibraryPathsBox.Text.TrimEnd();
            LibraryPathsBox.Text = string.IsNullOrWhiteSpace(current)
                ? dlg.FolderName
                : current + Environment.NewLine + dlg.FolderName;
        }

        private void RemoveLibraryPath_Click(object sender, RoutedEventArgs e)
        {
            // Remove the line that the caret is currently on.
            int idx = LibraryPathsBox.GetLineIndexFromCharacterIndex(LibraryPathsBox.CaretIndex);
            if (idx < 0) return;
            var lines = new List<string>(LibraryPathsBox.Text.Split('\n'));
            if (idx < lines.Count)
            {
                lines.RemoveAt(idx);
                LibraryPathsBox.Text = string.Join("\n", lines).TrimEnd();
            }
        }

        // ── JSON helpers ──────────────────────────────────────────────────────
        private string GetStr(string key, string def)
        {
            if (_raw.TryGetValue(key, out var v) && v.ValueKind == JsonValueKind.String)
                return v.GetString() ?? def;
            return def;
        }

        private int GetInt(string key, int def)
        {
            if (_raw.TryGetValue(key, out var v) && v.ValueKind == JsonValueKind.Number)
                return v.GetInt32();
            return def;
        }

        private bool GetBool(string key, bool def)
        {
            if (_raw.TryGetValue(key, out var v))
                return v.ValueKind == JsonValueKind.True || (v.ValueKind == JsonValueKind.False ? false : def);
            return def;
        }

        private static readonly HashSet<string> _knownKeys = new(StringComparer.OrdinalIgnoreCase)
        {
            "python_bridge_url", "arbiterEnginePort", "llm_backend_url", "llm_model",
            "default_voice", "tts_enabled", "git_author_name", "git_author_email",
            "library_paths", "chat_logging",
        };

        private static bool IsKnownKey(string k) => _knownKeys.Contains(k);
    }
}
