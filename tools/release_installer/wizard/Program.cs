using Microsoft.Win32;
using System.Diagnostics;
using System.Text.RegularExpressions;

namespace GoldenEraModInstaller;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new InstallerForm());
    }
}

internal sealed class InstallerForm : Form
{
    private readonly string packageRoot = AppContext.BaseDirectory;
    private readonly TextBox pathBox = new();
    private readonly TextBox homm3PathBox = new();
    private readonly TextBox logBox = new();
    private readonly Button browseButton = new();
    private readonly Button browseHomm3Button = new();
    private readonly Button installButton = new();
    private readonly Button repairButton = new();
    private readonly Button uninstallButton = new();
    private readonly Button closeButton = new();

    public InstallerForm()
    {
        SuspendLayout();
        Text = "Golden Era Mod Installer";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        Font = new Font("Segoe UI", 9F);
        MinimumSize = new Size(760, 620);
        ClientSize = new Size(900, 680);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 8,
            Padding = new Padding(18),
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        Controls.Add(root);

        var title = new Label
        {
            Text = "Heroes of Might and Magic Olden Era - Golden Era Mod",
            Font = new Font("Segoe UI", 13, FontStyle.Bold),
            AutoEllipsis = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 18),
            AutoSize = true,
            MaximumSize = new Size(0, 0)
        };
        root.Controls.Add(title, 0, 0);

        var pathLabel = new Label
        {
            Text = "Game folder",
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 6)
        };
        root.Controls.Add(pathLabel, 0, 1);

        var gameRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 18)
        };
        gameRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        gameRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        root.Controls.Add(gameRow, 0, 2);

        pathBox.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        pathBox.Dock = DockStyle.Fill;
        pathBox.Margin = new Padding(0, 0, 10, 0);
        pathBox.Text = FindFirstValidGameRoot() ?? "";
        gameRow.Controls.Add(pathBox, 0, 0);

        browseButton.Text = "Browse...";
        browseButton.AutoSize = true;
        browseButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        browseButton.Margin = new Padding(0);
        browseButton.MinimumSize = new Size(104, 0);
        browseButton.Click += (_, _) => Browse();
        gameRow.Controls.Add(browseButton, 1, 0);

        var homm3PathLabel = new Label
        {
            Text = "HoMM3 Complete or HD folder",
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 6)
        };
        root.Controls.Add(homm3PathLabel, 0, 3);

        var homm3Row = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 18)
        };
        homm3Row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        homm3Row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        root.Controls.Add(homm3Row, 0, 4);

        homm3PathBox.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        homm3PathBox.Dock = DockStyle.Fill;
        homm3PathBox.Margin = new Padding(0, 0, 10, 0);
        homm3PathBox.Text = FindFirstValidHomm3Root() ?? "";
        homm3Row.Controls.Add(homm3PathBox, 0, 0);

        browseHomm3Button.Text = "Browse...";
        browseHomm3Button.AutoSize = true;
        browseHomm3Button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        browseHomm3Button.Margin = new Padding(0);
        browseHomm3Button.MinimumSize = new Size(104, 0);
        browseHomm3Button.Click += (_, _) => BrowseHomm3();
        homm3Row.Controls.Add(browseHomm3Button, 1, 0);

        var info = new Label
        {
            Text = "Installs the bundled BepInEx loader, Golden Era mod files, and Core.zip overlay. Backups are created before files are changed.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 22)
        };
        root.Controls.Add(info, 0, 5);

        var buttonRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 5,
            Margin = new Padding(0, 0, 0, 20)
        };
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        root.Controls.Add(buttonRow, 0, 6);

        installButton.Text = "Install";
        installButton.AutoSize = true;
        installButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        installButton.Margin = new Padding(0, 0, 12, 0);
        installButton.MinimumSize = new Size(112, 0);
        installButton.Click += async (_, _) => await RunOperationAsync("Install", Path.Combine(packageRoot, "install.ps1"), false);
        buttonRow.Controls.Add(installButton, 0, 0);

        repairButton.Text = "Repair";
        repairButton.AutoSize = true;
        repairButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        repairButton.Margin = new Padding(0, 0, 12, 0);
        repairButton.MinimumSize = new Size(112, 0);
        repairButton.Click += async (_, _) => await RunOperationAsync("Repair", Path.Combine(packageRoot, "install.ps1"), true);
        buttonRow.Controls.Add(repairButton, 1, 0);

        uninstallButton.Text = "Uninstall";
        uninstallButton.AutoSize = true;
        uninstallButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        uninstallButton.Margin = new Padding(0, 0, 12, 0);
        uninstallButton.MinimumSize = new Size(112, 0);
        uninstallButton.Click += async (_, _) => await RunOperationAsync("Uninstall", Path.Combine(packageRoot, "uninstall.ps1"), false);
        buttonRow.Controls.Add(uninstallButton, 2, 0);

        closeButton.Text = "Close";
        closeButton.AutoSize = true;
        closeButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        closeButton.Margin = new Padding(0);
        closeButton.MinimumSize = new Size(104, 0);
        closeButton.Click += (_, _) => Close();
        buttonRow.Controls.Add(closeButton, 4, 0);

        logBox.Dock = DockStyle.Fill;
        logBox.Margin = new Padding(0);
        logBox.Multiline = true;
        logBox.ScrollBars = ScrollBars.Vertical;
        logBox.ReadOnly = true;
        logBox.Font = new Font("Consolas", 9);
        root.Controls.Add(logBox, 0, 7);

        AppendLog("Ready. Confirm the game folder, then click Install.");
        if (string.IsNullOrWhiteSpace(pathBox.Text))
        {
            AppendLog("Auto-detect did not find the game. Click Browse and choose the folder containing HeroesOldenEra.exe.");
        }
        if (string.IsNullOrWhiteSpace(homm3PathBox.Text))
        {
            AppendLog("Auto-detect did not find HoMM3 Complete or HD. Click Browse and choose that install folder before installing.");
        }
        else
        {
            AppendLog("Found HoMM3 prerequisite: " + homm3PathBox.Text);
        }
        ResumeLayout(false);
    }

    private void Browse()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose the folder containing HeroesOldenEra.exe",
            UseDescriptionForTitle = true
        };
        if (Directory.Exists(pathBox.Text))
        {
            dialog.SelectedPath = pathBox.Text;
        }
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            pathBox.Text = dialog.SelectedPath;
        }
    }

    private void BrowseHomm3()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose the HoMM3 Complete or HoMM3 HD install folder",
            UseDescriptionForTitle = true
        };
        if (Directory.Exists(homm3PathBox.Text))
        {
            dialog.SelectedPath = homm3PathBox.Text;
        }
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            homm3PathBox.Text = dialog.SelectedPath;
        }
    }

    private async Task RunOperationAsync(string label, string scriptPath, bool repair)
    {
        try
        {
            SetBusy(true);
            AppendLog($"Starting {label.ToLowerInvariant()}...");
            await Task.Run(() => RunBackend(scriptPath, pathBox.Text, homm3PathBox.Text, repair, label != "Uninstall"));
            AppendLog($"{label} complete.");
            MessageBox.Show(this, $"{label} complete.", "Golden Era Mod Installer", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            AppendLog("ERROR: " + ex.Message);
            MessageBox.Show(this, ex.Message, $"{label} failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void RunBackend(string scriptPath, string gameRoot, string homm3Root, bool repair, bool requireHomm3)
    {
        if (!File.Exists(scriptPath))
        {
            throw new FileNotFoundException("Missing backend script.", scriptPath);
        }
        if (string.IsNullOrWhiteSpace(gameRoot))
        {
            throw new InvalidOperationException("Choose the game folder first.");
        }
        if (!File.Exists(Path.Combine(gameRoot, "HeroesOldenEra.exe")))
        {
            throw new InvalidOperationException("The selected folder does not contain HeroesOldenEra.exe.");
        }
        if (requireHomm3)
        {
            if (string.IsNullOrWhiteSpace(homm3Root))
            {
                throw new InvalidOperationException("Choose the HoMM3 Complete or HoMM3 HD folder first.");
            }
            if (!IsValidHomm3Root(homm3Root))
            {
                throw new InvalidOperationException("The selected HoMM3 folder does not look like HoMM3 Complete or HoMM3 HD.");
            }
        }

        var args = $"-NoProfile -ExecutionPolicy Bypass -File \"{scriptPath}\" -GameRoot \"{gameRoot}\"";
        if (requireHomm3)
        {
            args += $" -Homm3Root \"{homm3Root}\"";
        }
        if (repair)
        {
            args += " -Repair";
        }

        AppendLog("Running backend...");
        var info = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = args,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true
        };

        using var process = new Process { StartInfo = info };
        process.OutputDataReceived += (_, e) => { if (e.Data is { Length: > 0 }) AppendLog(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is { Length: > 0 }) AppendLog(e.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        process.WaitForExit();
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"Backend exited with code {process.ExitCode}.");
        }
    }

    private void SetBusy(bool busy)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => SetBusy(busy));
            return;
        }
        installButton.Enabled = !busy;
        repairButton.Enabled = !busy;
        uninstallButton.Enabled = !busy;
        browseButton.Enabled = !busy;
        browseHomm3Button.Enabled = !busy;
        closeButton.Enabled = !busy;
        Cursor = busy ? Cursors.WaitCursor : Cursors.Default;
    }

    private void AppendLog(string text)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => AppendLog(text));
            return;
        }
        logBox.AppendText(text + Environment.NewLine);
        logBox.SelectionStart = logBox.Text.Length;
        logBox.ScrollToCaret();
    }

    private static string? FindFirstValidGameRoot()
    {
        foreach (var candidate in FindGameRootCandidates())
        {
            if (File.Exists(Path.Combine(candidate, "HeroesOldenEra.exe")))
            {
                return candidate;
            }
        }
        return null;
    }

    private static string? FindFirstValidHomm3Root()
    {
        foreach (var candidate in FindHomm3RootCandidates())
        {
            if (IsValidHomm3Root(candidate))
            {
                return candidate;
            }
        }
        return null;
    }

    private static IEnumerable<string> FindHomm3RootCandidates()
    {
        var candidates = new List<string>();
        AddCandidate(candidates, Path.Combine(AppContext.BaseDirectory, "HoMM 3 Complete"));
        AddCandidate(candidates, @"C:\GOG Games\HoMM 3 Complete");
        AddCandidate(candidates, @"C:\GOG Games\Heroes of Might and Magic 3 Complete");
        AddCandidate(candidates, @"C:\Program Files (x86)\GOG Galaxy\Games\HoMM 3 Complete");
        AddCandidate(candidates, @"C:\Program Files (x86)\GOG Galaxy\Games\Heroes of Might and Magic 3 Complete");
        AddCandidate(candidates, @"C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might & Magic III - HD Edition");
        AddCandidate(candidates, @"C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might and Magic III - HD Edition");

        var pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
        var pf = Environment.GetEnvironmentVariable("ProgramFiles");
        if (!string.IsNullOrWhiteSpace(pf86)) AddHomm3SteamLibraries(candidates, Path.Combine(pf86, "Steam"));
        if (!string.IsNullOrWhiteSpace(pf)) AddHomm3SteamLibraries(candidates, Path.Combine(pf, "Steam"));

        foreach (var drive in DriveInfo.GetDrives().Where(d => d.IsReady))
        {
            AddCandidate(candidates, Path.Combine(drive.RootDirectory.FullName, @"GOG Games\HoMM 3 Complete"));
            AddCandidate(candidates, Path.Combine(drive.RootDirectory.FullName, @"GOG Games\Heroes of Might and Magic 3 Complete"));
            AddCandidate(candidates, Path.Combine(drive.RootDirectory.FullName, @"SteamLibrary\steamapps\common\Heroes of Might & Magic III - HD Edition"));
            AddCandidate(candidates, Path.Combine(drive.RootDirectory.FullName, @"SteamLibrary\steamapps\common\Heroes of Might and Magic III - HD Edition"));
        }

        return candidates;
    }

    private static void AddHomm3SteamLibraries(List<string> candidates, string steamRoot, HashSet<string>? visited = null)
    {
        if (string.IsNullOrWhiteSpace(steamRoot)) return;
        visited ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var normalizedSteamRoot = Path.GetFullPath(Environment.ExpandEnvironmentVariables(steamRoot));
        if (!visited.Add(normalizedSteamRoot)) return;

        foreach (var folderName in new[]
        {
            "Heroes of Might & Magic III - HD Edition",
            "Heroes of Might and Magic III - HD Edition"
        })
        {
            AddCandidate(candidates, Path.Combine(normalizedSteamRoot, "steamapps", "common", folderName));
        }

        var libraryFile = Path.Combine(normalizedSteamRoot, @"steamapps\libraryfolders.vdf");
        if (!File.Exists(libraryFile)) return;

        foreach (var line in File.ReadLines(libraryFile))
        {
            var match = Regex.Match(line, "\"path\"\\s+\"([^\"]+)\"");
            if (match.Success)
            {
                var libraryPath = match.Groups[1].Value.Replace(@"\\", @"\");
                AddHomm3SteamLibraries(candidates, libraryPath, visited);
            }
        }
    }

    private static bool IsValidHomm3Root(string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Directory.Exists(path)) return false;

        var hasHeroes3Exe = File.Exists(Path.Combine(path, "Heroes3.exe")) ||
                            File.Exists(Path.Combine(path, "HD_Launcher.exe")) ||
                            File.Exists(Path.Combine(path, "Might & Magic Heroes III - HD Edition.exe")) ||
                            File.Exists(Path.Combine(path, "Heroes of Might & Magic III - HD Edition.exe"));
        if (!hasHeroes3Exe) return false;

        var data = Path.Combine(path, "Data");
        var hasCompleteLods = File.Exists(Path.Combine(data, "H3bitmap.lod")) &&
                              File.Exists(Path.Combine(data, "H3sprite.lod")) &&
                              File.Exists(Path.Combine(data, "H3ab_bmp.lod")) &&
                              File.Exists(Path.Combine(data, "H3ab_spr.lod"));
        var hasHdMarkers = Directory.Exists(Path.Combine(path, "_HD3_Data")) ||
                           path.Contains("HD Edition", StringComparison.OrdinalIgnoreCase);

        return hasCompleteLods || hasHdMarkers;
    }

    private static IEnumerable<string> FindGameRootCandidates()
    {
        var candidates = new List<string>();
        AddCandidate(candidates, @"C:\Program Files (x86)\Steam\steamapps\common\Heroes of Might and Magic Olden Era");

        var pf86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
        var pf = Environment.GetEnvironmentVariable("ProgramFiles");
        if (!string.IsNullOrWhiteSpace(pf86)) AddSteamLibraries(candidates, Path.Combine(pf86, "Steam"));
        if (!string.IsNullOrWhiteSpace(pf)) AddSteamLibraries(candidates, Path.Combine(pf, "Steam"));

        foreach (var regPath in new[]
        {
            (Registry.CurrentUser, @"Software\Valve\Steam"),
            (Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam"),
            (Registry.LocalMachine, @"SOFTWARE\Valve\Steam")
        })
        {
            try
            {
                using var key = regPath.Item1.OpenSubKey(regPath.Item2);
                var value = key?.GetValue("InstallPath") as string;
                if (!string.IsNullOrWhiteSpace(value)) AddSteamLibraries(candidates, value);
            }
            catch
            {
            }
        }

        foreach (var drive in DriveInfo.GetDrives().Where(d => d.IsReady))
        {
            AddCandidate(candidates, Path.Combine(drive.RootDirectory.FullName, @"SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era"));
        }

        return candidates;
    }

    private static void AddSteamLibraries(List<string> candidates, string steamRoot)
    {
        if (string.IsNullOrWhiteSpace(steamRoot)) return;
        AddCandidate(candidates, Path.Combine(steamRoot, @"steamapps\common\Heroes of Might and Magic Olden Era"));

        var libraryFile = Path.Combine(steamRoot, @"steamapps\libraryfolders.vdf");
        if (!File.Exists(libraryFile)) return;

        foreach (var line in File.ReadLines(libraryFile))
        {
            var match = Regex.Match(line, "\"path\"\\s+\"([^\"]+)\"");
            if (match.Success)
            {
                var libraryPath = match.Groups[1].Value.Replace(@"\\", @"\");
                AddCandidate(candidates, Path.Combine(libraryPath, @"steamapps\common\Heroes of Might and Magic Olden Era"));
            }
        }

        var steamApps = Path.Combine(steamRoot, "steamapps");
        if (Directory.Exists(steamApps))
        {
            foreach (var manifest in Directory.EnumerateFiles(steamApps, "appmanifest_*.acf"))
            {
                try
                {
                    var text = File.ReadAllText(manifest);
                    if (!text.Contains("Heroes of Might", StringComparison.OrdinalIgnoreCase) ||
                        !text.Contains("Olden Era", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    var installDir = Regex.Match(text, "\"installdir\"\\s+\"([^\"]+)\"");
                    if (installDir.Success)
                    {
                        AddCandidate(candidates, Path.Combine(steamRoot, "steamapps", "common", installDir.Groups[1].Value));
                    }
                }
                catch
                {
                }
            }
        }
    }

    private static void AddCandidate(List<string> candidates, string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var expanded = Environment.ExpandEnvironmentVariables(path);
        if (!candidates.Any(c => string.Equals(c, expanded, StringComparison.OrdinalIgnoreCase)))
        {
            candidates.Add(expanded);
        }
    }
}
