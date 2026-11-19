using System;
using System.Collections.Generic;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using L = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Tower Artificing graft picker (design: docs/homm3_tower_artificing.md; approval mockups:
/// tools/tower_artificing/picker_mockup.py). Opened by the Artificing world spell
/// (Homm3TowerArtificingRuntime.PrefixGraftSpellCast).
///
/// A uGUI clone of the game's Laws window built from the game's own loaded sprites and SDF fonts
/// (<see cref="Homm3TowerArtificingPickerLayout"/>): left half = the seven Tower lines with their graft slots, middle =
/// the tier column, right half = the hero's Schematic Book with the cost of each entry on the selected line, docked
/// panel = a clone of the law tooltip with the Graft button, which calls <see cref="Homm3TowerArtificingRuntime.TryGraft"/>.
/// A missing native sprite falls back to a flat colour (logged once); a missing font falls back to any loaded TMP font.
///
/// The full-screen Block image is the raycast shield for uGUI; the map does not raycast uGUI, so
/// <see cref="Homm3TowerArtificingPickerInputBlock"/> raises the game's own input gates (IsOverUI, key actions) and shows
/// the Normal cursor while the picker is open. Input is polled by the
/// host behaviour (legacy Input: left click, wheel over the book, Esc). The view is rebuilt after every change; the ledger
/// is re-read on open and after every graft, and TryGraft revalidates everything, so a stale view can only produce a
/// refused graft, never a wrong one. Esc or the close button closes it; a battle start closes it.
/// </summary>
internal static class Homm3TowerArtificingPicker
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_TOWER_ARTIFICING_PICKER";
	private const string LogPrefix = "HoMM3 Tower Artificing picker: ";
	private const string BannerKey = "homm3_tower_faction_banner";
	private const string AbilityIconPath = "icons/abilities/";

	private static bool _typeRegistered;
	private static bool _typeFailed;
	private static GameObject _canvasObject;
	private static RectTransform _canvasRect;
	private static RectTransform _window;
	private static RectTransform _content;

	private static bool _open;
	private static object _logicHero;
	private static string _heroLabel;
	private static Sprite _heroPortrait;
	private static int _rank;
	private static Homm3TowerArtificingRuntime.ArtificingState _state;
	private static readonly List<int> Book = new();
	private static int _line;
	private static int _slot;
	private static int _pick = -1;
	private static int _scroll;
	private static string _status;
	private static bool _statusError;
	private static bool _dirty;

	private static readonly List<(RectTransform Rect, Action OnClick)> Hits = new();
	private static RectTransform _bookArea;
	private static UnityImage _graftButton;
	private static UnityImage _closeButton;
	private static UnityImage _closeImage;

	private static readonly Dictionary<string, Sprite> NativeSprites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingSprites = new(StringComparer.Ordinal);
	private static readonly Dictionary<string, TMP_FontAsset> Fonts = new(StringComparer.Ordinal);
	private static readonly Dictionary<int, Sprite> PassiveIcons = new();
	private static Dictionary<int, string> _sourceUnitBySchematic;

	internal static bool IsOpen => _open;

	/// <summary>Opens the picker for this logic hero (caller checked the Artificing rank).</summary>
	internal static bool Open(object logicHero, string heroLabel, int rank, out string failReason)
	{
		failReason = null;
		if (!Homm3TowerArtificingRuntime.TryReadState(logicHero, out var state, out failReason))
			return false;
		_logicHero = logicHero;
		// heroLabel is the hero's configSid; show the hero's name and portrait (user 2026-11-13).
		_heroLabel = Homm3HeroDisplayNames.Resolve(heroLabel);
		_heroPortrait = null;
		try
		{
			var key = Homm3HeroPortraitHook.ResolveStrongholdHeroIconKey(logicHero);
			Sprite portrait = null;
			if ((key != null && Homm3HeroPortraitHook.TryGetHeroPortraitSprite(key, out portrait) && portrait)
			    || (!string.IsNullOrWhiteSpace(heroLabel) && Homm3HeroPortraitHook.TryGetHeroPortraitSprite(heroLabel, out portrait) && portrait))
				_heroPortrait = portrait;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "hero portrait lookup failed: " + ex.GetBaseException().Message);
		}
		_rank = Math.Max(1, Math.Min(3, rank));
		_state = state;
		RebuildBook();
		_line = Math.Max(0, Math.Min(_line, Homm3TowerArtificingCatalog.Lines - 1));
		_slot = 0;
		_pick = Book.Count > 0 ? Book[0] : -1;
		_scroll = 0;
		_status = null;
		_statusError = false;
		try
		{
			if (!EnsureCanvas(out failReason))
				return false;
			_open = true;
			Homm3TowerArtificingPickerInputBlock.Begin();
			Rebuild();
			return true;
		}
		catch (Exception ex)
		{
			failReason = "picker build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			Plugin.LogSource?.LogError(LogPrefix + failReason);
			Close();
			return false;
		}
	}

	internal static void Close()
	{
		_open = false;
		Homm3TowerArtificingPickerInputBlock.End();
		_logicHero = null;
		Hits.Clear();
		_graftButton = null;
		_closeButton = null;
		_closeImage = null;
		_bookArea = null;
		var canvas = _canvasObject;
		_canvasObject = null;
		_canvasRect = null;
		_window = null;
		_content = null;
		if (canvas != null)
		{
			try
			{
				UnityObject.Destroy(canvas);
			}
			catch
			{
			}
		}
	}

	private static void RebuildBook()
	{
		Book.Clear();
		foreach (var schematic in Homm3TowerArtificingCatalog.SchematicKeyByIndex.Keys)
		{
			if (schematic >= 0 && schematic < _state.SchematicTiers.Length && _state.SchematicTiers[schematic] > 0)
				Book.Add(schematic);
		}
		Book.Sort((a, b) =>
		{
			var byTier = _state.SchematicTiers[a].CompareTo(_state.SchematicTiers[b]);
			return byTier != 0 ? byTier : string.Compare(Name(a), Name(b), StringComparison.OrdinalIgnoreCase);
		});
	}

	// ---------------------------------------------------------------- input (host Update)

	internal static void Tick()
	{
		if (!_open || _canvasObject == null)
			return;
		try
		{
			if (Input.GetKeyDown(KeyCode.Escape))
			{
				Close();
				return;
			}
			var mouse = (Vector2)Input.mousePosition;
			if (_bookArea != null && Book.Count > L.BookRows && Contains(_bookArea, mouse))
			{
				var wheel = Input.mouseScrollDelta.y;
				if (wheel != 0f)
				{
					_scroll = Mathf.Clamp(_scroll + (wheel < 0f ? 1 : -1), 0, Book.Count - L.BookRows);
					_dirty = true;
				}
			}
			if (Input.GetMouseButtonDown(0))
			{
				for (var i = Hits.Count - 1; i >= 0; i--)
				{
					if (Hits[i].Rect != null && Contains(Hits[i].Rect, mouse))
					{
						Hits[i].OnClick();
						break;
					}
				}
			}
			if (!_open)
				return;
			Homm3TowerArtificingPickerInputBlock.Hold();
			if (_dirty)
				Rebuild();
			Hover(_graftButton, L.SpriteButton, L.SpriteButtonHover, mouse);
			Hover(_closeButton, L.SpriteClose, L.SpriteCloseHover, mouse);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(LogPrefix + "input failed; closing: " + ex.GetBaseException().Message);
			Close();
		}
	}

	private static bool Contains(RectTransform rect, Vector2 screen)
	{
		return RectTransformUtility.RectangleContainsScreenPoint(rect, screen, null);
	}

	private static void Hover(UnityImage image, string normal, string hover, Vector2 mouse)
	{
		if (image == null)
			return;
		var sprite = NativeSprite(Contains(image.rectTransform, mouse) ? hover : normal);
		if (sprite != null && image.sprite != sprite)
			image.sprite = sprite;
	}

	// ---------------------------------------------------------------- view

	private static void Rebuild()
	{
		_dirty = false;
		Hits.Clear();
		_graftButton = null;
		_closeButton = null;
		_bookArea = null;
		if (_content != null)
			UnityObject.Destroy(_content.gameObject);
		_content = NewRect("Content", _window);
		Place(_content, 0f, 0f, L.ContainerWidth, L.ContainerHeight);

		BuildScroll();
		BuildLines();
		BuildBook();
		BuildPoints();
		BuildPanel();
		BuildClose();
	}

	private static void BuildScroll()
	{
		AddImage(_content, L.SpritePaper, L.PaperX, L.PaperY, L.PaperWidth, L.PaperHeight, new Color(0.78f, 0.72f, 0.6f, 1f));
		AddImage(_content, L.SpriteRollerLeft, L.RollerLeftX, L.RollerY, L.RollerWidth, L.RollerHeight, new Color(0.55f, 0.45f, 0.3f, 1f));
		AddImage(_content, L.SpriteRollerRight, L.RollerRightX, L.RollerY, L.RollerWidth, L.RollerHeight, new Color(0.55f, 0.45f, 0.3f, 1f));
		if (Homm3CustomUiIconHook.TryResolveSprite(BannerKey, out var banner) && banner)
		{
			var emblem = AddSpriteImage(_content, "Emblem", banner, L.EmblemCenterX - L.EmblemSize / 2f, L.EmblemY, L.EmblemSize, L.EmblemSize);
			emblem.preserveAspect = true;
		}
		AddText(_content, L.FontRegular, L.SizeSubHeader, "Tower Lines", L.LinesHeaderCenterX - 150f, L.HeaderY, 300f, L.HeaderHeight, L.Ink, TextAlignmentOptions.Midline);
		AddText(_content, L.FontRegular, L.SizeSubHeader, "Schematic Book (" + Book.Count + ")", L.BookHeaderCenterX - 150f, L.HeaderY, 300f, L.HeaderHeight, L.Ink, TextAlignmentOptions.Midline);

		var first = L.RowsTop + L.RowPitch / 2f;
		var last = first + L.RowPitch * (Homm3TowerArtificingCatalog.Lines - 1);
		AddImage(_content, L.SpriteTierLine, L.TierColumnX - L.TierLineWidth / 2f, first, L.TierLineWidth, last - first, L.InkMuted);
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			var cy = first + L.RowPitch * line;
			AddCentered(_content, L.SpriteTierBadge, L.TierColumnX, cy, L.TierBadgeSize, L.TierBadgeSize, new Color(0.83f, 0.78f, 0.67f, 1f));
			AddText(_content, L.FontRegular, L.SizeSubHeader, (line + 1).ToString(), L.TierColumnX - 25f, cy - 13f, 50f, 26f, L.Ink, TextAlignmentOptions.Midline);
		}
	}

	private static void BuildLines()
	{
		var unlocked = Homm3TowerArtificingRuntime.SlotsForRank(_rank);
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			var top = L.RowsTop + L.RowPitch * line;
			var cy = top + L.RowPitch / 2f;
			if (line == _line)
				AddSliced(_content, L.SpriteRowSelected, L.LeftX, top + 4f, L.LeftWidth, L.RowPitch - 8f, L.RowSliceMultiplier, new Color(0.8f, 0.68f, 0.4f, 0.35f));
			Sprite portrait = null;
			var sids = Homm3TowerArtificingCatalog.TowerLineBaseSids;
			if (line < sids.Length && Homm3CustomUiIconHook.TryResolveSprite(sids[line], out var p) && p)
				portrait = p;
			AddCell(L.PortraitCenterX, cy, portrait, L.CellBack, L.CellFrame, L.CellIcon, false, false);
			var grafted = 0;
			for (var s = 0; s < unlocked && s < Homm3TowerArtificingCatalog.MaxSlots; s++)
				grafted += _state.GraftSlots[line, s] >= 0 ? 1 : 0;
			AddText(_content, L.FontRegular, L.SizeSubHeader, LineName(line), L.LineTextX, cy - 26f, L.LineTextWidth, 26f, L.Ink, TextAlignmentOptions.MidlineLeft);
			AddText(_content, L.FontMedium, L.SizeSmall, LineSubtitle(line, grafted, unlocked), L.LineTextX, cy + 2f, L.LineTextWidth, 22f, L.InkMuted, TextAlignmentOptions.MidlineLeft);
			for (var slot = 0; slot < Homm3TowerArtificingCatalog.MaxSlots; slot++)
			{
				var sx = L.SlotCenterX + L.SlotPitch * slot;
				var graft = _state.GraftSlots[line, slot];
				var locked = slot >= unlocked;
				var cell = AddCell(sx, cy, !locked && graft >= 0 ? PassiveIcon(graft) : null, L.CellBack, L.CellFrame, L.CellIcon,
					line == _line && slot == _slot, locked);
				if (locked)
					continue;
				var l = line;
				var s = slot;
				Hits.Add((cell, () =>
				{
					_line = l;
					_slot = s;
					_status = null;
					_dirty = true;
				}));
			}
		}
	}

	private static void BuildBook()
	{
		var pitch = L.RowPitch * Homm3TowerArtificingCatalog.Lines / L.BookRows;
		_bookArea = NewRect("BookArea", _content);
		Place(_bookArea, L.BookX, L.RowsTop, L.ScrollTrackX + L.ScrollTrackWidth - L.BookX, pitch * L.BookRows);
		if (Book.Count == 0)
		{
			var chances = Homm3TowerArtificingCatalog.ObservationChanceByRank;
			AddText(_content, L.FontMedium, L.SizeMain,
				"The Schematic Book is empty.\n\nAt the end of every battle, each passive ability in the enemy army has a "
				+ chances[0] + " / " + chances[1] + " / " + chances[2] + "% chance (Basic / Advanced / Expert) to be learned.",
				L.BookX + 20f, L.RowsTop + 40f, L.BookWidth - 60f, 200f, L.InkMuted, TextAlignmentOptions.Top, true);
			return;
		}
		_scroll = Mathf.Clamp(_scroll, 0, Math.Max(0, Book.Count - L.BookRows));
		var targetTier = _line + 1;
		var unlocked = Homm3TowerArtificingRuntime.SlotsForRank(_rank);
		for (var r = 0; r < L.BookRows && _scroll + r < Book.Count; r++)
		{
			var schematic = Book[_scroll + r];
			var top = L.RowsTop + pitch * r;
			var cy = top + pitch / 2f;
			var row = NewRect("BookRow" + r, _content);
			Place(row, L.BookX, cy - L.BookRowHeight / 2f, L.ScrollTrackX - L.BookX - 8f, L.BookRowHeight);
			if (schematic == _pick)
				AddSliced(_content, L.SpriteRowSelected, L.BookX, cy - L.BookRowHeight / 2f, L.ScrollTrackX - L.BookX - 8f, L.BookRowHeight, L.RowSliceMultiplier, new Color(0.8f, 0.68f, 0.4f, 0.35f));
			AddCell(L.BookIconCenterX, cy, PassiveIcon(schematic), L.BookCellBack, L.BookCellFrame, L.BookCellIcon, false, false);
			var onLine = SlotOnLine(schematic, unlocked);
			var heldBy = LineHolding(schematic, unlocked);
			AddText(_content, L.FontRegular, L.SizeMain, Name(schematic), L.BookTextX, cy - 23f, L.BookTextWidth, 24f, L.Ink, TextAlignmentOptions.MidlineLeft);
			AddText(_content, L.FontMedium, L.SizeSmall, BookSubtitle(_state.SchematicTiers[schematic], onLine, heldBy), L.BookTextX, cy + 1f, L.BookTextWidth, 20f,
				heldBy >= 0 ? L.InkGood : L.InkMuted, TextAlignmentOptions.MidlineLeft);
			// One Tower line per schematic: the holding line's portrait sits beside the price (user 2026-11-13).
			if (heldBy >= 0 && LinePortrait(heldBy) is { } holder)
			{
				var holderImage = AddSpriteImage(_content, "HeldBy", holder, L.PriceX - 40f, cy - 17f, 34f, 34f);
				holderImage.preserveAspect = true;
			}
			var cost = Cost(_state.SchematicTiers[schematic], targetTier);
			AddImage(_content, L.SpritePrice, L.PriceX, cy - L.PriceHeight / 2f, L.PriceWidth, L.PriceHeight, new Color(0.1f, 0.07f, 0.05f, 1f));
			AddCentered(_content, L.SpriteEssence, L.PriceX + 4f, cy, L.PriceIconSize, L.PriceIconSize, L.EssenceTint);
			AddText(_content, L.FontRegular, L.SizeMain, cost.ToString(), L.PriceX + 18f, cy - L.PriceHeight / 2f, L.PriceWidth - 26f, L.PriceHeight,
				cost <= _state.Essence ? L.CostOk : L.CostBad, TextAlignmentOptions.MidlineRight);
			var pick = schematic;
			Hits.Add((row, () =>
			{
				// Clicking the selected schematic again deselects it, bringing back the full guide (user 2026-11-13).
				_pick = _pick == pick ? -1 : pick;
				_status = null;
				_dirty = true;
			}));
		}
		if (Book.Count > L.BookRows)
		{
			var trackTop = L.RowsTop + 6f;
			var trackHeight = pitch * L.BookRows - 12f;
			AddSliced(_content, L.SpriteScrollTrack, L.ScrollTrackX, trackTop, L.ScrollTrackWidth, trackHeight, 1f, L.InkMuted);
			var handle = Math.Max(40f, trackHeight * L.BookRows / Book.Count);
			var y = trackTop + (trackHeight - handle) * _scroll / Math.Max(1, Book.Count - L.BookRows);
			AddSliced(_content, L.SpriteScrollHandle, L.ScrollTrackX + (L.ScrollTrackWidth - L.ScrollHandleWidth) / 2f, y + 4f, L.ScrollHandleWidth, handle - 8f, 1f, L.InkMuted);
		}
	}

	private static void BuildPoints()
	{
		var py = L.PointsCenterY;
		var number = AddText(_content, L.FontRegular, L.SizeBigNumbers, _state.Essence.ToString(), 0f, py - 32f, 200f, 44f, L.Ink, TextAlignmentOptions.MidlineLeft);
		var numberWidth = number != null ? Mathf.Min(200f, number.preferredWidth) : 60f;
		var total = L.PointsIconSize + 8f + numberWidth;
		var x0 = L.EmblemCenterX - total / 2f;
		if (number != null)
			Place(number.rectTransform, x0 + L.PointsIconSize + 8f, py - 32f, numberWidth + 4f, 44f);
		AddCentered(_content, L.SpriteEssence, x0 + L.PointsIconSize / 2f, py - 10f, L.PointsIconSize, L.PointsIconSize, L.EssenceTint);
		AddText(_content, L.FontMedium, L.SizeSmall, "Arcane Essence", L.EmblemCenterX - 100f, py + 16f, 200f, 22f, L.InkMuted, TextAlignmentOptions.Midline);
		var nameRight = L.EmblemCenterX - L.PointsSideOffset;
		var nameText = AddText(_content, L.FontMedium, L.SizeHeaderBig, _heroLabel, nameRight - L.PointsSideWidth, py - 18f, L.PointsSideWidth, 32f, L.Ink, TextAlignmentOptions.MidlineRight);
		if (_heroPortrait != null)
		{
			var nameWidth = nameText != null ? Mathf.Min(L.PointsSideWidth - L.CellBack - 12f, nameText.preferredWidth) : 120f;
			if (nameText != null)
				Place(nameText.rectTransform, nameRight - nameWidth - 4f, py - 18f, nameWidth + 4f, 32f);
			AddCell(nameRight - nameWidth - 14f - L.CellBack / 2f, py - 2f, _heroPortrait, L.CellBack, L.CellFrame, L.CellIcon, false, false);
		}
		AddText(_content, L.FontMedium, L.SizeHeaderBig, RankName(_rank) + " Artificing", L.EmblemCenterX + L.PointsSideOffset, py - 18f, L.PointsSideWidth, 32f, L.Ink, TextAlignmentOptions.MidlineLeft);
	}

	private static void BuildPanel()
	{
		var x = L.PanelX;
		var y = L.PanelY;
		var w = L.PanelWidth;
		var h = L.PanelHeight;
		var hh = L.PanelHeaderHeight;
		var fh = L.PanelFooterHeight;
		var pad = L.PanelPad;
		var plate = new Color(0.1f, 0.12f, 0.18f, 0.97f);
		AddSliced(_content, L.SpritePanelBody, x, y + hh - 12f, w, h - hh - fh + 24f, L.PanelSliceMultiplier, plate);
		AddSliced(_content, L.SpritePanelHeader, x, y, w, hh, L.PanelSliceMultiplier, plate);
		AddSliced(_content, L.SpritePanelFooter, x, y + h - fh, w, fh, L.PanelSliceMultiplier, plate);

		var picked = _pick >= 0 && Homm3TowerArtificingCatalog.SchematicKeyByIndex.ContainsKey(_pick);
		var title = picked ? Name(_pick) : "Artificing";
		var subtitle = picked ? "Tier " + _state.SchematicTiers[_pick] + " schematic" : "Choose a slot and a schematic";
		var ringCx = x + 16f + L.PanelRing / 2f;
		var ringCy = y + hh / 2f;
		if (picked && PassiveIcon(_pick) is { } ringIcon)
			AddRoundIcon(ringIcon, ringCx, ringCy, L.PanelRingIcon);
		AddCentered(_content, L.SpritePanelRing, ringCx, ringCy, L.PanelRing, L.PanelRing, L.TipTitle);
		var tx = x + 16f + L.PanelRing + 10f;
		var tw = w - (tx - x) - pad;
		AddText(_content, L.FontBook, L.SizeSubHeader, title, tx, y + 12f, tw, 28f, L.TipTitle, TextAlignmentOptions.MidlineLeft);
		AddText(_content, L.FontMedium, L.SizeSmall, subtitle, tx, y + 40f, tw, 22f, L.TipNote, TextAlignmentOptions.MidlineLeft);

		var bx = x + (w - L.ButtonWidth) / 2f;
		var by = y + h - L.ButtonBottom - L.ButtonHeight;
		var cy = y + hh + 16f;
		var current = _state.GraftSlots[_line, _slot];
		AddText(_content, L.FontMedium, L.SizeSmall, "Target: " + LineName(_line) + " line, slot " + (_slot + 1), x + pad, cy, w - 2f * pad, 22f, L.TipNote, TextAlignmentOptions.TopLeft);
		cy += 26f;
		if (current >= 0 && current != _pick)
		{
			AddText(_content, L.FontMedium, L.SizeSmall, "Replaces " + Name(current) + " (no refund)", x + pad, cy, w - 2f * pad, 22f, L.TipWarn, TextAlignmentOptions.TopLeft);
			cy += 26f;
		}
		cy += 6f;
		var afterTop = by - 150f;
		string reason;
		if (picked)
		{
			var desc = AddText(_content, L.FontMedium, L.SizeSmall, Description(_pick), x + pad, cy, w - 2f * pad, afterTop - cy - 12f, L.TipBody, TextAlignmentOptions.TopLeft, true);
			// User 2026-11-13: use the panel's free space below the description to explain the system to new players.
			var descHeight = MeasureHeight(desc, w - 2f * pad, afterTop - cy - 12f);
			BuildGuide(x + pad, cy + descHeight + 18f, w - 2f * pad, afterTop - 12f, true);
			AddImage(_content, L.SpriteSeparator, x + pad, afterTop, w - 2f * pad, 2f, L.TipNote);
			var cost = Cost(_state.SchematicTiers[_pick], _line + 1);
			var after = _state.Essence - cost;
			reason = BlockedReason(current, _pick, SlotOnLine(_pick, Homm3TowerArtificingRuntime.SlotsForRank(_rank)), after);
			AddText(_content, L.FontBook, L.SizeMain, "After grafting", x + pad, afterTop + 12f, w - 2f * pad, 26f, L.TipTitle, TextAlignmentOptions.MidlineLeft);
			AddText(_content, L.FontMedium, L.SizeSmall, "Cost", x + pad, afterTop + 46f, 160f, 24f, L.TipNote, TextAlignmentOptions.MidlineLeft);
			AddText(_content, L.FontRegular, L.SizeMain, cost.ToString(), x + w - pad - 120f, afterTop + 46f, 92f, 24f, after >= 0 ? L.CostOk : L.CostBad, TextAlignmentOptions.MidlineRight);
			AddCentered(_content, L.SpriteEssence, x + w - pad - 12f, afterTop + 58f, 26f, 26f, L.EssenceTint);
			AddText(_content, L.FontMedium, L.SizeSmall, "Essence left", x + pad, afterTop + 76f, 160f, 24f, L.TipNote, TextAlignmentOptions.MidlineLeft);
			AddText(_content, L.FontRegular, L.SizeMain, after.ToString(), x + w - pad - 160f, afterTop + 76f, 132f, 24f, after >= 0 ? L.TipBody : L.CostBad, TextAlignmentOptions.MidlineRight);
			AddCentered(_content, L.SpriteEssence, x + w - pad - 12f, afterTop + 88f, 26f, 26f, L.EssenceTint);
		}
		else
		{
			reason = "No schematic chosen";
			BuildGuide(x + pad, cy, w - 2f * pad, by - 16f, false);
		}

		var enabled = reason == null;
		var button = AddSliced(_content, enabled ? L.SpriteButton : L.SpriteButtonDisabled, bx, by, L.ButtonWidth, L.ButtonHeight, L.ButtonSliceMultiplier,
			enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		AddText(_content, L.FontRegular, L.SizeMain, "Graft", bx, by, L.ButtonWidth, L.ButtonHeight, enabled ? L.ButtonText : L.ButtonTextDisabled, TextAlignmentOptions.Midline);
		if (enabled && button != null)
		{
			_graftButton = button;
			Hits.Add((button.rectTransform, DoGraft));
		}
		var note = _status ?? reason;
		if (!string.IsNullOrEmpty(note))
		{
			var color = _status == null ? L.TipNote : _statusError ? L.CostBad : L.CostOk;
			AddText(_content, L.FontMedium, L.SizeSmall, note, x + pad, by + L.ButtonHeight + 8f, w - 2f * pad, 40f, color, TextAlignmentOptions.Top, true);
		}
	}

	internal static float MeasureHeight(TextMeshProUGUI text, float width, float max)
	{
		if (text == null)
			return max;
		try
		{
			return Mathf.Min(max, text.GetPreferredValues(text.text, width, 100000f).y);
		}
		catch
		{
			return max;
		}
	}

	/// <summary>
	/// "How Artificing works" primer in the side panel's free space (below the description, or the whole body when no
	/// schematic is chosen). Built from catalog values; the compact form drops lines that do not fit.
	/// </summary>
	private static void BuildGuide(float x, float top, float w, float bottom, bool compact)
	{
		const float headerHeight = 26f;
		if (bottom - top < headerHeight + 60f)
			return;
		var chances = Homm3TowerArtificingCatalog.ObservationChanceByRank;
		var slots = Homm3TowerArtificingCatalog.GraftSlotsByRank;
		var lines = new List<string>
		{
			"Learn: after every battle, each passive in the enemy army has a " + chances[0] + " / " + chances[1] + " / " + chances[2]
				+ "% chance (Basic / Advanced / Expert) to enter the Schematic Book.",
			"Essence: won battles give Arcane Essence for every enemy creature defeated; higher tiers give more.",
			"Graft: pick a slot on a Tower line on the left, then a schematic from the book. Higher-tier lines cost more; "
				+ "schematics learned from lower-tier creatures cost less.",
			"Slots: " + slots[0] + " / " + slots[1] + " / " + slots[2] + " per line by rank. Replacing a graft gives no refund.",
			"In battle: grafts become buffs on that line's stacks at battle start, and can be dispelled.",
		};
		if (compact)
			lines.RemoveAt(1);
		AddImage(_content, L.SpriteSeparator, x, top, w, 2f, L.TipNote);
		AddText(_content, L.FontBook, L.SizeMain, "How Artificing works", x, top + 8f, w, headerHeight, L.TipTitle, TextAlignmentOptions.MidlineLeft);
		var y = top + 8f + headerHeight + 6f;
		// The compact guide keeps room for a "click again" hint, so a cut-off guide is never a dead end.
		var reserve = compact ? 48f : 0f;
		for (var i = 0; i < lines.Count; i++)
		{
			var text = AddText(_content, L.FontMedium, L.SizeSmall, "• " + lines[i], x, y, w, Math.Max(1f, bottom - y), L.TipNote, TextAlignmentOptions.TopLeft, true);
			var used = MeasureHeight(text, w, 1000f);
			var last = i == lines.Count - 1;
			if (y + used > bottom - (last ? 0f : reserve))
			{
				if (text != null)
					UnityObject.Destroy(text.gameObject);
				if (compact)
					AddText(_content, L.FontMedium, L.SizeSmall, "Click the selected schematic again to read the full guide.", x, y, w,
						Math.Max(1f, bottom - y), L.TipTitle, TextAlignmentOptions.TopLeft, true);
				break;
			}
			y += used + 6f;
		}
	}

	private static void BuildClose()
	{
		// Corner close button: a canvas child (screen top-right), created once with the canvas; only its hit is re-registered.
		if (_closeImage == null)
		{
			_closeImage = NewImage("Close", _canvasRect, NativeSprite(L.SpriteClose), new Color(0.2f, 0.25f, 0.4f, 1f));
			var rect = _closeImage.rectTransform;
			rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(1f, 1f);
			rect.anchoredPosition = new Vector2(-L.CloseMargin, -L.CloseMargin);
			rect.sizeDelta = new Vector2(L.CloseSize, L.CloseSize);
		}
		_closeButton = _closeImage;
		Hits.Add((_closeImage.rectTransform, Close));
	}

	private static void DoGraft()
	{
		var line = _line;
		var slot = _slot;
		var pick = _pick;
		if (!Homm3TowerArtificingRuntime.TryGraft(_logicHero, line, slot, pick, out var cost, out var fail))
		{
			_status = "Graft refused: " + fail;
			_statusError = true;
			Plugin.LogSource?.LogWarning(LogPrefix + "graft refused: " + fail);
		}
		else
		{
			_status = "Grafted onto the " + LineName(line) + " line.";
			Plugin.LogSource?.LogInfo(LogPrefix + "grafted " + Name(pick) + " onto " + LineName(line) + " slot " + (slot + 1) + " for " + cost + " essence");
			_statusError = false;
		}
		if (Homm3TowerArtificingRuntime.TryReadState(_logicHero, out var state, out var readFail))
		{
			_state = state;
			RebuildBook();
			_dirty = true;
		}
		else
		{
			Plugin.LogSource?.LogError(LogPrefix + "ledger re-read failed after graft; closing: " + readFail);
			Close();
		}
	}

	// ---------------------------------------------------------------- texts (mirrored by tools/tower_artificing/picker_mockup.py)

	private static string LineSubtitle(int line, int grafted, int slots)
	{
		return "Tier " + (line + 1) + "  ·  " + grafted + "/" + slots + " grafted";
	}

	private static string BookSubtitle(int tier, int onLineSlot, int heldBy)
	{
		if (onLineSlot >= 0)
			return "Tier " + tier + "  ·  on this line, slot " + (onLineSlot + 1);
		if (heldBy >= 0)
			return "Tier " + tier + "  ·  taken by " + LineName(heldBy);
		return "Tier " + tier + " schematic";
	}

	private static string BlockedReason(int current, int pick, int onLineSlot, int after)
	{
		if (current == pick)
			return "Already grafted in this slot";
		if (onLineSlot >= 0)
			return "Already grafted on this line";
		var heldBy = LineHolding(pick, Homm3TowerArtificingRuntime.SlotsForRank(_rank));
		if (heldBy >= 0 && heldBy != _line)
			return "Already grafted onto the " + LineName(heldBy) + " line";
		if (after < 0)
			return "Not enough Arcane Essence";
		return null;
	}

	/// <summary>The Tower line (any, selected included) whose unlocked slots hold this schematic, else -1.</summary>
	private static int LineHolding(int schematic, int unlocked)
	{
		for (var line = 0; line < Homm3TowerArtificingCatalog.Lines; line++)
		{
			for (var slot = 0; slot < unlocked && slot < Homm3TowerArtificingCatalog.MaxSlots; slot++)
			{
				if (_state.GraftSlots[line, slot] == schematic)
					return line;
			}
		}
		return -1;
	}

	private static Sprite LinePortrait(int line)
	{
		var sids = Homm3TowerArtificingCatalog.TowerLineBaseSids;
		return line >= 0 && line < sids.Length && Homm3CustomUiIconHook.TryResolveSprite(sids[line], out var p) && p ? p : null;
	}

	/// <summary>Unlocked slot of the selected line that already holds this schematic, else -1.</summary>
	private static int SlotOnLine(int schematic, int unlocked)
	{
		for (var slot = 0; slot < unlocked && slot < Homm3TowerArtificingCatalog.MaxSlots; slot++)
		{
			if (_state.GraftSlots[_line, slot] == schematic)
				return slot;
		}
		return -1;
	}

	internal static int Cost(int sourceTier, int targetTier)
	{
		var matrix = Homm3TowerArtificingCatalog.GraftCost;
		if (sourceTier < 1 || targetTier < 1 || sourceTier > matrix.GetLength(0) || targetTier > matrix.GetLength(1))
			return int.MaxValue;
		return matrix[sourceTier - 1, targetTier - 1];
	}

	internal static string Name(int schematic)
	{
		return Homm3TowerArtificingCatalog.SchematicNameByIndex.TryGetValue(schematic, out var name) && !string.IsNullOrWhiteSpace(name)
			? name
			: Homm3TowerArtificingCatalog.SchematicKeyByIndex.TryGetValue(schematic, out var key) ? key : "#" + schematic;
	}

	private static string Description(int schematic)
	{
		return Homm3TowerArtificingCatalog.SchematicDescriptionByIndex.TryGetValue(schematic, out var text) ? text : "";
	}

	internal static string LineName(int line)
	{
		var sids = Homm3TowerArtificingCatalog.TowerLineBaseSids;
		if (line < 0 || line >= sids.Length)
			return "Line " + (line + 1);
		var sid = sids[line].StartsWith("h3_", StringComparison.Ordinal) ? sids[line].Substring(3) : sids[line];
		var words = sid.Split('_');
		for (var i = 0; i < words.Length; i++)
			words[i] = words[i].Length == 0 ? words[i] : char.ToUpperInvariant(words[i][0]) + words[i].Substring(1);
		return string.Join(" ", words);
	}

	private static string RankName(int rank)
	{
		return rank >= 3 ? "Expert" : rank == 2 ? "Advanced" : "Basic";
	}

	// ---------------------------------------------------------------- native assets

	/// <summary>The passive's own ability icon (icons/abilities/&lt;key&gt;_name; else, for h3 passives, the mod's icon hook
	/// and its donor icons), else the portrait of a unit that shows it. Cached, including misses.</summary>
	internal static Sprite PassiveIcon(int schematic)
	{
		if (PassiveIcons.TryGetValue(schematic, out var cached))
		{
			if (cached == null || cached)
				return cached;
			PassiveIcons.Remove(schematic);
		}
		Sprite sprite = null;
		try
		{
			if (Homm3TowerArtificingCatalog.SchematicKeyByIndex.TryGetValue(schematic, out var key))
			{
				var nameSid = key + "_name";
				var loaded = Resources.Load<Sprite>(AbilityIconPath + nameSid);
				if (loaded)
					sprite = loaded;
				else if (key.StartsWith("h3_", StringComparison.Ordinal) && Homm3CustomUiIconHook.TryResolveSprite(nameSid, out var custom) && custom)
					sprite = custom;
			}
			if (sprite == null && SourceUnit(schematic) is { } unit && Homm3CustomUiIconHook.TryResolveSprite(unit, out var portrait) && portrait)
				sprite = portrait;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "icon lookup failed for schematic " + schematic + ": " + ex.GetBaseException().Message);
		}
		PassiveIcons[schematic] = sprite;
		return sprite;
	}

	/// <summary>Shortest (base) unit sid that shows this schematic, from GraftableSchematicsByUnitSid.</summary>
	private static string SourceUnit(int schematic)
	{
		if (_sourceUnitBySchematic == null)
		{
			_sourceUnitBySchematic = new Dictionary<int, string>();
			foreach (var pair in Homm3TowerArtificingCatalog.GraftableSchematicsByUnitSid)
			{
				foreach (var index in pair.Value)
				{
					if (!_sourceUnitBySchematic.TryGetValue(index, out var best) || pair.Key.Length < best.Length
					    || pair.Key.Length == best.Length && string.CompareOrdinal(pair.Key, best) < 0)
						_sourceUnitBySchematic[index] = pair.Key;
				}
			}
		}
		return _sourceUnitBySchematic.TryGetValue(schematic, out var sid) ? sid : null;
	}

	internal static Sprite NativeSprite(string name)
	{
		if (NativeSprites.TryGetValue(name, out var sprite) && sprite)
			return sprite;
		return null;
	}

	/// <summary>One scan of the loaded sprites for the layout's native sprite names (re-run when one was unloaded).</summary>
	internal static void ResolveNativeSprites()
	{
		var stale = NativeSprites.Count < L.RequiredSprites.Length;
		foreach (var sprite in NativeSprites.Values)
			stale |= !sprite;
		if (!stale)
			return;
		NativeSprites.Clear();
		var wanted = new HashSet<string>(L.RequiredSprites, StringComparer.Ordinal);
		var all = Resources.FindObjectsOfTypeAll<Sprite>();
		for (var i = 0; i < all.Length; i++)
		{
			var s = all[i];
			if (!s)
				continue;
			var name = s.name;
			if (name == null || !wanted.Contains(name))
				continue;
			// Prefer the biggest copy (a few names exist as atlas thumbnails too).
			if (!NativeSprites.TryGetValue(name, out var have) || !have || s.rect.width * s.rect.height > have.rect.width * have.rect.height)
				NativeSprites[name] = s;
		}
		var missing = new List<string>();
		foreach (var name in L.RequiredSprites)
		{
			if (!NativeSprites.ContainsKey(name) && LoggedMissingSprites.Add(name))
				missing.Add(name);
		}
		if (missing.Count > 0)
			Plugin.LogSource?.LogWarning(LogPrefix + "native sprites not loaded, using flat fallbacks: " + string.Join(", ", missing));
	}

	/// <summary>Resolves a font ahead of use. The first lookup scans every loaded font asset, which is slow.</summary>
	internal static void WarmFont(string name) => Font(name);

	private static TMP_FontAsset Font(string name)
	{
		if (Fonts.TryGetValue(name, out var font) && font)
			return font;
		TMP_FontAsset fallback = null;
		var all = Resources.FindObjectsOfTypeAll<TMP_FontAsset>();
		for (var i = 0; i < all.Length; i++)
		{
			var f = all[i];
			if (!f)
				continue;
			if (string.Equals(f.name, name, StringComparison.Ordinal))
			{
				font = f;
				break;
			}
			if (fallback == null && f.name != null && f.name.StartsWith("EN-", StringComparison.Ordinal))
				fallback = f;
			fallback ??= f;
		}
		if (!font)
		{
			font = fallback;
			Plugin.LogSource?.LogWarning(LogPrefix + "font " + name + " not loaded; using " + (font ? font.name : "none"));
		}
		if (font)
			Fonts[name] = font;
		return font;
	}

	// ---------------------------------------------------------------- uGUI building

	private static bool EnsureCanvas(out string failReason)
	{
		failReason = null;
		if (_canvasObject != null)
			return true;
		if (_typeFailed)
		{
			failReason = "picker host type failed to register earlier";
			return false;
		}
		if (!_typeRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3TowerArtificingPickerHost>();
				_typeRegistered = true;
			}
			catch (Exception ex)
			{
				_typeFailed = true;
				failReason = "picker host failed: " + ex.GetType().Name + ": " + ex.Message;
				Plugin.LogSource?.LogError(LogPrefix + failReason);
				return false;
			}
		}
		ResolveNativeSprites();

		var go = new GameObject(CanvasObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
			Il2CppType.Of<GraphicRaycaster>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_canvasObject = go;
		var canvas = go.GetComponent<Canvas>();
		var scaler = go.GetComponent<CanvasScaler>();
		if (canvas == null || scaler == null || go.GetComponent<GraphicRaycaster>() == null)
		{
			Close();
			failReason = "picker canvas could not be created";
			return false;
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = L.SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(L.ReferenceWidth, L.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		// Match height on 16:9 and wider screens, width on narrower ones, so the scroll and the docked panel always fit.
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= L.ReferenceWidth / L.ReferenceHeight ? 1f : 0f;
		_canvasRect = go.GetComponent<RectTransform>();

		// Block: full-screen dim and the raycast shield.
		var block = NewImage("Block", _canvasRect, null, new Color(0f, 0f, 0f, L.BlockAlpha));
		Stretch(block.rectTransform);
		block.raycastTarget = true;
		var back = NewImage("Back", _canvasRect, NativeSprite(L.SpriteBack), new Color(0.05f, 0.08f, 0.14f, 0.9f));
		var backRect = back.rectTransform;
		backRect.anchorMin = backRect.anchorMax = backRect.pivot = new Vector2(0.5f, 0.5f);
		backRect.anchoredPosition = Vector2.zero;
		backRect.sizeDelta = new Vector2(L.BackWidth, L.BackHeight);

		_window = NewRect("Container", _canvasRect);
		_window.anchorMin = _window.anchorMax = _window.pivot = new Vector2(0.5f, 0.5f);
		_window.anchoredPosition = new Vector2(L.ContainerOffsetX, 0f);
		_window.sizeDelta = new Vector2(L.ContainerWidth, L.ContainerHeight);

		var host = go.AddComponent<Homm3TowerArtificingPickerHost>();
		if (host == null)
		{
			Close();
			failReason = "picker host component could not be added";
			return false;
		}
		return true;
	}

	internal static RectTransform NewRect(string name, Transform parent)
	{
		var go = new GameObject(name, new Il2CppSystem.Type[] { Il2CppType.Of<RectTransform>() });
		go.transform.SetParent(parent, false);
		return go.GetComponent<RectTransform>();
	}

	/// <summary>Window-space placement: top-left anchored, y down.</summary>
	internal static void Place(RectTransform rect, float x, float y, float w, float h)
	{
		rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0f, 1f);
		rect.anchoredPosition = new Vector2(x, -y);
		rect.sizeDelta = new Vector2(w, h);
	}

	internal static void Stretch(RectTransform rect)
	{
		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition = Vector2.zero;
		rect.sizeDelta = Vector2.zero;
	}

	internal static UnityImage NewImage(string name, Transform parent, Sprite sprite, Color fallback)
	{
		var go = new GameObject(name, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<CanvasRenderer>(),
			Il2CppType.Of<UnityImage>(),
		});
		go.transform.SetParent(parent, false);
		var image = go.GetComponent<UnityImage>();
		image.raycastTarget = false;
		if (sprite != null)
		{
			image.sprite = sprite;
			image.color = Color.white;
		}
		else
		{
			image.color = fallback;
		}
		return image;
	}

	internal static UnityImage AddImage(Transform parent, string sprite, float x, float y, float w, float h, Color fallback)
	{
		var image = NewImage(sprite, parent, NativeSprite(sprite), fallback);
		Place(image.rectTransform, x, y, w, h);
		return image;
	}

	internal static UnityImage AddSpriteImage(Transform parent, string name, Sprite sprite, float x, float y, float w, float h)
	{
		var image = NewImage(name, parent, sprite, Color.clear);
		Place(image.rectTransform, x, y, w, h);
		return image;
	}

	internal static UnityImage AddCentered(Transform parent, string sprite, float cx, float cy, float w, float h, Color fallback)
	{
		return AddImage(parent, sprite, cx - w / 2f, cy - h / 2f, w, h, fallback);
	}

	/// <summary>Image.Type.Sliced with the sprite's own 9-slice border scaled by the given pixelsPerUnitMultiplier.</summary>
	internal static UnityImage AddSliced(Transform parent, string sprite, float x, float y, float w, float h, float multiplier, Color fallback)
	{
		var image = AddImage(parent, sprite, x, y, w, h, fallback);
		if (image.sprite != null)
		{
			image.type = UnityImage.Type.Sliced;
			image.pixelsPerUnitMultiplier = multiplier;
			image.fillCenter = true;
		}
		return image;
	}

	/// <summary>FractionLaw cell: Contur (selection glow), BackGround, Icon, frame, and the law lock when locked.</summary>
	private static RectTransform AddCell(float cx, float cy, Sprite icon, float back, float frame, float iconSize, bool selected, bool locked)
	{
		if (selected)
			AddCentered(_content, L.SpriteCellContur, cx, cy, L.CellContur, L.CellContur, L.TipTitle);
		var bg = AddCentered(_content, L.SpriteCellBack, cx, cy, back, back, new Color(0.35f, 0.3f, 0.25f, 1f));
		if (icon != null)
		{
			var image = AddSpriteImage(_content, "Icon", icon, cx - iconSize / 2f, cy - iconSize / 2f, iconSize, iconSize);
			image.preserveAspect = true;
		}
		AddCentered(_content, L.SpriteCellFrame, cx, cy, frame, frame, new Color(0.7f, 0.58f, 0.3f, 0.6f));
		if (locked)
		{
			AddCentered(_content, L.SpriteCellLocked, cx, cy, back * 1.12f, back * 1.16f, L.LockedTint);
			AddCentered(_content, L.SpriteLock, cx, cy, L.CellLockWidth, L.CellLockHeight, L.InkMuted);
		}
		return bg.rectTransform;
	}

	/// <summary>Round portrait for the panel header: a Knob-sprite mask (falls back to a square icon).</summary>
	private static void AddRoundIcon(Sprite icon, float cx, float cy, float size)
	{
		var knob = NativeSprite("Knob") ?? FindLoadedSprite("Knob");
		if (knob == null)
		{
			var plain = AddSpriteImage(_content, "RingIcon", icon, cx - size / 2f, cy - size / 2f, size, size);
			plain.preserveAspect = true;
			return;
		}
		var mask = AddSpriteImage(_content, "RingMask", knob, cx - size / 2f, cy - size / 2f, size, size);
		var m = mask.gameObject.AddComponent<Mask>();
		if (m != null)
			m.showMaskGraphic = false;
		var inner = NewImage("RingIcon", mask.transform, icon, Color.clear);
		Stretch(inner.rectTransform);
		inner.preserveAspect = true;
	}

	private static Sprite FindLoadedSprite(string name)
	{
		var all = Resources.FindObjectsOfTypeAll<Sprite>();
		for (var i = 0; i < all.Length; i++)
		{
			if (all[i] && string.Equals(all[i].name, name, StringComparison.Ordinal))
			{
				NativeSprites[name] = all[i];
				return all[i];
			}
		}
		return null;
	}

	internal static TextMeshProUGUI AddText(Transform parent, string font, float size, string text, float x, float y, float w, float h, Color color,
		TextAlignmentOptions alignment, bool wrap = false)
	{
		var go = new GameObject("Text", new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<CanvasRenderer>(),
			Il2CppType.Of<TextMeshProUGUI>(),
		});
		go.transform.SetParent(parent, false);
		var tmp = go.GetComponent<TextMeshProUGUI>();
		if (tmp == null)
			return null;
		var asset = Font(font);
		if (asset)
			tmp.font = asset;
		tmp.fontSize = size;
		tmp.color = color;
		tmp.alignment = alignment;
		tmp.richText = false;
		tmp.raycastTarget = false;
		tmp.textWrappingMode = wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
		// Single-line labels must never be culled. In game, TMP's Ellipsis mode hid every label whose box was 44 px or
		// less (names, prices, tier numbers, essence total, tooltip title) while the 56 px Graft label and the tall
		// wrapped description rendered, so the box-height check is what culls them. Overflow mode always draws; long
		// strings are shortened by hand against the measured width instead.
		tmp.overflowMode = wrap ? TextOverflowModes.Ellipsis : TextOverflowModes.Overflow;
		tmp.text = wrap ? text ?? "" : FitSingleLine(tmp, font, text ?? "", w);
		Place(tmp.rectTransform, x, y, w, h);
		LogTextDiagnostic(tmp, font, size, w, h);
		return tmp;
	}

	private static string FitSingleLine(TextMeshProUGUI tmp, string font, string text, float width)
	{
		if (string.IsNullOrEmpty(text) || width <= 0f)
			return text;
		if (SingleLineWidth(tmp, font, text) <= width)
			return text;
		var lo = 0;
		var hi = text.Length;
		while (lo < hi)
		{
			var mid = (lo + hi + 1) / 2;
			if (SingleLineWidth(tmp, font, text.Substring(0, mid).TrimEnd() + "...") <= width)
				lo = mid;
			else
				hi = mid - 1;
		}
		return lo <= 0 ? text : text.Substring(0, lo).TrimEnd() + "...";
	}

	/// <summary>
	/// The wider of TMP's measure and the font-table measure (<see cref="Homm3PanelTextMetrics"/>). TMP's string measure is
	/// not proven through the live interop: Logistics level lines that should have been shortened here ran off the upgrade
	/// panel in game (2026-11-16 owner report), so a zero or failed TMP answer no longer lets a long label through.
	/// </summary>
	private static float SingleLineWidth(TextMeshProUGUI tmp, string font, string text)
	{
		var table = Homm3PanelTextMetrics.Knows(font) ? Homm3PanelTextMetrics.Width(font, tmp.fontSize, text) : 0f;
		try
		{
			return Math.Max(table, tmp.GetPreferredValues(text, 100000f, 100000f).x);
		}
		catch
		{
			return table;
		}
	}

	private static int _textDiagRemaining = 12;

	// One log line per label for the first labels built, so an in-game failure shows font, box and TMP's own layout.
	private static void LogTextDiagnostic(TextMeshProUGUI tmp, string font, float size, float w, float h)
	{
		if (_textDiagRemaining <= 0)
			return;
		_textDiagRemaining--;
		try
		{
			tmp.ForceMeshUpdate(false, false);
			var info = tmp.textInfo;
			Plugin.LogSource?.LogInfo(LogPrefix + "text diag '" + tmp.text + "' font=" + (tmp.font ? tmp.font.name : "none") + " (wanted " + font
				+ ") size=" + size + " box=" + w + "x" + h + " preferred=" + tmp.preferredWidth.ToString("0.#") + "x" + tmp.preferredHeight.ToString("0.#")
				+ " chars=" + (info != null ? info.characterCount : -1) + " lines=" + (info != null ? info.lineCount : -1)
				+ " overflow=" + tmp.overflowMode + " color=" + tmp.color + " active=" + tmp.isActiveAndEnabled);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "text diag failed: " + ex.GetBaseException().Message);
		}
	}
}

public sealed class Homm3TowerArtificingPickerHost : MonoBehaviour
{
	public Homm3TowerArtificingPickerHost(IntPtr ptr) : base(ptr) { }

	private void Update() => Homm3TowerArtificingPicker.Tick();
}

/// <summary>
/// Geometry, sprites, fonts and colours of the Artificing picker. Single source of truth for the runtime builder
/// below and for the approval mockup (tools/tower_artificing/picker_mockup.py parses these constants).
/// Window space: origin at the scroll container's top-left, y down, 1920x1080 reference canvas. The scroll
/// (paper, rollers, emblem, tier column, two halves, points area) copies level11 FractionLaws / ROOT / Container;
/// the docked panel copies the Laws window's docked law tooltip (tolltip_hader / tolltip 1 1 / tolltip_futer,
/// GENERIC BUTTON buttom / buttom_MouseOver / Button_NotActive). Text uses the game's FontsAlias styles
/// (main / sub-header = EN-Regular, content / header-big = EN-Medium, header-window = EN-Book) at their native sizes.
/// </summary>
internal static class Homm3TowerArtificingPickerLayout
{
	internal const float ReferenceWidth = 1920f;
	internal const float ReferenceHeight = 1080f;
	internal const int SortingOrder = 32000;

	// level11 FractionLaws: Block + Back, ROOT / Container 1250x940 (shifted left so the docked panel fits).
	internal const float BlockAlpha = 0.6f;
	internal const float BackWidth = 3510f;
	internal const float BackHeight = 1100f;
	internal const float ContainerWidth = 1250f;
	internal const float ContainerHeight = 940f;
	internal const float ContainerOffsetX = -175f;
	internal const float PaperX = 25f;
	internal const float PaperY = 42f;
	internal const float PaperWidth = 1225f;
	internal const float PaperHeight = 856f;
	internal const float RollerLeftX = 0f;
	internal const float RollerRightX = 1159f;
	internal const float RollerY = 6f;
	internal const float RollerWidth = 118f;
	internal const float RollerHeight = 928f;

	// FractionIcon (Tower banner), the Faction / Army sub-headers, ContainerLevels.
	internal const float EmblemCenterX = 635f;
	internal const float EmblemY = 26f;
	internal const float EmblemSize = 124f;
	internal const float HeaderY = 146f;
	internal const float HeaderHeight = 26f;
	internal const float LinesHeaderCenterX = 360f;
	internal const float BookHeaderCenterX = 910f;
	internal const float TierColumnX = 635f;
	internal const float TierBadgeSize = 50f;
	internal const float TierLineWidth = 5f;
	internal const float RowsTop = 186f;
	internal const float RowPitch = 84f;

	// Left half: one row per Tower line (portrait law cell, name, graft slots). FractionLaw cell parts at 1:1.
	internal const float LeftX = 118f;
	internal const float LeftWidth = 470f;
	internal const float CellBack = 70f;
	internal const float CellFrame = 76f;
	internal const float CellIcon = 60f;
	internal const float CellMask = 64f;
	internal const float CellContur = 104f;
	internal const float CellLockWidth = 22f;
	internal const float CellLockHeight = 30f;
	internal const float PortraitCenterX = 160f;
	internal const float LineTextX = 208f;
	internal const float LineTextWidth = 196f;
	internal const float SlotCenterX = 456f;
	internal const float SlotPitch = 90f;

	// Right half: the Schematic Book list (law cell + name + Frame_Law_Price pill), paper scrollbar.
	internal const float BookX = 666f;
	internal const float BookWidth = 488f;
	internal const int BookRows = 10;
	internal const float BookRowHeight = 54f;
	internal const float BookCellBack = 44f;
	internal const float BookCellFrame = 48f;
	internal const float BookCellIcon = 40f;
	internal const float BookIconCenterX = 700f;
	internal const float BookTextX = 734f;
	internal const float BookTextWidth = 290f;
	internal const float PriceX = 1040f;
	internal const float PriceWidth = 76f;
	internal const float PriceHeight = 30f;
	internal const float PriceIconSize = 34f;
	internal const float ScrollTrackX = 1134f;
	internal const float ScrollTrackWidth = 14f;
	internal const float ScrollHandleWidth = 10f;

	// ContainerPointsAndValue: big-numbers with the essence icon, header-big labels either side.
	internal const float PointsCenterY = 826f;
	internal const float PointsIconSize = 40f;
	internal const float PointsSideOffset = 250f;
	internal const float PointsSideWidth = 300f;

	// Docked panel (law tooltip clone), right of the scroll.
	internal const float PanelX = 1290f;
	internal const float PanelY = 70f;
	internal const float PanelWidth = 360f;
	internal const float PanelHeight = 800f;
	internal const float PanelHeaderHeight = 74f;
	internal const float PanelFooterHeight = 30f;
	internal const float PanelPad = 22f;
	internal const float PanelRing = 84f;
	internal const float PanelRingIcon = 62f;
	internal const float ButtonWidth = 300f;
	internal const float ButtonHeight = 56f;
	internal const float ButtonBottom = 104f;
	internal const float RowSliceMultiplier = 1.05f;
	internal const float PanelSliceMultiplier = 3f;
	internal const float ButtonSliceMultiplier = 1.4f;
	internal const float CloseSize = 80f;
	internal const float CloseMargin = 26f;

	// Font sizes (FontsAlias English sizes) and line spacing.
	internal const float SizeMain = 18f;
	internal const float SizeSmall = 16f;
	internal const float SizeSubHeader = 20f;
	internal const float SizeHeaderBig = 24f;
	internal const float SizeBigNumbers = 35f;
	internal const float LineSpacing = 1.22f;

	internal const string FontRegular = "EN-Regular";
	internal const string FontMedium = "EN-Medium";
	internal const string FontBook = "EN-Book";

	internal const string SpriteBack = "Skrenshot_Laws_Back";
	internal const string SpritePaper = "Scroll_Center";
	internal const string SpriteRollerLeft = "Scroll_Left";
	internal const string SpriteRollerRight = "Scroll_Right";
	internal const string SpriteTierBadge = "Frame_LawLevel (1)";
	internal const string SpriteTierLine = "Line_LawsLevel";
	internal const string SpriteCellContur = "Frame_Law_Back";
	internal const string SpriteCellBack = "Overlay_Law_NotOpen";
	internal const string SpriteCellFrame = "Frame_Law_Top";
	internal const string SpriteCellMask = "Overlay_Law_NotOpen 1";
	internal const string SpriteCellLocked = "Overlay_Law_Loced";
	internal const string SpriteLock = "Icon_Scroll_LevelLock";
	internal const string SpritePrice = "Frame_Law_Priсe";
	internal const string SpriteEssence = "Mana_icon";
	internal const string SpriteRowSelected = "Group 1412288";
	internal const string SpriteScrollTrack = "Skroll_Paper_Back";
	internal const string SpriteScrollHandle = "white_scroll";
	internal const string SpritePanelHeader = "tolltip_hader";
	internal const string SpritePanelBody = "littlr_tooltip 2";
	internal const string SpritePanelFooter = "tolltip_futer";
	internal const string SpritePanelRing = "bild_frame_top";
	internal const string SpriteSeparator = "tooltip_separate_string";
	internal const string SpriteButton = "buttom";
	internal const string SpriteButtonHover = "buttom_MouseOver";
	internal const string SpriteButtonDisabled = "Button_NotActive";
	internal const string SpriteClose = "FullSkreanExitButton";
	internal const string SpriteCloseHover = "FullSkreanExitButton_MouseOver";

	/// <summary>Native sprites resolved in one pass when the picker opens; a missing one is drawn as a flat colour (logged once).</summary>
	internal static readonly string[] RequiredSprites =
	{
		SpriteBack, SpritePaper, SpriteRollerLeft, SpriteRollerRight, SpriteTierBadge, SpriteTierLine, SpriteCellContur,
		SpriteCellBack, SpriteCellFrame, SpriteCellMask, SpriteCellLocked, SpriteLock, SpritePrice, SpriteEssence,
		SpriteRowSelected, SpriteScrollTrack, SpriteScrollHandle, SpritePanelHeader, SpritePanelBody, SpritePanelFooter,
		SpritePanelRing, SpriteSeparator, SpriteButton, SpriteButtonHover, SpriteButtonDisabled, SpriteClose, SpriteCloseHover,
	};

	internal static readonly Color Ink = new(0.22f, 0.15f, 0.09f, 1f);
	internal static readonly Color InkMuted = new(0.42f, 0.33f, 0.22f, 1f);
	internal static readonly Color InkGood = new(0.18f, 0.40f, 0.14f, 1f);
	internal static readonly Color EssenceTint = new(0.8f, 0.741f, 0.584f, 1f);
	internal static readonly Color CostOk = new(0.337f, 0.788f, 0.325f, 1f);
	internal static readonly Color CostBad = new(0.88f, 0.35f, 0.29f, 1f);
	internal static readonly Color TipTitle = new(0.839f, 0.737f, 0.486f, 1f);
	internal static readonly Color TipBody = new(0.925f, 0.925f, 0.925f, 1f);
	internal static readonly Color TipNote = new(0.706f, 0.678f, 0.639f, 1f);
	internal static readonly Color TipWarn = new(0.91f, 0.64f, 0.33f, 1f);
	internal static readonly Color ButtonText = new(0.95f, 0.9f, 0.78f, 1f);
	internal static readonly Color ButtonTextDisabled = new(0.6f, 0.6f, 0.6f, 1f);
	internal static readonly Color LockedTint = new(1f, 1f, 1f, 0.85f);
}
