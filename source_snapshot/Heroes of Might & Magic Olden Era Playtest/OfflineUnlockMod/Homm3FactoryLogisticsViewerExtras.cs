using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using L = OfflineUnlockMod.Homm3FactoryLogisticsViewerLayout;
using Ui = OfflineUnlockMod.Homm3FactoryLogisticsUi;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

// Logistics Network viewer, UX pass 2026-11-16 (docs/factory_logistics_ux_candidates.md items 1, 4, 6-13, 15, 16, 20 and
// bulk remote recruitment): primer / glossary, network totals bar, range overlay, cut-route fixes, to-do list and filters,
// keyboard shortcuts, delivery preview and the "Recruit all" screen. Everything expensive (range solves, before/after
// re-solves, army reads) is computed on demand and cached until the network is re-read.
internal static partial class Homm3FactoryLogisticsViewer
{
	// ---------------------------------------------------------------- state

	private const int PopupNone = 0, PopupPrimer = 1, PopupBulk = 2, PopupCut = 3;

	private static bool _primerSeen;          // per game session (item 1)
	private static int _popup;
	private static RectTransform _popupRoot;
	private static RectTransform _popupRect;
	private static readonly List<Ui.Clickable> PopupButtons = new();
	private static readonly List<Tip> ChromeTips = new();
	private static RectTransform _totalsRoot;
	private static Tip _totalsTip;
	private static RectTransform _panelRoot;
	private static RectTransform _panelRect;
	private static readonly List<Ui.Clickable> PanelButtons = new();
	private static bool _panelOpen;
	private static readonly HashSet<string> HiddenEffects = new(StringComparer.Ordinal);
	private static bool _rangeOn;

	private static LogisticsTotals _totals;
	private static string _totalsFail;
	private static readonly Dictionary<long, string> LinkStatus = new();
	private static readonly Dictionary<string, string[]> Previews = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, string> NoPathReasons = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, (LogisticsDeliveryPreview Preview, string Fail)> Deliveries = new(StringComparer.Ordinal);
	private static readonly Dictionary<long, (string Id, string Reason)> Recommendations = new();

	private static UnityImage _rangeImage;
	private static Texture2D _rangeTexture;
	private static Sprite _rangeSprite;
	private static long _rangeKey = -1;
	private static LogisticsNetworkView _rangeFor;
	private static string _rangeNote;

	private static readonly List<(RectTransform Rect, long Source, int X, int Y)> CutHits = new();
	private static (long Source, int X, int Y) _cut;

	private static List<LogisticsBulkRow> _bulkRows;
	private static List<LogisticsBulkTarget> _bulkTargets;
	private static string _bulkFail;
	private static int _bulkTarget;
	private static int _bulkPage;
	private static readonly Dictionary<string, int> BulkCounts = new(StringComparer.Ordinal);
	private static string _bulkStatus;
	private static bool _bulkStatusOk;

	private const string NoEffect = "(none)";

	private static void ResetExtras()
	{
		_popup = PopupNone;
		HiddenEffects.Clear();
		_rangeOn = false;
		_bulkRows = null;
		_bulkTargets = null;
		BulkCounts.Clear();
		_bulkStatus = null;
		ClearCaches();
	}

	private static void ClearCaches()
	{
		_totals = null;
		_totalsFail = null;
		LinkStatus.Clear();
		Previews.Clear();
		NoPathReasons.Clear();
		Deliveries.Clear();
		Recommendations.Clear();
		_rangeFor = null;
	}

	private static void ForgetExtras()
	{
		PopupButtons.Clear();
		PanelButtons.Clear();
		ChromeTips.Clear();
		CutHits.Clear();
		_popupRoot = _popupRect = _panelRoot = _panelRect = _totalsRoot = null;
		_totalsTip = null;
		_rangeImage = null;
		DestroyRange();
		ClearCaches();
		_popup = PopupNone;
	}

	/// <summary>After a command re-read the network: caches go, the totals bar is redrawn.</summary>
	private static void InvalidateExtras()
	{
		ClearCaches();
		_glowFor = null;
		BuildTotals();
	}

	/// <summary>Consumes <see cref="PendingFocusKey"/> (item 20) and shows the primer once per session (item 1).</summary>
	private static void AfterOpen()
	{
		var key = PendingFocusKey;
		PendingFocusKey = -1;
		if (key >= 0)
		{
			var b = Building(key);
			if (b != null)
			{
				Select(key);
				CentreOn(b.TileX, b.TileY);
			}
			else
			{
				_status = "That building is not part of the network yet (build an enhancement there first).";
				BuildCard();
			}
		}
		if (!_primerSeen)
			OpenPopup(PopupPrimer);
	}

	private static bool Hidden(long sourceKey)
	{
		if (HiddenEffects.Count == 0)
			return false;
		var b = Building(sourceKey);
		return b != null && HiddenEffects.Contains(b.ActiveEnhancementId ?? NoEffect);
	}

	private static void CentreOn(int x, int y)
	{
		var c = TileCentre(x, y);
		_pan = new Vector2(c.x - L.MapWidth / 2f, c.y - L.MapHeight / 2f);
		ClampPan();
		ApplyPan();
	}

	private static string Days(int mp) => Homm3FactoryLogistics.Days(mp);

	// ---------------------------------------------------------------- cached facade reads

	private static string LinkStatusOf(long key)
	{
		if (LinkStatus.TryGetValue(key, out var s))
			return s;
		s = Homm3FactoryLogistics.TryGetLinkStatus(key, out var summary, out var fail) ? summary : "Links unknown (" + fail + ")";
		LinkStatus[key] = s;
		return s;
	}

	private static (string Id, string Reason) RecommendationOf(long key)
	{
		if (Recommendations.TryGetValue(key, out var r))
			return r;
		r = Homm3FactoryLogistics.TryGetRecommendedEnhancement(key, out var id, out var reason, out _) ? (id, reason) : (null, null);
		Recommendations[key] = r;
		return r;
	}

	private static string[] PreviewOf(long key, string id, int level)
	{
		var k = key + "|" + id + "|" + level;
		if (Previews.TryGetValue(k, out var lines))
			return lines;
		lines = Homm3FactoryLogistics.TryPreview(key, id, level, out var result, out var fail) ? result : new[] { "Preview unavailable (" + fail + ")" };
		Previews[k] = lines;
		return lines;
	}

	private static string NoPathReasonOf(LogisticsRoute r)
	{
		var k = r.FromKey + "|" + r.ToKind + "|" + r.ToKey;
		if (NoPathReasons.TryGetValue(k, out var s))
			return s;
		s = Homm3FactoryLogistics.TryExplainNoPath(r.FromKey, r.ToKind, r.ToKey, out var reason, out var fail) ? reason : "reason unknown (" + fail + ")";
		NoPathReasons[k] = s;
		return s;
	}

	private static (LogisticsDeliveryPreview Preview, string Fail) DeliveryOf(string kind, long key, string unitSid)
	{
		var k = kind + "|" + key + "|" + unitSid;
		if (Deliveries.TryGetValue(k, out var d))
			return d;
		d = Homm3FactoryLogistics.TryPreviewDelivery(kind, key, unitSid, out var preview, out var fail) ? (preview, null) : (null, fail);
		Deliveries[k] = d;
		return d;
	}

	private static string DeliveryLine((LogisticsDeliveryPreview Preview, string Fail) d, string unitSid)
	{
		if (d.Preview == null)
			return "Army unreadable: " + d.Fail;
		var p = d.Preview;
		var merges = unitSid != null && p.Present.Contains(unitSid);
		return p.ArmyLabel + ": " + (merges ? "joins its stack, " : "") + p.FreeSlots + " of " + p.Slots + " slots free";
	}

	// ---------------------------------------------------------------- text helpers

	internal static string Tag(bool replaces) => replaces ? "Replaces output" : "Adds to output";

	private static Color TagColour(bool replaces) => replaces ? P.TipWarn : P.CostOk;

	/// <summary>First clause of an effect text (before ';'), for one-line rows; the full text goes in the tip.</summary>
	private static string FirstClause(string text)
	{
		if (string.IsNullOrEmpty(text))
			return null;
		var i = text.IndexOf(';');
		return i > 0 ? text.Substring(0, i) : text;
	}

	private static string[] Concat(params IEnumerable<string>[] parts)
	{
		var list = new List<string>();
		foreach (var part in parts)
			if (part != null)
				foreach (var s in part)
					if (s != null)
						list.Add(s);
		return list.ToArray();
	}

	/// <summary>Adds lines (and lazily computed lines) to the tip already on <paramref name="rect"/>, or a new tip.</summary>
	private static void AugmentTip(RectTransform rect, string title, string[] extra, Func<string[]> more)
	{
		if (rect == null)
			return;
		for (var i = Tips.Count - 1; i >= 0; i--)
		{
			if (Tips[i].Rect != rect)
				continue;
			Tips[i].Lines = Concat(Tips[i].Lines, extra);
			Tips[i].More = more;
			return;
		}
		var lines = Concat(extra);
		if (lines.Length == 0 && more == null)
			return;
		Tips.Add(new Tip { Rect = rect, Title = title, Lines = lines.Length > 0 ? lines : new[] { " " }, More = more });
	}

	// ---------------------------------------------------------------- glossary / primer text (items 1, 4)

	private static string[] GlossaryLines() => new[]
	{
		"Range: how far a route travels, in days of base hero movement (1.0 day = one day's walk). Roads stretch it; unexplored fog, water and neutral guards block it.",
		"Logistics Hub: a route entering its tile gets back part of the range it spent (Rail Stations and Supply Caravan heroes count as hubs).",
		"Upgrade Center N: a Logistics Network hero visited; you can build up to level N here from this viewer.",
		"Command Center N: the same, from a Mobile Command Center hero in range.",
		"Remote build: building from the viewer. Same cost; takes effect tomorrow.",
		"Switch: change which built enhancement is active. Once per week; takes effect tomorrow.",
		"Powered level: enhancement level plus Power Station bonus levels.",
		"Replaces output / Adds to output: whether the building stops or keeps producing its own resource or units.",
	};

	private static string[] KeyLines() => new[]
	{
		"Tab / Shift+Tab: next / previous building.  N: next to-do.  U: next unvisited.",
		"1 2 3: card tabs.  R: range overlay.  C: centre on the selected building.",
		"L: to-do list and filters.  B: recruit all.  H or ?: this help.  Esc: close.",
	};

	// ---------------------------------------------------------------- chrome: header buttons, totals bar (items 4, 6)

	private static void BuildChromeExtras()
	{
		ChromeTips.Clear();
		CutHits.Clear();
		// Header buttons, left of Close: [Recruit all] [To-do] [?].
		var right = L.Width - L.CloseSize - 16f;
		var helpX = right - 40f;
		var help = Ui.Image(_window, Ui.SpriteTab, helpX, 8f, 34f, 30f, new Color(0.12f, 0.16f, 0.26f, 1f));
		Ui.Text(_window, P.FontBook, P.SizeSubHeader, "?", helpX, 8f, 34f, 30f, P.TipTitle, TextAlignmentOptions.Center);
		ChromeButtons.Add(new Ui.Clickable { Rect = help.rectTransform, Image = help, Normal = Ui.Sprite(Ui.SpriteTab), Hover = Ui.Sprite(Ui.SpriteTabHover), Click = () => OpenPopup(PopupPrimer) });
		ChromeTips.Add(new Tip { Rect = help.rectTransform, Title = "Logistics words (click for the full help)", Lines = GlossaryLines(), NearMouse = true });
		Ui.Button(_window, ChromeButtons, "To-do (L)", helpX - 136f, 8f, 128f, 30f, true, false, TogglePanel, P.SizeSmall);
		Ui.Button(_window, ChromeButtons, "Recruit all (B)", helpX - 316f, 8f, 172f, 30f, true, true, () => OpenPopup(PopupBulk), P.SizeSmall);
		_totalsRoot = A.NewRect("Totals", _window);
		A.Stretch(_totalsRoot);
		_panelRoot = A.NewRect("Panel", _window);
		A.Stretch(_panelRoot);
		BuildTotals();
	}

	/// <summary>Network totals (item 6) as a plate over the top-left of the map, breakdown on hover.</summary>
	private static void BuildTotals()
	{
		if (_totalsRoot == null)
			return;
		Ui.ClearChildren(_totalsRoot);
		if (_totalsTip != null)
			ChromeTips.Remove(_totalsTip);
		_totalsTip = null;
		if (_totals == null && _totalsFail == null && !Homm3FactoryLogistics.TryGetNetworkTotals(out _totals, out _totalsFail))
			_totals = null;
		string text;
		var lines = new List<string>();
		if (_totals == null)
			text = "Network totals unavailable" + (_totalsFail != null ? " (" + _totalsFail + ")" : "");
		else
		{
			var t = _totals;
			var parts = new List<string> { "+" + Ui.N(t.GoldPerDay) + " gold/day", "+" + Ui.N(t.GoldPerWeek) + " gold/week" };
			foreach (var kv in t.ResourcesPerDay)
				parts.Add("+" + kv.Value.ToString(kv.Value >= 10 ? "0" : "0.#", System.Globalization.CultureInfo.InvariantCulture) + " " + Ui.ResourceName(kv.Key) + "/day");
			if (t.ExtraUnitsPerWeek > 0)
				parts.Add("+" + Ui.N(t.ExtraUnitsPerWeek) + " units/week");
			var lost = new List<string>();
			foreach (var kv in t.GivenUpPerDay)
				lost.Add(kv.Value + " " + Ui.ResourceName(kv.Key) + "/day");
			if (t.UnitsGivenUpPerWeek > 0)
				lost.Add(Ui.N(t.UnitsGivenUpPerWeek) + " units/week");
			text = "Network: " + string.Join("  ·  ", parts) + (lost.Count > 0 ? "  ·  given up: " + string.Join(", ", lost) : "");
			lines.Add("Gold per day (Export Offices, Byproduct Processing): " + Ui.N(t.GoldPerDay));
			lines.Add("Gold per week: 7 x daily + " + Ui.N(t.WeeklyGold) + " weekly (Mercenary Headquarters) = " + Ui.N(t.GoldPerWeek));
			if (t.ResourcesPerDay.Count > 0)
				lines.Add("Extra resources come from Byproduct Processing (rounded down when paid).");
			lines.Add("Extra units per week (Food Distribution Centers, Support Hubs): " + Ui.N(t.ExtraUnitsPerWeek));
			if (t.UpgradedPerWeek > 0)
				lines.Add("Units upgraded per week (Arcane Manufactory): " + Ui.N(t.UpgradedPerWeek));
			if (t.AstrologyPerDay > 0)
				lines.Add("Astrology per day: " + Ui.N(t.AstrologyPerDay));
			lines.Add("Given up: output of buildings whose enhancement replaces output.");
			lines.Add("Network range: " + Days(t.RangeMp));
		}
		var w = Math.Min(L.MapWidth - L.ZoomSize - 40f, Ui.TextWidth(text, P.SizeSmall) + 24f);
		var plate = Ui.Flat(_totalsRoot, L.MapX + 10f, L.MapY + 8f, w, 30f, L.Plate);
		Ui.Text(_totalsRoot, P.FontMedium, P.SizeSmall, text, L.MapX + 22f, L.MapY + 8f, w - 12f, 30f, _totals == null ? P.TipWarn : P.TipBody);
		if (lines.Count > 0)
		{
			_totalsTip = new Tip { Rect = plate.rectTransform, Title = "Network totals (today)", Lines = lines.ToArray(), NearMouse = true };
			ChromeTips.Add(_totalsTip);
		}
	}

	// ---------------------------------------------------------------- side panel: filters + to-do (item 12)

	private static void TogglePanel()
	{
		_panelOpen = !_panelOpen;
		BuildPanel();
	}

	private enum TodoKind { Unvisited, Unenhanced, Switch, Construction, Cut }

	private static List<(TodoKind Kind, LogisticsBuildingView B)> Todos()
	{
		var list = new List<(TodoKind, LogisticsBuildingView)>();
		if (_net?.Buildings == null)
			return list;
		var cut = new HashSet<long>();
		foreach (var r in Routes())
			if (r != null && r.Cut)
				cut.Add(r.FromKey);
		foreach (var kind in new[] { TodoKind.Unvisited, TodoKind.Unenhanced, TodoKind.Switch, TodoKind.Construction, TodoKind.Cut })
		{
			foreach (var b in _net.Buildings)
			{
				if (b == null)
					continue;
				var built = b.Built?.Count ?? 0;
				var match = kind switch
				{
					TodoKind.Unvisited => b.UpgradeCenterLevel <= 0 && built == 0,
					TodoKind.Unenhanced => b.UpgradeCenterLevel > 0 && built == 0,
					TodoKind.Switch => built > 1 && !b.SwitchUsedThisWeek && b.PendingActiveId == null,
					TodoKind.Construction => UnderConstruction(b),
					_ => cut.Contains(b.ObjectKey),
				};
				if (match)
					list.Add((kind, b));
			}
		}
		return list;
	}

	private static bool UnderConstruction(LogisticsBuildingView b)
	{
		if (b?.PendingActiveId != null)
			return true;
		foreach (var e in b?.Built ?? Array.Empty<LogisticsEnhancementView>())
			if (e != null && e.PendingLevel > e.Level)
				return true;
		return false;
	}

	private static string TodoLabel(TodoKind k) => k switch
	{
		TodoKind.Unvisited => "Unvisited",
		TodoKind.Unenhanced => "No enhancement",
		TodoKind.Switch => "Switch available",
		TodoKind.Construction => "Under construction",
		_ => "Route cut",
	};

	private static void BuildPanel()
	{
		PanelButtons.Clear();
		_panelRect = null;
		if (_panelRoot == null)
			return;
		Ui.ClearChildren(_panelRoot);
		if (!_panelOpen || _net == null)
			return;
		const float pw = 330f;
		var x = L.MapX + 10f;
		var y0 = L.MapY + 46f;
		var effects = new SortedDictionary<string, string>(StringComparer.Ordinal);
		foreach (var b in _net.Buildings)
		{
			if (b == null)
				continue;
			var id = b.ActiveEnhancementId ?? NoEffect;
			if (!effects.ContainsKey(id))
				effects[id] = id == NoEffect ? "No enhancement" : EnhancementName(b, id);
		}
		var todos = Todos();
		var shown = Math.Min(todos.Count, 14);
		var chipRows = (effects.Count + 1) / 2;
		var h = 36f + chipRows * 30f + 40f + Math.Max(1, shown) * 30f + (todos.Count > shown ? 26f : 0f) + 12f;
		h = Math.Min(h, L.MapHeight - 60f);
		var back = Ui.Flat(_panelRoot, x, y0, pw, h, new Color(0.05f, 0.07f, 0.14f, 0.96f));
		_panelRect = back.rectTransform;
		Ui.Text(_panelRoot, P.FontBook, P.SizeMain, "Show routes of", x + 12f, y0 + 6f, pw - 24f, 26f, P.TipTitle);
		var y = y0 + 36f;
		var i = 0;
		foreach (var kv in effects)
		{
			var id = kv.Key;
			var on = !HiddenEffects.Contains(id);
			var cx = x + 12f + (i % 2) * ((pw - 30f) / 2f + 6f);
			var cy = y + (i / 2) * 30f;
			Ui.Tab(_panelRoot, PanelButtons, (on ? "" : "Hidden: ") + kv.Value, cx, cy, (pw - 30f) / 2f, 26f, false, () =>
			{
				if (!HiddenEffects.Remove(id))
					HiddenEffects.Add(id);
				_glowFor = null;
				BuildOverlay();
				BuildPanel();
			});
			i++;
		}
		y += chipRows * 30f + 6f;
		Ui.Text(_panelRoot, P.FontBook, P.SizeMain, "To do (" + todos.Count + ")", x + 12f, y, pw - 24f, 26f, P.TipTitle);
		Ui.Text(_panelRoot, P.FontMedium, 13f, "N / U: next to-do / unvisited", x + 140f, y + 3f, pw - 152f, 22f, P.TipNote, TextAlignmentOptions.Right);
		y += 32f;
		if (todos.Count == 0)
			Ui.Text(_panelRoot, P.FontMedium, P.SizeSmall, "Nothing to do. Well run!", x + 12f, y, pw - 24f, 26f, P.TipNote);
		for (var j = 0; j < shown; j++)
		{
			var (kind, b) = todos[j];
			var key = b.ObjectKey;
			var selected = _hasSelection && key == _selectedKey;
			var row = Ui.Image(_panelRoot, Ui.SpriteRow, x + 8f, y, pw - 16f, 27f, selected ? new Color(0.14f, 0.22f, 0.36f, 1f) : new Color(0.09f, 0.12f, 0.19f, 1f));
			Ui.Text(_panelRoot, P.FontMedium, 13f, TodoLabel(kind), x + 16f, y, 120f, 27f, kind == TodoKind.Cut ? L.Red : kind == TodoKind.Switch ? P.CostOk : P.TipWarn);
			Ui.Text(_panelRoot, P.FontMedium, 14f, b.DisplayName ?? "Building", x + 138f, y, pw - 154f, 27f, P.TipBody);
			PanelButtons.Add(new Ui.Clickable { Rect = row.rectTransform, Image = row, Normal = Ui.Sprite(Ui.SpriteRow), Hover = Ui.Sprite(Ui.SpriteRowSelected), Click = () => FocusBuilding(key) });
			y += 30f;
		}
		if (todos.Count > shown)
			Ui.Text(_panelRoot, P.FontMedium, 13f, "+" + (todos.Count - shown) + " more (N cycles through all)", x + 12f, y, pw - 24f, 24f, P.TipNote);
	}

	private static void FocusBuilding(long key)
	{
		var b = Building(key);
		if (b == null)
			return;
		Select(key);
		CentreOn(b.TileX, b.TileY);
	}

	// ---------------------------------------------------------------- keys (item 13)

	private static void HandleKeys()
	{
		if (_net?.Buildings == null || _net.Buildings.Count == 0)
			return;
		if (Input.GetKeyDown(KeyCode.Tab))
		{
			var list = _net.Buildings;
			var at = _hasSelection ? SourceIndex(_selectedKey) : -1;
			var step = Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift) ? -1 : 1;
			for (var n = 0; n < list.Count; n++)
			{
				at = ((at + step) % list.Count + list.Count) % list.Count;
				if (list[at] != null)
				{
					FocusBuilding(list[at].ObjectKey);
					break;
				}
			}
		}
		else if (Input.GetKeyDown(KeyCode.N) || Input.GetKeyDown(KeyCode.U))
		{
			var unvisitedOnly = Input.GetKeyDown(KeyCode.U);
			var todos = Todos();
			if (unvisitedOnly)
				todos.RemoveAll(t => t.Kind != TodoKind.Unvisited);
			if (todos.Count == 0)
			{
				_status = unvisitedOnly ? "Every building has been visited." : "Nothing to do.";
				BuildCard();
				return;
			}
			var next = 0;
			for (var i = 0; i < todos.Count; i++)
			{
				if (_hasSelection && todos[i].B.ObjectKey == _selectedKey)
				{
					next = (i + 1) % todos.Count;
					// Skip further entries of the same building.
					while (next != i && todos[next].B.ObjectKey == _selectedKey)
						next = (next + 1) % todos.Count;
					break;
				}
			}
			_status = TodoLabel(todos[next].Kind) + ": " + todos[next].B.DisplayName;
			FocusBuilding(todos[next].B.ObjectKey);
		}
		else if (Input.GetKeyDown(KeyCode.Alpha1) || Input.GetKeyDown(KeyCode.Alpha2) || Input.GetKeyDown(KeyCode.Alpha3))
		{
			if (!_hasSelection)
				return;
			var tab = Input.GetKeyDown(KeyCode.Alpha1) ? 0 : Input.GetKeyDown(KeyCode.Alpha2) ? 1 : 2;
			if (tab == 2 && !RailNetworkActive(Building(_selectedKey)))
				return;
			_tab = tab;
			_status = null;
			BuildCard();
		}
		else if (Input.GetKeyDown(KeyCode.R))
			ToggleRange();
		else if (Input.GetKeyDown(KeyCode.C))
		{
			var b = _hasSelection ? Building(_selectedKey) : null;
			if (b != null)
				CentreOn(b.TileX, b.TileY);
		}
		else if (Input.GetKeyDown(KeyCode.L))
			TogglePanel();
		else if (Input.GetKeyDown(KeyCode.B))
			OpenPopup(PopupBulk);
		else if (Input.GetKeyDown(KeyCode.H) || Input.GetKeyDown(KeyCode.Slash))
			OpenPopup(PopupPrimer);
	}

	/// <summary>Esc closes the open popup first; true when it did (the viewer stays open).</summary>
	private static bool EscapeExtras()
	{
		if (_popup == PopupNone)
			return false;
		ClosePopup();
		return true;
	}

	// ---------------------------------------------------------------- range overlay (item 9)

	private static void ToggleRange()
	{
		_rangeOn = !_rangeOn;
		if (_rangeOn && !_hasSelection)
			_status = "Select a building to see its range.";
		RefreshRange();
		BuildCard();
	}

	private static void DestroyRange()
	{
		try
		{
			if (_rangeSprite)
				UnityObject.Destroy(_rangeSprite);
			if (_rangeTexture)
				UnityObject.Destroy(_rangeTexture);
		}
		catch
		{
		}
		_rangeSprite = null;
		_rangeTexture = null;
	}

	/// <summary>Shades every tile the selected building's routes can reach (one pixel per tile); pale where a hub refreshed range. Cached per selection and network.</summary>
	private static void RefreshRange()
	{
		if (_rangeImage == null)
			return;
		if (!_rangeOn || !_hasSelection)
		{
			_rangeImage.enabled = false;
			_rangeNote = null;
			return;
		}
		if (_rangeFor == _net && _rangeKey == _selectedKey && _rangeTexture)
		{
			_rangeImage.enabled = true;
			return;
		}
		_rangeFor = _net;
		_rangeKey = _selectedKey;
		_rangeImage.enabled = false;
		DestroyRange();
		if (!Homm3FactoryLogistics.TryGetReach(_selectedKey, out var remaining, out var viaHub, out var width, out var budget, out var fail) || width != _mapW || remaining.Length != _mapW * _mapH)
		{
			_rangeNote = "Range overlay unavailable" + (fail != null ? " (" + fail + ")" : "");
			Ui.LogWarning("viewer: " + _rangeNote);
			return;
		}
		var colour = L.SourceColour(SourceIndex(_selectedKey));
		var pixels = new Color32[_mapW * _mapH];
		var reached = 0;
		for (var y = 0; y < _mapH; y++)
		{
			for (var x = 0; x < _mapW; x++)
			{
				var rem = remaining[x + y * _mapW];
				if (rem < 0)
					continue;
				reached++;
				var k = budget > 0 ? Mathf.Clamp01(rem / (float)budget) : 1f;
				var c = viaHub[x + y * _mapW] ? L.HubRing : colour;
				pixels[x + (_mapH - 1 - y) * _mapW] = new Color32((byte)(c.r * 255f), (byte)(c.g * 255f), (byte)(c.b * 255f), (byte)(255f * (0.16f + 0.24f * k)));
			}
		}
		var texture = new Texture2D(_mapW, _mapH, TextureFormat.RGBA32, false);
		texture.filterMode = FilterMode.Point;
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		texture.SetPixels32(pixels);
		texture.Apply(false, false);
		var sprite = Sprite.Create(texture, new Rect(0f, 0f, _mapW, _mapH), new Vector2(0.5f, 0.5f), 100f);
		if (sprite == null)
		{
			UnityObject.Destroy(texture);
			_rangeNote = "Range overlay could not be drawn";
			return;
		}
		sprite.hideFlags = HideFlags.HideAndDontSave;
		_rangeTexture = texture;
		_rangeSprite = sprite;
		_rangeImage.sprite = sprite;
		_rangeImage.color = Color.white;
		_rangeImage.enabled = true;
		_rangeNote = "Range " + Days(budget) + " from " + (Building(_selectedKey)?.DisplayName ?? "here") + ": " + reached + " tiles (pale = range given back by a hub)";
		Ui.LogInfo("viewer: range overlay for " + _selectedKey + " budget=" + budget + "MP tiles=" + reached);
	}

	// ---------------------------------------------------------------- cut routes (item 10)

	private static void AddCutHit(long source, int x, int y, Vector2 at)
	{
		var hit = Ui.Flat(_overlay, at.x - 14f, at.y - 14f, 28f, 28f, new Color(0f, 0f, 0f, 0.001f));
		CutHits.Add((hit.rectTransform, source, x, y));
	}

	private static bool ClickCut(Vector2 mouse)
	{
		for (var i = CutHits.Count - 1; i >= 0; i--)
		{
			if (!Ui.Over(CutHits[i].Rect, mouse))
				continue;
			_cut = (CutHits[i].Source, CutHits[i].X, CutHits[i].Y);
			OpenPopup(PopupCut);
			return true;
		}
		return false;
	}

	private static List<string> CutFixLines(out string title)
	{
		var lines = new List<string>();
		var source = Building(_cut.Source);
		var enh = source == null ? null : EnhancementName(source, source.ActiveEnhancementId);
		title = "Route cut: " + (enh ?? "route") + " (" + (source?.DisplayName ?? "building") + ")";
		var routes = new List<LogisticsRoute>();
		foreach (var r in Routes())
		{
			if (r == null || !r.Cut || r.FromKey != _cut.Source || r.Tiles == null || r.Tiles.Count == 0)
				continue;
			var last = r.Tiles[r.Tiles.Count - 1];
			if (last.x == _cut.X && last.y == _cut.Y)
				routes.Add(r);
		}
		lines.Add("Why: the route runs out of range here.");
		foreach (var r in routes)
			lines.Add("  -> " + TargetName(r.ToKind, r.ToKey) + ": " + Homm3FactoryLogistics.NeedsRange(r.MissingMp));
		lines.Add("How to fix:");
		// Nearest network building to the cut point: a hub there gives routes their range back.
		LogisticsBuildingView near = null;
		var best = int.MaxValue;
		foreach (var b in _net.Buildings)
		{
			if (b == null || b.ObjectKey == _cut.Source || b.Level != (source?.Level ?? b.Level))
				continue;
			var d = Math.Max(Math.Abs(b.TileX - _cut.X), Math.Abs(b.TileY - _cut.Y));
			if (d < best)
			{
				best = d;
				near = b;
			}
		}
		if (near != null && best <= 12)
			lines.Add("- Build a Logistics Hub at " + near.DisplayName + " (" + best + " tiles from the cut): routes get range back on its tile.");
		else
			lines.Add("- Build a Logistics Hub on a building along the way: routes get range back on its tile.");
		lines.Add("- Build Rail Station levels: each level adds +" + Days(_net.RangeMpPerLevel) + " of range to the whole network.");
		lines.Add("- A Supply Caravan hero standing near the cut also gives range back.");
		var stackLines = 0;
		foreach (var s in _net.BlockingStacks ?? Array.Empty<LogisticsBlockingStack>())
		{
			if (s?.Links == null)
				continue;
			foreach (var r in routes)
			{
				var to = r.ToKind == "hero" ? Homm3FactoryLogisticsEffects.HeroKeyOffset + r.ToKey : r.ToKey;
				if (!ContainsLink(s.Links, r.FromKey, to) || stackLines >= 3)
					continue;
				lines.Add("- Defeat the neutral stack at " + s.TileX + ", " + s.TileY + ": its guard zone forces the long way round.");
				stackLines++;
				break;
			}
		}
		if (FogNear(_cut.X, _cut.Y, 3, source?.Level ?? _level))
			lines.Add("- Explore the fog near the cut: unexplored tiles block routes.");
		lines.Add("- Roads cost less range: a road through here lets the route go further.");
		return lines;
	}

	private static bool ContainsLink(IReadOnlyList<(long from, long to)> links, long from, long to)
	{
		foreach (var l in links)
			if (l.from == from && l.to == to)
				return true;
		return false;
	}

	private static bool FogNear(int cx, int cy, int radius, int level)
	{
		if (!Homm3FactoryLogistics.TryGetViewerSide(out var side))
			return false;
		for (var y = cy - radius; y <= cy + radius; y++)
		{
			for (var x = cx - radius; x <= cx + radius; x++)
			{
				if (x < 0 || y < 0 || x >= _mapW || y >= _mapH)
					continue;
				if (Homm3FactoryLogistics.TryGetTerrainTile(side, x, y, level, out _, out _, out _, out _, out var fogged) && fogged)
					return true;
			}
		}
		return false;
	}

	// ---------------------------------------------------------------- card additions (items 3, 11, 20)

	/// <summary>Card header lines 2 and 3 (Upgrade / Command Center, link status) and the Centre / Range buttons.</summary>
	private static void BuildCardHeaderExtras(LogisticsBuildingView b, float x0, float cw, float tx, float tw, float y0)
	{
		var center = b.UpgradeCenterLevel > 0 ? (b.ViaCommandCenter ? "Command Center " : "Upgrade Center ") + b.UpgradeCenterLevel : "Not yet visited by a Logistics Network hero";
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, center, tx, y0 + 38f, tw - 150f, 22f, b.UpgradeCenterLevel > 0 ? P.TipNote : P.TipWarn);
		var link = LinkStatusOf(b.ObjectKey);
		var isolated = link != null && link.StartsWith("Isolated", StringComparison.Ordinal);
		var linkText = Ui.Text(_cardRoot, P.FontMedium, 14f, link ?? "", tx, y0 + 62f, tw, 22f, isolated ? P.TipWarn : P.TipNote);
		// Route list on hover, with no-path reasons (item 11).
		var key = b.ObjectKey;
		var routeLines = new List<string>();
		foreach (var r in Routes())
		{
			if (r == null || r.FromKey != key)
				continue;
			routeLines.Add("-> " + TargetName(r.ToKind, r.ToKey) + ": " + (r.NoPath ? "no path" : r.Cut ? Homm3FactoryLogistics.NeedsRange(r.MissingMp) : "linked"));
		}
		if (routeLines.Count == 0)
			routeLines.Add("No routes start here (its active enhancement does not send any).");
		Tips.Add(new Tip
		{
			Rect = linkText.rectTransform, Title = "Links from " + (b.DisplayName ?? "this building"), Lines = routeLines.ToArray(),
			More = () =>
			{
				var more = new List<string>();
				foreach (var r in Routes())
					if (r != null && r.FromKey == key && r.NoPath)
						more.Add("No path to " + TargetName(r.ToKind, r.ToKey) + ": " + NoPathReasonOf(r));
				return more.ToArray();
			},
		});
		// Centre and Range toggles (top-right of the header).
		var bx = x0 + cw - 16f - 136f;
		Ui.Button(_cardRoot, CardButtons, "Centre", bx, y0 + 36f, 64f, 24f, true, false, () => CentreOn(b.TileX, b.TileY), 14f);
		Ui.Button(_cardRoot, CardButtons, _rangeOn ? "Hide range" : "Range", bx + 68f, y0 + 36f, 68f, 24f, true, _rangeOn, ToggleRange, 14f);
		if (_rangeOn && _rangeNote != null && _status == null && _statusText != null)
			_statusText.text = _rangeNote;
	}

	// ---------------------------------------------------------------- popups

	private static void OpenPopup(int which)
	{
		_popup = which;
		if (which == PopupBulk)
			ReadBulk();
		HideTip();
		BuildPopup();
	}

	private static void ClosePopup()
	{
		if (_popup == PopupPrimer)
			_primerSeen = true;
		_popup = PopupNone;
		BuildPopup();
	}

	/// <summary>Popup input: modal while open. True when a popup is open (the rest of Tick is skipped).</summary>
	private static bool TickPopup(Vector2 mouse)
	{
		if (_popup == PopupNone)
			return false;
		Ui.HoverButtons(PopupButtons, mouse);
		if (_shownTip != null)
			HideTip();
		if (Input.GetMouseButtonDown(0))
		{
			if (!Ui.ClickButtons(PopupButtons, mouse) && !Ui.Over(_popupRect, mouse))
				ClosePopup();
		}
		else if (Input.GetKeyDown(KeyCode.B) && _popup == PopupBulk || (Input.GetKeyDown(KeyCode.H) || Input.GetKeyDown(KeyCode.Slash)) && _popup == PopupPrimer)
			ClosePopup();
		return true;
	}

	private static void BuildPopup()
	{
		PopupButtons.Clear();
		_popupRect = null;
		if (_popupRoot == null)
			return;
		Ui.ClearChildren(_popupRoot);
		switch (_popup)
		{
			case PopupPrimer:
				BuildPrimer();
				break;
			case PopupCut:
				BuildCutPopup();
				break;
			case PopupBulk:
				BuildBulk();
				break;
		}
	}

	private static RectTransform PopupFrame(float w, float h, string title)
	{
		var x = (L.Width - w) / 2f;
		var y = Math.Max(50f, (L.Height - h) / 2f);
		Ui.Flat(_popupRoot, 0f, 0f, L.Width, L.Height, new Color(0f, 0f, 0f, 0.45f));
		Ui.Flat(_popupRoot, x - 2f, y - 2f, w + 4f, h + 4f, new Color(P.TipTitle.r, P.TipTitle.g, P.TipTitle.b, 0.6f));
		var back = Ui.Flat(_popupRoot, x, y, w, h, new Color(0.04f, 0.06f, 0.12f, 0.99f));
		Ui.Sliced(_popupRoot, P.SpritePanelHeader, x, y, w, 48f, P.PanelSliceMultiplier, Color.clear);
		Ui.Text(_popupRoot, P.FontBook, P.SizeSubHeader, title, x + 20f, y + 8f, w - 40f, 32f, P.TipTitle, TextAlignmentOptions.Center);
		_popupRect = back.rectTransform;
		return back.rectTransform;
	}

	private static float PopupX(float w) => (L.Width - w) / 2f;

	private static float PopupY(float h) => Math.Max(50f, (L.Height - h) / 2f);

	private static float WrappedHeight(string text, float size, float width, float line) =>
		Math.Max(1, Mathf.CeilToInt(Ui.TextWidth(text, size) / width)) * line;

	/// <summary>Primer (item 1) with the glossary and the keys; "Got it" dismisses it for this session; "?" / H reopens.</summary>
	private static void BuildPrimer()
	{
		const float w = 900f, size = 16f, line = 22f;
		var paras = new List<(string Text, Color Colour)>
		{
			("Enhancements turn your mines and dwellings into a network. A hero with Logistics Network builds them on site; after that visit you can manage the building from here.", P.TipBody),
			("Routes run from each enhanced building to the towns, heroes and buildings it helps. A route that runs out of range is cut (red X): click the X to see why and how to fix it.", P.TipBody),
		};
		foreach (var g in GlossaryLines())
			paras.Add(("- " + g, P.TipNote));
		foreach (var k in KeyLines())
			paras.Add((k, P.TipTitle));
		var h = 64f + 60f;
		foreach (var (text, _) in paras)
			h += WrappedHeight(text, size, w - 48f, line) + 6f;
		PopupFrame(w, h, "How the Logistics Network works");
		var x = PopupX(w);
		var y = PopupY(h) + 60f;
		foreach (var (text, colour) in paras)
		{
			var ph = WrappedHeight(text, size, w - 48f, line);
			Ui.Text(_popupRoot, P.FontMedium, size, text, x + 24f, y, w - 48f, ph, colour, TextAlignmentOptions.TopLeft, true);
			y += ph + 6f;
		}
		Ui.Button(_popupRoot, PopupButtons, "Got it", x + w / 2f - 80f, y + 10f, 160f, 36f, true, true, ClosePopup, P.SizeMain);
	}

	private static void BuildCutPopup()
	{
		const float w = 760f, size = 16f, line = 22f;
		var lines = CutFixLines(out var title);
		var h = 64f + 60f;
		foreach (var l in lines)
			h += WrappedHeight(l, size, w - 48f, line) + 4f;
		PopupFrame(w, h, title);
		var x = PopupX(w);
		var y = PopupY(h) + 60f;
		foreach (var l in lines)
		{
			var ph = WrappedHeight(l, size, w - 48f, line);
			var colour = l.StartsWith("  ->", StringComparison.Ordinal) ? L.Red : l.StartsWith("-", StringComparison.Ordinal) ? P.TipBody : P.TipTitle;
			Ui.Text(_popupRoot, P.FontMedium, size, l, x + 24f, y, w - 48f, ph, colour, TextAlignmentOptions.TopLeft, true);
			y += ph + 4f;
		}
		var cut = _cut;
		Ui.Button(_popupRoot, PopupButtons, "Select source", x + w / 2f - 250f, y + 10f, 160f, 34f, Building(cut.Source) != null, false, () =>
		{
			ClosePopup();
			FocusBuilding(cut.Source);
		}, P.SizeSmall);
		Ui.Button(_popupRoot, PopupButtons, "Centre on cut", x + w / 2f - 80f, y + 10f, 160f, 34f, true, false, () =>
		{
			ClosePopup();
			CentreOn(cut.X, cut.Y);
		}, P.SizeSmall);
		Ui.Button(_popupRoot, PopupButtons, "Close", x + w / 2f + 90f, y + 10f, 160f, 34f, true, false, ClosePopup, P.SizeSmall);
	}

	// ---------------------------------------------------------------- recruit all (bulk remote recruitment)

	private const int BulkPerPage = 11;

	private static string BulkKey(LogisticsBulkRow r) => r.DwellingKey + "|" + r.UnitSid + "|" + (r.Upgraded ? 1 : 0);

	private static void ReadBulk()
	{
		if (!Homm3FactoryLogistics.TryGetBulkHire(out _bulkRows, out _bulkTargets, out _bulkFail))
		{
			_bulkRows = null;
			_bulkTargets = null;
		}
		if (_bulkRows != null)
		{
			var keep = new HashSet<string>(StringComparer.Ordinal);
			foreach (var r in _bulkRows)
				keep.Add(BulkKey(r));
			foreach (var k in new List<string>(BulkCounts.Keys))
				if (!keep.Contains(k))
					BulkCounts.Remove(k);
		}
		if (_bulkTargets != null && _bulkTargets.Count > 0)
			_bulkTarget = (_bulkTarget % _bulkTargets.Count + _bulkTargets.Count) % _bulkTargets.Count;
	}

	private static int BulkCount(LogisticsBulkRow r) => BulkCounts.TryGetValue(BulkKey(r), out var n) ? n : 0;

	private static void SetBulkCount(LogisticsBulkRow r, int n) => BulkCounts[BulkKey(r)] = Math.Max(0, Math.Min(r.Available, n));

	private static void PopupStep(string glyph, float x, float cy, Action change)
	{
		const float s = 28f;
		var image = Ui.Image(_popupRoot, Ui.SpriteTab, x, cy - s / 2f, s, s, new Color(0.12f, 0.16f, 0.26f, 1f));
		Ui.Text(_popupRoot, P.FontBook, P.SizeSubHeader, glyph, x, cy - s / 2f, s, s, P.ButtonText, TextAlignmentOptions.Center);
		PopupButtons.Add(new Ui.Clickable
		{
			Rect = image.rectTransform, Image = image, Normal = Ui.Sprite(Ui.SpriteTab), Hover = Ui.Sprite(Ui.SpriteTabHover),
			Click = () =>
			{
				change();
				BuildPopup();
			},
		});
	}

	private static void BuildBulk()
	{
		const float w = 1200f, h = 800f;
		PopupFrame(w, h, "Recruit all through the Rail Network");
		var x = PopupX(w);
		var y0 = PopupY(h);
		if (_bulkRows == null)
		{
			Ui.Text(_popupRoot, P.FontMedium, P.SizeMain, "Dwellings unreadable: " + (_bulkFail ?? "unknown"), x + 24f, y0 + 80f, w - 48f, 30f, P.TipWarn, TextAlignmentOptions.Center);
			Ui.Button(_popupRoot, PopupButtons, "Close", x + w / 2f - 80f, y0 + h - 56f, 160f, 36f, true, false, ClosePopup, P.SizeMain);
			return;
		}
		if (_bulkRows.Count == 0)
		{
			Ui.Text(_popupRoot, P.FontMedium, P.SizeMain, "No dwelling with the Rail Network as its active enhancement has units to hire.", x + 24f, y0 + 80f, w - 48f, 30f, P.TipNote, TextAlignmentOptions.Center);
			Ui.Button(_popupRoot, PopupButtons, "Close", x + w / 2f - 80f, y0 + h - 56f, 160f, 36f, true, false, ClosePopup, P.SizeMain);
			return;
		}

		// Delivery target: [<] name [>] and the army it lands in.
		var ty = y0 + 74f;
		Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, "Deliver to", x + 24f, ty - 13f, 110f, 26f, P.TipNote);
		(string Kind, long Key) target = (null, 0);
		if (_bulkTargets == null || _bulkTargets.Count == 0)
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, "No town or hero in range of any Rail Network dwelling", x + 140f, ty - 13f, 520f, 26f, P.TipWarn);
		else
		{
			var t = _bulkTargets[_bulkTarget];
			target = (t.Kind, t.Key);
			if (_bulkTargets.Count > 1)
			{
				PopupStep("<", x + 140f, ty, () => _bulkTarget = (_bulkTarget - 1 + _bulkTargets.Count) % _bulkTargets.Count);
				PopupStep(">", x + 452f, ty, () => _bulkTarget = (_bulkTarget + 1) % _bulkTargets.Count);
			}
			Ui.Text(_popupRoot, P.FontMedium, P.SizeMain, t.Name, x + 172f, ty - 14f, 276f, 28f, P.TipBody, TextAlignmentOptions.Center);
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, DeliveryLine(DeliveryOf(t.Kind, t.Key, null), null), x + 500f, ty - 13f, w - 524f, 26f, P.TipNote);
		}

		// Column headers.
		var hy = y0 + 104f;
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Unit", x + 60f, hy, 200f, 22f, P.TipNote);
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Dwelling", x + 300f, hy, 200f, 22f, P.TipNote);
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Available", x + 520f, hy, 90f, 22f, P.TipNote);
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Each", x + 610f, hy, 170f, 22f, P.TipNote, TextAlignmentOptions.Center);
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Count", x + 790f, hy, 220f, 22f, P.TipNote, TextAlignmentOptions.Center);
		Ui.Text(_popupRoot, P.FontMedium, 14f, "Cost", x + 1012f, hy, 170f, 22f, P.TipNote, TextAlignmentOptions.Center);

		var pages = Math.Max(1, (_bulkRows.Count + BulkPerPage - 1) / BulkPerPage);
		_bulkPage = Math.Max(0, Math.Min(_bulkPage, pages - 1));
		var y = y0 + 130f;
		for (var i = _bulkPage * BulkPerPage; i < Math.Min(_bulkRows.Count, (_bulkPage + 1) * BulkPerPage); i++)
		{
			var row = _bulkRows[i];
			var deliverable = target.Kind != null && row.Targets.Contains(target);
			var count = deliverable ? BulkCount(row) : 0;
			Ui.Flat(_popupRoot, x + 14f, y, w - 28f, 42f, i % 2 == 0 ? new Color(0.08f, 0.11f, 0.18f, 1f) : new Color(0.06f, 0.08f, 0.14f, 1f));
			var cy = y + 21f;
			var portrait = Ui.UnitPortrait(row.UnitSid);
			if (portrait != null)
				Ui.SpriteImage(_popupRoot, portrait, x + 20f, y + 3f, 36f, 36f);
			var name = Homm3UnitDisplayNames.Resolve(row.UnitSid) + (row.Upgraded ? " (upgraded)" : "");
			Ui.Text(_popupRoot, P.FontBook, P.SizeSmall, name, x + 60f, cy - 13f, 236f, 26f, deliverable ? P.TipBody : P.TipNote);
			Ui.Text(_popupRoot, P.FontMedium, 14f, row.DwellingName, x + 300f, cy - 12f, 216f, 24f, P.TipNote);
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, Ui.N(row.Available), x + 520f, cy - 13f, 80f, 26f, P.TipBody);
			Ui.Cost(_popupRoot, row.UnitCost, x + 610f, cy, 170f, 20f, 14f, P.TipBody);
			if (deliverable)
			{
				var r = row;
				PopupStep("-", x + 800f, cy, () => SetBulkCount(r, BulkCount(r) - (ShiftHeld() ? 10 : 1)));
				Ui.Text(_popupRoot, P.FontBook, P.SizeMain, Ui.N(count), x + 830f, cy - 14f, 70f, 28f, count > 0 ? P.TipTitle : P.TipBody, TextAlignmentOptions.Center);
				PopupStep("+", x + 902f, cy, () => SetBulkCount(r, BulkCount(r) + (ShiftHeld() ? 10 : 1)));
				Ui.Button(_popupRoot, PopupButtons, "Max", x + 936f, cy - 14f, 66f, 28f, true, false, () =>
				{
					var others = new List<IReadOnlyDictionary<string, int>>();
					foreach (var o in _bulkRows)
						if (o != r && BulkCount(o) > 0 && o.PriceOf != null && o.Targets.Contains(target))
							others.Add(o.PriceOf(BulkCount(o)));
					int lo = 0, hi = r.Available;
					while (lo < hi)
					{
						var mid = (lo + hi + 1) / 2;
						var trial = new List<IReadOnlyDictionary<string, int>>(others) { r.PriceOf(mid) };
						if (Homm3FactoryLogistics.CanAffordNow(Homm3FactoryLogistics.SumCost(trial), out _))
							lo = mid;
						else
							hi = mid - 1;
					}
					SetBulkCount(r, lo);
					BuildPopup();
				}, 14f);
				if (count > 0 && row.PriceOf != null)
					Ui.Cost(_popupRoot, row.PriceOf(count), x + 1012f, cy, 170f, 20f, 14f, P.TipBody);
			}
			else
			{
				Ui.Text(_popupRoot, P.FontMedium, 14f, target.Kind == "hero" && row.HeroNote != null ? "Heroes: " + row.HeroNote : "Not in range of this target", x + 790f, cy - 12f, 390f, 24f, P.TipWarn, TextAlignmentOptions.Center);
			}
			y += 44f;
		}
		if (pages > 1)
		{
			var py = y0 + 130f + BulkPerPage * 44f + 18f;
			PopupStep("<", x + w / 2f - 100f, py, () => _bulkPage = Math.Max(0, _bulkPage - 1));
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, "Page " + (_bulkPage + 1) + " / " + pages, x + w / 2f - 66f, py - 13f, 132f, 26f, P.TipBody, TextAlignmentOptions.Center);
			PopupStep(">", x + w / 2f + 72f, py, () => _bulkPage = Math.Min(pages - 1, _bulkPage + 1));
		}

		// Total against current resources, then the buttons.
		var orders = new List<(LogisticsBulkRow Row, int Count)>();
		var costs = new List<IReadOnlyDictionary<string, int>>();
		var units = 0;
		foreach (var r in _bulkRows)
		{
			var n = BulkCount(r);
			if (n <= 0 || target.Kind == null || !r.Targets.Contains(target) || r.PriceOf == null)
				continue;
			orders.Add((r, n));
			costs.Add(r.PriceOf(n));
			units += n;
		}
		var total = Homm3FactoryLogistics.SumCost(costs);
		string missing = null;
		var affordable = orders.Count > 0 && Homm3FactoryLogistics.CanAffordNow(total, out missing);
		var totalY = y0 + h - 104f;
		Ui.Text(_popupRoot, P.FontBook, P.SizeMain, "Total: " + Ui.N(units) + " unit" + (units == 1 ? "" : "s") + " from " + orders.Count + " stock" + (orders.Count == 1 ? "" : "s"), x + 24f, totalY - 14f, 420f, 28f, P.TipTitle);
		if (orders.Count > 0)
			Ui.Cost(_popupRoot, total, x + 440f, totalY, 460f, 22f, P.SizeSmall, affordable ? P.TipBody : P.CostBad);
		if (orders.Count > 0 && !affordable)
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, "Not enough " + (missing ?? "resources"), x + 900f, totalY - 13f, 280f, 26f, P.CostBad);
		var by = y0 + h - 62f;
		var tgt = target;
		Ui.Button(_popupRoot, PopupButtons, "Max all", x + 24f, by, 150f, 36f, tgt.Kind != null, false, () =>
		{
			var counts = Homm3FactoryLogistics.MaxAll(_bulkRows, tgt);
			for (var i = 0; i < counts.Length; i++)
				SetBulkCount(_bulkRows[i], counts[i]);
			_bulkStatus = null;
			BuildPopup();
		}, P.SizeSmall);
		Ui.Button(_popupRoot, PopupButtons, "Clear", x + 184f, by, 120f, 36f, orders.Count > 0, false, () =>
		{
			BulkCounts.Clear();
			BuildPopup();
		}, P.SizeSmall);
		Ui.Button(_popupRoot, PopupButtons, "Hire all", x + w / 2f - 90f, by, 180f, 36f, affordable, true, () => HireAll(orders, tgt), P.SizeMain);
		Ui.Button(_popupRoot, PopupButtons, "Close", x + w - 174f, by, 150f, 36f, true, false, ClosePopup, P.SizeSmall);
		if (_bulkStatus != null)
			Ui.Text(_popupRoot, P.FontMedium, P.SizeSmall, _bulkStatus, x + 24f, by - 36f, w - 48f, 26f, _bulkStatusOk ? P.CostOk : P.CostBad, TextAlignmentOptions.Center);
		else if (target.Kind != null && orders.Count > 0)
			Ui.Text(_popupRoot, P.FontMedium, 14f, "Each stock is hired in turn into the same army; it stops at the first refusal (e.g. no free slot) and keeps what was hired.", x + 24f, by - 34f, w - 48f, 24f, P.TipNote, TextAlignmentOptions.Center);
	}

	private static void HireAll(List<(LogisticsBulkRow Row, int Count)> orders, (string Kind, long Key) target)
	{
		var ok = Homm3FactoryLogistics.TryHireAll(orders, target.Kind, target.Key, out var report, out var hired);
		Ui.LogInfo("viewer: recruit all " + orders.Count + " orders -> " + target.Kind + " " + target.Key + ": " + report);
		_bulkStatus = report;
		_bulkStatusOk = ok;
		if (hired > 0)
		{
			for (var i = 0; i < hired && i < orders.Count; i++)
				BulkCounts.Remove(BulkKey(orders[i].Row));
			if (Homm3FactoryLogistics.TryGetNetwork(out var net, out var netFail) && net?.Buildings != null)
				_net = net;
			else
				Ui.LogWarning("viewer: network re-read failed after recruit all (" + netFail + ")");
			InvalidateExtras();
			ReadRemote();
			BuildOverlay();
			BuildCard();
		}
		Deliveries.Clear();
		ReadBulk();
		BuildPopup();
	}
}
