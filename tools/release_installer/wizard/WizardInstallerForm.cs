using System.Diagnostics;
using System.Text.RegularExpressions;

namespace GoldenEraModInstaller;

internal sealed class WizardInstallerForm : Form
{
    private enum WizardStep
    {
        Operation,
        Source,
        Target,
        Homm3,
        Review,
        Progress
    }

    private readonly Panel pageHost = new() { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(24) };
    private readonly Label titleLabel = new() { AutoSize = true, Dock = DockStyle.Top, Font = new Font("Segoe UI", 16F, FontStyle.Bold) };
    private readonly Label subtitleLabel = new() { AutoSize = true, Dock = DockStyle.Top, MaximumSize = new Size(840, 0), Margin = new Padding(0, 8, 0, 18) };
    private readonly TextBox logBox = new()
    {
        Dock = DockStyle.Bottom,
        Height = 96,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        Font = new Font("Segoe UI", 9F)
    };
    private readonly ProgressBar progressBar = new()
    {
        Dock = DockStyle.Top,
        Height = 28,
        Minimum = 0,
        Maximum = 1000,
        Style = ProgressBarStyle.Continuous,
        Visible = false
    };
    private readonly Label progressStatusLabel = NewWrapLabel();
    private readonly Button backButton = new() { Text = "Back", Width = 96, Height = 34 };
    private readonly Button nextButton = new() { Text = "Next", Width = 120, Height = 34 };
    private readonly Button closeButton = new() { Text = "Close", Width = 96, Height = 34 };

    private readonly RadioButton installRadio = new() { Text = "Install a fresh modded copy", AutoSize = true, Checked = true };
    private readonly RadioButton updateRadio = new() { Text = "Update an existing Golden Era copy", AutoSize = true };
    private readonly RadioButton repairRadio = new() { Text = "Repair by rebuilding from a clean Steam source", AutoSize = true };
    private readonly RadioButton uninstallRadio = new() { Text = "Uninstall from an existing copy", AutoSize = true };

    private readonly TextBox depotCommandBox = NewReadOnlyBox();
    private readonly TextBox sourcePathBox = new() { Dock = DockStyle.Fill };
    private readonly TextBox targetPathBox = new() { Dock = DockStyle.Fill };
    private readonly TextBox homm3PathBox = new() { Dock = DockStyle.Fill };
    private readonly Label sourceStatusLabel = NewWrapLabel();
    private readonly Label targetStatusLabel = NewWrapLabel();
    private readonly Label homm3StatusLabel = NewWrapLabel();

    private readonly List<string> technicalLog = [];

    private WizardStep currentStep = WizardStep.Operation;
    private string lastAutoTarget = "";

    public WizardInstallerForm()
    {
        Text = "Golden Era Mod Installer";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(800, 700);
        Size = new Size(960, 800);
        AutoScaleMode = AutoScaleMode.Font;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(12)
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 180F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 68F));
        Controls.Add(root);

        var header = new Panel { Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(12, 8, 12, 8) };
        header.Controls.Add(subtitleLabel);
        header.Controls.Add(titleLabel);
        root.Controls.Add(header, 0, 0);
        root.Controls.Add(pageHost, 0, 1);

        var logPanel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            Padding = new Padding(0)
        };
        logPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        logPanel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        logPanel.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        progressStatusLabel.Text = "";
        progressStatusLabel.Margin = new Padding(0, 0, 0, 6);
        progressBar.Margin = new Padding(0, 0, 0, 6);
        logBox.Dock = DockStyle.Fill;
        logBox.Height = 120;
        logPanel.Controls.Add(progressStatusLabel, 0, 0);
        logPanel.Controls.Add(progressBar, 0, 1);
        logPanel.Controls.Add(logBox, 0, 2);
        root.Controls.Add(logPanel, 0, 2);

        var footer = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
            AutoSize = false,
            Padding = new Padding(0, 8, 0, 8)
        };
        footer.Controls.Add(closeButton);
        footer.Controls.Add(nextButton);
        footer.Controls.Add(backButton);
        root.Controls.Add(footer, 0, 3);

        closeButton.Click += (_, _) => Close();
        backButton.Click += (_, _) => MoveBack();
        nextButton.Click += async (_, _) => await MoveNextOrRunAsync();
        WireOperationRadioButtons();

        depotCommandBox.Text = InstallerBackend.CompatibleSteamDepotCommand;
        var expectedDepotPath = InstallerBackend.GetExpectedSteamDepotPath();
        if (!string.IsNullOrWhiteSpace(expectedDepotPath))
        {
            sourcePathBox.Text = expectedDepotPath;
        }

        homm3StatusLabel.Text = "Heroes III folder will be checked when this step opens.";

        AppendLog("Ready.");
        RenderStep();
    }

    private static TextBox NewReadOnlyBox(bool multiline = false)
    {
        return new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = multiline,
            ReadOnly = true,
            ScrollBars = multiline ? ScrollBars.Vertical : ScrollBars.None,
            Font = new Font("Segoe UI", 9F)
        };
    }

    private static Label NewWrapLabel()
    {
        return new Label
        {
            AutoSize = true,
            Dock = DockStyle.Fill,
            MaximumSize = new Size(860, 0),
            Margin = new Padding(0, 8, 0, 8)
        };
    }
    private void WireOperationRadioButtons()
    {
        RadioButton[] radios = [installRadio, updateRadio, repairRadio, uninstallRadio];
        foreach (var radio in radios)
        {
            radio.CheckedChanged += (_, _) =>
            {
                if (!radio.Checked)
                {
                    return;
                }

                foreach (var other in radios)
                {
                    if (!ReferenceEquals(other, radio))
                    {
                        other.Checked = false;
                    }
                }
            };
        }
    }
    private void RenderStep()
    {
        pageHost.Controls.Clear();
        backButton.Enabled = currentStep != WizardStep.Operation && currentStep != WizardStep.Progress;
        nextButton.Enabled = currentStep != WizardStep.Progress;
        closeButton.Enabled = true;

        switch (currentStep)
        {
            case WizardStep.Operation:
                titleLabel.Text = "What do you want to do?";
                subtitleLabel.Text = "Choose one action. The installer will ask for only the folders needed for that action.";
                nextButton.Text = "Next";
                pageHost.Controls.Add(BuildOperationPage());
                break;
            case WizardStep.Source:
                titleLabel.Text = "Select the June 4 Steam depot";
                subtitleLabel.Text = "Download the pinned Steam depot, then select or detect the download folder. This must be the June 4 build.";
                nextButton.Text = "Next";
                pageHost.Controls.Add(BuildSourcePage());
                break;
            case WizardStep.Target:
                titleLabel.Text = UsesSourceStep() ? "Choose the modded copy folder" : "Choose the existing modded copy";
                subtitleLabel.Text = UsesSourceStep()
                    ? "This is where the installer will create or rebuild the Golden Era copy."
                    : "Select the Golden Era copy that should be updated or removed.";
                nextButton.Text = "Next";
                pageHost.Controls.Add(BuildTargetPage());
                break;
            case WizardStep.Homm3:
                titleLabel.Text = "Select your Heroes III folder";
                subtitleLabel.Text = "The mod uses Heroes III art data. Select a HoMM3 Complete, HoMM3 HD, or compatible installation folder.";
                nextButton.Text = "Next";
                pageHost.Controls.Add(BuildHomm3Page());
                break;
            case WizardStep.Review:
                titleLabel.Text = "Review and run";
                subtitleLabel.Text = "Confirm the choices below. The next click starts the operation.";
                nextButton.Text = GetRunButtonText();
                pageHost.Controls.Add(BuildReviewPage());
                break;
            case WizardStep.Progress:
                titleLabel.Text = "Working";
                subtitleLabel.Text = "If this installer needs the mod payload, it downloads it from GitHub Releases first. Do not close this window until the operation finishes.";
                nextButton.Text = GetRunButtonText();
                pageHost.Controls.Add(BuildProgressPage());
                break;
        }
    }

    private Control BuildOperationPage()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewRadioRow(installRadio, "Create a clean Golden Era copy from the pinned Steam depot and install the mod."));
        panel.Controls.Add(NewRadioRow(updateRadio, "Refresh the mod payload in a copy that was already installed by this installer."));
        panel.Controls.Add(NewRadioRow(repairRadio, "Rebuild a target copy from the pinned Steam depot, then reinstall the mod payload."));
        panel.Controls.Add(NewRadioRow(uninstallRadio, "Delete an existing Golden Era target copy created for this mod."));
        return panel;
    }

    private Control BuildSourcePage()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewInfoLabel("In Steam, open the console and run this command:"));
        panel.Controls.Add(NewPathRow(depotCommandBox,
            ("Open Steam Console", OpenSteamConsole),
            ("Copy Command", () => CopyText(depotCommandBox.Text, "Steam depot command"))));
        panel.Controls.Add(NewInfoLabel("After Steam says the download is complete, select the depot folder below."));
        panel.Controls.Add(NewPathRow(sourcePathBox,
            ("Find Download", DetectSteamDepot),
            ("Browse", BrowseSource),
            ("Copy Path", () => CopyText(sourcePathBox.Text, "Steam depot path"))));
        panel.Controls.Add(sourceStatusLabel);
        return panel;
    }

    private Control BuildTargetPage()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewInfoLabel(UsesSourceStep()
            ? "A separate modded copy keeps Steam's live install untouched."
            : "Pick the modded copy that already contains Golden Era."));
        panel.Controls.Add(NewPathRow(targetPathBox,
            ("Browse", BrowseTarget),
            ("Use Suggested", UseSuggestedTarget),
            ("Copy Path", () => CopyText(targetPathBox.Text, "target path"))));
        panel.Controls.Add(targetStatusLabel);
        return panel;
    }

    private Control BuildHomm3Page()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewInfoLabel("Select the folder that contains Heroes3.exe, HD_Launcher.exe, or another supported HoMM3 executable."));
        panel.Controls.Add(NewPathRow(homm3PathBox,
            ("Find", DetectHomm3),
            ("Browse", BrowseHomm3),
            ("Copy Path", () => CopyText(homm3PathBox.Text, "Heroes III path"))));
        panel.Controls.Add(homm3StatusLabel);
        return panel;
    }

    private Control BuildReviewPage()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewReviewLabel(BuildReviewText()));
        return panel;
    }

    private Control BuildProgressPage()
    {
        var panel = NewPagePanel();
        panel.Controls.Add(NewInfoLabel(
            "Status and download progress appear in the bar and log below. A first-time install may download about 4 GB from GitHub."));
        return panel;
    }

    private static FlowLayoutPanel NewPagePanel()
    {
        return new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false
        };
    }

    private static Control NewRadioRow(RadioButton radio, string description)
    {
        var panel = new TableLayoutPanel { AutoSize = true, Dock = DockStyle.Top, ColumnCount = 1, Margin = new Padding(0, 0, 0, 14) };
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        panel.Controls.Add(radio, 0, 0);
        panel.Controls.Add(NewInfoLabel(description), 0, 1);
        return panel;
    }

    private static Label NewInfoLabel(string text)
    {
        return new Label
        {
            Text = text,
            AutoSize = true,
            MaximumSize = new Size(860, 0),
            Margin = new Padding(0, 4, 0, 8)
        };
    }

    private static Label NewReviewLabel(string text)
    {
        var label = NewInfoLabel(text);
        label.Font = new Font("Segoe UI", 10F);
        label.Margin = new Padding(0, 8, 0, 8);
        return label;
    }

    private static Control NewPathRow(TextBox box, params (string Text, Action Handler)[] buttons)
    {
        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            ColumnCount = buttons.Length + 1,
            Margin = new Padding(0, 0, 0, 10)
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
        box.MinimumSize = new Size(460, 30);
        panel.Controls.Add(box, 0, 0);

        for (var i = 0; i < buttons.Length; i++)
        {
            var button = new Button { Text = buttons[i].Text, AutoSize = true, Height = 32, Margin = new Padding(8, 0, 0, 0) };
            var handler = buttons[i].Handler;
            button.Click += (_, _) => handler();
            panel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            panel.Controls.Add(button, i + 1, 0);
        }

        return panel;
    }

    private async Task MoveNextOrRunAsync()
    {
        try
        {
            if (currentStep == WizardStep.Operation)
            {
                currentStep = UsesSourceStep() ? WizardStep.Source : WizardStep.Target;
            }
            else if (currentStep == WizardStep.Source)
            {
                ValidateSourceStep();
                currentStep = WizardStep.Target;
            }
            else if (currentStep == WizardStep.Target)
            {
                ValidateTargetStep();
                currentStep = UsesHomm3Step() ? WizardStep.Homm3 : WizardStep.Review;
                if (currentStep == WizardStep.Homm3)
                {
                    DetectHomm3IfEmpty();
                }
            }
            else if (currentStep == WizardStep.Homm3)
            {
                ValidateHomm3Step();
                currentStep = WizardStep.Review;
            }
            else if (currentStep == WizardStep.Review)
            {
                await RunSelectedOperationAsync();
                return;
            }

            RenderStep();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Golden Era Installer", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void MoveBack()
    {
        currentStep = currentStep switch
        {
            WizardStep.Source => WizardStep.Operation,
            WizardStep.Target => UsesSourceStep() ? WizardStep.Source : WizardStep.Operation,
            WizardStep.Homm3 => WizardStep.Target,
            WizardStep.Review => UsesHomm3Step() ? WizardStep.Homm3 : WizardStep.Target,
            _ => WizardStep.Operation
        };
        RenderStep();
    }

    private async Task RunSelectedOperationAsync()
    {
        currentStep = WizardStep.Progress;
        RenderStep();
        backButton.Enabled = false;
        nextButton.Enabled = false;
        closeButton.Enabled = false;
        technicalLog.Clear();
        logBox.Clear();
        progressBar.Visible = true;
        progressBar.Style = ProgressBarStyle.Marquee;
        progressBar.Value = 0;
        progressStatusLabel.Text = "Starting...";
        AppendLog(GetOperationStartMessage());
        AppendLog("If the payload is not cached yet, the installer will download it from GitHub Releases now.");

        var request = new InstallRequest(
            GetOperation(),
            sourcePathBox.Text.Trim(),
            targetPathBox.Text.Trim(),
            homm3PathBox.Text.Trim(),
            false);

        try
        {
            await Task.Run(() => InstallerBackend.Run(request, CaptureTechnicalLog, ReportProgress));
            ReportProgress(InstallerProgress.OfBytes("Complete", GetOperationSuccessMessage(), 1, 1));
            AppendLog(GetOperationSuccessMessage());
            if (GetOperation() != InstallerOperation.Uninstall)
            {
                AppendLog("Launch the game from the mod folder you chose, not from Steam.");
                AppendLog("The first mod launch will take longer than normal.");
                MessageBox.Show(
                    this,
                    GetOperationSuccessMessage() + "\n\nLaunch HeroesOldenEra.exe from the mod folder you chose, not from Steam.\n\nThe first mod launch will take longer than normal while caches are prepared.",
                    "Golden Era Installer",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }

            subtitleLabel.Text = "Complete. You can close the installer.";
            closeButton.Enabled = true;
        }
        catch (Exception ex)
        {
            AppendLog("Golden Era could not finish.");
            AppendLog(ex.Message);
            if (technicalLog.Count > 0)
            {
                AppendLog("Technical details:");
                foreach (var line in technicalLog)
                {
                    AppendLog(line);
                }
            }

            progressStatusLabel.Text = "Failed.";
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Value = 0;
            currentStep = WizardStep.Review;
            RenderStep();
            subtitleLabel.Text = "The operation failed. Review the log below, then adjust the choices and try again.";
            backButton.Enabled = true;
            nextButton.Enabled = true;
            closeButton.Enabled = true;
        }
    }

    private void ValidateSourceStep()
    {
        var summary = InstallerBackend.ValidateCompatibleSteamDepot(sourcePathBox.Text.Trim());
        sourceStatusLabel.Text = summary;
        AppendLog("Compatible Olden Era source selected.");
        UseSuggestedTarget();
    }

    private void ValidateTargetStep()
    {
        if (string.IsNullOrWhiteSpace(targetPathBox.Text))
        {
            throw new InvalidOperationException("Choose a target folder before continuing.");
        }

        targetStatusLabel.Text = "Target selected: " + targetPathBox.Text.Trim();
    }

    private void ValidateHomm3Step()
    {
        if (!InstallerBackend.IsValidHomm3Root(homm3PathBox.Text.Trim()))
        {
            throw new InvalidOperationException("The selected HoMM3 folder does not look like a supported Heroes III install.");
        }

        homm3StatusLabel.Text = "HoMM3 folder selected: " + homm3PathBox.Text.Trim();
    }

    private void DetectSteamDepot()
    {
        if (InstallerBackend.TryFindCompatibleSteamDepot(out var path, out var summary))
        {
            sourcePathBox.Text = path;
            sourceStatusLabel.Text = summary;
            AppendLog("Compatible Olden Era source found.");
            UseSuggestedTarget();
        }
        else
        {
            sourceStatusLabel.Text = summary;
            AppendLog("Compatible Olden Era source was not found yet.");
        }
    }

    private void BrowseSource()
    {
        using var dialog = new FolderBrowserDialog { Description = "Select the June 4 Steam depot folder" };
        if (Directory.Exists(sourcePathBox.Text))
        {
            dialog.SelectedPath = sourcePathBox.Text;
        }

        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            sourcePathBox.Text = dialog.SelectedPath;
        }
    }

    private void BrowseTarget()
    {
        using var dialog = new FolderBrowserDialog { Description = "Select the Golden Era target folder" };
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
        using var dialog = new FolderBrowserDialog { Description = "Select your Heroes III folder" };
        if (Directory.Exists(homm3PathBox.Text))
        {
            dialog.SelectedPath = homm3PathBox.Text;
        }

        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            homm3PathBox.Text = dialog.SelectedPath;
        }
    }

    private void UseSuggestedTarget()
    {
        var suggested = InstallerBackend.GetPreferredTargetRoot(sourcePathBox.Text.Trim());
        if (string.IsNullOrWhiteSpace(targetPathBox.Text) || targetPathBox.Text == lastAutoTarget)
        {
            targetPathBox.Text = suggested;
            lastAutoTarget = suggested;
        }
    }

    private void DetectHomm3()
    {
        DetectHomm3IfEmpty(force: true);
    }

    private void DetectHomm3IfEmpty(bool force = false)
    {
        if (!force && !string.IsNullOrWhiteSpace(homm3PathBox.Text))
        {
            return;
        }

        var detected = FindFirstValidHomm3Root();
        if (string.IsNullOrWhiteSpace(detected))
        {
            homm3StatusLabel.Text = "Heroes III folder was not found automatically. Use Browse to select it.";
            AppendLog("Heroes III folder was not found automatically.");
            return;
        }

        homm3PathBox.Text = detected;
        homm3StatusLabel.Text = "Heroes III folder found: " + detected;
        AppendLog("Heroes III folder found.");
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

    private static void AddCandidate(List<string> candidates, string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var expanded = Environment.ExpandEnvironmentVariables(path);
        if (!candidates.Any(c => string.Equals(c, expanded, StringComparison.OrdinalIgnoreCase)))
        {
            candidates.Add(expanded);
        }
    }
    private static void OpenSteamConsole()
    {
        Process.Start(new ProcessStartInfo(InstallerBackend.CompatibleSteamConsoleUri) { UseShellExecute = true });
    }

    private void CopyText(string text, string label)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }

        Clipboard.SetText(text);
        AppendLog("Copied " + label + ".");
    }

    private void CaptureTechnicalLog(string message)
    {
        lock (technicalLog)
        {
            technicalLog.Add(message);
        }

        AppendLog(message);
    }

    private void ReportProgress(InstallerProgress progress)
    {
        if (InvokeRequired)
        {
            BeginInvoke(new Action<InstallerProgress>(ReportProgress), progress);
            return;
        }

        progressBar.Visible = true;
        if (progress.FractionComplete is double fraction)
        {
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Value = Math.Clamp((int)Math.Round(fraction * progressBar.Maximum), progressBar.Minimum, progressBar.Maximum);
        }
        else
        {
            progressBar.Style = ProgressBarStyle.Marquee;
        }

        if (progress.BytesCompleted is long done && progress.BytesTotal is long total && total > 0)
        {
            progressStatusLabel.Text =
                $"{progress.Phase}: {progress.Detail} ({done / (1024d * 1024d):0.0} / {total / (1024d * 1024d):0.0} MB)";
        }
        else
        {
            progressStatusLabel.Text = $"{progress.Phase}: {progress.Detail}";
        }
    }

    private void AppendLog(string message)
    {
        if (InvokeRequired)
        {
            BeginInvoke(new Action<string>(AppendLog), message);
            return;
        }

        logBox.AppendText("[" + DateTime.Now.ToString("HH:mm:ss") + "] " + message + Environment.NewLine);
    }

    private string GetOperationStartMessage()
    {
        return GetOperation() switch
        {
            InstallerOperation.Update => "Updating Golden Era...",
            InstallerOperation.Repair => "Repairing Golden Era...",
            InstallerOperation.Uninstall => "Removing Golden Era...",
            _ => "Installing Golden Era..."
        };
    }

    private string GetOperationSuccessMessage()
    {
        return GetOperation() switch
        {
            InstallerOperation.Update => "Golden Era was updated successfully.",
            InstallerOperation.Repair => "Golden Era was repaired successfully.",
            InstallerOperation.Uninstall => "Golden Era was removed successfully.",
            _ => "Golden Era was installed successfully."
        };
    }
    private string BuildReviewText()
    {
        var operation = GetOperation();
        var lines = new List<string>
        {
            "Operation: " + operation
        };

        if (UsesSourceStep())
        {
            lines.Add("Steam source: " + sourcePathBox.Text.Trim());
        }

        lines.Add("Target copy: " + targetPathBox.Text.Trim());

        if (UsesHomm3Step())
        {
            lines.Add("HoMM3 folder: " + homm3PathBox.Text.Trim());
        }

        if (UsesSourceStep())
        {
            lines.Add("");
            lines.Add("Pinned depot command:");
            lines.Add(InstallerBackend.CompatibleSteamDepotCommand);
        }

        lines.Add("");
        lines.Add("When you continue, the installer prepares the mod payload first. If it is not already cached, it downloads about 4 GB from this version's GitHub Release, then installs.");

        return string.Join(Environment.NewLine, lines);
    }

    private InstallerOperation GetOperation()
    {
        if (updateRadio.Checked) return InstallerOperation.Update;
        if (repairRadio.Checked) return InstallerOperation.Repair;
        if (uninstallRadio.Checked) return InstallerOperation.Uninstall;
        return InstallerOperation.Install;
    }

    private bool UsesSourceStep()
    {
        var operation = GetOperation();
        return operation is InstallerOperation.Install or InstallerOperation.Repair;
    }

    private bool UsesHomm3Step()
    {
        var operation = GetOperation();
        return operation is InstallerOperation.Install or InstallerOperation.Repair;
    }

    private string GetRunButtonText()
    {
        return GetOperation() switch
        {
            InstallerOperation.Update => "Update",
            InstallerOperation.Repair => "Repair",
            InstallerOperation.Uninstall => "Uninstall",
            _ => "Install"
        };
    }
}
