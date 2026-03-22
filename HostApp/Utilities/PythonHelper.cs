using System.Diagnostics;

namespace ArbiterHost.Utilities
{
    /// <summary>
    /// Locates a usable Python 3 executable on the current machine.
    /// Tries "python3", then "python", then "py" (Windows Python Launcher).
    /// </summary>
    internal static class PythonHelper
    {
        /// <summary>
        /// Returns the first Python executable that responds successfully to
        /// <c>--version</c>, or "python" as a last-resort fallback.
        /// </summary>
        public static string FindExecutable()
        {
            foreach (var candidate in new[] { "python3", "python", "py" })
            {
                try
                {
                    using var p = Process.Start(new ProcessStartInfo
                    {
                        FileName = candidate,
                        Arguments = "--version",
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        // Don't redirect streams — avoids buffer-full hangs on the version banner
                        RedirectStandardOutput = false,
                        RedirectStandardError = false,
                    });

                    if (p != null && p.WaitForExit(2000) && p.ExitCode == 0)
                        return candidate;
                }
                catch { /* candidate not found or not executable */ }
            }

            return "python"; // last-resort fallback
        }
    }
}
