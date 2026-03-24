// Novaforge — ArbiterAI Manager
// NF1-6:  ArbiterAIManager singleton: workspace-aware, 40-prompt live memory, SQLite archive
// NF1-7:  WorkspaceContextManager: tracks files, tooling state, server state
// NF1-8:  Streaming AI responses via IAsyncEnumerable token stream
// NF1-9:  GenerateActionsAsync() → clickable AIAction list
// NF1-10: ExecuteActionAsync() → safe action application
// NF1-11: Prompt archive: tag-based SQLite; RetrieveRelevantArchives() feeds context back

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Novaforge.ToolingLayer
{
    // ── AIAction model (NF1-9) ────────────────────────────────────────────────

    public enum AIActionType
    {
        InsertPrefab,
        AddScript,
        ToolingUpdate,
        ServerCommand,
        WriteFile,
        RunAnalysis,
    }

    public record AIAction(
        AIActionType Type,
        string Title,
        string Description,
        Dictionary<string, string> Payload
    );

    // ── WorkspaceContextManager (NF1-7) ──────────────────────────────────────

    /// <summary>
    /// Tracks all project files, tooling state, and server state so they can
    /// be injected into every AI prompt as context.
    /// </summary>
    public class WorkspaceContextManager
    {
        private readonly Dictionary<string, object> _state = new();

        public string ProjectRoot { get; }

        public WorkspaceContextManager(string projectRoot)
        {
            ProjectRoot = projectRoot;
        }

        public void Set(string key, object value) => _state[key] = value;

        public object? Get(string key) => _state.GetValueOrDefault(key);

        /// <summary>
        /// Build a compact context string injected at the front of every prompt.
        /// Lists key state entries and the first 30 files in the project tree.
        /// </summary>
        public string BuildContextString(int maxFiles = 30)
        {
            var sb = new StringBuilder();
            sb.AppendLine("=== Workspace Context ===");
            foreach (var kv in _state)
                sb.AppendLine($"{kv.Key}: {kv.Value}");

            if (Directory.Exists(ProjectRoot))
            {
                sb.AppendLine("\nProject files (excerpt):");
                var files = Directory.GetFiles(ProjectRoot, "*", SearchOption.AllDirectories)
                    .Where(f => !f.Contains(".git") && !f.Contains("__pycache__"))
                    .Take(maxFiles)
                    .Select(f => Path.GetRelativePath(ProjectRoot, f));
                foreach (var f in files)
                    sb.AppendLine($"  {f}");
            }
            sb.AppendLine("=== End Context ===");
            return sb.ToString();
        }
    }

    // ── Prompt archive (NF1-11) ───────────────────────────────────────────────

    /// <summary>
    /// Tag-based SQLite prompt archive.  Older turns (beyond the 40-turn live
    /// window) are written here and retrieved by relevance via a simple
    /// keyword-overlap heuristic.
    /// </summary>
    public class PromptArchive : IDisposable
    {
        private readonly string _dbPath;
        private Microsoft.Data.Sqlite.SqliteConnection? _conn;

        public PromptArchive(string dbPath = "settings/novaforge_archive.db")
        {
            _dbPath = dbPath;
            _EnsureSchema();
        }

        private void _EnsureSchema()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_dbPath) ?? ".");
                _conn = new Microsoft.Data.Sqlite.SqliteConnection($"Data Source={_dbPath}");
                _conn.Open();
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = @"
                    CREATE TABLE IF NOT EXISTS prompts (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        role      TEXT NOT NULL,
                        content   TEXT NOT NULL,
                        tags      TEXT DEFAULT '',
                        ts        TEXT NOT NULL
                    );";
                cmd.ExecuteNonQuery();
            }
            catch { _conn = null; }
        }

        public void Archive(string role, string content, IEnumerable<string>? tags = null)
        {
            if (_conn == null) return;
            try
            {
                using var cmd = _conn.CreateCommand();
                cmd.CommandText = "INSERT INTO prompts (role, content, tags, ts) VALUES ($r,$c,$t,$ts)";
                cmd.Parameters.AddWithValue("$r",  role);
                cmd.Parameters.AddWithValue("$c",  content);
                cmd.Parameters.AddWithValue("$t",  string.Join(",", tags ?? []));
                cmd.Parameters.AddWithValue("$ts", DateTime.UtcNow.ToString("o"));
                cmd.ExecuteNonQuery();
            }
            catch { /* non-fatal */ }
        }

        /// <summary>
        /// Retrieve up to <paramref name="limit"/> archived turns whose content
        /// shares at least one word with <paramref name="query"/>.
        /// </summary>
        public List<(string role, string content)> RetrieveRelevantArchives(
            string query, int limit = 5)
        {
            var result = new List<(string, string)>();
            if (_conn == null) return result;
            var keywords = query.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                                .Select(w => w.ToLowerInvariant())
                                .Distinct()
                                .Take(10)
                                .ToList();
            if (keywords.Count == 0) return result;

            try
            {
                using var cmd = _conn.CreateCommand();
                // SQLite LIKE-based keyword search
                var conditions = string.Join(" OR ",
                    keywords.Select((_, i) => $"LOWER(content) LIKE $k{i}"));
                cmd.CommandText = $@"
                    SELECT role, content FROM prompts
                    WHERE {conditions}
                    ORDER BY id DESC LIMIT $lim";
                for (int i = 0; i < keywords.Count; i++)
                    cmd.Parameters.AddWithValue($"$k{i}", $"%{keywords[i]}%");
                cmd.Parameters.AddWithValue("$lim", limit);

                using var reader = cmd.ExecuteReader();
                while (reader.Read())
                    result.Add((reader.GetString(0), reader.GetString(1)));
            }
            catch { /* non-fatal */ }
            return result;
        }

        public void Dispose() => _conn?.Dispose();
    }

    // ── ArbiterAIManager singleton (NF1-6) ───────────────────────────────────

    /// <summary>
    /// Singleton AI manager connecting Novaforge Tooling Layer to ArbiterEngine.
    ///
    /// Features:
    ///   • 40-prompt live memory window in RAM
    ///   • Older turns archived to SQLite via PromptArchive
    ///   • Workspace context injected into every prompt
    ///   • Streaming token responses (NF1-8)
    ///   • Action generation + execution (NF1-9, NF1-10)
    /// </summary>
    public sealed class ArbiterAIManager : IDisposable
    {
        // ── Singleton ─────────────────────────────────────────────────────────
        private static ArbiterAIManager? _instance;
        public static ArbiterAIManager Instance =>
            _instance ??= new ArbiterAIManager();

        // ── Config ────────────────────────────────────────────────────────────
        public string  EngineUrl  { get; set; } = "http://127.0.0.1:8001";
        public string  Project    { get; set; } = "Novaforge";
        public int     MaxHistory { get; } = 40;

        // ── State ─────────────────────────────────────────────────────────────
        private readonly List<ChatMessage>    _memory   = new();
        private readonly PromptArchive        _archive  = new();
        private readonly HttpClient           _http     = new() { Timeout = TimeSpan.FromSeconds(120) };
        public  readonly WorkspaceContextManager Context;

        private ArbiterAIManager()
        {
            Context = new WorkspaceContextManager(".");
        }

        // ── Memory helpers ────────────────────────────────────────────────────

        private void _PushMemory(string role, string content)
        {
            _memory.Add(new ChatMessage(role, content));
            if (_memory.Count > MaxHistory)
            {
                var evicted = _memory[0];
                _archive.Archive(evicted.Role, evicted.Content);
                _memory.RemoveAt(0);
            }
        }

        private List<object> _BuildHistory(string? contextOverride = null)
        {
            var history = new List<object>();

            // Inject workspace context as a system message
            var ctx = contextOverride ?? Context.BuildContextString();
            history.Add(new { role = "system", content = ctx });

            // Inject relevant archive entries
            var archived = _archive.RetrieveRelevantArchives(
                _memory.LastOrDefault()?.Content ?? "", limit: 3);
            foreach (var (r, c) in archived)
                history.Add(new { role = r, content = $"[archived] {c}" });

            // Live window
            foreach (var m in _memory)
                history.Add(new { role = m.Role, content = m.Content });

            return history;
        }

        // ── NF1-8: Single-turn query ──────────────────────────────────────────

        /// <summary>Send a single prompt and return the full response string.</summary>
        public async Task<string> QueryAsync(string prompt, CancellationToken ct = default)
        {
            _PushMemory("user", prompt);
            var payload = new
            {
                project = Project,
                message = prompt,
                history = _BuildHistory(),
            };
            var json    = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var resp    = await _http.PostAsync($"{EngineUrl}/chat", content, ct);
            resp.EnsureSuccessStatusCode();
            var body    = await resp.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(body);
            var reply = doc.RootElement.GetProperty("reply").GetString() ?? "";
            _PushMemory("assistant", reply);
            return reply;
        }

        // ── NF1-8: Streaming token response ──────────────────────────────────

        /// <summary>
        /// Stream AI response tokens as an <see cref="IAsyncEnumerable{T}"/>.
        /// The ChatPanel subscribes to this and appends tokens in real time.
        /// </summary>
        public async IAsyncEnumerable<string> StreamAsync(
            string prompt,
            [EnumeratorCancellation] CancellationToken ct = default)
        {
            _PushMemory("user", prompt);
            var payload = new
            {
                project = Project,
                message = prompt,
                history = _BuildHistory(),
            };
            var json    = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var req = new HttpRequestMessage(HttpMethod.Post, $"{EngineUrl}/chat/stream")
            {
                Content = content,
            };
            var resp = await _http.SendAsync(req,
                HttpCompletionOption.ResponseHeadersRead, ct);
            resp.EnsureSuccessStatusCode();

            using var stream = await resp.Content.ReadAsStreamAsync(ct);
            using var reader = new StreamReader(stream);

            var fullReply = new StringBuilder();
            while (!reader.EndOfStream && !ct.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(ct);
                if (line == null) break;
                if (line.StartsWith("data: "))
                {
                    var data = line[6..];
                    if (data == "[DONE]") break;
                    try
                    {
                        using var doc = JsonDocument.Parse(data);
                        var token = doc.RootElement.TryGetProperty("token", out var t)
                            ? t.GetString() ?? ""
                            : doc.RootElement.TryGetProperty("delta", out var d)
                                ? d.GetString() ?? ""
                                : "";
                        if (!string.IsNullOrEmpty(token))
                        {
                            fullReply.Append(token);
                            yield return token;
                        }
                    }
                    catch { /* malformed chunk — skip */ }
                }
            }
            _PushMemory("assistant", fullReply.ToString());
        }

        // ── NF1-9: Generate AI actions ────────────────────────────────────────

        /// <summary>
        /// Ask ArbiterEngine to generate a list of executable AIActions for the
        /// current project goal.
        /// </summary>
        public async Task<List<AIAction>> GenerateActionsAsync(
            string prompt, CancellationToken ct = default)
        {
            var systemPrompt =
                "You are an action planner. Given a development goal, return a JSON array of actions.\n"
                + "Each action: {\"type\": \"insert_prefab|add_script|tooling_update|server_command|write_file\", "
                + "\"title\": \"...\", \"description\": \"...\", \"payload\": {\"key\": \"value\"}}\n"
                + "Output ONLY the JSON array.";

            var payload = new
            {
                project = Project,
                message = prompt,
                history = new[]
                {
                    new { role = "system", content = systemPrompt },
                    new { role = "user",   content = prompt },
                },
            };
            var json    = JsonSerializer.Serialize(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");
            var resp    = await _http.PostAsync($"{EngineUrl}/chat", content, ct);
            if (!resp.IsSuccessStatusCode) return [];

            var body = await resp.Content.ReadAsStringAsync(ct);
            using var doc = JsonDocument.Parse(body);
            var raw = doc.RootElement.GetProperty("reply").GetString() ?? "[]";

            // Extract JSON array from response
            var start = raw.IndexOf('[');
            var end   = raw.LastIndexOf(']');
            if (start < 0 || end < start) return [];

            try
            {
                var actions = JsonSerializer.Deserialize<List<RawAction>>(raw[start..(end + 1)]);
                return (actions ?? []).Select(a => new AIAction(
                    Type:        ParseActionType(a.type),
                    Title:       a.title ?? "",
                    Description: a.description ?? "",
                    Payload:     a.payload ?? new()
                )).ToList();
            }
            catch { return []; }
        }

        private static AIActionType ParseActionType(string? s) => s?.ToLowerInvariant() switch
        {
            "insert_prefab"  => AIActionType.InsertPrefab,
            "add_script"     => AIActionType.AddScript,
            "tooling_update" => AIActionType.ToolingUpdate,
            "server_command" => AIActionType.ServerCommand,
            "write_file"     => AIActionType.WriteFile,
            "run_analysis"   => AIActionType.RunAnalysis,
            _                => AIActionType.ToolingUpdate,
        };

        // ── NF1-10: Execute AI action ─────────────────────────────────────────

        /// <summary>
        /// Safely apply an AIAction.  File writes stay within the project root.
        /// Server commands are relayed via the SSA client stub.
        /// </summary>
        public async Task<(bool success, string message)> ExecuteActionAsync(
            AIAction action, CancellationToken ct = default)
        {
            try
            {
                switch (action.Type)
                {
                    case AIActionType.WriteFile:
                    {
                        var relPath = action.Payload.GetValueOrDefault("path", "");
                        var content = action.Payload.GetValueOrDefault("content", "");
                        if (string.IsNullOrEmpty(relPath))
                            return (false, "write_file: missing 'path' in payload");

                        var target = Path.GetFullPath(
                            Path.Combine(Context.ProjectRoot, relPath));
                        // Guard: stay inside project root (case-insensitive on Windows)
                        var rootNorm = Path.GetFullPath(Context.ProjectRoot);
                        var rootPrefix = rootNorm.TrimEnd(Path.DirectorySeparatorChar)
                                                 + Path.DirectorySeparatorChar;
                        if (!target.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase)
                            && !string.Equals(target, rootNorm, StringComparison.OrdinalIgnoreCase))
                            return (false, "write_file: path escapes project root");

                        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                        await File.WriteAllTextAsync(target, content, ct);
                        return (true, $"Written {content.Length} chars to {relPath}");
                    }
                    case AIActionType.RunAnalysis:
                    {
                        var filePath = action.Payload.GetValueOrDefault("path", "");
                        // Delegate to ArbiterEngine lint endpoint
                        var resp = await _http.GetAsync(
                            $"{EngineUrl}/analysis/lint?project={Uri.EscapeDataString(Project)}&file_path={Uri.EscapeDataString(filePath)}", ct);
                        return (resp.IsSuccessStatusCode, $"Analysis request status: {resp.StatusCode}");
                    }
                    case AIActionType.ServerCommand:
                    {
                        // Relay via SSA client — stub for NF3-2
                        var cmd = action.Payload.GetValueOrDefault("command", "");
                        return (false, $"Server command '{cmd}' — SSA integration pending (NF3)");
                    }
                    default:
                        return (false, $"Action type '{action.Type}' — pending full implementation");
                }
            }
            catch (Exception ex)
            {
                return (false, $"ExecuteActionAsync error: {ex.Message}");
            }
        }

        public void Dispose()
        {
            _archive.Dispose();
            _http.Dispose();
        }

        // ── Private helpers ───────────────────────────────────────────────────

        private record ChatMessage(string Role, string Content);

        private record RawAction(
            string? type,
            string? title,
            string? description,
            Dictionary<string, string>? payload
        );
    }
}
