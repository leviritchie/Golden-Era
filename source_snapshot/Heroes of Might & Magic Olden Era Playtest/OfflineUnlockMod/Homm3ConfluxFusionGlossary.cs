using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Hex.Configs;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using W = OfflineUnlockMod.Homm3DungeonWarCaptivesWindowLayout;
using G = OfflineUnlockMod.Homm3ConfluxFusionGlossaryLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// The Fusion Glossary: an encyclopedia of every Elemental Fusion (stage I pairs and stage II recipes from
/// fusion_config.json), opened from the "?" database button in the fusion panel's header (user-approved mockup
/// tools/conflux_fusion/glossary_mockup.py, 2026-11-15). It is drawn on the fusion panel's canvas, above the panel, in
/// the same native modal shell; Esc or the close button closes it and the panel underneath is untouched.
/// Left: search field (typing is read from Input.inputString while the glossary is open), stage tabs, a sortable list
/// (click a column header; again to reverse), mouse wheel and a draggable scrollbar. Right: the selected fusion's card,
/// stats, family tree and abilities.
/// Data is read live when the glossary opens: stats from the loaded UnitLogicConfig, ability / passive cards from the
/// loaded UnitViewConfig, names and texts from the installed Core's english Lang (units.json / unitsAbility.json).
/// The game fills ability-text numbers ({0}, {1}...) per unit instance in its native tooltip (an ability wrapper bound
/// to a live battle unit); the glossary has no such unit, so it shows "#" for each number instead of inventing one.
/// </summary>
internal static class Homm3ConfluxFusionGlossary
{
	internal const string ButtonTooltip = "Fusion Glossary";

	internal sealed class Card
	{
		internal string Name;
		internal string Text;
		internal string Icon;
		internal bool Active;
	}

	internal sealed class Entry
	{
		internal string Sid;
		internal string Name;
		internal int Stage;
		internal string[] ParentSids;
		internal string[] ParentNames;
		internal int Rank;
		internal bool HasStats;
		internal int Hp, Attack, Defence, DamageMin, DamageMax, Speed, Initiative;
		internal bool Ranged;
		internal bool Flying;
		internal readonly List<Card> Cards = new();
		internal string Hay;
	}

	private enum SortKey { Name, Parents, Rank, Hp, Attack, Defence, Damage, Speed, Initiative }

	private static readonly (SortKey Key, string Label, float Width, bool Wrap, TextAlignmentOptions Align)[] Columns =
	{
		(SortKey.Name, "Name", 205f, true, TextAlignmentOptions.Left),
		(SortKey.Parents, "Fused from", 245f, true, TextAlignmentOptions.Left),
		(SortKey.Rank, "Needs", 92f, false, TextAlignmentOptions.Center),
		(SortKey.Hp, "HP", 58f, false, TextAlignmentOptions.Center),
		(SortKey.Attack, "Atk", 50f, false, TextAlignmentOptions.Center),
		(SortKey.Defence, "Def", 50f, false, TextAlignmentOptions.Center),
		(SortKey.Damage, "Damage", 78f, false, TextAlignmentOptions.Center),
		(SortKey.Speed, "Spd", 48f, false, TextAlignmentOptions.Center),
		(SortKey.Initiative, "Init", 48f, false, TextAlignmentOptions.Center),
	};

	/// <summary>Plain attack / flying cards the list leaves out (their meaning is already in the trait line).</summary>
	private static readonly HashSet<string> TrivialCardTokens = new(StringComparer.Ordinal)
	{
		"h3_common_melee_attack_name", "h3_common_ranged_attack_name", "base_passive_flyer_name", "base_passive_melee_attack_no_counter_name",
	};
	private static readonly HashSet<string> TrivialCardNames = new(StringComparer.Ordinal) { "Melee Attack", "Ranged Attack", "Flying" };
	private const string FlyingToken = "base_passive_flyer_name";

	private static readonly Homm3LangTokenFile AbilityTexts = new("Lang/english/texts/unitsAbility.json", "unit ability texts");
	private static readonly Regex Tags = new("<[^>]+>", RegexOptions.Compiled);
	private static readonly Regex Numbers = new(@"\{\d+\}", RegexOptions.Compiled);

	private static readonly Dictionary<string, Sprite> Sprites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingSprites = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, Sprite> Icons = new(StringComparer.Ordinal);

	private static List<Entry> _entries;
	private static Dictionary<string, Entry> _bySid;
	private static Homm3ConfluxFusionConfig _entriesConfig;

	// Window state.
	private static RectTransform _root;
	private static RectTransform _win;
	private static RectTransform _listLayer;
	private static RectTransform _detailLayer;
	private static TextMeshProUGUI _searchText;
	private static UnityImage _searchField;
	private static string _query = "";
	private static int _stage;
	private static SortKey _sort = SortKey.Name;
	private static bool _desc;
	private static string _selected;
	private static int _start;
	private static float _wheel;
	private static List<Entry> _rows = new();
	private static bool _thumbDrag;
	private static float _thumbGrabOffset;
	/// <summary>Shell buttons (close) live as long as the window; list buttons (tabs, headers) are rebuilt with the list.</summary>
	private static readonly List<(UnityImage Image, Sprite Normal, Sprite Hover, Action Click)> ShellButtons = new();
	private static readonly List<(UnityImage Image, Sprite Normal, Sprite Hover, Action Click)> Buttons = new();
	private static readonly List<(float Y, UnityImage Hover, string Sid)> RowHits = new();

	// The open button in the fusion panel header.
	private static UnityImage _openButton;
	private static RectTransform _openTip;

	internal static bool IsOpen => _root != null;

	private static readonly Dictionary<string, Entry> Described = new(StringComparer.Ordinal);

	/// <summary>One unit's stats and ability cards for other panels (Factory Logistics hire tab); read once per sid.</summary>
	internal static Entry DescribeUnit(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		if (Described.TryGetValue(sid, out var e))
			return e;
		e = new Entry { Sid = sid, Name = Homm3UnitDisplayNames.Resolve(sid) };
		ReadLogic(e);
		ReadView(e);
		Described[sid] = e;
		return e;
	}

	// ---------------------------------------------------------------- the panel's "?" button

	/// <summary>
	/// The native database button ("?") centred at (cx, cy) in the panel window, plus its hidden "Fusion Glossary" tooltip.
	/// Returns the image and its normal / hover sprites for the panel's button list (it calls <see cref="Open"/> on click).
	/// </summary>
	internal static (UnityImage Image, Sprite Normal, Sprite Hover) AddOpenButton(RectTransform window, float cx, float cy)
	{
		ResolveSprites(false);
		var normal = Sprite(G.SpriteDatabase);
		var hover = Sprite(G.SpriteDatabaseHover);
		var size = G.OpenButtonSize;
		var image = A.AddSpriteImage(window, "GlossaryButton", normal, cx - size / 2f, cy - size / 2f, size, size);
		image.preserveAspect = true;
		if (normal == null)
		{
			// Sprite not loaded: an invisible hit box with a "?" glyph keeps the glossary reachable.
			image.color = new Color(0f, 0f, 0f, 0.01f);
			A.AddText(window, P.FontBook, P.SizeHeaderBig, "?", cx - size / 2f, cy - size / 2f, size, size, P.TipTitle, TextAlignmentOptions.Center);
		}
		_openButton = image;
		var tipW = G.OpenTipWidth;
		var tip = A.NewRect("GlossaryTip", window);
		A.Place(tip, cx - tipW + size / 2f, cy + size / 2f + 4f, tipW, G.OpenTipHeight);
		var back = A.NewImage("Back", tip, Sprite(G.SpriteRow), new Color(0.05f, 0.07f, 0.11f, 0.95f));
		A.Stretch(back.rectTransform);
		if (back.sprite != null)
		{
			back.type = UnityImage.Type.Sliced;
			back.pixelsPerUnitMultiplier = 1f;
		}
		A.AddText(tip, P.FontMedium, P.SizeSmall, ButtonTooltip, 0f, 0f, tipW, G.OpenTipHeight, P.TipTitle, TextAlignmentOptions.Center);
		tip.gameObject.SetActive(false);
		_openTip = tip;
		return (image, normal, hover);
	}

	/// <summary>Panel hover pass: shows the button's tooltip while the mouse is on it.</summary>
	internal static void TickOpenButton(Vector2 mouse, bool dragging)
	{
		if (_openTip == null)
			return;
		var on = !dragging && _openButton != null && RectTransformUtility.RectangleContainsScreenPoint(_openButton.rectTransform, mouse, null);
		if (_openTip.gameObject.activeSelf != on)
			_openTip.gameObject.SetActive(on);
	}

	/// <summary>The panel rebuilt or closed: its button objects are gone.</summary>
	internal static void ForgetOpenButton()
	{
		_openButton = null;
		_openTip = null;
	}

	// ---------------------------------------------------------------- open / close

	/// <summary>Builds the glossary on the panel's canvas, above the panel. False (logged) when it cannot.</summary>
	internal static bool Open(Transform canvas, Homm3ConfluxFusionConfig config)
	{
		if (_root != null || canvas == null || config == null)
			return false;
		try
		{
			ResolveSprites(true);
			EnsureEntries(config);
			_root = A.NewRect("FusionGlossary", canvas);
			A.Stretch(_root);
			var block = A.NewImage("Block", _root, null, new Color(0f, 0f, 0f, P.BlockAlpha));
			A.Stretch(block.rectTransform);
			block.raycastTarget = true;
			_win = A.NewRect("Window", _root);
			_win.anchorMin = _win.anchorMax = _win.pivot = new Vector2(0.5f, 0.5f);
			_win.anchoredPosition = Vector2.zero;
			_win.sizeDelta = new Vector2(G.Width, G.Height);
			_query = "";
			_stage = 0;
			_sort = SortKey.Name;
			_desc = false;
			_start = 0;
			_wheel = 0f;
			_thumbDrag = false;
			BuildShell();
			Filter();
			if (_selected == null || !_bySid.ContainsKey(_selected))
				_selected = _rows.Count > 0 ? _rows[0].Sid : null;
			BuildList();
			BuildDetail();
			Homm3ConfluxFusionRuntime.LogEvent("glossary opened: " + _entries.Count + " fusions");
			return true;
		}
		catch (Exception ex)
		{
			Homm3ConfluxFusionRuntime.LogWarning("glossary build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message);
			Close();
			return false;
		}
	}

	internal static void Close()
	{
		var root = _root;
		_root = null;
		_win = null;
		_listLayer = null;
		_detailLayer = null;
		_searchText = null;
		_searchField = null;
		_thumbDrag = false;
		ShellButtons.Clear();
		Buttons.Clear();
		RowHits.Clear();
		if (root == null)
			return;
		try
		{
			UnityObject.Destroy(root.gameObject);
		}
		catch
		{
		}
	}

	/// <summary>The canvas went away under the glossary (panel closed): drop the references only.</summary>
	internal static void Forget()
	{
		_root = null;
		Close();
		ForgetOpenButton();
	}

	// ---------------------------------------------------------------- input (from the panel's Tick)

	internal static void Tick(Vector2 mouse)
	{
		if (_root == null || _win == null)
			return;
		try
		{
			// Esc closes the glossary only; the panel underneath stays open.
			if (Input.GetKeyDown(KeyCode.Escape))
			{
				Close();
				return;
			}
			TickTyping();
			if (_root == null)
				return;
			var p = Local(mouse);
			TickHover(mouse, p);
			TickWheel(p);
			TickMouse(mouse, p);
		}
		catch (Exception ex)
		{
			// A glossary fault closes the glossary, never the fusion panel (which would refund the cast).
			Homm3ConfluxFusionRuntime.LogWarning("glossary input failed; closing the glossary: " + ex.GetBaseException().Message);
			Close();
		}
	}

	private static void TickTyping()
	{
		var typed = Input.inputString;
		var query = _query;
		var sawBackspace = false;
		if (!string.IsNullOrEmpty(typed))
		{
			foreach (var ch in typed)
			{
				if (ch == '\b')
				{
					sawBackspace = true;
					if (query.Length > 0)
						query = query.Substring(0, query.Length - 1);
				}
				else if (!char.IsControl(ch) && query.Length < G.MaxQueryLength)
				{
					query += ch;
				}
			}
		}
		if (!sawBackspace && Input.GetKeyDown(KeyCode.Backspace) && query.Length > 0)
			query = query.Substring(0, query.Length - 1);
		if (string.Equals(query, _query, StringComparison.Ordinal))
			return;
		_query = query;
		UpdateSearchText();
		_start = 0;
		Filter();
		BuildList();
	}

	private static void TickHover(Vector2 mouse, Vector2 p)
	{
		foreach (var list in new[] { ShellButtons, Buttons })
		{
			foreach (var (image, normal, hover, _) in list)
			{
				if (image == null)
					continue;
				var sprite = !_thumbDrag && Over(image.rectTransform, mouse) ? hover : normal;
				if (sprite != null && image.sprite != sprite)
					image.sprite = sprite;
			}
		}
		if (_searchField != null)
		{
			var sprite = Over(_searchField.rectTransform, mouse) ? Sprite(G.SpriteKeyFieldHover) ?? Sprite(G.SpriteKeyField) : Sprite(G.SpriteKeyField);
			if (sprite != null && _searchField.sprite != sprite)
				_searchField.sprite = sprite;
		}
		var row = _thumbDrag ? -1 : RowAt(p);
		for (var i = 0; i < RowHits.Count; i++)
		{
			var hover = RowHits[i].Hover;
			if (hover != null)
				hover.enabled = i == row;
		}
	}

	private static void TickWheel(Vector2 p)
	{
		var delta = Input.mouseScrollDelta.y;
		if (delta == 0f || p.x < 0f || p.x > G.Width || p.y < 0f || p.y > G.Height)
			return;
		// The detail page has no scrolling; the wheel always scrolls the list.
		_wheel += -delta * G.WheelRows;
		var step = (int)_wheel;
		if (step == 0)
			return;
		_wheel -= step;
		ScrollTo(_start + step);
	}

	private static void TickMouse(Vector2 mouse, Vector2 p)
	{
		var visible = VisibleRows();
		var trackY = G.ListY0;
		var trackH = visible * G.RowHeight;
		var max = Math.Max(0, _rows.Count - visible);
		if (_thumbDrag)
		{
			if (!Input.GetMouseButton(0))
			{
				_thumbDrag = false;
				return;
			}
			var thumbH = ThumbHeight(visible, trackH);
			var free = trackH - thumbH;
			if (free > 0f && max > 0)
				ScrollTo(Mathf.RoundToInt((p.y - _thumbGrabOffset - trackY) / free * max));
			return;
		}
		if (!Input.GetMouseButtonDown(0))
			return;
		foreach (var list in new[] { ShellButtons, Buttons })
		{
			foreach (var (image, _, _, click) in list)
			{
				if (image != null && Over(image.rectTransform, mouse))
				{
					click();
					return;
				}
			}
		}
		var sx = ScrollX();
		if (max > 0 && p.x >= sx - 4f && p.x <= sx + G.ScrollWidth + 4f && p.y >= trackY && p.y <= trackY + trackH)
		{
			var thumbH = ThumbHeight(visible, trackH);
			var thumbY = trackY + (trackH - thumbH) * _start / max;
			if (p.y < thumbY || p.y > thumbY + thumbH)
			{
				// Track click: jump so the thumb centres on the click, then keep dragging from there.
				var free = trackH - thumbH;
				ScrollTo(Mathf.RoundToInt((p.y - thumbH / 2f - trackY) / Math.Max(1f, free) * max));
				thumbY = trackY + (trackH - thumbH) * _start / max;
			}
			_thumbDrag = true;
			_thumbGrabOffset = p.y - thumbY;
			return;
		}
		var row = RowAt(p);
		if (row >= 0 && row < RowHits.Count)
		{
			var sid = RowHits[row].Sid;
			if (!string.Equals(sid, _selected, StringComparison.Ordinal))
			{
				_selected = sid;
				BuildList();
				BuildDetail();
			}
		}
	}

	private static void ScrollTo(int start)
	{
		var max = Math.Max(0, _rows.Count - VisibleRows());
		start = Math.Max(0, Math.Min(max, start));
		if (start == _start)
			return;
		_start = start;
		BuildList();
	}

	private static int RowAt(Vector2 p)
	{
		if (p.x < G.ListX || p.x > G.ListX + ListWidth() || p.y < G.ListY0)
			return -1;
		var i = (int)((p.y - G.ListY0) / G.RowHeight);
		if (i < 0 || i >= RowHits.Count || p.y - G.ListY0 - i * G.RowHeight > G.RowHeight - G.RowGap)
			return -1;
		return i;
	}

	/// <summary>Screen point to window space (top-left origin, y down).</summary>
	private static Vector2 Local(Vector2 mouse)
	{
		if (_win == null || !RectTransformUtility.ScreenPointToLocalPointInRectangle(_win, mouse, null, out var local))
			return new Vector2(-1f, -1f);
		return new Vector2(local.x + G.Width / 2f, G.Height / 2f - local.y);
	}

	private static bool Over(RectTransform rect, Vector2 mouse) => rect != null && RectTransformUtility.RectangleContainsScreenPoint(rect, mouse, null);

	// ---------------------------------------------------------------- filter / sort

	private static void Filter()
	{
		var q = _query.Trim();
		_rows = new List<Entry>();
		foreach (var e in _entries)
		{
			if (_stage != 0 && e.Stage != _stage)
				continue;
			if (q.Length > 0 && e.Hay.IndexOf(q, StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			_rows.Add(e);
		}
		_rows.Sort(Compare);
		_start = Math.Max(0, Math.Min(_start, _rows.Count - VisibleRows()));
	}

	private static int Compare(Entry a, Entry b)
	{
		int c;
		switch (_sort)
		{
			case SortKey.Parents:
				c = string.Compare(string.Join(" ", a.ParentNames), string.Join(" ", b.ParentNames), StringComparison.OrdinalIgnoreCase);
				break;
			case SortKey.Rank: c = a.Rank.CompareTo(b.Rank); break;
			case SortKey.Hp: c = a.Hp.CompareTo(b.Hp); break;
			case SortKey.Attack: c = a.Attack.CompareTo(b.Attack); break;
			case SortKey.Defence: c = a.Defence.CompareTo(b.Defence); break;
			case SortKey.Damage: c = (a.DamageMin + a.DamageMax).CompareTo(b.DamageMin + b.DamageMax); break;
			case SortKey.Speed: c = a.Speed.CompareTo(b.Speed); break;
			case SortKey.Initiative: c = a.Initiative.CompareTo(b.Initiative); break;
			default: c = 0; break;
		}
		if (c == 0)
			c = string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase);
		if (c == 0)
			c = string.CompareOrdinal(a.Sid, b.Sid);
		return _desc ? -c : c;
	}

	private static void SetSort(SortKey key)
	{
		if (_sort == key)
		{
			_desc = !_desc;
		}
		else
		{
			_sort = key;
			// Text columns start A-Z, number columns start with the highest.
			_desc = key != SortKey.Name && key != SortKey.Parents && key != SortKey.Rank;
		}
		Filter();
		BuildList();
	}

	private static void SetStage(int stage)
	{
		if (_stage == stage)
			return;
		_stage = stage;
		_start = 0;
		Filter();
		BuildList();
	}

	// ---------------------------------------------------------------- build

	private static float ListWidth()
	{
		var w = G.ThumbColumn;
		foreach (var col in Columns)
			w += col.Width;
		return w;
	}

	private static float ScrollX() => G.ListX + ListWidth() + G.ScrollGap;

	private static int VisibleRows() => Math.Max(1, (int)((G.Height - G.ListBottomMargin - G.ListY0) / G.RowHeight));

	private static float ThumbHeight(int visible, float trackH) => Math.Max(G.ScrollThumbMin, trackH * visible / Math.Max(1, _rows.Count));

	/// <summary>The fusion panel's native modal shell at glossary size, the title, the search field and the close button.</summary>
	private static void BuildShell()
	{
		var w = G.Width;
		var h = G.Height;
		var plate = new Color(0.08f, 0.1f, 0.15f, 0.98f);
		Img(_win, W.SpriteRecruitBack, 0f, 0f, w, h, plate);
		Sliced(_win, W.SpriteRecruitGradient, 0f, 0f, w, h, 1f, Color.clear);
		Sliced(_win, W.SpriteRecruitBackFrame, 0f, 0f, w, h, 1f, Color.clear);
		Sliced(_win, W.SpriteRecruitFrame, 0f, 0f, w, h, 1f, new Color(0.55f, 0.47f, 0.3f, 0.6f));
		var c = W.RecruitCorner;
		Img(_win, W.SpriteRecruitCorner, 0f, 0f, c, c, Color.clear);
		Flip(Img(_win, W.SpriteRecruitCorner, w - c, 0f, c, c, Color.clear), true, false);
		Flip(Img(_win, W.SpriteRecruitCorner, 0f, h - c, c, c, Color.clear), false, true);
		Flip(Img(_win, W.SpriteRecruitCorner, w - c, h - c, c, c, Color.clear), true, true);
		Img(_win, W.SpriteRecruitDecorFooter, w / 2f - W.RecruitDecorFooterWidth / 2f, h - W.RecruitDecorFooterHeight, W.RecruitDecorFooterWidth, W.RecruitDecorFooterHeight, Color.clear);
		Sliced(_win, W.SpriteRecruitHeader, -W.RecruitHeaderOverhang / 2f, 0f, w + W.RecruitHeaderOverhang, W.RecruitHeaderHeight, 1f, plate);
		Img(_win, W.SpriteRecruitDecorHeader, w / 2f - W.RecruitDecorHeaderWidth / 2f, -W.RecruitFrameInset, W.RecruitDecorHeaderWidth, W.RecruitDecorHeaderHeight, Color.clear);
		A.AddText(_win, P.FontBook, P.SizeSubHeader, "Fusion Glossary", w / 2f - G.TitleWidth / 2f, 0f, G.TitleWidth, W.RecruitHeaderHeight, P.TipTitle, TextAlignmentOptions.Center);

		// Close (back to the fusion panel): the game's full-screen exit button, small, on the header's right end.
		var cs = G.CloseSize;
		var close = A.AddSpriteImage(_win, "Close", A.NativeSprite(P.SpriteClose), w - G.CloseRight - cs, W.RecruitHeaderHeight / 2f - cs / 2f, cs, cs);
		close.preserveAspect = true;
		if (close.sprite == null)
		{
			close.color = new Color(0f, 0f, 0f, 0.01f);
			A.AddText(_win, P.FontBook, P.SizeSubHeader, "X", w - G.CloseRight - cs, W.RecruitHeaderHeight / 2f - cs / 2f, cs, cs, P.TipTitle, TextAlignmentOptions.Center);
		}
		ShellButtons.Add((close, A.NativeSprite(P.SpriteClose), A.NativeSprite(P.SpriteCloseHover), Close));

		_searchField = Sliced(_win, G.SpriteKeyField, G.SearchX, G.ToolbarY, G.SearchWidth, G.SearchHeight, G.SearchSliceMultiplier, new Color(0.1f, 0.16f, 0.26f, 1f));
		_searchText = A.AddText(_win, P.FontMedium, P.SizeMain, "", G.SearchTextX, G.ToolbarY, G.SearchWidth - (G.SearchTextX - G.SearchX) - 12f, G.SearchHeight, P.TipNote, TextAlignmentOptions.Left);
		UpdateSearchText();

		_listLayer = A.NewRect("List", _win);
		A.Place(_listLayer, 0f, 0f, w, h);
		_detailLayer = A.NewRect("Detail", _win);
		A.Place(_detailLayer, 0f, 0f, w, h);
	}

	private static void UpdateSearchText()
	{
		if (_searchText == null)
			return;
		var empty = _query.Length == 0;
		_searchText.text = empty ? "Search names, parents, abilities…" : _query + "|";
		_searchText.color = empty ? P.TipNote : P.TipBody;
	}

	private static void Clear(RectTransform layer)
	{
		if (layer == null)
			return;
		for (var i = layer.childCount - 1; i >= 0; i--)
		{
			var child = layer.GetChild(i);
			if (child != null)
				UnityObject.Destroy(child.gameObject);
		}
	}

	/// <summary>Stage tabs, column headers, the visible rows, the count line and the scrollbar.</summary>
	private static void BuildList()
	{
		Clear(_listLayer);
		Buttons.Clear();
		RowHits.Clear();
		var layer = _listLayer;

		var n1 = 0;
		foreach (var e in _entries)
			n1 += e.Stage == 1 ? 1 : 0;
		var n2 = _entries.Count - n1;
		var tabs = new[] { ("All (" + _entries.Count + ")", 0), ("Stage I (" + n1 + ")", 1), ("Stage II (" + n2 + ")", 2) };
		for (var i = 0; i < tabs.Length; i++)
		{
			var stage = tabs[i].Item2;
			Tab(layer, tabs[i].Item1, G.TabsX + i * G.TabPitch, G.ToolbarY + G.TabInset, G.TabWidth, G.TabHeight, _stage == stage, () => SetStage(stage));
		}

		// Column headers.
		var lx = G.ListX;
		var hy = G.HeaderY;
		Img(layer, G.SpriteTab, lx, hy, G.ThumbColumn, G.HeaderHeight, new Color(0.1f, 0.13f, 0.2f, 1f));
		var x = lx + G.ThumbColumn;
		foreach (var col in Columns)
		{
			var key = col.Key;
			if (key == _sort)
			{
				var image = Img(layer, G.SpriteTabSelected, x, hy, col.Width - 2f, G.HeaderHeight, new Color(0.3f, 0.26f, 0.15f, 1f));
				var label = A.AddText(layer, P.FontMedium, P.SizeSmall, col.Label, x, hy, col.Width - 2f, G.HeaderHeight, P.TipTitle, TextAlignmentOptions.Center);
				var lw = PreferredWidth(label, col.Label);
				var lx0 = x + (col.Width - 2f - lw - G.ArrowGap - G.ArrowWidth) / 2f;
				A.Place(label.rectTransform, lx0, hy, lw + 2f, G.HeaderHeight);
				label.alignment = TextAlignmentOptions.Left;
				var arrow = Img(layer, G.SpriteArrow, lx0 + lw + G.ArrowGap, hy + G.HeaderHeight / 2f - G.ArrowHeight / 2f, G.ArrowWidth, G.ArrowHeight, P.TipTitle);
				if (arrow.sprite == null)
				{
					arrow.color = Color.clear;
					A.AddText(layer, P.FontMedium, P.SizeSmall, _desc ? "v" : "^", lx0 + lw + G.ArrowGap, hy, G.ArrowWidth + 4f, G.HeaderHeight, P.TipTitle, TextAlignmentOptions.Center);
				}
				else if (!_desc)
				{
					Flip(arrow, false, true);
				}
				Buttons.Add((image, null, null, () => SetSort(key)));
			}
			else
			{
				Tab(layer, col.Label, x, hy, col.Width - 2f, G.HeaderHeight, false, () => SetSort(key));
			}
			x += col.Width;
		}
		var listW = x - lx;

		// Rows.
		var visible = VisibleRows();
		var y0 = G.ListY0;
		var rowH = G.RowHeight - G.RowGap;
		for (var i = 0; i < visible && _start + i < _rows.Count; i++)
		{
			var e = _rows[_start + i];
			var y = y0 + i * G.RowHeight;
			var stage2 = e.Stage == 2;
			var selected = string.Equals(e.Sid, _selected, StringComparison.Ordinal);
			Sliced(layer, selected ? G.SpriteRowSelected : G.SpriteRow, lx, y, listW, rowH, 1f, selected ? new Color(0.16f, 0.25f, 0.4f, 1f) : new Color(0.1f, 0.13f, 0.2f, 1f));
			if (stage2 && !selected)
			{
				var tint = Sliced(layer, G.SpriteRowSelected, lx, y, listW, rowH, 1f, G.Stage2RowTint);
				if (tint.sprite != null)
					tint.color = G.Stage2RowTint;
			}
			UnityImage hover = null;
			if (!selected)
			{
				hover = Sliced(layer, G.SpriteRowSelected, lx, y, listW, rowH, 1f, new Color(0.16f, 0.25f, 0.4f, 0.6f));
				hover.enabled = false;
			}
			if (stage2)
				A.Place(A.NewImage("Stage2Bar", layer, null, G.Stage2).rectTransform, lx, y, G.Stage2BarWidth, rowH);
			var thumbW = (G.RowHeight - 6f) * W.RecruitCardWidth / W.RecruitCardHeight;
			Thumb(layer, e.Sid, lx + 10f, y + 1f, thumbW, null);
			x = lx + G.ThumbColumn;
			foreach (var col in Columns)
			{
				string text;
				var color = P.TipBody;
				switch (col.Key)
				{
					case SortKey.Name:
						text = e.Name;
						color = stage2 ? G.Stage2 : P.TipTitle;
						break;
					case SortKey.Parents:
						text = e.ParentNames[0] + " + " + e.ParentNames[1];
						break;
					case SortKey.Rank:
						text = Homm3ConfluxFusionRuntime.RankName(e.Rank);
						color = P.TipNote;
						break;
					default:
						text = e.HasStats ? StatText(e, col.Key) : "–";
						break;
				}
				A.AddText(layer, P.FontMedium, P.SizeSmall, text, x + 8f, y, col.Width - 14f, rowH, color, col.Align, col.Wrap);
				x += col.Width;
			}
			RowHits.Add((y, hover, e.Sid));
		}
		A.AddText(layer, P.FontMedium, P.SizeSmall, _rows.Count + " of " + _entries.Count + " shown", lx, y0 + visible * G.RowHeight + 4f, listW, G.FooterHeight, P.TipNote, TextAlignmentOptions.Right);
		if (_rows.Count == 0)
			A.AddText(layer, P.FontMedium, P.SizeMain, "No fusion matches “" + _query.Trim() + "”.", lx, y0, listW, G.RowHeight, P.TipNote, TextAlignmentOptions.Center);

		// Scrollbar.
		var sx = ScrollX();
		var trackH = visible * G.RowHeight;
		Sliced(layer, G.SpriteScrollTrack, sx, y0, G.ScrollWidth, trackH, 1f, new Color(0.06f, 0.08f, 0.12f, 1f));
		var max = _rows.Count - visible;
		if (max > 0)
		{
			var thumbH = ThumbHeight(visible, trackH);
			Sliced(layer, G.SpriteScrollThumb, sx, y0 + (trackH - thumbH) * _start / max, G.ScrollWidth, thumbH, 1f, new Color(0.3f, 0.45f, 0.7f, 1f));
		}
	}

	private static string StatText(Entry e, SortKey key) => key switch
	{
		SortKey.Hp => N(e.Hp),
		SortKey.Attack => N(e.Attack),
		SortKey.Defence => N(e.Defence),
		SortKey.Damage => N(e.DamageMin) + "–" + N(e.DamageMax),
		SortKey.Speed => N(e.Speed),
		SortKey.Initiative => N(e.Initiative),
		_ => "",
	};

	private static void Tab(RectTransform parent, string label, float x, float y, float w, float h, bool selected, Action click)
	{
		var image = Img(parent, selected ? G.SpriteTabSelected : G.SpriteTab, x, y, w, h, selected ? new Color(0.3f, 0.26f, 0.15f, 1f) : new Color(0.1f, 0.13f, 0.2f, 1f));
		A.AddText(parent, P.FontMedium, P.SizeSmall, label, x, y, w, h, selected ? P.TipTitle : P.ButtonText, TextAlignmentOptions.Center);
		Buttons.Add((image, selected ? null : Sprite(G.SpriteTab), selected ? null : Sprite(G.SpriteTabHover), click));
	}

	/// <summary>The selected fusion: card, name, kind, traits, rank, stats, family tree and abilities.</summary>
	private static void BuildDetail()
	{
		Clear(_detailLayer);
		if (_selected == null || !_bySid.TryGetValue(_selected, out var e))
			return;
		var layer = _detailLayer;
		var x = ScrollX() + G.DetailGap;
		var y = G.ToolbarY;
		var w = G.Width - x - G.DetailRight;
		var stage2 = e.Stage == 2;
		var ch = Thumb(layer, e.Sid, x, y, G.DetailCard, null);
		var tx = x + G.DetailCard + 18f;
		var tw = w - G.DetailCard - 18f;
		A.AddText(layer, P.FontBook, P.SizeHeaderBig, e.Name, tx, y + 2f, tw, 34f, stage2 ? G.Stage2 : P.TipTitle, TextAlignmentOptions.Left);
		A.AddText(layer, P.FontMedium, P.SizeSmall, stage2 ? "Stage II fusion" : "Fusion", tx, y + 38f, tw, 22f, stage2 ? G.Stage2 : P.TipNote, TextAlignmentOptions.Left);
		var traits = e.Ranged ? "Ranged" : "Melee";
		if (e.Flying)
			traits += " · Flying";
		A.AddText(layer, P.FontMedium, P.SizeSmall, traits, tx, y + 62f, tw, 22f, P.TipBody, TextAlignmentOptions.Left);
		A.AddText(layer, P.FontMedium, P.SizeSmall, "Needs " + Homm3ConfluxFusionRuntime.RankName(e.Rank) + " Conflux", tx, y + 86f, tw, 22f, P.TipNote, TextAlignmentOptions.Left);

		// Stat tiles.
		var sy = y + ch + 14f;
		var stats = new[]
		{
			("HP", e.HasStats ? N(e.Hp) : "–"), ("Attack", e.HasStats ? N(e.Attack) : "–"), ("Defence", e.HasStats ? N(e.Defence) : "–"),
			("Damage", e.HasStats ? N(e.DamageMin) + "–" + N(e.DamageMax) : "–"), ("Speed", e.HasStats ? N(e.Speed) : "–"), ("Initiative", e.HasStats ? N(e.Initiative) : "–"),
		};
		var cw = w / 3f;
		for (var i = 0; i < stats.Length; i++)
		{
			var cx = x + (i % 3) * cw;
			var cy = sy + (i / 3) * G.StatPitch;
			Img(layer, G.SpriteTab, cx, cy, cw - 6f, G.StatHeight, new Color(0.1f, 0.13f, 0.2f, 1f));
			A.AddText(layer, P.FontMedium, P.SizeSmall, stats[i].Item1, cx + 10f, cy, cw - 20f, G.StatHeight, P.TipNote, TextAlignmentOptions.Left);
			A.AddText(layer, P.FontMedium, P.SizeMain, stats[i].Item2, cx + 10f, cy, cw - 26f, G.StatHeight, P.TipBody, TextAlignmentOptions.Right);
		}

		// Family tree.
		var ty = sy + 2f * G.StatPitch + 12f;
		A.AddText(layer, P.FontBook, P.SizeMain, "Family tree", x, ty, w, 26f, P.TipTitle, TextAlignmentOptions.Left);
		ty = Tree(layer, e, x, ty + 30f, w);

		// Abilities.
		A.AddText(layer, P.FontBook, P.SizeMain, "Abilities", x, ty + 6f, w, 26f, P.TipTitle, TextAlignmentOptions.Left);
		var ay = ty + 38f;
		var limit = G.Height - G.DetailBottomMargin;
		var maxDesc = 4f * P.SizeSmall * P.LineSpacing + 4f;
		var shown = 0;
		foreach (var card in e.Cards)
		{
			if (ay + 24f + P.SizeSmall * P.LineSpacing > limit)
				break;
			var icon = IconSprite(card.Icon);
			if (icon != null)
				A.AddSpriteImage(layer, "AbilityIcon", icon, x, ay, G.AbilityIcon, G.AbilityIcon).preserveAspect = true;
			A.AddText(layer, P.FontMedium, P.SizeMain, card.Name + (card.Active ? "  (active)" : ""), x + G.AbilityTextX, ay, w - G.AbilityTextX, 22f, P.TipTitle, TextAlignmentOptions.Left);
			var room = Math.Min(maxDesc, limit - ay - 24f);
			var desc = A.AddText(layer, P.FontRegular, P.SizeSmall, card.Text, x + G.AbilityTextX, ay + 24f, w - G.AbilityTextX, room, P.TipBody, TextAlignmentOptions.TopLeft, true);
			var h = Math.Min(room, A.MeasureHeight(desc, w - G.AbilityTextX, room) + 4f);
			if (desc != null)
				desc.rectTransform.sizeDelta = new Vector2(w - G.AbilityTextX, h);
			ay += 24f + Math.Max(h, G.AbilityIcon - 24f) + 12f;
			shown++;
		}
		if (shown == 0)
			A.AddText(layer, P.FontMedium, P.SizeSmall, e.Cards.Count == 0 ? "No special abilities." : "", x, ay, w, 22f, P.TipNote, TextAlignmentOptions.Left);
		else if (shown < e.Cards.Count)
			A.AddText(layer, P.FontMedium, P.SizeSmall, "+" + (e.Cards.Count - shown) + " more", x, Math.Min(ay, limit), w, 22f, P.TipNote, TextAlignmentOptions.Left);
	}

	/// <summary>Stage II: unit, its two stage I parents, their four elementals. Stage I: unit and its two elementals.</summary>
	private static float Tree(RectTransform layer, Entry e, float x, float y, float w)
	{
		var levels = new List<string[]> { new[] { e.Sid }, e.ParentSids };
		if (e.Stage == 2)
		{
			var grand = new List<string>();
			foreach (var p in e.ParentSids)
			{
				if (_bySid.TryGetValue(p, out var pe))
					grand.AddRange(pe.ParentSids);
				else
					grand.AddRange(new string[] { null, null });
			}
			levels.Add(grand.ToArray());
		}
		var node = G.TreeNode;
		var gap = G.TreeGap;
		var nodeH = node * W.RecruitCardHeight / W.RecruitCardWidth;
		var line = new Color(P.TipNote.r, P.TipNote.g, P.TipNote.b, 1f);
		float Cx(int li, int i) => x + w * (i + 0.5f) / levels[li].Length;
		// Connectors first, so the cards sit on top of them.
		for (var li = 1; li < levels.Count; li++)
		{
			for (var i = 0; i < levels[li].Length; i++)
			{
				var px = Cx(li - 1, i / 2);
				var py = y + (li - 1) * gap;
				var cx = Cx(li, i);
				var cy = y + li * gap;
				var bend = py + nodeH + 6f;
				Line(layer, px - 1f, py + nodeH - 2f, 2f, bend - (py + nodeH - 2f) + 1f, line);
				Line(layer, Math.Min(px, cx) - 1f, bend - 1f, Math.Abs(cx - px) + 2f, 2f, line);
				Line(layer, cx - 1f, bend - 1f, 2f, cy + 2f - bend + 1f, line);
			}
		}
		for (var li = 0; li < levels.Count; li++)
		{
			var n = levels[li].Length;
			for (var i = 0; i < n; i++)
			{
				var sid = levels[li][i];
				if (sid == null)
					continue;
				var cx = Cx(li, i);
				var cy = y + li * gap;
				var nw = node * (li == 0 ? 1.15f : 1f);
				Thumb(layer, sid, cx - nw / 2f, cy, nw, null);
				_bySid.TryGetValue(sid, out var ent);
				var label = ent != null ? ent.Name : Homm3UnitDisplayNames.Resolve(sid);
				var color = ent != null && ent.Stage == 2 ? G.Stage2 : ent != null ? P.TipTitle : P.TipNote;
				if (n <= 2)
					A.AddText(layer, P.FontRegular, G.TreeLabelSize, label, cx + nw / 2f + 4f, cy, w / n / 2f - nw / 2f - 6f, 30f, color, TextAlignmentOptions.TopLeft, true);
				else
					A.AddText(layer, P.FontRegular, G.TreeLabelSizeSmall, label, cx - w / 8f, cy + nw * 1.2f, w / 4f, 16f, color, TextAlignmentOptions.Center);
			}
		}
		return y + gap * (levels.Count - 1) + node * 1.6f + (levels.Count == 3 ? 18f : 0f);
	}

	private static void Line(RectTransform parent, float x, float y, float w, float h, Color color)
	{
		var image = A.NewImage("Line", parent, null, color);
		A.Place(image.rectTransform, x, y, Math.Max(1f, w), Math.Max(1f, h));
	}

	/// <summary>
	/// The native unit card with the portrait masked into it, as the fusion panel draws it, scaled to width <paramref name="size"/>.
	/// Returns the card height.
	/// </summary>
	private static float Thumb(RectTransform parent, string sid, float x, float y, float size, Color? tint)
	{
		var k = size / W.RecruitCardWidth;
		var cw = W.RecruitCardWidth * k;
		var ch = W.RecruitCardHeight * k;
		var card = Img(parent, W.SpriteRecruitCard, x, y, cw, ch, new Color(0.15f, 0.17f, 0.22f, 1f));
		if (tint is { } t && card.sprite != null)
			card.color = t;
		var pw = W.RecruitPortraitWidth * k;
		var ph = W.RecruitPortraitHeight * k;
		var px = x + cw / 2f - pw / 2f;
		var py = y + ch / 2f - ph / 2f;
		if (!TryPortrait(sid, out var portrait))
			return ch;
		var maskSprite = Sprite(W.SpriteRecruitPortraitMask);
		if (maskSprite == null)
		{
			A.AddSpriteImage(parent, "Portrait", portrait, px, py, pw, ph).preserveAspect = true;
			return ch;
		}
		var mask = A.AddSpriteImage(parent, "PortraitMask", maskSprite, px, py, pw, ph);
		var m = mask.gameObject.AddComponent<Mask>();
		if (m != null)
			m.showMaskGraphic = false;
		var inner = A.NewImage("Portrait", mask.transform, portrait, Color.clear);
		A.Stretch(inner.rectTransform);
		inner.preserveAspect = false;
		var r = portrait.rect;
		if (r.width > 0f && r.height > 0f)
		{
			var s = Math.Max(pw / r.width, ph / r.height);
			inner.rectTransform.sizeDelta = new Vector2(r.width * s - pw, r.height * s - ph);
		}
		return ch;
	}

	private static bool TryPortrait(string sid, out Sprite portrait)
	{
		if (Homm3CustomUiIconHook.TryResolveSprite(sid, out portrait) && portrait)
			return true;
		return Homm3NativeSpriteCatalogRegistrar.TryResolveNative(sid, out portrait) && portrait;
	}

	private static float PreferredWidth(TextMeshProUGUI text, string value)
	{
		if (text == null)
			return value.Length * P.SizeSmall * 0.5f;
		try
		{
			return text.GetPreferredValues(value, 100000f, 100000f).x;
		}
		catch
		{
			return value.Length * P.SizeSmall * 0.5f;
		}
	}

	private static string N(int value) => value.ToString(CultureInfo.InvariantCulture);

	// ---------------------------------------------------------------- data (live)

	/// <summary>Builds the 142 entries once per config (fusion_config.json re-parsed => rebuilt).</summary>
	private static void EnsureEntries(Homm3ConfluxFusionConfig config)
	{
		if (_entries != null && ReferenceEquals(_entriesConfig, config))
			return;
		var entries = new List<Entry>();
		var bySid = new Dictionary<string, Entry>(StringComparer.Ordinal);
		var rank = new Dictionary<string, int>(StringComparer.Ordinal);
		var missingLogic = new List<string>();
		var missingView = new List<string>();
		// config.Pairs lists the stage I pairs first, then the stage II recipes (whose ranks need their parents').
		foreach (var pair in config.Pairs)
		{
			int r;
			if (pair.Stage == 1)
			{
				r = Math.Max(LineRank(config, pair.A), LineRank(config, pair.B));
			}
			else
			{
				rank.TryGetValue(pair.A, out var ra);
				rank.TryGetValue(pair.B, out var rb);
				r = Math.Max(config.RecipeMinRank, Math.Max(ra, rb));
			}
			rank[pair.Fused] = r;
			var e = new Entry
			{
				Sid = pair.Fused,
				Name = Homm3ConfluxFusionRuntime.FusedName(pair),
				Stage = pair.Stage,
				ParentSids = new[] { pair.A, pair.B },
				Rank = Math.Min(3, r),
			};
			e.ParentNames = new[] { ParentName(bySid, pair.A), ParentName(bySid, pair.B) };
			if (!ReadLogic(e))
				missingLogic.Add(e.Sid);
			if (!ReadView(e))
				missingView.Add(e.Sid);
			var hay = new StringBuilder(e.Name).Append('\n').Append(e.ParentNames[0]).Append('\n').Append(e.ParentNames[1]);
			foreach (var card in e.Cards)
				hay.Append('\n').Append(card.Name).Append('\n').Append(card.Text);
			e.Hay = hay.ToString();
			entries.Add(e);
			bySid[e.Sid] = e;
		}
		if (missingLogic.Count > 0)
			Homm3ConfluxFusionRuntime.LogWarning("glossary: no live unit logic for " + missingLogic.Count + " fusions (stats shown as -): " + string.Join(", ", missingLogic));
		if (missingView.Count > 0)
			Homm3ConfluxFusionRuntime.LogWarning("glossary: no live unit view for " + missingView.Count + " fusions (no abilities shown): " + string.Join(", ", missingView));
		_entries = entries;
		_bySid = bySid;
		_entriesConfig = config;
	}

	private static int LineRank(Homm3ConfluxFusionConfig config, string sid) =>
		config.LineByUnit.TryGetValue(sid, out var line) ? config.RankForLine(line) : 3;

	private static string ParentName(Dictionary<string, Entry> bySid, string sid) =>
		bySid.TryGetValue(sid, out var parent) ? parent.Name : Homm3UnitDisplayNames.Resolve(sid);

	private static bool ReadLogic(Entry e)
	{
		try
		{
			var logic = Homm3DungeonDraconicDominionHook.ResolveUnitLogicConfigBySid(e.Sid);
			var stats = logic?.stats;
			if (stats == null)
				return false;
			DeobfInteropCompat.TryGetInt32Member(stats, out e.Hp, GameSymbols.LiveRenamedMembers.UnitStatHp);
			e.Attack = stats.offence;
			e.Defence = stats.defence;
			e.DamageMin = stats.damageMin;
			e.DamageMax = stats.damageMax;
			e.Speed = stats.speed;
			e.Initiative = stats.initiative;
			e.HasStats = true;
			var attacks = logic.defaultAttacks;
			if (attacks != null)
			{
				for (var i = 0; i < attacks.Length; i++)
				{
					var attack = attacks[i];
					if (attack != null && string.Equals(attack.attackType_, "shoot", StringComparison.Ordinal))
						e.Ranged = true;
				}
			}
			return true;
		}
		catch (Exception ex)
		{
			Homm3ConfluxFusionRuntime.LogWarning("glossary: logic read failed for " + e.Sid + ": " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static bool ReadView(Entry e)
	{
		try
		{
			var view = ResolveView(e.Sid);
			if (view == null)
				return false;
			AddCards(e, view.abilities, true);
			AddCards(e, view.passives, false);
			return true;
		}
		catch (Exception ex)
		{
			Homm3ConfluxFusionRuntime.LogWarning("glossary: view read failed for " + e.Sid + ": " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static void AddCards(Entry e, Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppReferenceArray<AbilityViewConfig> cards, bool active)
	{
		if (cards == null)
			return;
		for (var i = 0; i < cards.Length; i++)
		{
			var card = cards[i];
			if (card == null)
				continue;
			var nameToken = card.name;
			if (string.Equals(nameToken, FlyingToken, StringComparison.Ordinal))
				e.Flying = true;
			var name = Clean(Text(nameToken));
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if ((nameToken != null && TrivialCardTokens.Contains(nameToken)) || TrivialCardNames.Contains(name))
			{
				if (string.Equals(name, "Flying", StringComparison.Ordinal))
					e.Flying = true;
				continue;
			}
			e.Cards.Add(new Card { Name = name, Text = Clean(Text(card.description)), Icon = card.icon, Active = active });
		}
	}

	private static string Text(string token)
	{
		if (string.IsNullOrWhiteSpace(token))
			return "";
		return AbilityTexts.TryGet(token.Trim(), out var text) ? text : token;
	}

	/// <summary>Drops rich-text tags (the labels are plain text) and shows each per-unit number placeholder as "#".</summary>
	internal static string Clean(string text)
	{
		if (string.IsNullOrEmpty(text))
			return "";
		text = Tags.Replace(text, "");
		text = Numbers.Replace(text, "#");
		return text.Replace(' ', ' ').Trim();
	}

	// Live UnitViewConfig table (the config root's view table; same GameSymbols hints as the hire-ability icon hook).
	private static object _viewTable;
	private static MethodInfo _viewTryGet;

	private static UnitViewConfig ResolveView(string sid)
	{
		var table = ViewTable();
		if (table == null)
			return null;
		_viewTryGet ??= FindTryGet(table.GetType(), typeof(UnitViewConfig));
		if (_viewTryGet == null)
			return null;
		var args = new object[] { sid, null };
		return _viewTryGet.Invoke(table, args) is bool found && found ? args[1] as UnitViewConfig : null;
	}

	private static object ViewTable()
	{
		if (_viewTable != null)
			return _viewTable;
		var rootType = GameMember.FindTypeFromHints("conflux.glossary.configRoot", GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		var root = Member(rootType, null, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return null;
		_viewTable = Member(root.GetType(), root, GameSymbols.UnitPreviewAbilityIcons.UnitViewConfigTables);
		return _viewTable;
	}

	private static object Member(Type type, object obj, string[] names)
	{
		if (type == null || names == null)
			return null;
		var flags = (obj == null ? BindingFlags.Static : BindingFlags.Instance) | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					var value = property.GetValue(obj, null);
					if (value != null)
						return value;
				}
			}
			catch
			{
			}
			try
			{
				var field = type.GetField(name, flags);
				var value = field?.GetValue(obj);
				if (value != null)
					return value;
			}
			catch
			{
			}
		}
		return null;
	}

	private static MethodInfo FindTryGet(Type tableType, Type valueType)
	{
		MethodInfo[] methods;
		try
		{
			methods = tableType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		}
		catch
		{
			return null;
		}
		foreach (var method in methods)
		{
			if (method == null || method.ReturnType != typeof(bool))
				continue;
			var named = false;
			foreach (var hint in GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints)
				named |= !string.IsNullOrWhiteSpace(hint) && (string.Equals(method.Name, hint, StringComparison.Ordinal) || string.Equals(GameMember.ReadObfuscatedName(method), hint, StringComparison.Ordinal));
			if (!named)
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 2 && ps[0].ParameterType == typeof(string) && ps[1].ParameterType.IsByRef && ps[1].ParameterType.GetElementType() == valueType)
				return method;
		}
		return null;
	}

	// ---------------------------------------------------------------- sprites

	/// <summary>One scan of the loaded sprites for the glossary's native sprites (and the panel shell's).</summary>
	private static void ResolveSprites(bool retryMissing)
	{
		var stale = Sprites.Count == 0;
		foreach (var sprite in Sprites.Values)
			stale |= !sprite;
		if (!stale && retryMissing)
		{
			foreach (var name in G.Sprites)
				stale |= !Sprites.ContainsKey(name);
		}
		if (!stale)
			return;
		Sprites.Clear();
		var wanted = new HashSet<string>(G.Sprites, StringComparer.Ordinal);
		wanted.UnionWith(W.RecruitSprites);
		var all = Resources.FindObjectsOfTypeAll<Sprite>();
		for (var i = 0; i < all.Length; i++)
		{
			var s = all[i];
			if (!s || s.name == null || !wanted.Contains(s.name))
				continue;
			if (!Sprites.TryGetValue(s.name, out var have) || !have || s.rect.width * s.rect.height > have.rect.width * have.rect.height)
				Sprites[s.name] = s;
		}
		var missing = new List<string>();
		foreach (var name in G.Sprites)
		{
			if (Sprites.ContainsKey(name))
				continue;
			if (Homm3NativeSpriteCatalogRegistrar.TryResolveNative(name, out var native) && native)
				Sprites[name] = native;
			else if (LoggedMissingSprites.Add(name))
				missing.Add(name);
		}
		if (missing.Count > 0)
			Homm3ConfluxFusionRuntime.LogWarning("glossary sprites not loaded, using flat fallbacks: " + string.Join(", ", missing));
	}

	private static Sprite Sprite(string name) => name != null && Sprites.TryGetValue(name, out var s) && s ? s : null;

	/// <summary>Ability icon: plugin-served homm3_skill_icons first, then the mod's and the game's own resolvers.</summary>
	private static Sprite IconSprite(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return null;
		if (Icons.TryGetValue(key, out var cached) && cached)
			return cached;
		Sprite sprite = null;
		try
		{
			if (!(Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(key, out sprite) && sprite)
			    && !(Homm3CustomUiIconHook.TryResolveSprite(key, out sprite) && sprite)
			    && !(Homm3NativeSpriteCatalogRegistrar.TryResolveNative(key, out sprite) && sprite)
			    && !(Homm3CustomUiIconHook.TryResolveLoadedVanillaSprite(key, out sprite) && sprite))
				sprite = null;
		}
		catch
		{
			sprite = null;
		}
		if (sprite)
			Icons[key] = sprite;
		return sprite ? sprite : null;
	}

	private static UnityImage Img(RectTransform parent, string sprite, float x, float y, float w, float h, Color fallback)
	{
		var image = A.NewImage(sprite, parent, Sprite(sprite), fallback);
		A.Place(image.rectTransform, x, y, w, h);
		return image;
	}

	private static UnityImage Sliced(RectTransform parent, string sprite, float x, float y, float w, float h, float multiplier, Color fallback)
	{
		var image = Img(parent, sprite, x, y, w, h, fallback);
		if (image.sprite != null)
		{
			image.type = UnityImage.Type.Sliced;
			image.pixelsPerUnitMultiplier = multiplier;
			image.fillCenter = true;
		}
		return image;
	}

	private static void Flip(UnityImage image, bool x, bool y)
	{
		var rect = image.rectTransform;
		var size = rect.sizeDelta;
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition += new Vector2(size.x / 2f, -size.y / 2f);
		rect.localScale = new Vector3(x ? -1f : 1f, y ? -1f : 1f, 1f);
	}
}

/// <summary>
/// Geometry, sprites and colours of the Fusion Glossary (window space: top-left origin, y down, 1920x1080 reference
/// canvas). Mirrors tools/conflux_fusion/glossary_mockup.py (the approved mockup); the shell comes from
/// <see cref="Homm3DungeonWarCaptivesWindowLayout"/>, fonts and text colours from <see cref="Homm3TowerArtificingPickerLayout"/>.
/// </summary>
internal static class Homm3ConfluxFusionGlossaryLayout
{
	internal const float Width = 1520f;
	internal const float Height = 900f;
	internal const float TitleWidth = 600f;
	internal const float CloseSize = 34f;
	internal const float CloseRight = 22f;

	// Fusion panel header button ("?"), opposite the skill icon at RecruitWidth - IconCenterX - OpenButtonInset.
	internal const float OpenButtonInset = 8f;
	internal const float OpenButtonSize = 44f;
	internal const float OpenTipWidth = 170f;
	internal const float OpenTipHeight = 30f;

	// Toolbar: search field and stage tabs.
	internal const float ToolbarY = 68f;
	internal const float SearchX = 34f;
	internal const float SearchWidth = 440f;
	internal const float SearchHeight = 46f;
	internal const float SearchTextX = 62f;
	internal const float SearchSliceMultiplier = 1.6f;
	internal const int MaxQueryLength = 40;
	internal const float TabsX = 500f;
	internal const float TabPitch = 172f;
	internal const float TabWidth = 166f;
	internal const float TabHeight = 40f;
	internal const float TabInset = 3f;

	// List.
	internal const float ListX = 30f;
	internal const float HeaderY = 138f;
	internal const float HeaderHeight = 40f;
	internal const float ListY0 = 184f;
	internal const float RowHeight = 50f;
	internal const float RowGap = 4f;
	internal const float ThumbColumn = 70f;
	internal const float ListBottomMargin = 70f;
	internal const float FooterHeight = 26f;
	internal const float ArrowWidth = 12f;
	internal const float ArrowHeight = 10f;
	internal const float ArrowGap = 4f;
	internal const float Stage2BarWidth = 4f;
	internal const float ScrollGap = 8f;
	internal const float ScrollWidth = 12f;
	internal const float ScrollThumbMin = 40f;
	internal const float WheelRows = 3f;

	// Detail page.
	internal const float DetailGap = 34f;
	internal const float DetailRight = 34f;
	internal const float DetailCard = 110f;
	internal const float DetailBottomMargin = 40f;
	internal const float StatPitch = 46f;
	internal const float StatHeight = 40f;
	internal const float TreeNode = 54f;
	internal const float TreeGap = 74f;
	internal const float TreeLabelSize = 13f;
	internal const float TreeLabelSizeSmall = 12f;
	internal const float AbilityIcon = 40f;
	internal const float AbilityTextX = 52f;

	internal const string SpriteDatabase = "Button_Database";
	internal const string SpriteDatabaseHover = "Button_Database_MouseOver";
	internal const string SpriteTab = "Button_Tab_Dark";
	internal const string SpriteTabHover = "Button_Tab_Dark_MouseOver";
	internal const string SpriteTabSelected = "Button_Tab_Dark_Selected";
	internal const string SpriteScrollTrack = "scroll_background";
	internal const string SpriteScrollThumb = "scroll";
	internal const string SpriteKeyField = "KeyField";
	internal const string SpriteKeyFieldHover = "KeyField_MouseOver";
	internal const string SpriteArrow = "Dropdown_arrow";
	internal const string SpriteRow = "tab_1";
	internal const string SpriteRowSelected = "tab_selected_1";

	internal static readonly string[] Sprites =
	{
		SpriteDatabase, SpriteDatabaseHover, SpriteTab, SpriteTabHover, SpriteTabSelected, SpriteScrollTrack, SpriteScrollThumb,
		SpriteKeyField, SpriteKeyFieldHover, SpriteArrow, SpriteRow, SpriteRowSelected,
	};

	/// <summary>Stage II: astral violet (names, tree nodes, edge bar).</summary>
	internal static readonly Color Stage2 = new(190f / 255f, 150f / 255f, 1f, 1f);
	/// <summary>Stage II row tint on a second native row plate.</summary>
	internal static readonly Color Stage2RowTint = new(170f / 255f, 110f / 255f, 1f, 90f / 255f);
}
