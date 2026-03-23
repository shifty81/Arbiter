using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ArbiterVSIX
{
    /// <summary>
    /// Lightweight HTTP client for communicating with the Arbiter backend
    /// (either the FastAPI bridge on port 8000 or the ArbiterEngine on port 8001).
    /// </summary>
    internal sealed class ArbiterApiClient : IDisposable
    {
        private readonly HttpClient _http;
        private string _baseUrl;

        // Default probe order: try ArbiterEngine first, then PythonBridge.
        private static readonly string[] _candidateUrls =
        {
            "http://127.0.0.1:8001",
            "http://127.0.0.1:8000",
        };

        public string BaseUrl => _baseUrl;

        public ArbiterApiClient()
        {
            _http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
            _baseUrl = _candidateUrls[0];
        }

        /// <summary>
        /// Probe candidate backend URLs and store the first reachable one.
        /// Returns <c>true</c> if a live backend was found.
        /// </summary>
        public async Task<bool> AutoDetectBackendAsync(CancellationToken ct = default)
        {
            foreach (var url in _candidateUrls)
            {
                try
                {
                    var resp = await _http.GetAsync(url + "/health", ct).ConfigureAwait(false);
                    if (resp.IsSuccessStatusCode)
                    {
                        _baseUrl = url;
                        return true;
                    }
                }
                catch
                {
                    // Try next candidate
                }
            }
            return false;
        }

        /// <summary>
        /// Override the backend URL (e.g. from the settings page).
        /// </summary>
        public void SetBaseUrl(string url) => _baseUrl = url.TrimEnd('/');

        // ── Convenience wrappers ──────────────────────────────────────────────

        /// <summary>POST /ai/action — execute a named AI command on selected text.</summary>
        public async Task<string> AiActionAsync(
            string action,
            string code,
            string filePath = "",
            string project = "default",
            CancellationToken ct = default)
        {
            var payload = new
            {
                action,
                code,
                file_path = filePath,
                project,
            };
            return await PostJsonAsync("/ai/action", payload, ct).ConfigureAwait(false);
        }

        /// <summary>POST /assistant/chat — conversational AI request.</summary>
        public async Task<string> ChatAsync(
            string message,
            string project = "default",
            CancellationToken ct = default)
        {
            var payload = new { message, project };
            return await PostJsonAsync("/assistant/chat", payload, ct).ConfigureAwait(false);
        }

        /// <summary>GET /health — check backend liveness.</summary>
        public async Task<bool> IsAliveAsync(CancellationToken ct = default)
        {
            try
            {
                var resp = await _http.GetAsync(_baseUrl + "/health", ct).ConfigureAwait(false);
                return resp.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        // ── Internal helpers ─────────────────────────────────────────────────

        private async Task<string> PostJsonAsync(
            string path,
            object payload,
            CancellationToken ct)
        {
            var body = JsonSerializer.Serialize(payload);
            using var content = new StringContent(body, Encoding.UTF8, "application/json");
            var resp = await _http.PostAsync(_baseUrl + path, content, ct).ConfigureAwait(false);
            var raw = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            // Try to extract the "reply" or "response" field from JSON; fall back to raw text.
            try
            {
                using var doc = JsonDocument.Parse(raw);
                if (doc.RootElement.TryGetProperty("reply", out var r)) return r.GetString() ?? raw;
                if (doc.RootElement.TryGetProperty("response", out var r2)) return r2.GetString() ?? raw;
                if (doc.RootElement.TryGetProperty("result", out var r3)) return r3.GetString() ?? raw;
            }
            catch { /* fall through */ }
            return raw;
        }

        public void Dispose() => _http.Dispose();
    }
}
