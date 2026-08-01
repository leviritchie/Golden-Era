using Microsoft.Win32;
using System.Diagnostics;
using System.Reflection;
using System.Text.RegularExpressions;

namespace GoldenEraModInstaller;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Any(arg => string.Equals(arg, "--verify-payload", StringComparison.OrdinalIgnoreCase)))
        {
            var logPath = Path.Combine(
                InstallerBackend.GetInstallerCacheRoot(),
                "verify-payload.log");
            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
            using var logWriter = new StreamWriter(logPath, append: false) { AutoFlush = true };
            void Log(string message)
            {
                logWriter.WriteLine(message);
                try { Console.Error.WriteLine(message); } catch { /* WinExe may have no console */ }
            }

            try
            {
                InstallerBackend.VerifyEmbeddedPayload(Log);
                Log("VERIFY_OK");
                return 0;
            }
            catch (Exception ex)
            {
                Log("VERIFY_FAILED: " + ex);
                return 1;
            }
        }

        var verifyHomm3RootIndex = Array.FindIndex(args, arg => string.Equals(arg, "--verify-homm3-root", StringComparison.OrdinalIgnoreCase));
        if (verifyHomm3RootIndex >= 0)
        {
            if (verifyHomm3RootIndex + 1 >= args.Length)
            {
                Console.Error.WriteLine("Missing path after --verify-homm3-root.");
                return 1;
            }

            var root = args[verifyHomm3RootIndex + 1];
            var isValid = InstallerBackend.IsValidHomm3Root(root);
            Console.Error.WriteLine(isValid ? "HoMM3 root is valid." : "HoMM3 root is not valid.");
            return isValid ? 0 : 1;
        }

        ApplicationConfiguration.Initialize();
        Application.Run(new WizardInstallerForm());
        return 0;
    }
}

internal sealed class InstallerForm : Form
{
    private readonly TextBox sourcePathBox = new();
    private readonly TextBox targetPathBox = new();
    private readonly TextBox homm3PathBox = new();
    private readonly TextBox logBox = new();
    private readonly Button browseSourceButton = new();
    private readonly Button browseTargetButton = new();
    private readonly Button browseHomm3Button = new();
    private readonly Button installButton = new();
    private readonly Button updateButton = new();
    private readonly Button repairButton = new();
    private readonly Button uninstallButton = new();
    private readonly Button closeButton = new();
    private readonly TextBox steamDepotCommandBox = new();
    private readonly TextBox steamDepotPathBox = new();
    private readonly Label steamDepotStatusLabel = new();
    private readonly Button openSteamConsoleButton = new();
    private readonly Button copyDepotCommandButton = new();
    private readonly Button detectSteamDepotButton = new();
    private readonly Button copyDepotPathButton = new();
    private readonly Button browseSteamDepotButton = new();

    private string lastAutoTarget = "";
    private bool suppressAutoTargetRefresh;

    public InstallerForm()
    {
        SuspendLayout();
        Text = "Golden Era Mod Installer";
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        AutoScroll = true;
        Font = new Font("Segoe UI", 9F);
        MinimumSize = new Size(820, 700);
        ClientSize = new Size(980, 820);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 11,
            Padding = new Padding(18),
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        for (var i = 0; i < 10; i++)
        {
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        Controls.Add(root);

        var title = new Label
        {
            Text = "Heroes of Might and Magic Olden Era - Golden Era Mod",
            Font = new Font("Segoe UI", 13, FontStyle.Bold),
            AutoEllipsis = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 12),
            AutoSize = true
        };
        root.Controls.Add(title, 0, 0);

        var info = new Label
        {
            Text = "Installs Golden Era into a separate modded copy. Update refreshes an existing Golden Era copy from its saved clean baseline when possible.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 12)
        };
        root.Controls.Add(info, 0, 1);
        root.Controls.Add(CreateSteamDepotPanel(), 0, 2);

        AddPathRow(root, 3, "Clean Olden Era source folder", sourcePathBox, browseSourceButton, (_, _) => BrowseSource());
        AddPathRow(root, 5, "Modded copy folder", targetPathBox, browseTargetButton, (_, _) => BrowseTarget());
        AddPathRow(root, 7, "HoMM3 Complete or HD folder", homm3PathBox, browseHomm3Button, (_, _) => BrowseHomm3());

        var buttonRow = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 6,
            Margin = new Padding(0, 4, 0, 20)
        };
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        buttonRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        root.Controls.Add(buttonRow, 0, 9);

        installButton.Text = "Install";
        installButton.AutoSize = true;
        installButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        installButton.Margin = new Padding(0, 0, 12, 0);
        installButton.MinimumSize = new Size(112, 0);
        installButton.Click += async (_, _) => await RunOperationAsync(InstallerOperation.Install);
        buttonRow.Controls.Add(installButton, 0, 0);

        updateButton.Text = "Update";
        updateButton.AutoSize = true;
        updateButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        updateButton.Margin = new Padding(0, 0, 12, 0);
        updateButton.MinimumSize = new Size(112, 0);
        updateButton.Click += async (_, _) => await RunOperationAsync(InstallerOperation.Update);
        buttonRow.Controls.Add(updateButton, 1, 0);

        repairButton.Text = "Repair";
        repairButton.AutoSize = true;
        repairButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        repairButton.Margin = new Padding(0, 0, 12, 0);
        repairButton.MinimumSize = new Size(112, 0);
        repairButton.Click += async (_, _) => await RunOperationAsync(InstallerOperation.Repair);
        buttonRow.Controls.Add(repairButton, 2, 0);

        uninstallButton.Text = "Uninstall";
        uninstallButton.AutoSize = true;
        uninstallButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        uninstallButton.Margin = new Padding(0, 0, 12, 0);
        uninstallButton.MinimumSize = new Size(112, 0);
        uninstallButton.Click += async (_, _) => await RunOperationAsync(InstallerOperation.Uninstall);
        buttonRow.Controls.Add(uninstallButton, 3, 0);

        closeButton.Text = "Close";
        closeButton.AutoSize = true;
        closeButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        closeButton.Margin = new Padding(0);
        closeButton.MinimumSize = new Size(104, 0);
        closeButton.Click += (_, _) => Close();
        buttonRow.Controls.Add(closeButton, 5, 0);

        logBox.Dock = DockStyle.Fill;
        logBox.Margin = new Padding(0);
        logBox.Multiline = true;
        logBox.ScrollBars = ScrollBars.Vertical;
        logBox.ReadOnly = true;
        logBox.Font = new Font("Consolas", 9);
        root.Controls.Add(logBox, 0, 10);

        sourcePathBox.Text = FindFirstValidGameRoot() ?? "";
        lastAutoTarget = InstallerBackend.GetPreferredTargetRoot(sourcePathBox.Text);
        targetPathBox.Text = lastAutoTarget;
        homm3PathBox.Text = FindFirstValidHomm3Root() ?? "";
        sourcePathBox.TextChanged += (_, _) => RefreshAutoTarget();

        AppendLog($"Ready. Installer version: {InstallerBackend.PackageVersion}");
        AppendLog("Install and Repair copy the selected Steam folder to the modded copy folder, then patch only that copy.");
        AppendLog("Update refreshes the selected modded copy from its saved clean Core.zip baseline without copying Steam again.");
        if (string.IsNullOrWhiteSpace(sourcePathBox.Text))
        {
            AppendLog("Auto-detect did not find Olden Era. Use Browse, or use the Steam depot helper above to download the compatible build.");
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

    private Control CreateSteamDepotPanel()
    {
        var group = new GroupBox
        {
            Text = "Need the compatible Steam build?",
            Dock = DockStyle.Fill,
            AutoSize = true,
            Padding = new Padding(12, 10, 12, 12),
            Margin = new Padding(0, 0, 0, 16)
        };

        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 1,
            RowCount = 6,
            Margin = new Padding(0)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        for (var i = 0; i < 6; i++)
        {
            panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        }
        group.Controls.Add(panel);

        var help = new Label
        {
            Text = "If Steam updated your installed game, open Steam's official console, run the depot command, then detect the downloaded folder here. Golden Era will copy from that verified depot into the modded folder; it never asks for your Steam password.",
            AutoSize = true,
            Dock = DockStyle.Fill,
            Margin = new Padding(0, 0, 0, 8)
        };
        panel.Controls.Add(help, 0, 0);

        steamDepotCommandBox.Text = InstallerBackend.CompatibleSteamDepotCommand;
        AddCopyRow(
            panel,
            1,
            "Steam console command",
            steamDepotCommandBox,
            ("Open Steam Console", openSteamConsoleButton, OpenSteamConsole),
            ("Copy Command", copyDepotCommandButton, () => CopyTextToClipboard(steamDepotCommandBox.Text, "Steam depot command")));

        steamDepotPathBox.Text = InstallerBackend.GetExpectedSteamDepotPath() ?? "";
        AddCopyRow(
            panel,
            2,
            "Expected Steam download folder",
            steamDepotPathBox,
            ("Detect Download", detectSteamDepotButton, DetectSteamDepot),
            ("Copy Path", copyDepotPathButton, () => CopyTextToClipboard(steamDepotPathBox.Text, "Steam depot path")),
            ("Browse Download", browseSteamDepotButton, BrowseSteamDepot));

        steamDepotStatusLabel.AutoSize = true;
        steamDepotStatusLabel.Dock = DockStyle.Fill;
        steamDepotStatusLabel.Margin = new Padding(0, 4, 0, 0);
        steamDepotStatusLabel.Text = string.IsNullOrWhiteSpace(steamDepotPathBox.Text)
            ? "Steam install path was not found automatically. You can still browse to Steam's depot download folder after the command finishes."
            : "After Steam reports the depot download is complete, click Detect Download.";
        panel.Controls.Add(steamDepotStatusLabel, 0, 5);

        return group;
    }

    private static void AddCopyRow(
        TableLayoutPanel root,
        int rowIndex,
        string labelText,
        TextBox textBox,
        params (string Text, Button Button, Action Handler)[] actions)
    {
        var label = new Label
        {
            Text = labelText,
            AutoSize = true,
            Margin = new Padding(0, rowIndex == 1 ? 0 : 8, 0, 4)
        };
        root.Controls.Add(label, 0, rowIndex * 2 - 1);

        var row = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = actions.Length + 1,
            Margin = new Padding(0, 0, 0, 0)
        };
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        foreach (var _ in actions)
        {
            row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        }
        root.Controls.Add(row, 0, rowIndex * 2);

        textBox.ReadOnly = true;
        textBox.Dock = DockStyle.Fill;
        textBox.Margin = new Padding(0, 0, 10, 0);
        textBox.Font = new Font("Consolas", 9F);
        row.Controls.Add(textBox, 0, 0);

        for (var i = 0; i < actions.Length; i++)
        {
            var action = actions[i];
            action.Button.Text = action.Text;
            action.Button.AutoSize = true;
            action.Button.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            action.Button.Margin = new Padding(0, 0, i == actions.Length - 1 ? 0 : 8, 0);
            action.Button.MinimumSize = new Size(104, 0);
            action.Button.Click += (_, _) => action.Handler();
            row.Controls.Add(action.Button, i + 1, 0);
        }
    }

    private void OpenSteamConsole()
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = InstallerBackend.CompatibleSteamConsoleUri,
                UseShellExecute = true
            });
            AppendLog("Opened Steam console. Paste this command there: " + InstallerBackend.CompatibleSteamDepotCommand);
        }
        catch (Exception ex)
        {
            AppendLog("Could not open Steam console automatically: " + ex.Message);
            MessageBox.Show(this, "Steam console could not be opened automatically. Copy the command and open Steam manually.", "Steam Console", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void DetectSteamDepot()
    {
        try
        {
            if (InstallerBackend.TryFindCompatibleSteamDepot(out var depotPath, out var summary))
            {
                SelectSteamDepotSource(depotPath);
                steamDepotStatusLabel.Text = "Compatible depot verified and selected as the clean source folder.";
                AppendLog(summary);
                return;
            }

            steamDepotStatusLabel.Text = summary;
            AppendLog(summary);
        }
        catch (Exception ex)
        {
            steamDepotStatusLabel.Text = ex.Message;
            AppendLog("Depot detection failed: " + ex.Message);
        }
    }

    private void BrowseSteamDepot()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose Steam's downloaded depot folder containing HeroesOldenEra.exe",
            UseDescriptionForTitle = true
        };
        if (Directory.Exists(steamDepotPathBox.Text))
        {
            dialog.SelectedPath = steamDepotPathBox.Text;
        }
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }

        try
        {
            var summary = InstallerBackend.ValidateCompatibleSteamDepot(dialog.SelectedPath);
            SelectSteamDepotSource(dialog.SelectedPath);
            steamDepotStatusLabel.Text = "Compatible depot verified and selected as the clean source folder.";
            AppendLog(summary);
        }
        catch (Exception ex)
        {
            steamDepotStatusLabel.Text = ex.Message;
            AppendLog("Depot validation failed: " + ex.Message);
            MessageBox.Show(this, ex.Message, "Downloaded depot is not compatible", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SelectSteamDepotSource(string depotPath)
    {
        steamDepotPathBox.Text = depotPath;
        suppressAutoTargetRefresh = true;
        try
        {
            sourcePathBox.Text = depotPath;
        }
        finally
        {
            suppressAutoTargetRefresh = false;
        }

        if (string.IsNullOrWhiteSpace(targetPathBox.Text))
        {
            lastAutoTarget = InstallerBackend.GetPreferredTargetRoot("");
            targetPathBox.Text = lastAutoTarget;
        }
    }

    private void CopyTextToClipboard(string text, string label)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            MessageBox.Show(this, "There is no " + label + " to copy yet.", "Golden Era Mod Installer", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        Clipboard.SetText(text);
        AppendLog("Copied " + label + " to clipboard.");
    }

    private static void AddPathRow(
        TableLayoutPanel root,
        int labelRow,
        string labelText,
        TextBox textBox,
        Button browseButton,
        EventHandler browseHandler)
    {
        var label = new Label
        {
            Text = labelText,
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 6)
        };
        root.Controls.Add(label, 0, labelRow);

        var row = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            ColumnCount = 2,
            Margin = new Padding(0, 0, 0, 16)
        };
        row.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        row.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        root.Controls.Add(row, 0, labelRow + 1);

        textBox.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        textBox.Dock = DockStyle.Fill;
        textBox.Margin = new Padding(0, 0, 10, 0);
        row.Controls.Add(textBox, 0, 0);

        browseButton.Text = "Browse...";
        browseButton.AutoSize = true;
        browseButton.AutoSizeMode = AutoSizeMode.GrowAndShrink;
        browseButton.Margin = new Padding(0);
        browseButton.MinimumSize = new Size(104, 0);
        browseButton.Click += browseHandler;
        row.Controls.Add(browseButton, 1, 0);
    }

    private void BrowseSource()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose a clean Steam install or downloaded depot folder containing HeroesOldenEra.exe",
            UseDescriptionForTitle = true
        };
        if (Directory.Exists(sourcePathBox.Text))
        {
            dialog.SelectedPath = sourcePathBox.Text;
        }
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            sourcePathBox.Text = dialog.SelectedPath;
            RefreshAutoTarget(force: true);
        }
    }

    private void BrowseTarget()
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Choose where the separate Golden Era game copy should be installed",
            UseDescriptionForTitle = true
        };
        if (Directory.Exists(targetPathBox.Text))
        {
            dialog.SelectedPath = targetPathBox.Text;
        }
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            targetPathBox.Text = dialog.SelectedPath;
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

    private async Task RunOperationAsync(InstallerOperation operation)
    {
        var sourceBeforeRun = sourcePathBox.Text;
        try
        {
            SetBusy(true);
            AppendLog($"Starting {operation.ToString().ToLowerInvariant()}...");
            var request = new InstallRequest(
                operation,
                sourceBeforeRun,
                targetPathBox.Text,
                homm3PathBox.Text,
                string.Equals(targetPathBox.Text, lastAutoTarget, StringComparison.OrdinalIgnoreCase));
            await Task.Run(() => InstallerBackend.Run(request, AppendLog));
            AppendLog($"{operation} complete.");
            await OfferSteamDepotCleanupAsync(operation, sourceBeforeRun);
            MessageBox.Show(this, $"{operation} complete.", "Golden Era Mod Installer", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            AppendLog("ERROR: " + ex.Message);
            MessageBox.Show(this, ex.Message, $"{operation} failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async Task OfferSteamDepotCleanupAsync(InstallerOperation operation, string sourceRoot)
    {
        if (operation is not (InstallerOperation.Install or InstallerOperation.Repair) ||
            !InstallerBackend.IsExpectedSteamDepotContentRoot(sourceRoot))
        {
            return;
        }

        var result = MessageBox.Show(
            this,
            "Golden Era has copied and verified the modded install. Delete Steam's temporary depot download now?\r\n\r\n" + sourceRoot,
            "Clean Up Steam Depot Download",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question,
            MessageBoxDefaultButton.Button2);
        if (result != DialogResult.Yes)
        {
            AppendLog("Left Steam depot download in place: " + sourceRoot);
            return;
        }

        try
        {
            AppendLog("Deleting Steam depot download: " + sourceRoot);
            await Task.Run(() => InstallerBackend.DeleteExpectedSteamDepotContentRoot(sourceRoot));
            AppendLog("Deleted Steam depot download.");
        }
        catch (Exception ex)
        {
            AppendLog("Depot cleanup failed: " + ex.Message);
            MessageBox.Show(this, ex.Message, "Depot cleanup failed", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void RefreshAutoTarget(bool force = false)
    {
        if (suppressAutoTargetRefresh)
        {
            return;
        }

        var newAutoTarget = InstallerBackend.GetPreferredTargetRoot(sourcePathBox.Text);
        if (force ||
            string.IsNullOrWhiteSpace(targetPathBox.Text) ||
            string.Equals(targetPathBox.Text, lastAutoTarget, StringComparison.OrdinalIgnoreCase))
        {
            targetPathBox.Text = newAutoTarget;
        }
        lastAutoTarget = newAutoTarget;
    }

    private void SetBusy(bool busy)
    {
        if (InvokeRequired)
        {
            BeginInvoke(() => SetBusy(busy));
            return;
        }
        installButton.Enabled = !busy;
        updateButton.Enabled = !busy;
        repairButton.Enabled = !busy;
        uninstallButton.Enabled = !busy;
        browseSourceButton.Enabled = !busy;
        browseTargetButton.Enabled = !busy;
        browseHomm3Button.Enabled = !busy;
        openSteamConsoleButton.Enabled = !busy;
        copyDepotCommandButton.Enabled = !busy;
        detectSteamDepotButton.Enabled = !busy;
        copyDepotPathButton.Enabled = !busy;
        browseSteamDepotButton.Enabled = !busy;
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
            if (InstallerBackend.IsValidHomm3Root(candidate))
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
