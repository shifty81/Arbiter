using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace ArbiterHost.Utilities
{
    /// <summary>
    /// Applies a dark title bar (caption area) to a WPF Window on Windows 10 20H1+ and Windows 11
    /// by calling the DWM immersive dark-mode attribute via P/Invoke.
    /// </summary>
    internal static class DarkTitleBar
    {
        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

        [DllImport("dwmapi.dll", PreserveSig = true)]
        private static extern int DwmSetWindowAttribute(
            IntPtr hwnd, int dwAttribute, ref int pvAttribute, int cbAttribute);

        /// <summary>
        /// Enables the dark title bar for the given window.
        /// Call from <c>OnSourceInitialized</c> so the HWND is available.
        /// Silently ignored on OS versions that do not support the attribute.
        /// </summary>
        public static void Apply(Window window)
        {
            try
            {
                IntPtr hwnd = new WindowInteropHelper(window).EnsureHandle();
                int useDark = 1;
                DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int));
            }
            catch
            {
                // Best-effort: silently ignore on unsupported Windows versions
            }
        }
    }
}
