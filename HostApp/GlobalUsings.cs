// Disambiguate names that exist in both System.Windows.Forms (pulled in by
// UseWindowsForms=true for the NotifyIcon tray icon) and the WPF namespaces.
// Every file in this project that writes the short name resolves to the WPF
// type.  Only the five types reported as CS0104 and three more that would
// also collide are listed here; all others keep their default WPF resolution.
global using Application   = System.Windows.Application;
global using Button        = System.Windows.Controls.Button;
global using Clipboard     = System.Windows.Clipboard;
global using DataFormats   = System.Windows.DataFormats;
global using DragEventArgs = System.Windows.DragEventArgs;
global using KeyEventArgs  = System.Windows.Input.KeyEventArgs;
global using MessageBox    = System.Windows.MessageBox;
global using TextBox       = System.Windows.Controls.TextBox;
