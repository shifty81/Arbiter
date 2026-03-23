using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using ArbiterHost.Utilities;

namespace ArbiterHost
{
    public partial class WorkspaceWindow : Window
    {
        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            DarkTitleBar.Apply(this);
        }

        private readonly string projectsRoot = Path.Combine(
            Directory.GetCurrentDirectory(), "Projects");

        public WorkspaceWindow()
        {
            InitializeComponent();
            LoadProjects();
        }

        private void LoadProjects()
        {
            ProjectListBox.Items.Clear();
            if (Directory.Exists(projectsRoot))
            {
                foreach (var dir in Directory.GetDirectories(projectsRoot))
                    ProjectListBox.Items.Add(Path.GetFileName(dir));
            }
        }

        private void CreateProject_Click(object sender, RoutedEventArgs e)
        {
            string? name = InputDialog.Show("Enter project name:", "Create Project", "NewProject");
            if (string.IsNullOrWhiteSpace(name)) return;

            // Sanitize: allow only alphanumeric, dash, underscore, and space
            name = Regex.Replace(name.Trim(), @"[^\w\s\-]", "");
            name = name.Replace(' ', '_');
            if (string.IsNullOrWhiteSpace(name)) return;

            string newProjectPath = Path.Combine(projectsRoot, name);
            Directory.CreateDirectory(newProjectPath);
            File.WriteAllText(Path.Combine(newProjectPath, "roadmap.json"),
                "{ \"phases\": [], \"tasks\": [] }");
            ProjectListBox.Items.Add(name);
            ProjectListBox.SelectedItem = name;
        }

        private void OpenProject_Click(object sender, RoutedEventArgs e)
        {
            if (ProjectListBox.SelectedItem == null) return;
            string projectName = ProjectListBox.SelectedItem.ToString() ?? string.Empty;
            var projectWindow = new ProjectWindow(projectName, projectsRoot);
            projectWindow.Show();
        }

        private void ProjectListBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
        {
            if (ProjectListBox.SelectedItem == null)
            {
                ProjectSummaryBox.Text = string.Empty;
                return;
            }
            string projectName = ProjectListBox.SelectedItem.ToString() ?? string.Empty;
            ProjectSummaryBox.Text = BuildProjectSummary(projectName);
        }

        private string BuildProjectSummary(string projectName)
        {
            string projectPath = Path.Combine(projectsRoot, projectName);
            var sb = new StringBuilder();

            sb.AppendLine($"Project : {projectName}");
            sb.AppendLine($"Path    : {projectPath}");
            sb.AppendLine();

            // File stats
            try
            {
                var allFiles = Directory.GetFiles(projectPath, "*", SearchOption.AllDirectories);
                DateTime? lastModified = allFiles.Length > 0
                    ? allFiles.Select(f => File.GetLastWriteTime(f)).Max()
                    : (DateTime?)null;

                sb.AppendLine($"Files   : {allFiles.Length}");
                if (lastModified.HasValue)
                    sb.AppendLine($"Modified: {lastModified.Value:yyyy-MM-dd HH:mm}");
            }
            catch
            {
                sb.AppendLine("Files   : (unavailable)");
            }

            // Roadmap
            string roadmapPath = Path.Combine(projectPath, "roadmap.json");
            if (File.Exists(roadmapPath))
            {
                try
                {
                    sb.AppendLine();
                    sb.AppendLine("=== Roadmap ===");
                    using var doc = JsonDocument.Parse(File.ReadAllText(roadmapPath));
                    var root = doc.RootElement;

                    if (root.TryGetProperty("phases", out var phases))
                    {
                        foreach (var phase in phases.EnumerateArray())
                        {
                            string phaseName = phase.TryGetProperty("name", out var n)
                                ? n.GetString() ?? "Phase"
                                : phase.TryGetProperty("id", out var id)
                                    ? $"Phase {id.GetInt32()}"
                                    : "Phase";
                            string status = phase.TryGetProperty("status", out var s)
                                ? s.GetString() ?? ""
                                : "";
                            string badge = status switch
                            {
                                "done"        => "[done]",
                                "active"      => "[active]",
                                "in-progress" => "[active]",
                                "pending"     => "[pending]",
                                _             => "",
                            };
                            sb.AppendLine($"  {badge} {phaseName}");
                        }
                    }

                    if (root.TryGetProperty("tasks", out var tasks))
                    {
                        sb.AppendLine();
                        sb.AppendLine("=== Tasks ===");
                        foreach (var task in tasks.EnumerateArray())
                        {
                            string title = task.TryGetProperty("title", out var t)
                                ? t.GetString() ?? "Task"
                                : "Task";
                            string tStatus = task.TryGetProperty("status", out var ts)
                                ? ts.GetString() ?? ""
                                : "";
                            string badge = tStatus switch
                            {
                                "done"        => "[done]",
                                "in-progress" => "[active]",
                                "pending"     => "[pending]",
                                _             => "",
                            };
                            sb.AppendLine($"  {badge} {title}");
                        }
                    }
                }
                catch
                {
                    sb.AppendLine("  (roadmap.json parse error)");
                }
            }

            return sb.ToString().TrimEnd();
        }

        private void ProjectListBox_Drop(object sender, DragEventArgs e)
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            string[] files = (string[])e.Data.GetData(DataFormats.FileDrop);
            foreach (var file in files)
            {
                string folderName = Path.GetFileNameWithoutExtension(file);
                string destPath = Path.Combine(projectsRoot, folderName);
                Directory.CreateDirectory(destPath);
                string dest = Path.Combine(destPath, Path.GetFileName(file));
                File.Copy(file, dest, true);
                if (!ProjectListBox.Items.Contains(folderName))
                    ProjectListBox.Items.Add(folderName);
            }
        }
    }
}
