using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace ArbiterHost.BuildInterface
{
    /// <summary>Structured result from a build / run / test command.</summary>
    public sealed record BuildResult(int ExitCode, string Stdout, string Stderr)
    {
        public bool Success => ExitCode == 0;

        /// <summary>Combined stdout + stderr for display.</summary>
        public string Output =>
            string.IsNullOrWhiteSpace(Stderr)
                ? Stdout
                : string.IsNullOrWhiteSpace(Stdout)
                    ? Stderr
                    : Stdout + "\n" + Stderr;
    }

    /// <summary>
    /// Detects the project type in a directory and runs build / run / test commands.
    /// </summary>
    public sealed class BuildManager
    {
        public enum BuildAction { Build, Run, Test }

        /// <summary>Default timeout for build / test commands (seconds).</summary>
        private const int DefaultTimeoutSeconds = 120;

        /// <summary>Default timeout for run commands (seconds).</summary>
        private const int RunTimeoutSeconds = 60;

        private readonly string _projectPath;

        public BuildManager(string projectPath)
        {
            _projectPath = projectPath;
        }

        /// <summary>
        /// Returns the default shell command for <paramref name="action"/> based on the
        /// files found in the project directory, or an empty string when the type cannot
        /// be determined.
        /// </summary>
        public string AutoDetectCommand(BuildAction action)
        {
            // .NET / C# — look for .csproj or .sln anywhere inside the project tree
            if (Directory.GetFiles(_projectPath, "*.csproj", SearchOption.AllDirectories).Length > 0
                || Directory.GetFiles(_projectPath, "*.sln", SearchOption.AllDirectories).Length > 0)
            {
                return action switch
                {
                    BuildAction.Build => "dotnet build",
                    BuildAction.Run   => "dotnet run",
                    BuildAction.Test  => "dotnet test",
                    _                 => string.Empty,
                };
            }

            // Node.js / JavaScript
            if (File.Exists(Path.Combine(_projectPath, "package.json")))
            {
                return action switch
                {
                    BuildAction.Build => "npm run build",
                    BuildAction.Run   => "npm start",
                    BuildAction.Test  => "npm test",
                    _                 => string.Empty,
                };
            }

            // Python (pyproject.toml / setup.py / requirements.txt)
            if (File.Exists(Path.Combine(_projectPath, "pyproject.toml"))
                || File.Exists(Path.Combine(_projectPath, "setup.py"))
                || File.Exists(Path.Combine(_projectPath, "requirements.txt")))
            {
                string buildCmd = File.Exists(Path.Combine(_projectPath, "requirements.txt"))
                    ? "pip install -r requirements.txt"
                    : "pip install -e .";
                return action switch
                {
                    BuildAction.Build => buildCmd,
                    BuildAction.Run   => "python main.py",
                    BuildAction.Test  => "pytest",
                    _                 => string.Empty,
                };
            }

            // Makefile
            if (File.Exists(Path.Combine(_projectPath, "Makefile")))
            {
                return action switch
                {
                    BuildAction.Build => "make",
                    BuildAction.Run   => "make run",
                    BuildAction.Test  => "make test",
                    _                 => string.Empty,
                };
            }

            return string.Empty;
        }

        /// <summary>
        /// Executes <paramref name="command"/> in the project directory and returns the result.
        /// </summary>
        public async Task<BuildResult> RunAsync(
            string command,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(command))
                return new BuildResult(-1, string.Empty, "No command specified.");

            var (shell, flag) = OperatingSystem.IsWindows()
                ? ("cmd.exe", "/C")
                : ("/bin/bash", "-c");

            var psi = new ProcessStartInfo
            {
                FileName               = shell,
                Arguments              = $"{flag} {command}",
                WorkingDirectory       = _projectPath,
                RedirectStandardOutput = true,
                RedirectStandardError  = true,
                UseShellExecute        = false,
                CreateNoWindow         = true,
            };

            var stdout = new StringBuilder();
            var stderr = new StringBuilder();

            using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
            process.OutputDataReceived += (_, args) =>
            {
                if (args.Data != null) stdout.AppendLine(args.Data);
            };
            process.ErrorDataReceived += (_, args) =>
            {
                if (args.Data != null) stderr.AppendLine(args.Data);
            };

            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();

            using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            cts.CancelAfter(TimeSpan.FromSeconds(DefaultTimeoutSeconds));

            try
            {
                await process.WaitForExitAsync(cts.Token);
            }
            catch (OperationCanceledException)
            {
                try { process.Kill(entireProcessTree: true); } catch { /* best-effort */ }
                return new BuildResult(-1, stdout.ToString(),
                    stderr + $"\n[Arbiter] Command timed out after {DefaultTimeoutSeconds}s.");
            }

            return new BuildResult(process.ExitCode, stdout.ToString(), stderr.ToString());
        }
    }
}
