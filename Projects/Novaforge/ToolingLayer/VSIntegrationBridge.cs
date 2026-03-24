// Novaforge — Visual Studio Integration bridge
// NF1-12: Connect Tooling Layer to Arbiter VSIX for code generation and
//         inline AI suggestions.
//
// The Tooling Layer acts as the LOCAL HTTP server.  The Arbiter VSIX
// (running inside Visual Studio) calls into these endpoints to:
//   • POST /nf/vs/chat          — send a chat message from VS, receive a reply
//   • POST /nf/vs/complete      — inline completion at cursor
//   • POST /nf/vs/action        — execute an AIAction triggered from VS
//   • GET  /nf/vs/capabilities  — advertise what VS features are available
//
// In the other direction the Tooling Layer can push code-generation events
// to VS via the shared ArbiterEngine /vs/* endpoints.

using System;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Novaforge.ToolingLayer
{
    /// <summary>
    /// Lightweight embedded HTTP listener that exposes the Tooling Layer
    /// as a local REST server for the Arbiter VSIX to call into.
    ///
    /// Start with: <c>VSIntegrationBridge.Instance.StartAsync()</c>
    /// </summary>
    public sealed class VSIntegrationBridge : IDisposable
    {
        // ── Singleton ─────────────────────────────────────────────────────────
        private static VSIntegrationBridge? _instance;
        public static VSIntegrationBridge Instance =>
            _instance ??= new VSIntegrationBridge();

        // ── Config ────────────────────────────────────────────────────────────
        public int    Port    { get; set; } = 8005;
        public string Prefix  => $"http://127.0.0.1:{Port}/nf/vs/";

        // ── State ─────────────────────────────────────────────────────────────
        private HttpListener?        _listener;
        private CancellationTokenSource? _cts;
        private Task?                _serverTask;

        private VSIntegrationBridge() { }

        // ── Lifecycle ─────────────────────────────────────────────────────────

        public async Task StartAsync(CancellationToken ct = default)
        {
            _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            _listener = new HttpListener();
            _listener.Prefixes.Add(Prefix);
            try
            {
                _listener.Start();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[VSIntegrationBridge] Could not start listener: {ex.Message}");
                return;
            }
            _serverTask = _RunAsync(_cts.Token);
            await Task.CompletedTask;
        }

        public void Stop()
        {
            _cts?.Cancel();
            _listener?.Stop();
        }

        private async Task _RunAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                HttpListenerContext? ctx = null;
                try
                {
                    ctx = await _listener!.GetContextAsync().WaitAsync(ct);
                }
                catch (OperationCanceledException) { break; }
                catch { continue; }

                _ = Task.Run(() => _HandleAsync(ctx), ct);
            }
        }

        // ── Request dispatch ──────────────────────────────────────────────────

        private async Task _HandleAsync(HttpListenerContext ctx)
        {
            var req  = ctx.Request;
            var resp = ctx.Response;
            resp.ContentType = "application/json; charset=utf-8";

            try
            {
                var path = req.Url?.AbsolutePath ?? "";

                if (path.EndsWith("/capabilities") && req.HttpMethod == "GET")
                {
                    await _WriteJson(resp, _Capabilities());
                }
                else if (path.EndsWith("/chat") && req.HttpMethod == "POST")
                {
                    await _HandleChat(req, resp);
                }
                else if (path.EndsWith("/complete") && req.HttpMethod == "POST")
                {
                    await _HandleComplete(req, resp);
                }
                else if (path.EndsWith("/action") && req.HttpMethod == "POST")
                {
                    await _HandleAction(req, resp);
                }
                else
                {
                    resp.StatusCode = 404;
                    await _WriteJson(resp, new { error = "not found" });
                }
            }
            catch (Exception ex)
            {
                resp.StatusCode = 500;
                await _WriteJson(resp, new { error = ex.Message });
            }
        }

        private static object _Capabilities() => new
        {
            inline_completion = true,
            chat              = true,
            action_execution  = true,
            streaming         = true,
            version           = "1.0.0",
        };

        private async Task _HandleChat(HttpListenerRequest req, HttpListenerResponse resp)
        {
            var body   = await new System.IO.StreamReader(req.InputStream).ReadToEndAsync();
            using var doc   = JsonDocument.Parse(body);
            var prompt = doc.RootElement.GetProperty("message").GetString() ?? "";
            var reply  = await ArbiterAIManager.Instance.QueryAsync(prompt);
            await _WriteJson(resp, new { reply });
        }

        private async Task _HandleComplete(HttpListenerRequest req, HttpListenerResponse resp)
        {
            var body = await new System.IO.StreamReader(req.InputStream).ReadToEndAsync();
            using var doc  = JsonDocument.Parse(body);
            var prefix     = doc.RootElement.TryGetProperty("prefix", out var p) ? p.GetString() ?? "" : "";
            var lang       = doc.RootElement.TryGetProperty("language", out var l) ? l.GetString() ?? "" : "";

            var prompt     = $"Complete the following {lang} code at <CURSOR>:\n{prefix}<CURSOR>";
            var completion = await ArbiterAIManager.Instance.QueryAsync(prompt);
            await _WriteJson(resp, new { completion });
        }

        private async Task _HandleAction(HttpListenerRequest req, HttpListenerResponse resp)
        {
            var body = await new System.IO.StreamReader(req.InputStream).ReadToEndAsync();
            using var doc  = JsonDocument.Parse(body);
            var type       = doc.RootElement.TryGetProperty("type", out var t) ? t.GetString() : "write_file";
            var title      = doc.RootElement.TryGetProperty("title", out var ti) ? ti.GetString() ?? "" : "";
            var desc       = doc.RootElement.TryGetProperty("description", out var d) ? d.GetString() ?? "" : "";

            var payload = new System.Collections.Generic.Dictionary<string, string>();
            if (doc.RootElement.TryGetProperty("payload", out var pl))
                foreach (var kv in pl.EnumerateObject())
                    payload[kv.Name] = kv.Value.GetString() ?? "";

            var action = new AIAction(
                Type:        type == "write_file" ? AIActionType.WriteFile : AIActionType.RunAnalysis,
                Title:       title,
                Description: desc,
                Payload:     payload
            );
            var (success, message) = await ArbiterAIManager.Instance.ExecuteActionAsync(action);
            await _WriteJson(resp, new { success, message });
        }

        private static async Task _WriteJson(HttpListenerResponse resp, object data)
        {
            var json  = JsonSerializer.Serialize(data);
            var bytes = Encoding.UTF8.GetBytes(json);
            resp.ContentLength64 = bytes.Length;
            await resp.OutputStream.WriteAsync(bytes);
            resp.OutputStream.Close();
        }

        public void Dispose()
        {
            Stop();
            _listener?.Close();
        }
    }
}
