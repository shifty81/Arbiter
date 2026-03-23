using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

namespace ArbiterHost.VoiceInterface
{
    public static class VoiceManager
    {
        private static string currentVoice = "British_Female";

        private static string GetVoiceManagerScriptPath()
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            return Path.GetFullPath(Path.Combine(
                baseDir, "..", "..", "..", "..", "AIEngine", "PythonBridge", "VoiceManager.py"));
        }

        public static void SetVoice(string voice)
        {
            currentVoice = voice;
        }

        public static void Speak(string text)
        {
            string scriptPath = GetVoiceManagerScriptPath();
            if (!File.Exists(scriptPath))
            {
                Console.WriteLine($"[TTS] VoiceManager.py not found at {scriptPath}");
                return;
            }

            var psi = new ProcessStartInfo
            {
                FileName = "python",
                Arguments = $"\"{scriptPath}\" \"{text.Replace("\"", "\\\"")}\" {currentVoice}",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false
            };

            try
            {
                using var process = Process.Start(psi);
                if (process == null) return;
                string stderr = process.StandardError.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0)
                    Console.WriteLine($"[TTS Error] {stderr}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[TTS Error] Failed to start voice process: {ex.Message}");
            }
        }
    }
}
