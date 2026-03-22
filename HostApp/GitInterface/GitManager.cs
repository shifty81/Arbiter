using LibGit2Sharp;
using LibGit2Sharp.Handlers;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace ArbiterHost.GitInterface
{
    public class GitManager
    {
        private Repository? repo;
        private string authorName = "ArbiterUser";
        private string authorEmail = "arbiter@local";

        public GitManager()
        {
            LoadIdentityFromSettings();
        }

        private void LoadIdentityFromSettings()
        {
            try
            {
                string settingsPath = Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory, "Config", "settings.json");
                if (!File.Exists(settingsPath)) return;
                using var doc = JsonDocument.Parse(File.ReadAllText(settingsPath));
                var root = doc.RootElement;
                if (root.TryGetProperty("git_author_name", out var nameProp))
                    authorName = nameProp.GetString() ?? authorName;
                if (root.TryGetProperty("git_author_email", out var emailProp))
                    authorEmail = emailProp.GetString() ?? authorEmail;
            }
            catch
            {
                // Use defaults if settings cannot be read
            }
        }

        public void InitRepo(string path)
        {
            if (!Repository.IsValid(path))
                repo = new Repository(Repository.Init(path));
            else
                repo = new Repository(path);
        }

        public void Commit(string message)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            Commands.Stage(repo, "*");
            var author = new Signature(authorName, authorEmail, DateTimeOffset.Now);
            repo.Commit(message, author, author);
        }

        public void CreateBranch(string branchName)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            var branch = repo.CreateBranch(branchName);
            Commands.Checkout(repo, branch);
        }

        public void CheckoutBranch(string branchName)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            Commands.Checkout(repo, branchName);
        }

        public void SetRemote(string url)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            var existing = repo.Network.Remotes["origin"];
            if (existing == null)
                repo.Network.Remotes.Add("origin", url);
            else
                repo.Network.Remotes.Update("origin", r => r.Url = url);
        }

        public void Push(string? username = null, string? password = null)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            var remote = repo.Network.Remotes["origin"]
                ?? throw new InvalidOperationException("No remote 'origin' configured. Use SetRemote first.");
            var options = new PushOptions();
            if (!string.IsNullOrEmpty(username))
            {
                string user = username;
                string pass = password ?? string.Empty;
                options.CredentialsProvider = (_, _, _) =>
                    new UsernamePasswordCredentials { Username = user, Password = pass };
            }
            repo.Network.Push(remote, repo.Head.CanonicalName, options);
        }

        public void Pull(string? username = null, string? password = null)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            var options = new PullOptions { FetchOptions = new FetchOptions() };
            if (!string.IsNullOrEmpty(username))
            {
                string user = username;
                string pass = password ?? string.Empty;
                options.FetchOptions.CredentialsProvider = (_, _, _) =>
                    new UsernamePasswordCredentials { Username = user, Password = pass };
            }
            var merger = new Signature(authorName, authorEmail, DateTimeOffset.Now);
            Commands.Pull(repo, merger, options);
        }

        private const int ShortShaLength = 7;

        public IEnumerable<(string Sha, string Message, string Author, DateTimeOffset When)> GetLog(int limit = 20)
        {
            if (repo == null) throw new InvalidOperationException("Repository not initialized.");
            return repo.Commits
                .Take(limit)
                .Select(c => (c.Sha.Substring(0, Math.Min(ShortShaLength, c.Sha.Length)), c.MessageShort.Trim(), c.Author.Name, c.Author.When));
        }
    }
}
