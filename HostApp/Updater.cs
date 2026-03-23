using System;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;

namespace ArbiterHost
{
    /// <summary>
    /// Checks GitHub Releases for a newer version of Arbiter and exposes the
    /// result for display in any window.
    ///
    /// M8-2 — Auto-update: check GitHub releases, download and install new version.
    /// </summary>
    internal static class Updater
    {
        // ── Constants ──────────────────────────────────────────────────────────

        /// <summary>Current application version (keep in sync with roadmap + vsixmanifest).</summary>
        public const string CurrentVersion = "0.5.0";

        /// <summary>GitHub repository for release lookups.</summary>
        private const string GitHubOwner = "shifty81";
        private const string GitHubRepo  = "Arbiter";

        /// <summary>GitHub Releases API URL.</summary>
        private static readonly string _releasesUrl =
            $"https://api.github.com/repos/{GitHubOwner}/{GitHubRepo}/releases/latest";

        /// <summary>Shared HTTP client — reuse across calls.</summary>
        private static readonly HttpClient _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(10),
        };

        // ── Result type ────────────────────────────────────────────────────────

        /// <summary>Result returned by <see cref="CheckForUpdateAsync"/>.</summary>
        public sealed class UpdateInfo
        {
            /// <summary>True when a newer release is available on GitHub.</summary>
            public bool   UpdateAvailable { get; init; }
            /// <summary>Tag name of the latest release (e.g. "v0.6.0").</summary>
            public string LatestVersion   { get; init; } = CurrentVersion;
            /// <summary>Browser URL for the GitHub release page.</summary>
            public string ReleaseUrl      { get; init; } = string.Empty;
            /// <summary>Download URL for the first installer asset (.exe).</summary>
            public string DownloadUrl     { get; init; } = string.Empty;
            /// <summary>Release body (Markdown) — shown in the update dialog.</summary>
            public string ReleaseNotes    { get; init; } = string.Empty;
            /// <summary>Error description when the check failed, otherwise empty.</summary>
            public string Error           { get; init; } = string.Empty;
        }

        // ── Public API ─────────────────────────────────────────────────────────

        /// <summary>
        /// Queries the GitHub Releases API for the latest release and compares it
        /// against <see cref="CurrentVersion"/>.
        ///
        /// Returns an <see cref="UpdateInfo"/> regardless of outcome; check
        /// <see cref="UpdateInfo.Error"/> for network / parse failures.
        /// </summary>
        public static async Task<UpdateInfo> CheckForUpdateAsync()
        {
            try
            {
                // GitHub API requires a User-Agent header
                using var request = new HttpRequestMessage(HttpMethod.Get, _releasesUrl);
                request.Headers.Add("User-Agent", $"Arbiter/{CurrentVersion}");
                request.Headers.Add("Accept", "application/vnd.github+json");

                using var response = await _http.SendAsync(request).ConfigureAwait(false);
                response.EnsureSuccessStatusCode();

                var json = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;

                // Tag name is usually "v0.6.0" — strip leading 'v'
                string tagName = root.TryGetProperty("tag_name", out var tagProp)
                    ? tagProp.GetString() ?? string.Empty
                    : string.Empty;
                string latestRaw = tagName.TrimStart('v', 'V');

                string releaseUrl = root.TryGetProperty("html_url", out var urlProp)
                    ? urlProp.GetString() ?? string.Empty
                    : string.Empty;

                string releaseNotes = root.TryGetProperty("body", out var notesProp)
                    ? notesProp.GetString() ?? string.Empty
                    : string.Empty;

                // Find a .exe asset (installer)
                string downloadUrl = string.Empty;
                if (root.TryGetProperty("assets", out var assets) &&
                    assets.ValueKind == JsonValueKind.Array)
                {
                    foreach (var asset in assets.EnumerateArray())
                    {
                        string? name = asset.TryGetProperty("name", out var nProp)
                            ? nProp.GetString() : null;
                        if (name != null && name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                        {
                            downloadUrl = asset.TryGetProperty("browser_download_url", out var dlProp)
                                ? dlProp.GetString() ?? string.Empty
                                : string.Empty;
                            break;
                        }
                    }
                }

                bool newer = IsNewer(latestRaw, CurrentVersion);
                return new UpdateInfo
                {
                    UpdateAvailable = newer,
                    LatestVersion   = latestRaw,
                    ReleaseUrl      = releaseUrl,
                    DownloadUrl     = downloadUrl,
                    ReleaseNotes    = releaseNotes,
                };
            }
            catch (Exception ex)
            {
                return new UpdateInfo { Error = ex.Message };
            }
        }

        /// <summary>
        /// Returns true when <paramref name="candidate"/> is strictly newer than
        /// <paramref name="current"/> using semantic versioning (major.minor.patch).
        /// Non-conforming strings are treated as equal (no update).
        /// </summary>
        internal static bool IsNewer(string candidate, string current)
        {
            if (Version.TryParse(candidate, out var cv) &&
                Version.TryParse(current,   out var cw))
                return cv > cw;
            return false;
        }
    }
}
