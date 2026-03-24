// Novaforge — GUI Theme System
// NF1-2: GUITheme, GUIThemes enum (Dark/Day/Custom), GUIThemeManager singleton
// NF1-3: Dark mode default (ChatGPT palette)
// NF1-4: Day mode (soft palette)
// NF1-5: Custom theme — user-defined RGB values persisted in settings; import/export

using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;

namespace Novaforge.ToolingLayer
{
    // ── Theme enum ────────────────────────────────────────────────────────────

    public enum GUIThemes { Dark, Day, Custom }

    // ── Theme data class ──────────────────────────────────────────────────────

    /// <summary>
    /// Holds the complete colour palette for one UI theme.
    /// All colours are expressed as HTML hex strings (#RRGGBB).
    /// </summary>
    public class GUITheme
    {
        public GUIThemes Name          { get; init; }
        public string    Background    { get; set; } = "#202123";
        public string    Panel         { get; set; } = "#2A2B2F";
        public string    AiText        { get; set; } = "#00FFAB";
        public string    Foreground    { get; set; } = "#ECECEC";
        public string    Border        { get; set; } = "#3A3B40";
        public string    Accent        { get; set; } = "#007ACC";
        public string    Selection     { get; set; } = "#264F78";
        public string    InputBg       { get; set; } = "#3C3C3C";
        public string    ButtonBg      { get; set; } = "#3C3C3C";
        public string    ButtonHover   { get; set; } = "#505050";
        public string    UserText      { get; set; } = "#ECECEC";

        // ── Built-in palettes ─────────────────────────────────────────────────

        /// <summary>ChatGPT-inspired dark palette (NF1-3).</summary>
        public static GUITheme Dark => new()
        {
            Name       = GUIThemes.Dark,
            Background = "#202123",
            Panel      = "#2A2B2F",
            AiText     = "#00FFAB",
            Foreground = "#ECECEC",
            Border     = "#3A3B40",
            Accent     = "#007ACC",
            Selection  = "#264F78",
            InputBg    = "#40414F",
            ButtonBg   = "#3C3C3C",
            ButtonHover= "#505050",
            UserText   = "#ECECEC",
        };

        /// <summary>Soft day-mode palette (NF1-4).</summary>
        public static GUITheme Day => new()
        {
            Name       = GUIThemes.Day,
            Background = "#F5F5F5",
            Panel      = "#E6E6E6",
            AiText     = "#007864",
            Foreground = "#1A1A1A",
            Border     = "#C8C8C8",
            Accent     = "#0078D4",
            Selection  = "#B8D4F0",
            InputBg    = "#FFFFFF",
            ButtonBg   = "#DCDCDC",
            ButtonHover= "#C0C0C0",
            UserText   = "#1A1A1A",
        };

        // ── Resource dictionary builder ───────────────────────────────────────

        /// <summary>
        /// Convert this theme into a WPF ResourceDictionary so it can be
        /// merged into Application.Current.Resources at runtime.
        /// </summary>
        public ResourceDictionary ToResourceDictionary()
        {
            var dict = new ResourceDictionary();
            dict["Theme.Background"]  = BrushFrom(Background);
            dict["Theme.Panel"]       = BrushFrom(Panel);
            dict["Theme.AiText"]      = BrushFrom(AiText);
            dict["Theme.Foreground"]  = BrushFrom(Foreground);
            dict["Theme.Border"]      = BrushFrom(Border);
            dict["Theme.Accent"]      = BrushFrom(Accent);
            dict["Theme.Selection"]   = BrushFrom(Selection);
            dict["Theme.InputBg"]     = BrushFrom(InputBg);
            dict["Theme.ButtonBg"]    = BrushFrom(ButtonBg);
            dict["Theme.ButtonHover"] = BrushFrom(ButtonHover);
            dict["Theme.UserText"]    = BrushFrom(UserText);
            return dict;
        }

        private static SolidColorBrush BrushFrom(string hex)
        {
            try
            {
                var colour = (Color)ColorConverter.ConvertFromString(hex);
                var brush  = new SolidColorBrush(colour);
                brush.Freeze();
                return brush;
            }
            catch
            {
                return Brushes.Transparent;
            }
        }

        // ── Serialisation (NF1-5) ─────────────────────────────────────────────

        public string ToJson() => JsonSerializer.Serialize(this, _jsonOpts);

        public static GUITheme? FromJson(string json)
        {
            try   { return JsonSerializer.Deserialize<GUITheme>(json, _jsonOpts); }
            catch { return null; }
        }

        private static readonly JsonSerializerOptions _jsonOpts = new() { WriteIndented = true };
    }

    // ── GUIThemeManager singleton (NF1-2) ─────────────────────────────────────

    /// <summary>
    /// Singleton that owns the active theme and notifies subscribers when it
    /// changes.  Persists the custom theme and last-used theme name to
    /// <c>settings.json</c>.
    /// </summary>
    public sealed class GUIThemeManager
    {
        // ── Singleton ─────────────────────────────────────────────────────────
        private static GUIThemeManager? _instance;
        public static GUIThemeManager Instance => _instance ??= new GUIThemeManager();

        // ── State ─────────────────────────────────────────────────────────────
        private GUITheme _active;
        public GUITheme  Active => _active;

        /// <summary>Fires whenever the theme changes. Arg = the new theme.</summary>
        public event EventHandler<GUITheme>? OnThemeChanged;

        private string _settingsPath = "settings/novaforge_theme.json";
        private GUITheme _custom = GUITheme.Dark;   // user-defined custom palette

        private GUIThemeManager()
        {
            _active = GUITheme.Dark;
            LoadFromDisk();
        }

        // ── Apply ─────────────────────────────────────────────────────────────

        /// <summary>Switch to a built-in theme (Dark / Day).</summary>
        public void Apply(GUIThemes theme)
        {
            _active = theme switch
            {
                GUIThemes.Day    => GUITheme.Day,
                GUIThemes.Custom => _custom,
                _                => GUITheme.Dark,
            };
            PushToApplication();
            OnThemeChanged?.Invoke(this, _active);
            SaveToDisk();
        }

        /// <summary>Apply a fully custom theme (NF1-5).</summary>
        public void ApplyCustom(GUITheme customTheme)
        {
            _custom = customTheme;
            _active = customTheme;
            PushToApplication();
            OnThemeChanged?.Invoke(this, _active);
            SaveToDisk();
        }

        private void PushToApplication()
        {
            if (Application.Current == null) return;
            var dict = _active.ToResourceDictionary();
            // Replace or add our theme entry in the app merged dictionaries
            var merged = Application.Current.Resources.MergedDictionaries;
            for (int i = merged.Count - 1; i >= 0; i--)
                if (merged[i].Contains("Theme.Background"))
                {
                    merged.RemoveAt(i);
                }
            merged.Add(dict);
        }

        // ── Export / Import (NF1-5) ───────────────────────────────────────────

        public string ExportCustom() => _custom.ToJson();

        public bool ImportCustom(string json)
        {
            var theme = GUITheme.FromJson(json);
            if (theme == null) return false;
            ApplyCustom(theme);
            return true;
        }

        // ── Persistence ───────────────────────────────────────────────────────

        private void SaveToDisk()
        {
            try
            {
                var dir = Path.GetDirectoryName(_settingsPath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                var payload = new
                {
                    active_theme  = _active.Name.ToString(),
                    custom_palette = _custom,
                };
                File.WriteAllText(_settingsPath,
                    JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
            }
            catch { /* non-fatal */ }
        }

        private void LoadFromDisk()
        {
            try
            {
                if (!File.Exists(_settingsPath)) return;
                using var doc = JsonDocument.Parse(File.ReadAllText(_settingsPath));
                var root = doc.RootElement;
                if (root.TryGetProperty("custom_palette", out var cp))
                {
                    var t = JsonSerializer.Deserialize<GUITheme>(cp.GetRawText());
                    if (t != null) _custom = t;
                }
                if (root.TryGetProperty("active_theme", out var at))
                {
                    if (Enum.TryParse<GUIThemes>(at.GetString(), out var name))
                        Apply(name);
                }
            }
            catch { /* non-fatal */ }
        }
    }
}
