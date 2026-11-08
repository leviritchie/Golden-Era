using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text.Json;
using System.Windows.Forms;

namespace OfflineLauncher;

internal sealed class MainForm : Form
{
	private readonly TextBox _gameRootTextBox = new() { Dock = DockStyle.Fill, ReadOnly = true };
	private readonly ComboBox _modeComboBox = CreateDropDown();
	private readonly ComboBox _mapComboBox = CreateDropDown();
	private readonly ComboBox _difficultyComboBox = CreateDropDown();
	private readonly ComboBox _playerOneFactionComboBox = CreateDropDown();
	private readonly ComboBox _playerOneHeroComboBox = CreateDropDown();
	private readonly ComboBox _playerTwoFactionComboBox = CreateDropDown();
	private readonly ComboBox _playerTwoHeroComboBox = CreateDropDown();
	private readonly CheckBox _autoLaunchCheckBox = new()
	{
		AutoSize = true,
		Enabled = false,
		Text = "Auto-start at main menu (temporarily disabled)"
	};
	private readonly GroupBox _playerTwoGroupBox = new() { Dock = DockStyle.Top, AutoSize = true };
	private readonly Label _statusLabel = new() { Dock = DockStyle.Top, AutoSize = true, ForeColor = Color.DarkSlateGray };

	private GameCatalog? _catalog;

	internal MainForm()
	{
		Text = "HeroesOE Offline Launcher";
		StartPosition = FormStartPosition.CenterScreen;
		FormBorderStyle = FormBorderStyle.FixedDialog;
		MaximizeBox = false;
		MinimizeBox = false;
		ClientSize = new Size(760, 520);

		BuildLayout();
		WireEvents();
		LoadModeChoices();
		TryAutoDetectGameRoot();
	}

	private void BuildLayout()
	{
		var rootPanel = new TableLayoutPanel
		{
			Dock = DockStyle.Fill,
			AutoSize = true,
			ColumnCount = 1,
			RowCount = 6,
			Padding = new Padding(12)
		};

		var noteLabel = new Label
		{
			Dock = DockStyle.Top,
			AutoSize = true,
			Text = "Configure the match here, launch the game, and use Single Player -> New Game. The earlier auto-start path is disabled for stability."
		};

		var gameRootGroup = new GroupBox
		{
			Text = "Game Folder",
			Dock = DockStyle.Top,
			AutoSize = true
		};
		gameRootGroup.Controls.Add(BuildGameRootLayout());

		var matchGroup = new GroupBox
		{
			Text = "Match Setup",
			Dock = DockStyle.Top,
			AutoSize = true
		};
		matchGroup.Controls.Add(BuildMatchLayout());

		var playerOneGroup = new GroupBox
		{
			Text = "Player 1",
			Dock = DockStyle.Top,
			AutoSize = true
		};
		playerOneGroup.Controls.Add(BuildSideLayout(_playerOneFactionComboBox, _playerOneHeroComboBox));

		_playerTwoGroupBox.Text = "AI Opponent";
		_playerTwoGroupBox.Controls.Add(BuildSideLayout(_playerTwoFactionComboBox, _playerTwoHeroComboBox));

		var buttonPanel = new FlowLayoutPanel
		{
			Dock = DockStyle.Top,
			AutoSize = true,
			FlowDirection = FlowDirection.LeftToRight
		};

		var saveButton = new Button { Text = "Save Config", AutoSize = true };
		saveButton.Click += (_, _) => SaveConfig(showMessage: true);

		var launchButton = new Button { Text = "Save && Launch Game", AutoSize = true };
		launchButton.Click += (_, _) => LaunchGame();

		buttonPanel.Controls.Add(saveButton);
		buttonPanel.Controls.Add(launchButton);

		rootPanel.Controls.Add(noteLabel);
		rootPanel.Controls.Add(gameRootGroup);
		rootPanel.Controls.Add(matchGroup);
		rootPanel.Controls.Add(playerOneGroup);
		rootPanel.Controls.Add(_playerTwoGroupBox);
		rootPanel.Controls.Add(buttonPanel);
		rootPanel.Controls.Add(_statusLabel);

		Controls.Add(rootPanel);
	}

	private Control BuildGameRootLayout()
	{
		var layout = new TableLayoutPanel
		{
			Dock = DockStyle.Top,
			AutoSize = true,
			ColumnCount = 3,
			Padding = new Padding(8)
		};
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

		var browseButton = new Button { Text = "Browse...", AutoSize = true };
		browseButton.Click += (_, _) => BrowseForGameRoot();

		var reloadButton = new Button { Text = "Reload Data", AutoSize = true };
		reloadButton.Click += (_, _) => LoadCatalogForSelectedRoot();

		layout.Controls.Add(_gameRootTextBox, 0, 0);
		layout.Controls.Add(browseButton, 1, 0);
		layout.Controls.Add(reloadButton, 2, 0);
		return layout;
	}

	private Control BuildMatchLayout()
	{
		var layout = new TableLayoutPanel
		{
			Dock = DockStyle.Top,
			AutoSize = true,
			ColumnCount = 2,
			Padding = new Padding(8)
		};
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));

		AddLabeledControl(layout, 0, "Mode", _modeComboBox);
		AddLabeledControl(layout, 1, "Map", _mapComboBox);
		AddLabeledControl(layout, 2, "Difficulty", _difficultyComboBox);
		layout.Controls.Add(_autoLaunchCheckBox, 1, 3);
		return layout;
	}

	private static Control BuildSideLayout(ComboBox factionComboBox, ComboBox heroComboBox)
	{
		var layout = new TableLayoutPanel
		{
			Dock = DockStyle.Top,
			AutoSize = true,
			ColumnCount = 2,
			Padding = new Padding(8)
		};
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
		layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f));

		AddLabeledControl(layout, 0, "Faction", factionComboBox);
		AddLabeledControl(layout, 1, "Hero", heroComboBox);
		return layout;
	}

	private static void AddLabeledControl(TableLayoutPanel layout, int row, string labelText, Control control)
	{
		while (layout.RowCount <= row)
		{
			layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
			layout.RowCount++;
		}

		var label = new Label
		{
			Text = labelText,
			TextAlign = ContentAlignment.MiddleLeft,
			Anchor = AnchorStyles.Left,
			AutoSize = true,
			Margin = new Padding(0, 7, 8, 7)
		};

		control.Dock = DockStyle.Fill;
		layout.Controls.Add(label, 0, row);
		layout.Controls.Add(control, 1, row);
	}

	private void WireEvents()
	{
		_modeComboBox.SelectedIndexChanged += (_, _) =>
		{
			UpdateModeLabels();
			RefreshMapOptions();
		};
		_playerOneFactionComboBox.SelectedIndexChanged += (_, _) => UpdateHeroOptions(_playerOneFactionComboBox, _playerOneHeroComboBox);
		_playerTwoFactionComboBox.SelectedIndexChanged += (_, _) => UpdateHeroOptions(_playerTwoFactionComboBox, _playerTwoHeroComboBox);
	}

	private void LoadModeChoices()
	{
		_modeComboBox.Items.Clear();
		_modeComboBox.Items.Add("SinglePlayer");
		_modeComboBox.Items.Add("Hotseat");
		_modeComboBox.SelectedIndex = 0;
	}

	private void TryAutoDetectGameRoot()
	{
		var directory = new DirectoryInfo(AppContext.BaseDirectory);
		while (directory != null)
		{
			if (File.Exists(Path.Combine(directory.FullName, "HeroesOE.exe")) &&
				Directory.Exists(Path.Combine(directory.FullName, "HeroesOE_Data")))
			{
				_gameRootTextBox.Text = directory.FullName;
				LoadCatalogForSelectedRoot();
				return;
			}

			directory = directory.Parent;
		}

		SetStatus("Select the game folder to load factions, heroes, and map templates.");
	}

	private void BrowseForGameRoot()
	{
		using var dialog = new FolderBrowserDialog
		{
			Description = "Select the Heroes of Might & Magic Olden Era Playtest folder.",
			SelectedPath = string.IsNullOrWhiteSpace(_gameRootTextBox.Text) ? AppContext.BaseDirectory : _gameRootTextBox.Text
		};

		if (dialog.ShowDialog(this) != DialogResult.OK)
		{
			return;
		}

		_gameRootTextBox.Text = dialog.SelectedPath;
		LoadCatalogForSelectedRoot();
	}

	private void LoadCatalogForSelectedRoot()
	{
		try
		{
			var root = GetValidatedGameRoot();
			_catalog = GameCatalogLoader.Load(root);
			PopulateControlsFromCatalog(_catalog);
			LoadExistingConfig(root);
			SetStatus($"Loaded {_catalog.Fractions.Count} factions, {_catalog.MapTemplates.Count} map templates, and {_catalog.Difficulties.Count} difficulty presets.");
		}
		catch (Exception ex)
		{
			_catalog = null;
			SetStatus(ex.Message, isError: true);
		}
	}

	private string GetValidatedGameRoot()
	{
		var root = _gameRootTextBox.Text.Trim();
		if (string.IsNullOrWhiteSpace(root))
		{
			throw new InvalidOperationException("Choose the game folder first.");
		}

		if (!File.Exists(Path.Combine(root, "HeroesOE.exe")))
		{
			throw new FileNotFoundException("HeroesOE.exe was not found in the selected folder.");
		}

		return root;
	}

	private void PopulateControlsFromCatalog(GameCatalog catalog)
	{
		_difficultyComboBox.Items.Clear();
		foreach (var difficulty in catalog.Difficulties)
		{
			_difficultyComboBox.Items.Add(difficulty);
		}

		PopulateFactionCombo(_playerOneFactionComboBox, catalog.Fractions);
		PopulateFactionCombo(_playerTwoFactionComboBox, catalog.Fractions);

		if (_difficultyComboBox.Items.Count > 0)
		{
			_difficultyComboBox.SelectedIndex = _difficultyComboBox.Items.Count - 1;
		}

		_playerOneFactionComboBox.SelectedIndex = 0;
		_playerTwoFactionComboBox.SelectedIndex = 0;
		UpdateModeLabels();
		RefreshMapOptions();
	}

	private static void PopulateFactionCombo(ComboBox comboBox, IEnumerable<string> fractions)
	{
		comboBox.Items.Clear();
		comboBox.Items.Add("random");
		foreach (var fraction in fractions)
		{
			comboBox.Items.Add(fraction);
		}
		comboBox.SelectedIndex = 0;
	}

	private void UpdateHeroOptions(ComboBox factionComboBox, ComboBox heroComboBox)
	{
		heroComboBox.Items.Clear();
		heroComboBox.Items.Add("random");

		var selectedFaction = factionComboBox.SelectedItem as string;
		var factionIsRandom = string.IsNullOrWhiteSpace(selectedFaction) || string.Equals(selectedFaction, "random", StringComparison.OrdinalIgnoreCase);
		if (!factionIsRandom && _catalog != null && _catalog.HeroesByFraction.TryGetValue(selectedFaction!, out var heroes))
		{
			foreach (var hero in heroes)
			{
				heroComboBox.Items.Add(hero);
			}
		}

		heroComboBox.SelectedIndex = 0;
		heroComboBox.Enabled = !factionIsRandom;
	}

	private void UpdateModeLabels()
	{
		var isHotseat = string.Equals(_modeComboBox.SelectedItem as string, "Hotseat", StringComparison.OrdinalIgnoreCase);
		_playerTwoGroupBox.Text = isHotseat ? "Player 2" : "AI Opponent";
	}

	private void RefreshMapOptions()
	{
		if (_catalog == null)
		{
			return;
		}

		var selectedMap = _mapComboBox.SelectedItem as string;
		var isHotseat = string.Equals(_modeComboBox.SelectedItem as string, "Hotseat", StringComparison.OrdinalIgnoreCase);
		_mapComboBox.Items.Clear();

		foreach (var template in _catalog.MapTemplates)
		{
			_mapComboBox.Items.Add(template);
		}

		if (_mapComboBox.Items.Count == 0)
		{
			return;
		}

		SetComboSelection(_mapComboBox, selectedMap);
		if (_mapComboBox.SelectedIndex < 0)
		{
			SetComboSelection(_mapComboBox, isHotseat ? "Jebus Outcast" : "Arcade");
		}

		if (_mapComboBox.SelectedIndex < 0)
		{
			_mapComboBox.SelectedIndex = 0;
		}
	}

	private void LoadExistingConfig(string gameRoot)
	{
		var path = GameCatalogLoader.GetConfigPath(gameRoot);
		if (!File.Exists(path))
		{
			_autoLaunchCheckBox.Checked = false;
			return;
		}

		try
		{
			var json = File.ReadAllText(path);
			var config = JsonSerializer.Deserialize<LauncherConfig>(json);
			if (config == null)
			{
				return;
			}

			SetComboSelection(_modeComboBox, config.MatchMode);
			SetComboSelection(_mapComboBox, config.MapTemplate);
			SetDifficultySelection(config.DifficultyIndex);
			SetComboSelection(_playerOneFactionComboBox, config.PlayerOneFaction);
			UpdateHeroOptions(_playerOneFactionComboBox, _playerOneHeroComboBox);
			SetComboSelection(_playerOneHeroComboBox, config.PlayerOneHero);
			SetComboSelection(_playerTwoFactionComboBox, config.PlayerTwoFaction);
			UpdateHeroOptions(_playerTwoFactionComboBox, _playerTwoHeroComboBox);
			SetComboSelection(_playerTwoHeroComboBox, config.PlayerTwoHero);
			_autoLaunchCheckBox.Checked = false;
			UpdateModeLabels();
		}
		catch (Exception ex)
		{
			SetStatus($"Failed to load existing config: {ex.Message}", isError: true);
		}
	}

	private void SetDifficultySelection(int difficultyIndex)
	{
		for (var i = 0; i < _difficultyComboBox.Items.Count; i++)
		{
			if (_difficultyComboBox.Items[i] is DifficultyOption option && option.Index == difficultyIndex)
			{
				_difficultyComboBox.SelectedIndex = i;
				return;
			}
		}
	}

	private static void SetComboSelection(ComboBox comboBox, string? value)
	{
		if (string.IsNullOrWhiteSpace(value))
		{
			return;
		}

		for (var i = 0; i < comboBox.Items.Count; i++)
		{
			if (string.Equals(comboBox.Items[i]?.ToString(), value, StringComparison.OrdinalIgnoreCase))
			{
				comboBox.SelectedIndex = i;
				return;
			}
		}
	}

	private bool SaveConfig(bool showMessage)
	{
		try
		{
			if (_catalog == null)
			{
				throw new InvalidOperationException("Load the game data first.");
			}

			var root = GetValidatedGameRoot();
			var config = new LauncherConfig
			{
				MatchMode = _modeComboBox.SelectedItem as string ?? "SinglePlayer",
				MapTemplate = _mapComboBox.SelectedItem as string ?? "Jebus Outcast",
				DifficultyIndex = (_difficultyComboBox.SelectedItem as DifficultyOption)?.Index ?? 0,
				PlayerOneFaction = _playerOneFactionComboBox.SelectedItem as string ?? "random",
				PlayerOneHero = _playerOneHeroComboBox.SelectedItem as string ?? "random",
				PlayerTwoFaction = _playerTwoFactionComboBox.SelectedItem as string ?? "random",
				PlayerTwoHero = _playerTwoHeroComboBox.SelectedItem as string ?? "random",
				AutoLaunchOnMenu = false
			};

			if (string.Equals(config.PlayerOneFaction, "random", StringComparison.OrdinalIgnoreCase))
			{
				config.PlayerOneHero = "random";
			}

			if (string.Equals(config.PlayerTwoFaction, "random", StringComparison.OrdinalIgnoreCase))
			{
				config.PlayerTwoHero = "random";
			}

			var json = JsonSerializer.Serialize(config, new JsonSerializerOptions { WriteIndented = true });
			File.WriteAllText(GameCatalogLoader.GetConfigPath(root), json);
			SetStatus($"Saved config to {GameCatalogLoader.ConfigFileName}.");
			if (showMessage)
			{
				MessageBox.Show(this, "Launcher config saved.", "Offline Launcher", MessageBoxButtons.OK, MessageBoxIcon.Information);
			}

			return true;
		}
		catch (Exception ex)
		{
			SetStatus(ex.Message, isError: true);
			if (showMessage)
			{
				MessageBox.Show(this, ex.Message, "Offline Launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
			}

			return false;
		}
	}

	private void LaunchGame()
	{
		if (!SaveConfig(showMessage: false))
		{
			return;
		}

		try
		{
			var root = GetValidatedGameRoot();
			var gameExe = Path.Combine(root, "HeroesOE.exe");
			Process.Start(new ProcessStartInfo
			{
				FileName = gameExe,
				WorkingDirectory = root,
				UseShellExecute = true
			});
			SetStatus("Game launched. If auto-start is off, use Single Player -> New Game in the main menu.");
		}
		catch (Exception ex)
		{
			SetStatus($"Failed to launch the game: {ex.Message}", isError: true);
		}
	}

	private void SetStatus(string message, bool isError = false)
	{
		_statusLabel.Text = message;
		_statusLabel.ForeColor = isError ? Color.DarkRed : Color.DarkSlateGray;
	}

	private static ComboBox CreateDropDown()
	{
		return new ComboBox
		{
			DropDownStyle = ComboBoxStyle.DropDownList,
			MaxDropDownItems = 20
		};
	}
}
