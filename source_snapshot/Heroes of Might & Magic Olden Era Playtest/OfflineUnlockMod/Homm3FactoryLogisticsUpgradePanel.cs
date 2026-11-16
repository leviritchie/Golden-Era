using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using W = OfflineUnlockMod.Homm3DungeonWarCaptivesWindowLayout;
using L = OfflineUnlockMod.Homm3FactoryLogisticsUpgradePanelLayout;
using Ui = OfflineUnlockMod.Homm3FactoryLogisticsUi;
using Info = OfflineUnlockMod.Homm3FactoryLogisticsPanelInfo;

namespace OfflineUnlockMod;

/// <summary>
/// Logistics Network upgrade panel: opens when <see cref="Homm3FactoryLogistics.VisitRequested"/> fires (a Factory hero with
/// the skill visits an owned mine or dwelling). One row per enhancement the building may hold: icon, name, built state with
/// the Active badge / "Set active" switch, the three level lines (levels above the hero's cap are greyed with the rank they
/// need), and the next step's cost. Click a row to select it; Build / Upgrade acts on the selection with the visiting hero
/// (immediate), Demolish asks once more, Close and Esc close. Everything shown comes from
/// <see cref="Homm3FactoryLogistics.TryGetBuilding"/> and is re-read after every command; refusals show on the status line.
/// Mockups: V:/olden_port_work/factory_logistics/mockups/upgrade_*.png (tools/factory_logistics/upgrade_panel_mockup.py).
/// Proof tier: source/static until compiled; runtime unproven.
/// </summary>
internal static class Homm3FactoryLogisticsUpgradePanel
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_FACTORY_LOGISTICS_UPGRADE";
	private static readonly string[] Ranks = { "", "Basic", "Advanced", "Expert" };

	private static GameObject _canvasObject;
	private static RectTransform _window;
	private static object _hero;
	private static long _key;
	private static LogisticsBuildingView _view;
	private static string _networkLine;
	private static string _linkLine;
	private static string _recId;
	private static string _recReason;
	private static string _selected;
	private static string _status;
	private static bool _confirmDemolish;
	private static int _tickFrame;
	private static readonly List<Ui.Clickable> Buttons = new();
	private static readonly List<(RectTransform Rect, string Id)> Rows = new();

	internal static bool IsOpen => _view != null;

	internal static void OnVisitRequested(object dataHero, long objectKey)
	{
		if (!Open(dataHero, objectKey, out var fail))
			Ui.LogWarning("upgrade panel not opened for object " + objectKey + ": " + fail);
	}

	internal static bool Open(object dataHero, long objectKey, out string fail)
	{
		fail = null;
		if (_view != null || Homm3FactoryLogisticsViewer.IsOpen)
		{
			fail = "a Logistics panel is already open";
			return false;
		}
		if (dataHero == null)
		{
			fail = "no visiting hero";
			return false;
		}
		try
		{
			if (!Homm3FactoryLogistics.TryGetBuilding(objectKey, dataHero, out var view, out fail))
				return false;
			if (view == null || view.Options == null)
			{
				fail = "building view has no options";
				return false;
			}
			if (!Ui.TryCreateCanvas(CanvasObjectName, L.Width, 400f, out _canvasObject, out _window, out fail))
				return false;
			_hero = dataHero;
			_key = objectKey;
			_view = view;
			_selected = null;
			_status = null;
			_confirmDemolish = false;
			_networkLine = Homm3FactoryLogistics.TryGetNetwork(out var net, out _) && net != null
				? "Network: " + (net.Buildings?.Count ?? 0) + ((net.Buildings?.Count ?? 0) == 1 ? " building" : " buildings") + " \u00b7 range " + Info.RangeDays(net.LogisticsLevel, net.RangeMpPerLevel)
				: "";
			ReadInsights();
			// Suggested first build (UX item 5): preselected while the building has nothing built.
			if (_recId != null && (view.Built == null || view.Built.Count == 0) && Option(_recId) != null)
				_selected = _recId;
			Homm3TowerArtificingPickerInputBlock.Begin();
			Build();
			Ui.LogInfo("upgrade panel opened: object=" + objectKey + " name=" + view.DisplayName + " options=" + view.Options.Count + " built=" + (view.Built?.Count ?? 0)
				+ " active=" + (view.ActiveEnhancementId ?? "none") + " uc=" + view.UpgradeCenterLevel);
			return true;
		}
		catch (Exception ex)
		{
			fail = "upgrade panel build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			var wasOpen = _view != null;
			Forget();
			if (wasOpen)
				Homm3TowerArtificingPickerInputBlock.End();
			return false;
		}
	}

	/// <summary>
	/// Link status (UX item 24) and the suggested enhancement (item 5) from the viewer lane's insights: one range solve,
	/// read when the panel opens and after each command, never per frame. A failure hides the line.
	/// </summary>
	private static void ReadInsights()
	{
		_linkLine = null;
		_recId = null;
		_recReason = null;
		try
		{
			if (Homm3FactoryLogistics.TryGetLinkStatus(_key, out var summary, out var linkFail))
				_linkLine = summary;
			else
				Ui.LogInfo("upgrade panel: link status unavailable for object " + _key + " (" + linkFail + ")");
			if (Homm3FactoryLogistics.TryGetRecommendedEnhancement(_key, out var id, out var reason, out _))
			{
				_recId = id;
				_recReason = reason;
			}
		}
		catch (Exception ex)
		{
			Ui.LogWarning("upgrade panel: insights failed: " + ex.GetBaseException().Message);
		}
	}

	private static void Forget()
	{
		var canvas = _canvasObject;
		_canvasObject = null;
		_window = null;
		_view = null;
		_hero = null;
		Buttons.Clear();
		Rows.Clear();
		Ui.DestroyCanvas(canvas);
	}

	private static void Close(string why)
	{
		if (_view == null)
			return;
		Forget();
		Homm3TowerArtificingPickerInputBlock.End();
		Ui.LogInfo("upgrade panel closed (" + why + ")");
	}

	internal static void HostDestroyed()
	{
		// Another Logistics canvas being destroyed also lands here; only react when this panel's own canvas is gone.
		if (_view == null || _canvasObject)
			return;
		_canvasObject = null;
		Forget();
		Homm3TowerArtificingPickerInputBlock.End();
		Ui.LogWarning("upgrade panel canvas was destroyed while open; closed");
	}

	// ---------------------------------------------------------------- input

	internal static void Tick()
	{
		if (_view == null || _canvasObject == null || _tickFrame == Time.frameCount)
			return;
		_tickFrame = Time.frameCount;
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			if (Input.GetKeyDown(KeyCode.Escape))
			{
				if (_confirmDemolish)
				{
					_confirmDemolish = false;
					Build();
					return;
				}
				Close("Esc");
				return;
			}
			var mouse = (Vector2)Input.mousePosition;
			Ui.HoverButtons(Buttons, mouse);
			if (!Input.GetMouseButtonDown(0))
				return;
			if (Ui.ClickButtons(Buttons, mouse))
				return;
			foreach (var row in Rows)
			{
				if (!Ui.Over(row.Rect, mouse))
					continue;
				if (_selected != row.Id)
				{
					_selected = row.Id;
					_status = null;
					_confirmDemolish = false;
					Build();
				}
				return;
			}
		}
		catch (Exception ex)
		{
			Ui.LogWarning("upgrade panel input failed; closing: " + ex.GetBaseException().Message);
			Close("panel error");
		}
	}

	/// <summary>Re-reads the building after a command; a failed read closes the panel (the building may have been lost).</summary>
	private static bool Refresh()
	{
		if (Homm3FactoryLogistics.TryGetBuilding(_key, _hero, out var view, out var fail) && view != null && view.Options != null)
		{
			_view = view;
			return true;
		}
		Ui.LogWarning("upgrade panel: building " + _key + " can no longer be read (" + fail + "); closing");
		Close("building unreadable");
		return false;
	}

	private static void Run(string what, string id, Func<(bool Ok, string Fail)> command)
	{
		_confirmDemolish = false;
		var (ok, fail) = command();
		Ui.LogInfo("upgrade panel: " + what + " " + id + " on object " + _key + " -> " + (ok ? "ok" : "refused: " + fail));
		_status = ok ? null : fail ?? what + " refused";
		if (Refresh())
		{
			if (ok)
				ReadInsights();
			Build();
		}
	}

	private static LogisticsOption Option(string id)
	{
		if (id == null || _view?.Options == null)
			return null;
		foreach (var o in _view.Options)
		{
			if (o != null && o.Id == id)
				return o;
		}
		return null;
	}

	private static int PendingLevel(string id)
	{
		if (_view?.Built == null)
			return 0;
		foreach (var e in _view.Built)
		{
			if (e != null && e.Id == id)
				return e.PendingLevel;
		}
		return 0;
	}

	// ---------------------------------------------------------------- build

	private static void Build()
	{
		Buttons.Clear();
		Rows.Clear();
		Ui.ClearChildren(_window);
		var v = _view;
		var w = L.Width;
		var rowsHeight = 0f;
		foreach (var o in v.Options)
			rowsHeight += RowHeight(o) + L.RowGap;
		var stock = v.UpgradedStock ?? Array.Empty<LogisticsUpgradedStockView>();
		var stockHeight = stock.Count == 0 ? 0f : L.StockHeader + stock.Count * (L.StockRow + L.RowGap);
		var h = L.RowsTop + rowsHeight + stockHeight + L.StatusGap + L.StatusHeight + L.ButtonAreaHeight;
		var buttonY = h - L.ButtonAreaHeight / 2f - 4f;
		Ui.Shell(_window, w, h, "Logistics Network", buttonY - 4f);

		// Info strip: the building on the left; the network and this building's Upgrade Center on the right.
		var iy = L.InfoTop;
		var icx = L.Pad + L.BuildingIcon / 2f + 6f;
		var icy = iy + L.InfoHeight / 2f;
		Ui.Centered(_window, P.SpriteCellBack, icx, icy, L.BuildingIcon + 4f, L.BuildingIcon + 4f, new Color(0.35f, 0.3f, 0.25f, 1f));
		var icon = Ui.BuildingIcon(v);
		if (icon != null)
			Ui.SpriteImage(_window, icon, icx - L.BuildingIcon / 2f + 5f, icy - L.BuildingIcon / 2f + 5f, L.BuildingIcon - 10f, L.BuildingIcon - 10f);
		Ui.Centered(_window, P.SpriteCellFrame, icx, icy, L.BuildingIcon + 8f, L.BuildingIcon + 8f, new Color(0.7f, 0.58f, 0.3f, 0.6f));
		var tx = L.Pad + L.BuildingIcon + 26f;
		Ui.Text(_window, P.FontBook, P.SizeHeaderBig, v.DisplayName ?? "Building", tx, iy + 6f, 420f, 32f, P.TipTitle);
		var sub = v.Kind == LogisticsBuildingKind.Dwelling
			? (v.UnitTier > 0 ? "Tier " + v.UnitTier + " dwelling" : "Creature dwelling") + " \u00b7 owned by you"
			: "Mine \u00b7 owned by you";
		Ui.Text(_window, P.FontMedium, P.SizeSmall, sub, tx, iy + 40f, 420f, 24f, P.TipNote);
		var rx = w / 2f;
		var rw = w / 2f - L.Pad;
		Ui.Text(_window, P.FontMedium, P.SizeMain, _networkLine, rx, iy, rw, 28f, P.TipBody, TextAlignmentOptions.Right);
		var cap = 0;
		foreach (var o in v.Options)
			cap = Math.Max(cap, o?.MaxLevelNow ?? 0);
		var second = new List<string>();
		if (cap > 0)
			second.Add("This hero builds up to level " + cap);
		if (v.UpgradeCenterLevel > 0)
			second.Add(Info.RemoteCenter(v.UpgradeCenterLevel, v.ViaCommandCenter) + " (remote builds up to level " + v.UpgradeCenterLevel + ")");
		if (second.Count > 0)
			Ui.Text(_window, P.FontMedium, P.SizeSmall, string.Join(" \u00b7 ", second), rx, iy + 28f, rw, 24f, P.TipNote, TextAlignmentOptions.Right);
		if (!string.IsNullOrEmpty(_linkLine))
		{
			var linked = _linkLine.StartsWith("Linked", StringComparison.Ordinal);
			var isolated = _linkLine.StartsWith("Isolated", StringComparison.Ordinal);
			Ui.Text(_window, P.FontMedium, P.SizeSmall, _linkLine, rx, iy + 52f, rw, 24f, linked ? P.CostOk : isolated ? P.TipWarn : P.TipNote, TextAlignmentOptions.Right);
		}

		var y = L.RowsTop;
		foreach (var o in v.Options)
		{
			if (o == null)
				continue;
			var rh = RowHeight(o);
			BuildRow(o, L.Pad, y, w - 2f * L.Pad, rh);
			y += rh + L.RowGap;
		}
		if (stock.Count > 0)
			y = BuildStock(stock, L.Pad, y, w - 2f * L.Pad);

		// Status line: the last refusal, else why the selection cannot be built, else the switch rule.
		var sel = Option(_selected);
		var next = sel == null ? 0 : sel.BuiltLevel + 1;
		var canBuild = sel != null && next <= 3 && next <= sel.MaxLevelNow && sel.BlockReason == null && sel.CanAfford;
		string status;
		var warn = true;
		if (_confirmDemolish && sel != null)
			status = "Demolish " + sel.Name + "? It is free, with no refund.";
		else if (_status != null)
			status = _status;
		else if (sel != null && next <= 3 && sel.BlockReason != null)
			status = sel.BlockReason;
		else if (sel != null && next <= 3 && next <= sel.MaxLevelNow && !sel.CanAfford)
			status = "Not enough resources for " + sel.Name + " level " + next + ".";
		else
		{
			warn = false;
			status = sel != null && sel.Id == _recId && _recReason != null && (v.Built == null || v.Built.Count <= 1)
				? "Suggested: " + _recReason
				: v.Built != null && v.Built.Count > 1
				? v.SwitchUsedThisWeek
					? "Only the active enhancement works. Switch used this week; next switch: start of next week."
					: "Only the active enhancement works. 1 switch left this week; a switch applies next day."
				: sel == null ? "Select an enhancement. Builds and upgrades by a visiting hero apply immediately." : "";
		}
		y += L.StatusGap;
		Ui.Text(_window, P.FontMedium, P.SizeSmall, status, W.RecruitTextInset, y, w - 2f * W.RecruitTextInset, L.StatusHeight, warn ? P.TipWarn : P.TipNote, TextAlignmentOptions.Center);

		// Buttons: [Demolish] Close [Build / Upgrade].
		var labels = new List<(string Label, bool Enabled, Action Click)>();
		if (_confirmDemolish && sel != null)
		{
			labels.Add(("Cancel", true, () =>
			{
				_confirmDemolish = false;
				Build();
			}));
			var id = sel.Id;
			labels.Add(("Confirm", true, () => Run("demolish", id, () => (Homm3FactoryLogistics.TryDemolish(_key, id, out var f), f))));
		}
		else
		{
			if (sel != null && sel.BuiltLevel > 0)
				labels.Add(("Demolish", true, () =>
				{
					_confirmDemolish = true;
					_status = null;
					Build();
				}));
			labels.Add(("Close", true, () => Close("Close")));
			if (cap > 0)
				labels.Add(("Open network here", true, OpenNetworkHere));
			if (sel != null && next <= 3)
			{
				var id = sel.Id;
				labels.Add((sel.BuiltLevel > 0 ? "Upgrade to L" + next : "Build", canBuild, () => Run("build", id, () => (Homm3FactoryLogistics.TryBuild(_key, id, _hero, out var f), f))));
			}
		}
		var bw = W.RecruitButtonWidth;
		var gap = W.RecruitButtonGap;
		var bx = (w - labels.Count * bw - (labels.Count - 1) * gap) / 2f;
		for (var i = 0; i < labels.Count; i++)
			Ui.Button(_window, Buttons, labels[i].Label, bx + i * (bw + gap), buttonY - W.RecruitButtonHeight / 2f, bw, W.RecruitButtonHeight, labels[i].Enabled, false, labels[i].Click);
	}

	/// <summary>UX item 20: closes this panel and opens the network viewer centred on this building, for the same hero.</summary>
	private static void OpenNetworkHere()
	{
		var hero = _hero;
		var key = _key;
		Close("open network here");
		string fail;
		try
		{
			if (Homm3FactoryLogisticsViewer.OpenFocused(hero, key, out fail))
				return;
		}
		catch (Exception ex)
		{
			fail = ex.GetBaseException().Message;
		}
		Ui.LogWarning("upgrade panel: network viewer not opened for object " + key + ": " + fail);
		Homm3DungeonWarCaptivesWindow.ShowBanner("Logistics Network: " + fail);
	}

	/// <summary>
	/// Arcane Manufactory upgraded stock: one row per upgraded unit (name, count, price per unit at this dwelling's
	/// current charge) with Hire 1 / Hire all into the visiting hero's army (CORE checks stock, price and army).
	/// </summary>
	private static float BuildStock(IReadOnlyList<LogisticsUpgradedStockView> stock, float x, float y, float w)
	{
		var title = "Upgraded stock from the Arcane Manufactory" + (_view.ConversionPct > 0 ? " \u00b7 " + _view.ConversionPct + "% of each week's growth" : "");
		Ui.Text(_window, P.FontBook, P.SizeMain, title, x + 6f, y, w - 12f, L.StockHeader - 6f, P.TipTitle);
		y += L.StockHeader;
		foreach (var s in stock)
		{
			if (s == null)
				continue;
			Ui.Sliced(_window, Ui.SpriteRow, x, y, w, L.StockRow, 1f, new Color(0.09f, 0.12f, 0.19f, 1f));
			var cy = y + L.StockRow / 2f;
			Ui.Text(_window, P.FontBook, P.SizeSubHeader, Homm3UnitDisplayNames.Resolve(s.UnitSid), L.NameX - 40f, cy - 14f, 300f, 28f, P.ButtonText);
			Ui.Text(_window, P.FontMedium, P.SizeMain, Ui.N(s.Count) + " available", L.LevelX + 40f, cy - 14f, 200f, 28f, P.TipBody);
			Ui.Text(_window, P.FontMedium, P.SizeSmall, "each", L.LevelTextX + 210f, cy - 12f, 60f, 24f, P.TipNote, TextAlignmentOptions.Right);
			Ui.Cost(_window, s.UnitCost, L.LevelTextX + 276f, cy, 250f, L.CostIcon - 4f, P.SizeMain, s.CanAffordOne ? P.TipBody : P.CostBad);
			var sid = s.UnitSid;
			var all = s.Count;
			var bx = x + w - 2f * L.StockButton - 16f;
			Ui.Button(_window, Buttons, "Hire 1", bx, cy - L.StockButtonHeight / 2f, L.StockButton, L.StockButtonHeight, s.CanAffordOne && s.Count > 0, false,
				() => Run("hire upgraded 1x", sid, () => (Homm3FactoryLogistics.TryHireUpgradedOnSite(_key, sid, 1, _hero, out var f), f)), P.SizeMain);
			Ui.Button(_window, Buttons, "Hire all", bx + L.StockButton + 8f, cy - L.StockButtonHeight / 2f, L.StockButton, L.StockButtonHeight, s.CanAffordOne && s.Count > 0, true,
				() => Run("hire upgraded " + all + "x", sid, () => (Homm3FactoryLogistics.TryHireUpgradedOnSite(_key, sid, all, _hero, out var f), f)), P.SizeMain);
			y += L.StockRow + L.RowGap;
		}
		return y;
	}

	private static float RowHeight(LogisticsOption o) =>
		L.RowHeight + (o != null && _view.PowerStationBonusLevels > 0 && o.Id == _view.ActiveEnhancementId ? L.RowExtra : 0f);

	private static void BuildRow(LogisticsOption o, float x, float y, float w, float h)
	{
		var v = _view;
		var selected = o.Id == _selected;
		var built = o.BuiltLevel > 0;
		var active = built && o.Id == v.ActiveEnhancementId;
		var row = Ui.Sliced(_window, selected ? Ui.SpriteRowSelected : Ui.SpriteRow, x, y, w, h, 1f, selected ? new Color(0.14f, 0.22f, 0.36f, 1f) : new Color(0.09f, 0.12f, 0.19f, 1f));
		Rows.Add((row.rectTransform, o.Id));
		if (selected)
			Ui.Flat(_window, x, y, 4f, h, P.TipTitle);
		var cy = y + L.RowHeight / 2f;
		Ui.Centered(_window, P.SpriteCellBack, L.CellCenterX, cy, L.CellBack, L.CellBack, new Color(0.35f, 0.3f, 0.25f, 1f));
		var icon = Ui.EnhancementIcon(o.Id, o.Name);
		if (icon != null)
			Ui.SpriteImage(_window, icon, L.CellCenterX - L.CellIcon / 2f, cy - L.CellIcon / 2f, L.CellIcon, L.CellIcon);
		Ui.Centered(_window, P.SpriteCellFrame, L.CellCenterX, cy, L.CellBack + 6f, L.CellBack + 6f, new Color(0.7f, 0.58f, 0.3f, 0.6f));
		Ui.Text(_window, P.FontBook, P.SizeSubHeader, o.Name ?? o.Id, L.NameX, cy - 38f, L.NameWidth, 28f, selected ? P.TipTitle : P.ButtonText);

		var pending = PendingLevel(o.Id);
		if (built)
		{
			Ui.Text(_window, P.FontMedium, P.SizeSmall, "Built: level " + o.BuiltLevel, L.NameX, cy - 8f, L.StateWidth, 26f, active ? P.CostOk : P.TipBody);
			var tx = L.NameX + L.StateWidth;
			if (active)
			{
				Ui.Sliced(_window, W.SpriteRecruitButtonGreen, tx, cy - 8f, L.ToggleWidth, 26f, 3f, new Color(0.18f, 0.4f, 0.16f, 1f));
				Ui.Text(_window, P.FontMedium, P.SizeSmall, v.PendingActiveId != null && v.PendingActiveId != o.Id ? "Until tomorrow" : "Active", tx, cy - 8f, L.ToggleWidth, 26f, P.ButtonText, TextAlignmentOptions.Center);
			}
			else if (v.PendingActiveId == o.Id)
			{
				Ui.Text(_window, P.FontMedium, P.SizeSmall, "Active tomorrow", tx, cy - 8f, L.ToggleWidth + 30f, 26f, P.TipWarn);
			}
			else if (!v.SwitchUsedThisWeek && v.PendingActiveId == null)
			{
				var id = o.Id;
				Ui.Tab(_window, Buttons, "Set active", tx, cy - 8f, L.ToggleWidth, 26f, false, () => Run("set active", id, () => (Homm3FactoryLogistics.TrySetActive(_key, id, out var f), f)));
			}
		}
		else
		{
			Ui.Text(_window, P.FontMedium, P.SizeSmall, pending > 0 ? "Under construction - active tomorrow" : "Not built", L.NameX, cy - 8f, L.NameWidth, 26f, pending > 0 ? P.TipWarn : P.TipNote);
		}
		// Replaces output / Adds to output (UX item 3): whether the building keeps producing while this one is active.
		var outputTag = Info.OutputTag(o.Id);
		if (outputTag != null)
			Ui.Text(_window, P.FontMedium, P.SizeSmall, outputTag, L.NameX, cy + 20f, L.LevelX - L.NameX - 10f, 22f, outputTag == Info.ReplacesOutputTag ? P.TipWarn : P.TipNote);

		// Level lines.
		var lines = o.LevelLines ?? Array.Empty<string>();
		var lineW = L.LockX - L.LevelX + L.LockWidth - 6f;
		for (var i = 0; i < 3; i++)
		{
			var lvl = i + 1;
			var ly = y + L.LevelTop + i * L.LevelPitch;
			var lh = L.LevelPitch - 4f;
			var reach = lvl <= o.MaxLevelNow;
			var done = lvl <= o.BuiltLevel;
			if (reach && !done)
				Ui.Flat(_window, L.LevelX - 6f, ly, lineW, lh, L.HighlightTint);
			var col = done ? (active ? P.CostOk : P.TipBody) : reach ? P.TipBody : P.ButtonTextDisabled;
			var badge = Ui.Centered(_window, P.SpriteTierBadge, L.LevelX + L.BadgeSize / 2f, ly + lh / 2f, L.BadgeSize, L.BadgeSize, new Color(0.8f, 0.74f, 0.58f, 1f));
			if (!reach && !done)
				badge.color = L.LockedTint;
			Ui.Text(_window, P.FontBook, P.SizeSmall, lvl.ToString(), L.LevelX, ly, L.BadgeSize, lh, P.Ink, TextAlignmentOptions.Center);
			var tag = done ? "Built" : reach ? null : "Requires " + Ranks[lvl];
			Ui.Text(_window, P.FontMedium, P.SizeSmall, i < lines.Length ? lines[i] : "", L.LevelTextX, ly, L.LevelTextWidth + (tag == null ? L.LockWidth - 12f : 0f), lh, col);
			if (tag != null)
				Ui.Text(_window, P.FontMedium, P.SizeSmall, tag, L.LockX, ly, L.LockWidth - 12f, lh, done ? (active ? P.CostOk : P.TipNote) : P.TipWarn, TextAlignmentOptions.Right);
		}
		if (active && v.PowerStationBonusLevels > 0)
			Ui.Text(_window, P.FontMedium, P.SizeSmall, "Powered level " + (o.BuiltLevel + v.PowerStationBonusLevels) + ": +" + v.PowerStationBonusLevels + " from a Power Station in range",
				L.LevelTextX, y + L.LevelTop + 3f * L.LevelPitch, L.LevelTextWidth + L.LockWidth, L.LevelPitch - 4f, P.TipTitle);

		// Suggested enhancement (UX item 5), under the cost column.
		if (o.Id == _recId)
			Ui.Text(_window, P.FontMedium, P.SizeSmall, v.Built == null || v.Built.Count == 0 ? "Suggested first build" : "Suggested", L.CostX, cy + 30f, L.CostWidth, 22f, P.TipTitle, TextAlignmentOptions.Center);

		// Cost column: the next step.
		var next = o.BuiltLevel + 1;
		if (next > 3)
		{
			Ui.Text(_window, P.FontMedium, P.SizeSmall, "Fully upgraded", L.CostX, cy - 12f, L.CostWidth, 24f, P.CostOk, TextAlignmentOptions.Center);
			return;
		}
		if (next > o.MaxLevelNow)
		{
			Ui.Text(_window, P.FontMedium, P.SizeSmall, "Level " + next + " requires " + Ranks[next], L.CostX, cy - 12f, L.CostWidth, 24f, P.TipWarn, TextAlignmentOptions.Center);
			return;
		}
		Ui.Text(_window, P.FontMedium, P.SizeSmall, built ? "Upgrade to level " + next : "Build: level 1", L.CostX, cy - 34f, L.CostWidth, 22f, P.TipNote, TextAlignmentOptions.Center);
		Ui.Cost(_window, o.NextCost, L.CostX, cy + 6f, L.CostWidth, L.CostIcon, P.SizeMain, o.CanAfford ? P.TipBody : P.CostBad);
	}
}

/// <summary>
/// Geometry of the Logistics Network upgrade panel (window space: top-left origin, y down, 1920x1080 reference canvas).
/// Mirrors class Lay in tools/factory_logistics/upgrade_panel_mockup.py (the approved mockups); keep the two in step.
/// </summary>
internal static class Homm3FactoryLogisticsUpgradePanelLayout
{
	internal const float Width = 1240f;
	internal const float InfoTop = 60f;
	internal const float InfoHeight = 74f;
	internal const float BuildingIcon = 66f;
	internal const float Pad = 30f;
	internal const float RowsTop = 146f;
	internal const float RowHeight = 112f;
	internal const float RowExtra = 26f;
	internal const float RowGap = 8f;
	internal const float CellCenterX = 92f;
	internal const float CellBack = 74f;
	internal const float CellIcon = 64f;
	internal const float NameX = 142f;
	internal const float NameWidth = 236f;
	internal const float StateWidth = 116f;
	internal const float ToggleWidth = 104f;
	internal const float LevelX = 392f;
	internal const float BadgeSize = 26f;
	internal const float LevelTextX = 426f;
	internal const float LevelTextWidth = 380f;
	internal const float LockX = 812f;
	internal const float LockWidth = 120f;
	internal const float LevelTop = 12f;
	internal const float LevelPitch = 28f;
	internal const float CostX = 948f;
	internal const float CostWidth = 262f;
	internal const float CostIcon = 28f;
	internal const float StatusGap = 10f;
	internal const float StatusHeight = 28f;
	internal const float ButtonAreaHeight = 92f;
	internal const float StockHeader = 34f;
	internal const float StockRow = 52f;
	internal const float StockButton = 120f;
	internal const float StockButtonHeight = 34f;
	internal static readonly Color HighlightTint = new(0.84f, 0.74f, 0.49f, 0.18f);
	internal static readonly Color LockedTint = new(0.47f, 0.47f, 0.47f, 1f);
}
