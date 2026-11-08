using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Text;
using System.Windows.Forms;
using OldenAiSim;

namespace OldenAiSim.Gui
{
	internal sealed class MainForm : Form
	{
		private AdventureSimState _editState;
		private AdventureSimStepper _session;
		private AdventureSimKnobs _knobs = new AdventureSimKnobs { TimeBudgetMs = 200 };
		private readonly MapPanel _map;
		private readonly ListBox _candidates;
		private readonly ListBox _biases;
		private readonly TextBox _worldBox;
		private readonly TextBox _actionBox;
		private readonly TextBox _fightBox;
		private ComboBox _scenario;
		private NumericUpDown _depth;
		private NumericUpDown _width;
		private NumericUpDown _budget;
		private NumericUpDown _winRatio;
		private CheckBox _terrainCosts;
		private CheckBox _multiHero;
		private Label _status;
		private ComboBox _paintMode;
		private Button _btnStepBack;
		private Button _btnStepFwd;
		private Button _btnRunEnd;
		private Button _btnReset;
		private int _selectedNode = -1;

		public MainForm()
		{
			Text = "Olden AI Sim Workbench (step-debug)";
			Width = 1400;
			Height = 900;
			StartPosition = FormStartPosition.CenterScreen;
			MinimumSize = new Size(1100, 700);

			_map = new MapPanel { Dock = DockStyle.Fill };
			_map.AllowPaint = () => _session == null || _session.CurrentIndex < 0;
			_map.GetKnobs = () => _knobs;
			_map.NodeClicked += OnNodeClicked;
			_map.NodePainted += OnNodePainted;

			_candidates = new ListBox { Dock = DockStyle.Fill, Font = new Font(FontFamily.GenericMonospace, 9f) };
			_biases = new ListBox { Dock = DockStyle.Fill, Font = new Font(FontFamily.GenericMonospace, 9f) };
			_worldBox = MakeReadonlyBox();
			_actionBox = MakeReadonlyBox();
			_fightBox = MakeReadonlyBox();

			var inspectTabs = new TabControl { Dock = DockStyle.Fill };
			inspectTabs.TabPages.Add(MakeTab("World", _worldBox));
			inspectTabs.TabPages.Add(MakeTab("Action", _actionBox));
			inspectTabs.TabPages.Add(MakeTab("Candidates", _candidates));
			inspectTabs.TabPages.Add(MakeTab("Fight", _fightBox));
			inspectTabs.TabPages.Add(MakeTab("Biases", _biases));

			var mainSplit = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 860 };
			mainSplit.Panel1.Controls.Add(_map);
			mainSplit.Panel2.Controls.Add(inspectTabs);

			_btnReset = Btn("Reset", ResetSession);
			_btnStepBack = Btn("Step back", StepBack);
			_btnStepFwd = Btn("Step forward", StepForward);
			_btnRunEnd = Btn("Run to end", RunToEnd);

			Controls.Add(mainSplit);
			Controls.Add(BuildToolbar());
			_status = new Label
			{
				Dock = DockStyle.Bottom,
				Height = 28,
				TextAlign = ContentAlignment.MiddleLeft,
				Padding = new Padding(8, 0, 0, 0),
			};
			Controls.Add(_status);

			LoadScenario("frontier_hold");
		}

		private static TextBox MakeReadonlyBox()
		{
			return new TextBox
			{
				Dock = DockStyle.Fill,
				Multiline = true,
				ReadOnly = true,
				ScrollBars = ScrollBars.Vertical,
				Font = new Font(FontFamily.GenericMonospace, 9f),
			};
		}

		private static TabPage MakeTab(string title, Control child)
		{
			var page = new TabPage(title);
			child.Dock = DockStyle.Fill;
			page.Controls.Add(child);
			return page;
		}

		private Control BuildToolbar()
		{
			var panel = new FlowLayoutPanel
			{
				Dock = DockStyle.Top,
				Height = 100,
				Padding = new Padding(6),
				WrapContents = true,
			};

			_scenario = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 160 };
			foreach (var name in AdventureSimScenarios.Names)
				_scenario.Items.Add(name);
			_scenario.SelectedIndex = 0;
			_scenario.SelectedIndexChanged += (s, e) =>
			{
				if (_scenario.SelectedItem != null)
					LoadScenario(_scenario.SelectedItem.ToString());
			};

			_depth = Num(3, 1, 8);
			_width = Num(12, 1, 32);
			_budget = Num(200, 5, 2000);
			_winRatio = new NumericUpDown
			{
				DecimalPlaces = 2,
				Increment = 0.05M,
				Minimum = 0.5M,
				Maximum = 3M,
				Value = 1.15M,
				Width = 70,
			};
			_terrainCosts = new CheckBox { Text = "Terrain costs", Checked = true, AutoSize = true };
			_multiHero = new CheckBox { Text = "Multi-hero", Checked = true, AutoSize = true };
			_paintMode = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 120 };
			_paintMode.Items.AddRange(new object[]
			{
				"Select", "Toggle block", "Grass", "Sand", "Dirt", "Water", "Rock",
			});
			_paintMode.SelectedIndex = 0;

			panel.Controls.Add(Lbl("Scenario"));
			panel.Controls.Add(_scenario);
			panel.Controls.Add(Btn("Evaluate", StartEvaluate));
			panel.Controls.Add(_btnReset);
			panel.Controls.Add(_btnStepBack);
			panel.Controls.Add(_btnStepFwd);
			panel.Controls.Add(_btnRunEnd);
			panel.Controls.Add(Btn("Save…", SaveScenario));
			panel.Controls.Add(Btn("Load…", LoadScenarioFile));
			panel.Controls.Add(Lbl("Depth"));
			panel.Controls.Add(_depth);
			panel.Controls.Add(Lbl("Width"));
			panel.Controls.Add(_width);
			panel.Controls.Add(Lbl("Budget ms"));
			panel.Controls.Add(_budget);
			panel.Controls.Add(Lbl("Win ratio"));
			panel.Controls.Add(_winRatio);
			panel.Controls.Add(_terrainCosts);
			panel.Controls.Add(_multiHero);
			panel.Controls.Add(Lbl("Paint"));
			panel.Controls.Add(_paintMode);
			return panel;
		}

		private static Label Lbl(string text)
		{
			return new Label { Text = text, AutoSize = true, Padding = new Padding(6, 8, 0, 0) };
		}

		private static NumericUpDown Num(decimal value, decimal min, decimal max)
		{
			return new NumericUpDown { Minimum = min, Maximum = max, Value = value, Width = 60 };
		}

		private static Button Btn(string text, Action action)
		{
			var b = new Button { Text = text, AutoSize = true };
			b.Click += (s, e) => action();
			return b;
		}

		private void LoadScenario(string name)
		{
			_editState = AdventureSimScenarios.Create(name);
			_session = null;
			_map.SetBoard(_editState, null, null, null, -1);
			ClearInspectors();
			_worldBox.Text = "Loaded '" + name + "'. Click Evaluate, then Step forward.";
			RefreshStatus();
		}

		private void StartEvaluate()
		{
			if (_editState == null)
				return;
			SyncKnobs();
			_session = AdventureSimStepper.Run(_editState, _knobs);
			_session.Reset();
			RefreshFromSession();
			if (!_session.Result.Ok)
				_actionBox.Text = "FAIL: " + _session.Result.Error;
		}

		private void ResetSession()
		{
			if (_session != null)
				_session.Reset();
			RefreshFromSession();
		}

		private void StepForward()
		{
			if (_session == null)
			{
				MessageBox.Show(this, "Run Evaluate first.", "Step", MessageBoxButtons.OK, MessageBoxIcon.Information);
				return;
			}
			string err;
			if (!_session.TryStepForward(out err))
			{
				MessageBox.Show(this, err, "Step forward", MessageBoxButtons.OK, MessageBoxIcon.Warning);
				return;
			}
			RefreshFromSession();
		}

		private void StepBack()
		{
			if (_session == null)
				return;
			string err;
			if (!_session.TryStepBack(out err))
			{
				MessageBox.Show(this, err, "Step back", MessageBoxButtons.OK, MessageBoxIcon.Warning);
				return;
			}
			RefreshFromSession();
		}

		private void RunToEnd()
		{
			if (_session == null)
			{
				StartEvaluate();
				if (_session == null)
					return;
			}
			_session.RunToEnd();
			RefreshFromSession();
		}

		private void RefreshFromSession()
		{
			if (_session == null)
			{
				_map.SetBoard(_editState, null, null, null, -1);
				RefreshStatus();
				return;
			}

			var world = _session.CurrentWorld();
			var rec = _session.CurrentRecord();
			var result = _session.Result;
			List<int> path = null;
			Dictionary<int, int> reach = null;
			var preferredNode = -1;

			if (rec != null && rec.ActionKind == AdventureSimActionKind.MoveToOccupy && rec.FromNode >= 0)
			{
				path = AdventurePathfinder.ReconstructPath(
					_editState, _knobs, rec.FromNode, rec.ToNode, 50000,
					world.Occupancy, rec.TargetEntityId);
				var horizon = 5000;
				reach = AdventurePathfinder.ReachableCosts(
					_editState, _knobs, rec.FromNode, horizon, world.Occupancy, rec.TargetEntityId);
			}
			else if (_session.IsComplete && result.PreferredNode >= 0)
			{
				preferredNode = result.PreferredNode;
				reach = result.ReachOverlay;
			}

			_map.SetBoard(_editState, world, path, reach, preferredNode);
			FillWorld(world);
			FillAction(rec);
			FillCandidates(rec);
			FillFight(rec);
			FillBiases(result, _session.IsComplete);
			RefreshStatus();
		}

		private void FillWorld(AdventureSimWorldSnapshot world)
		{
			if (world == null)
			{
				_worldBox.Text = "";
				return;
			}
			var sb = new StringBuilder();
			sb.AppendLine("day=" + world.Day);
			sb.AppendLine("gold=" + world.Resources.Gold
				+ " wood=" + world.Resources.Wood
				+ " ore=" + world.Resources.Ore);
			sb.AppendLine("marks city=" + world.Marks.MarkedCity
				+ " hero=" + world.Marks.MarkedHero
				+ " obj=" + world.Marks.MarkedObject
				+ " node=" + world.Marks.MarkedNode);
			sb.AppendLine("heroes:");
			for (var i = 0; i < world.Heroes.Count; i++)
			{
				var h = world.Heroes[i];
				sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
					"  id={0} {1} node={2} mp={3}/{4} power={5}",
					h.HeroId, h.Name, h.Node, h.MovePoints, h.MaxMovePoints,
					AdventureFightEstimate.ArmyPower(h)));
			}
			sb.AppendLine("occupancy:");
			for (var i = 0; i < world.Occupancy.Count; i++)
			{
				var o = world.Occupancy[i];
				sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
					"  {0}:{1} node={2} alive={3} owner={4} gold={5} {6}",
					o.Kind, o.EntityId, o.Node, o.Alive, o.OwnerSide, o.GoldReward, o.Label));
			}
			if (world.Towns != null && world.Towns.Count > 0)
			{
				sb.AppendLine("towns:");
				for (var i = 0; i < world.Towns.Count; i++)
				{
					var t = world.Towns[i];
					sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
						"  id={0} buildings=[{1}] garrison={2} daily≈{3}",
						t.EntityId,
						t.Buildings == null ? "" : string.Join(",", t.Buildings),
						t.Garrison == null ? 0 : t.Garrison.Count,
						AdventureSimTownCatalog.DailyTownGold(t)));
				}
			}
			if (_selectedNode >= 0 && _editState != null)
			{
				AdventurePathfinder.XzOf(_selectedNode, _editState.SizeX, out var x, out var z);
				var terr = _editState.Terrain != null && _selectedNode < _editState.Terrain.Length
					? AdventureSimTerrain.Name(_editState.Terrain[_selectedNode]) : "?";
				var mp = AdventurePathfinder.CellCost(_editState, _knobs, _selectedNode);
				sb.AppendLine(string.Format(CultureInfo.InvariantCulture,
					"selected=({0},{1}) node={2} terrain={3} cellMp={4}",
					x, z, _selectedNode, terr, mp));
			}
			_worldBox.Text = sb.ToString();
		}

		private void FillAction(AdventureSimStepRecord rec)
		{
			if (rec == null)
			{
				_actionBox.Text = _session == null
					? ""
					: "index=-1 (initial world). Step forward to apply the first action.\n"
						+ "steps=" + _session.StepCount + "\n"
						+ (_session.Result.Diagnostics ?? "");
				return;
			}
			_actionBox.Text = string.Format(CultureInfo.InvariantCulture,
				"step {0}/{1}\nkind={2}\nhero={3}\n{4} -> {5}\npathCost={6}\nmp {7} -> {8}\ntarget={9}:{10}\ntown={11} build={12} unit={13}\nΔu={14:0.###} u={15:0.###}\n{16}",
				rec.Index + 1,
				_session.StepCount,
				rec.ActionKind,
				rec.HeroId,
				rec.FromNode,
				rec.ToNode,
				rec.PathCost,
				rec.MpBefore,
				rec.MpAfter,
				rec.TargetKind,
				rec.TargetEntityId,
				rec.TownEntityId,
				rec.BuildingId ?? "-",
				rec.UnitSid ?? "-",
				rec.UtilityDelta,
				rec.CumulativeUtility,
				rec.Note ?? "");
		}

		private void FillCandidates(AdventureSimStepRecord rec)
		{
			_candidates.Items.Clear();
			if (rec?.Candidates == null)
				return;
			for (var i = 0; i < rec.Candidates.Count; i++)
			{
				var c = rec.Candidates[i];
				_candidates.Items.Add(string.Format(CultureInfo.InvariantCulture,
					"{0} {1}:{2} u={3:0.#} cost={4} {5}{6}",
					c.Accepted ? "OK" : "NO",
					c.Kind,
					c.EntityId,
					c.Utility,
					c.PathCost,
					c.RequiresFight ? "FIGHT " : "",
					c.RejectReason ?? ""));
			}
		}

		private void FillFight(AdventureSimStepRecord rec)
		{
			if (rec?.Fight == null)
			{
				_fightBox.Text = "(no fight this step)";
				return;
			}
			var f = rec.Fight;
			_fightBox.Text = string.Format(CultureInfo.InvariantCulture,
				"PROVISIONAL fight estimate (not fda.bjeg)\npower={0} threat={1} ratio={2:0.00}\ncanWin={3} loss={4:0.00}\nheroMult={5:0.##} mobMult={6:0.##}\n{7}",
				f.Power, f.Threat, f.Ratio, f.CanWin, f.LossFraction,
				f.HeroPowerMultiplier, f.ValuesVsMobsMultiplier, f.Summary);
		}

		private void FillBiases(AdventureSimResult result, bool complete)
		{
			_biases.Items.Clear();
			if (!complete || result?.Biases == null)
			{
				_biases.Items.Add("(biases available after Run to end / final step)");
				return;
			}
			for (var i = 0; i < result.Biases.Count; i++)
			{
				var b = result.Biases[i];
				_biases.Items.Add(string.Format(CultureInfo.InvariantCulture,
					"{0}:{1} × {2:0.###}", b.TargetKind, b.TargetId, b.Multiplier));
			}
		}

		private void ClearInspectors()
		{
			_worldBox.Clear();
			_actionBox.Clear();
			_fightBox.Clear();
			_candidates.Items.Clear();
			_biases.Items.Clear();
		}

		private void SyncKnobs()
		{
			_knobs.BeamDepth = (int)_depth.Value;
			_knobs.BeamWidth = (int)_width.Value;
			_knobs.TimeBudgetMs = (int)_budget.Value;
			_knobs.WinPowerRatio = (float)_winRatio.Value;
			_knobs.UseTerrainCosts = _terrainCosts.Checked;
			_knobs.MultiHero = _multiHero.Checked;
		}

		private void SaveScenario()
		{
			using (var dlg = new SaveFileDialog
			{
				Filter = "AI sim scenario (*.aisim)|*.aisim|All files|*.*",
				FileName = (_editState.ScenarioName ?? "scenario") + ".aisim",
			})
			{
				if (dlg.ShowDialog(this) != DialogResult.OK)
					return;
				AdventureSimScenarioIo.Save(_editState, dlg.FileName);
				_status.Text = "Saved " + dlg.FileName;
			}
		}

		private void LoadScenarioFile()
		{
			using (var dlg = new OpenFileDialog
			{
				Filter = "AI sim scenario (*.aisim)|*.aisim|All files|*.*",
			})
			{
				if (dlg.ShowDialog(this) != DialogResult.OK)
					return;
				try
				{
					_editState = AdventureSimScenarioIo.Load(dlg.FileName);
					if (_editState.MoveCost == null)
						OldenTileMp.FillMoveCost(_editState);
				}
				catch (Exception ex)
				{
					MessageBox.Show(this, ex.Message, "Load failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
					return;
				}
				_session = null;
				_map.SetBoard(_editState, null, null, null, -1);
				ClearInspectors();
				_worldBox.Text = "Loaded " + dlg.FileName;
				RefreshStatus();
			}
		}

		private void OnNodeClicked(int node)
		{
			_selectedNode = node;
			if (_session != null)
				FillWorld(_session.CurrentWorld());
			RefreshStatus();
		}

		private void OnNodePainted(int node)
		{
			if (_editState == null || !AdventurePathfinder.InBounds(node, _editState))
				return;
			if (_session != null && _session.CurrentIndex >= 0)
			{
				MessageBox.Show(this, "Reset the session before painting (edit vs play fail-closed).", "Paint locked",
					MessageBoxButtons.OK, MessageBoxIcon.Warning);
				return;
			}
			var mode = _paintMode.SelectedItem as string ?? "Select";
			switch (mode)
			{
				case "Toggle block":
					_editState.Pathable[node] = !_editState.Pathable[node];
					_editState.Terrain[node] = _editState.Pathable[node]
						? AdventureSimTerrain.OldenGrass
						: AdventureSimTerrain.OldenRockBlocked;
					break;
				case "Grass":
					_editState.Terrain[node] = AdventureSimTerrain.OldenGrass;
					_editState.Pathable[node] = true;
					break;
				case "Sand":
					_editState.Terrain[node] = AdventureSimTerrain.OldenSand;
					_editState.Pathable[node] = true;
					break;
				case "Dirt":
					_editState.Terrain[node] = AdventureSimTerrain.OldenDirt;
					_editState.Pathable[node] = true;
					break;
				case "Water":
					_editState.Terrain[node] = AdventureSimTerrain.OldenWater;
					_editState.Pathable[node] = true;
					break;
				case "Rock":
					_editState.Terrain[node] = AdventureSimTerrain.OldenRockBlocked;
					_editState.Pathable[node] = false;
					break;
			}
			OldenTileMp.FillMoveCost(_editState);
			_map.Invalidate();
		}

		private void RefreshStatus()
		{
			if (_editState == null)
			{
				_status.Text = "No state";
				return;
			}
			AdventurePathfinder.XzOf(_selectedNode, _editState.SizeX, out var x, out var z);
			var stepInfo = _session == null
				? "no session"
				: string.Format(CultureInfo.InvariantCulture, "step {0}/{1}", _session.CurrentIndex + 1, _session.StepCount);
			_status.Text = string.Format(CultureInfo.InvariantCulture,
				"{0}  {1}x{2}  {3}  selected=({4},{5}) node={6}  preferred={7}",
				_editState.ScenarioName ?? "?",
				_editState.SizeX,
				_editState.SizeZ,
				stepInfo,
				x, z, _selectedNode,
				_session?.Result == null ? "-" : (_session.Result.PreferredKind + ":" + _session.Result.PreferredId));
		}
	}

	internal sealed class MapPanel : Panel
	{
		private AdventureSimState _board;
		private AdventureSimWorldSnapshot _world;
		private List<int> _path = new List<int>();
		private Dictionary<int, int> _reach;
		private int _preferredNode = -1;
		private readonly int _cell = 28;
		private readonly ToolTip _tip = new ToolTip
		{
			InitialDelay = 200,
			ReshowDelay = 100,
			AutoPopDelay = 20000,
			ShowAlways = true,
		};
		private int _hoverNode = -1;

		public event Action<int> NodeClicked;
		public event Action<int> NodePainted;
		public Func<bool> AllowPaint;
		public Func<AdventureSimKnobs> GetKnobs;

		public MapPanel()
		{
			DoubleBuffered = true;
			BackColor = Color.FromArgb(30, 34, 40);
			MouseDown += OnMouse;
			MouseMove += OnMouseMove;
			MouseLeave += (s, e) =>
			{
				_hoverNode = -1;
				_tip.Hide(this);
			};
		}

		public void SetBoard(
			AdventureSimState board,
			AdventureSimWorldSnapshot world,
			List<int> path,
			Dictionary<int, int> reach,
			int preferredNode)
		{
			_board = board;
			_world = world;
			_path = path ?? new List<int>();
			_reach = reach;
			_preferredNode = preferredNode;
			_hoverNode = -1;
			Invalidate();
		}

		private void OnMouse(object sender, MouseEventArgs e)
		{
			var node = HitTest(e.Location);
			if (node < 0)
				return;
			if (e.Button == MouseButtons.Left)
			{
				NodeClicked?.Invoke(node);
				if (AllowPaint == null || AllowPaint())
					NodePainted?.Invoke(node);
			}
		}

		private void OnMouseMove(object sender, MouseEventArgs e)
		{
			if (e.Button == MouseButtons.Left)
				PaintAt(e.Location);

			var node = HitTest(e.Location);
			if (node == _hoverNode)
				return;
			_hoverNode = node;
			if (node < 0 || _board == null)
			{
				_tip.SetToolTip(this, "");
				return;
			}
			_tip.SetToolTip(this, BuildHoverText(node));
		}

		private string BuildHoverText(int node)
		{
			AdventurePathfinder.XzOf(node, _board.SizeX, out var x, out var z);
			var knobs = GetKnobs != null ? GetKnobs() : new AdventureSimKnobs();
			var sb = new StringBuilder();
			sb.AppendFormat(CultureInfo.InvariantCulture, "({0},{1})  node={2}", x, z, node);

			var pathable = AdventurePathfinder.IsPathable(_board, node);
			sb.AppendLine();
			sb.Append(pathable ? "pathable" : "BLOCKED");

			if (_board.Terrain != null && node < _board.Terrain.Length)
			{
				var tid = _board.Terrain[node];
				sb.AppendFormat(CultureInfo.InvariantCulture, "  terrain={0} (id {1})",
					AdventureSimTerrain.Name(tid), tid);
			}

			var cellMp = AdventurePathfinder.CellCost(_board, knobs, node);
			sb.AppendLine();
			sb.AppendFormat(CultureInfo.InvariantCulture, "cellMp={0}", cellMp);
			if (_board.MoveCost != null && node < _board.MoveCost.Length)
				sb.AppendFormat(CultureInfo.InvariantCulture, "  MoveCost[{0}]={1}", node, _board.MoveCost[node]);
			if (_board.Road != null && node < _board.Road.Length && _board.Road[node] > 0)
				sb.AppendFormat(CultureInfo.InvariantCulture, "  roadId={0}", _board.Road[node]);

			if (_reach != null)
			{
				int reachCost;
				if (_reach.TryGetValue(node, out reachCost))
				{
					sb.AppendLine();
					sb.AppendFormat(CultureInfo.InvariantCulture, "reachCost={0}", reachCost);
				}
			}

			if (_board.Portals != null)
			{
				List<int> links;
				if (_board.Portals.TryGetValue(node, out links) && links != null && links.Count > 0)
				{
					sb.AppendLine();
					sb.Append("portal -> ");
					sb.Append(string.Join(", ", links));
				}
			}

			var heroes = _world?.Heroes ?? _board.Heroes;
			if (heroes != null)
			{
				for (var i = 0; i < heroes.Count; i++)
				{
					var h = heroes[i];
					if (h == null || h.Node != node)
						continue;
					sb.AppendLine();
					sb.AppendFormat(CultureInfo.InvariantCulture,
						"HERO id={0} {1}  mp={2}/{3}  power={4}",
						h.HeroId, h.Name ?? "", h.MovePoints, h.MaxMovePoints,
						AdventureFightEstimate.ArmyPower(h));
				}
			}

			var occ = _world?.Occupancy ?? _board.Occupancy;
			if (occ != null)
			{
				for (var i = 0; i < occ.Count; i++)
				{
					var o = occ[i];
					if (o == null || o.Node != node)
						continue;
					if (!o.Alive && o.Kind != AdventureSimTargetKind.Mine && o.Kind != AdventureSimTargetKind.Town)
						continue;
					sb.AppendLine();
					sb.AppendFormat(CultureInfo.InvariantCulture,
						"{0} id={1}  alive={2}  owner={3}  startValue={4}  gold={5}  {6}",
						o.Kind, o.EntityId, o.Alive, o.OwnerSide, o.StartValue, o.GoldReward,
						o.Label ?? "");
					if (o.Kind == AdventureSimTargetKind.Town)
					{
						var towns = _world?.Towns ?? _board.Towns;
						var town = AdventureSimTownLogic.Find(towns, o.EntityId);
						if (town != null)
						{
							sb.AppendLine();
							sb.AppendFormat(CultureInfo.InvariantCulture,
								"  buildings=[{0}] garrison={1} daily≈{2}",
								town.Buildings == null ? "" : string.Join(",", town.Buildings),
								town.Garrison == null ? 0 : town.Garrison.Count,
								AdventureSimTownCatalog.DailyTownGold(town));
						}
					}
				}
			}

			if (_path != null && _path.Contains(node))
			{
				sb.AppendLine();
				sb.Append("on active path");
			}
			if (node == _preferredNode)
			{
				sb.AppendLine();
				sb.Append("preferred target");
			}

			return sb.ToString();
		}

		private void PaintAt(Point p)
		{
			if (AllowPaint != null && !AllowPaint())
				return;
			var node = HitTest(p);
			if (node >= 0)
				NodePainted?.Invoke(node);
		}

		private int HitTest(Point p)
		{
			if (_board == null || _board.SizeX <= 0)
				return -1;
			var x = p.X / _cell;
			var z = p.Y / _cell;
			if (x < 0 || z < 0 || x >= _board.SizeX || z >= _board.SizeZ)
				return -1;
			return AdventurePathfinder.NodeOf(x, z, _board.SizeX);
		}

		protected override void OnPaint(PaintEventArgs e)
		{
			base.OnPaint(e);
			if (_board == null)
				return;
			var g = e.Graphics;
			for (var z = 0; z < _board.SizeZ; z++)
			{
				for (var x = 0; x < _board.SizeX; x++)
				{
					var node = AdventurePathfinder.NodeOf(x, z, _board.SizeX);
					var rect = new Rectangle(x * _cell, z * _cell, _cell - 1, _cell - 1);
					g.FillRectangle(TerrainBrush(node), rect);
					if (_board.Road != null && node < _board.Road.Length && _board.Road[node] > 0)
					{
						using (var road = new SolidBrush(Color.FromArgb(90, 180, 140, 40)))
							g.FillRectangle(road, rect);
					}
					if (_reach != null && _reach.ContainsKey(node))
					{
						using (var overlay = new SolidBrush(Color.FromArgb(40, 80, 160, 255)))
							g.FillRectangle(overlay, rect);
					}
					if (!_board.Pathable[node])
					{
						using (var hatch = new SolidBrush(Color.FromArgb(120, 20, 20, 20)))
							g.FillRectangle(hatch, rect);
					}
					g.DrawRectangle(Pens.Black, rect);
				}
			}

			DrawPortals(g);

			for (var i = 0; i < _path.Count; i++)
			{
				AdventurePathfinder.XzOf(_path[i], _board.SizeX, out var px, out var pz);
				var rect = new Rectangle(px * _cell + 4, pz * _cell + 4, _cell - 9, _cell - 9);
				using (var pen = new Pen(Color.Gold, 2))
					g.DrawEllipse(pen, rect);
			}

			DrawOccupants(g);
			DrawHeroes(g);

			if (_preferredNode >= 0)
			{
				AdventurePathfinder.XzOf(_preferredNode, _board.SizeX, out var tx, out var tz);
				using (var pen = new Pen(Color.Lime, 3))
					g.DrawRectangle(pen, tx * _cell + 1, tz * _cell + 1, _cell - 3, _cell - 3);
			}
		}

		private void DrawPortals(Graphics g)
		{
			if (_board.Portals == null)
				return;
			foreach (var kv in _board.Portals)
			{
				AdventurePathfinder.XzOf(kv.Key, _board.SizeX, out var x, out var z);
				using (var pen = new Pen(Color.Cyan, 2))
					g.DrawEllipse(pen, x * _cell + 8, z * _cell + 8, _cell - 17, _cell - 17);
			}
		}

		private void DrawHeroes(Graphics g)
		{
			var heroes = _world?.Heroes ?? _board.Heroes;
			for (var i = 0; i < heroes.Count; i++)
			{
				var h = heroes[i];
				AdventurePathfinder.XzOf(h.Node, _board.SizeX, out var x, out var z);
				var rect = new Rectangle(x * _cell + 5, z * _cell + 5, _cell - 11, _cell - 11);
				g.FillEllipse(Brushes.DodgerBlue, rect);
				g.DrawEllipse(Pens.White, rect);
				TextRenderer.DrawText(g, h.Name ?? ("H" + h.HeroId), Font,
					new Point(x * _cell + 2, z * _cell + _cell - 14), Color.White);
			}
		}

		private void DrawOccupants(Graphics g)
		{
			var occ = _world?.Occupancy ?? _board.Occupancy;
			for (var i = 0; i < occ.Count; i++)
			{
				var o = occ[i];
				if (!o.Alive && o.Kind != AdventureSimTargetKind.Mine && o.Kind != AdventureSimTargetKind.Town)
					continue;
				AdventurePathfinder.XzOf(o.Node, _board.SizeX, out var x, out var z);
				var rect = new Rectangle(x * _cell + 6, z * _cell + 6, _cell - 13, _cell - 13);
				Brush brush;
				switch (o.Kind)
				{
					case AdventureSimTargetKind.Town: brush = Brushes.MediumPurple; break;
					case AdventureSimTargetKind.Pickup: brush = o.Alive ? Brushes.Goldenrod : Brushes.Gray; break;
					case AdventureSimTargetKind.Mine:
						brush = o.OwnerSide >= 0 ? Brushes.LimeGreen : Brushes.DarkOrange;
						break;
					default: brush = o.Alive ? Brushes.IndianRed : Brushes.DimGray; break;
				}
				g.FillRectangle(brush, rect);
				g.DrawRectangle(Pens.White, rect);
			}
		}

		private Brush TerrainBrush(int node)
		{
			if (_board.Terrain == null || node >= _board.Terrain.Length)
				return Brushes.DarkOliveGreen;
			var t = _board.Terrain[node];
			switch (t)
			{
				case AdventureSimTerrain.OldenSand: return Brushes.DarkKhaki;
				case AdventureSimTerrain.OldenSnow: return Brushes.LightSteelBlue;
				case AdventureSimTerrain.OldenSwamp: return Brushes.DarkSlateGray;
				case AdventureSimTerrain.OldenWater: return Brushes.SteelBlue;
				case AdventureSimTerrain.OldenDirt: return Brushes.SaddleBrown;
				case AdventureSimTerrain.OldenRockBlocked: return Brushes.DimGray;
				case AdventureSimTerrain.OldenWasteland: return Brushes.Peru;
				default: return Brushes.DarkOliveGreen;
			}
		}
	}
}
