using System;
using System.Collections.Generic;
using System.Globalization;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using L = OfflineUnlockMod.Homm3DungeonWarCaptivesWindowLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Dungeon War Captives choice window (approval mockup: tools/dungeon_war_captives/window_mockup.py).
/// Queued by <see cref="Homm3DungeonCaptivesRuntime"/> after a local human's won battle and opened once the native result
/// has been written (the army strip shows the post-battle army): a law-tooltip styled panel
/// (the Artificing picker's native sprites, fonts and colours) with one row per choice: Execute, Ransom, Eat, Enslave,
/// Recruit. A row that cannot be taken is greyed with its reason ("Requires Enslave Captives", "Not enough gold", ...).
/// Clicking an available row closes the window and hands the choice to <see cref="Homm3DungeonCaptivesRuntime.Choose"/>;
/// Recruit first opens the recruit panel, a clone of the native diplomacy join panel (army row over captives row, drag
/// stacks between slots, split/move buttons on a clicked stack, "Recruit all"), and recruits exactly that arrangement.
/// There is no close button and Esc does nothing: every won battle resolves its captives. Any failure inside the
/// window closes it with Ransom, so captives are never dropped.
/// </summary>
internal static class Homm3DungeonWarCaptivesWindow
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_DUNGEON_WAR_CAPTIVES";
	private const string LogPrefix = "HoMM3 Dungeon War Captives window: ";

	private static bool _typeRegistered;
	private static bool _typeFailed;
	private static GameObject _canvasObject;
	private static RectTransform _window;
	private static Homm3DungeonCaptivesRuntime.Offer _offer;
	private static string _status;
	private static readonly List<(UnityImage Image, Homm3DungeonCaptivesRuntime.Choice Choice)> Rows = new();

	internal static bool IsOpen => _offer != null;

	// ---------------------------------------------------------------- open after the battle result

	private const string TickerObjectName = "OFFLINE_UNLOCK_MOD_DUNGEON_WAR_CAPTIVES_TICKER";
	// The native result writes the hero/army inside the result call; the army strip and hero panel refresh over the
	// next frames. Opening after this delay shows the player the post-battle state they are deciding on.
	private const float OpenDelaySeconds = 0.6f;
	private const float QueuedOfferTimeoutSeconds = 30f;
	private static readonly Queue<(Homm3DungeonCaptivesRuntime.Offer Offer, float QueuedAt)> QueuedOffers = new();
	private static GameObject _tickerObject;
	private static int _lastTickFrame = -1;

	/// <summary>
	/// Queues the choice window to open once the native battle result has been applied and the HUD has refreshed.
	/// Returns false (caller pays the fallback) only when no ticker can be created.
	/// </summary>
	internal static bool OpenAfterResult(Homm3DungeonCaptivesRuntime.Offer offer, out string failReason)
	{
		failReason = null;
		if (offer == null)
		{
			failReason = "no offer";
			return false;
		}
		if (!EnsureTicker(out failReason))
			return false;
		QueuedOffers.Enqueue((offer, Time.unscaledTime));
		return true;
	}

	private static bool EnsureTicker(out string failReason)
	{
		failReason = null;
		if (_tickerObject != null)
			return true;
		if (!EnsureHostType())
		{
			failReason = "window host type failed to register";
			return false;
		}
		try
		{
			var go = new GameObject(TickerObjectName);
			UnityEngine.Object.DontDestroyOnLoad(go);
			go.AddComponent<Homm3DungeonWarCaptivesWindowHost>();
			_tickerObject = go;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "ticker failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static void TickQueuedOffers()
	{
		if (_offer != null || QueuedOffers.Count == 0)
			return;
		var (offer, queuedAt) = QueuedOffers.Peek();
		var age = Time.unscaledTime - queuedAt;
		if (age < OpenDelaySeconds)
			return;
		QueuedOffers.Dequeue();
		if (age > QueuedOfferTimeoutSeconds)
			Plugin.LogSource?.LogWarning(LogPrefix + "battle " + offer.BattleKey + " waited " + age.ToString("0.0", CultureInfo.InvariantCulture) + "s for the window.");
		if (!Open(offer, out var fail))
		{
			Plugin.LogSource?.LogError(LogPrefix + "choice window did not open for battle " + offer.BattleKey + " (" + fail + "); paying Ransom.");
			Homm3DungeonCaptivesRuntime.Choose(offer, Homm3DungeonCaptivesRuntime.Choice.Ransom, out _);
		}
	}

	internal static bool Open(Homm3DungeonCaptivesRuntime.Offer offer, out string failReason)
	{
		failReason = null;
		if (offer == null)
		{
			failReason = "no offer";
			return false;
		}
		if (_offer != null)
		{
			failReason = "another captives choice is still open (battle " + _offer.BattleKey + ")";
			return false;
		}
		try
		{
			_offer = offer;
			_status = null;
			_board = null;
			if (!EnsureCanvas(out failReason))
			{
				_offer = null;
				return false;
			}
			Homm3TowerArtificingPickerInputBlock.Begin();
			Build();
			return true;
		}
		catch (Exception ex)
		{
			failReason = "window build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			Plugin.LogSource?.LogError(LogPrefix + failReason);
			DestroyCanvas();
			_offer = null;
			return false;
		}
	}

	// ---------------------------------------------------------------- input (host Update)

	internal static void Tick()
	{
		// Every host (ticker, window canvas, banner) calls this; run once per frame.
		var frame = Time.frameCount;
		if (frame == _lastTickFrame)
			return;
		_lastTickFrame = frame;
		TickBanner();
		TickQueuedOffers();
		if (_offer == null || _canvasObject == null)
			return;
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			var mouse = (Vector2)Input.mousePosition;
			if (_board != null)
			{
				TickRecruit(mouse);
				return;
			}
			foreach (var (image, choice) in Rows)
			{
				if (image == null)
					continue;
				var sprite = A.NativeSprite(RectTransformUtility.RectangleContainsScreenPoint(image.rectTransform, mouse, null) ? P.SpriteButtonHover : P.SpriteButton);
				if (sprite != null && image.sprite != sprite)
					image.sprite = sprite;
			}
			if (!Input.GetMouseButtonDown(0))
				return;
			foreach (var (image, choice) in Rows)
			{
				if (image != null && RectTransformUtility.RectangleContainsScreenPoint(image.rectTransform, mouse, null))
				{
					Pick(choice);
					return;
				}
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(LogPrefix + "input failed; closing with Ransom: " + ex.GetBaseException().Message);
			Finish(Homm3DungeonCaptivesRuntime.Choice.Ransom);
		}
	}

	private static void Pick(Homm3DungeonCaptivesRuntime.Choice choice)
	{
		if (!Homm3DungeonCaptivesRuntime.IsChoiceAvailable(_offer, choice, out var reason))
		{
			// Resources can change while the window is open (Recruit): rebuild with the new state.
			_status = choice + ": " + reason;
			Build();
			return;
		}
		if (choice == Homm3DungeonCaptivesRuntime.Choice.Recruit && !OpenRecruitPanel(out reason))
		{
			_status = "Recruit: " + reason;
			Build();
			return;
		}
		if (choice != Homm3DungeonCaptivesRuntime.Choice.Recruit)
			Finish(choice);
	}

	/// <summary>Closes the window first, then applies the choice to the live (post-result) hero and army.</summary>
	private static void Finish(Homm3DungeonCaptivesRuntime.Choice choice, Homm3DungeonCaptivesRuntime.RecruitBoard board = null)
	{
		var offer = _offer;
		_offer = null;
		_board = null;
		Rows.Clear();
		ClearRecruitState();
		Homm3TowerArtificingPickerInputBlock.End();
		DestroyCanvas();
		if (offer == null)
			return;
		// The payout reports itself on the result banner (LastOutcome); only a refused choice is reported here.
		var accepted = Homm3DungeonCaptivesRuntime.Choose(offer, choice, out var fail, board);
		if (!accepted && choice != Homm3DungeonCaptivesRuntime.Choice.Ransom)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + choice + " refused (" + fail + "); paying Ransom.");
			accepted = Homm3DungeonCaptivesRuntime.Choose(offer, Homm3DungeonCaptivesRuntime.Choice.Ransom, out fail);
		}
		if (!accepted)
			ShowBanner("The captives could not be dealt with: " + fail);
	}

	// ---------------------------------------------------------------- result banner (non-blocking, fades out)

	private const string BannerObjectName = "OFFLINE_UNLOCK_MOD_DUNGEON_WAR_CAPTIVES_RESULT";
	private const float BannerWidth = 760f;
	private const float BannerHeight = 64f;
	/// <summary>Wrap width of the banner text (plate less the panel pads); callers size multi-line banners with it.</summary>
	internal const float BannerTextWidth = BannerWidth - 2f * Homm3DungeonWarCaptivesWindowLayout.Pad;
	private const float BannerTop = 150f;
	private const float BannerHold = 3.5f;
	private const float BannerFade = 1f;
	private static GameObject _bannerObject;
	private static CanvasGroup _bannerGroup;
	private static float _bannerShownAt;

	internal static void ShowBanner(string text, int lines = 1)
	{
		try
		{
			DestroyBanner();
			if (string.IsNullOrEmpty(text) || !EnsureHostType())
				return;
			var go = new GameObject(BannerObjectName, new Il2CppSystem.Type[]
			{
				Il2CppType.Of<RectTransform>(),
				Il2CppType.Of<Canvas>(),
				Il2CppType.Of<CanvasScaler>(),
				Il2CppType.Of<CanvasGroup>(),
			});
			UnityObject.DontDestroyOnLoad(go);
			_bannerObject = go;
			var canvas = go.GetComponent<Canvas>();
			var scaler = go.GetComponent<CanvasScaler>();
			_bannerGroup = go.GetComponent<CanvasGroup>();
			canvas.renderMode = RenderMode.ScreenSpaceOverlay;
			canvas.overrideSorting = true;
			canvas.sortingOrder = P.SortingOrder;
			scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
			scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
			scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
			scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
			_bannerGroup.blocksRaycasts = false;
			_bannerGroup.interactable = false;
			var root = A.NewRect("Banner", go.GetComponent<RectTransform>());
			root.anchorMin = root.anchorMax = new Vector2(0.5f, 1f);
			root.pivot = new Vector2(0.5f, 1f);
			root.anchoredPosition = new Vector2(0f, -BannerTop);
			// One line per TMP line pitch (EN-Medium 18 px: 35.5 px); the old 28 px step cut the last lines of long banners.
			var height = BannerHeight + Math.Max(0, lines - 1) * Homm3PanelTextMetrics.LinePitch(P.FontMedium, P.SizeMain);
			root.sizeDelta = new Vector2(BannerWidth, height);
			var plate = new Color(0.1f, 0.12f, 0.18f, 0.97f);
			A.AddSliced(root, P.SpritePanelBody, 0f, 0f, BannerWidth, height, P.PanelSliceMultiplier, plate);
			A.AddText(root, P.FontMedium, P.SizeMain, text, L.Pad, 0f, BannerWidth - 2f * L.Pad, height, P.TipTitle, TextAlignmentOptions.Center, true);
			foreach (var graphic in go.GetComponentsInChildren<Graphic>(true))
				if (graphic != null)
					graphic.raycastTarget = false;
			go.AddComponent<Homm3DungeonWarCaptivesWindowHost>();
			_bannerShownAt = Time.unscaledTime;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "result banner failed: " + ex.GetBaseException().Message);
			DestroyBanner();
		}
	}

	private static void TickBanner()
	{
		if (_bannerObject == null)
			return;
		var age = Time.unscaledTime - _bannerShownAt;
		if (age >= BannerHold + BannerFade)
		{
			DestroyBanner();
			return;
		}
		if (_bannerGroup != null)
			_bannerGroup.alpha = age <= BannerHold ? 1f : 1f - (age - BannerHold) / BannerFade;
	}

	private static void DestroyBanner()
	{
		var go = _bannerObject;
		_bannerObject = null;
		_bannerGroup = null;
		if (go == null)
			return;
		try
		{
			UnityObject.Destroy(go);
		}
		catch
		{
		}
	}

	// ---------------------------------------------------------------- view

	private static void Build()
	{
		Rows.Clear();
		ClearRecruitState();
		foreach (var child in _window.GetComponentsInChildren<RectTransform>(true))
		{
			if (child != null && child != _window && child.parent == _window)
				UnityObject.Destroy(child.gameObject);
		}
		if (_board != null)
		{
			BuildRecruit();
			return;
		}
		var o = _offer;
		var rows = BuildRowModels(o);
		var height = L.HeaderHeight + L.IntroTop + L.IntroHeight + L.FooterHeight + L.BottomPad + (_status != null ? L.StatusHeight : 0f);
		foreach (var row in rows)
			height += RowHeight(row) + L.RowGap;
		_window.sizeDelta = new Vector2(L.Width, height);

		var plate = new Color(0.1f, 0.12f, 0.18f, 0.97f);
		A.AddSliced(_window, P.SpritePanelBody, 0f, L.HeaderHeight - 12f, L.Width, height - L.HeaderHeight - L.FooterHeight + 24f, P.PanelSliceMultiplier, plate);
		A.AddSliced(_window, P.SpritePanelHeader, 0f, 0f, L.Width, L.HeaderHeight, P.PanelSliceMultiplier, plate);
		A.AddSliced(_window, P.SpritePanelFooter, 0f, height - L.FooterHeight, L.Width, L.FooterHeight, P.PanelSliceMultiplier, plate);

		var ringCx = L.Pad + L.Ring / 2f;
		var ringCy = L.HeaderHeight / 2f;
		if (Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(L.SkillIconKey, out var icon) && icon)
		{
			var image = A.AddSpriteImage(_window, "SkillIcon", icon, ringCx - L.RingIcon / 2f, ringCy - L.RingIcon / 2f, L.RingIcon, L.RingIcon);
			image.preserveAspect = true;
		}
		A.AddCentered(_window, P.SpritePanelRing, ringCx, ringCy, L.Ring, L.Ring, P.TipTitle);
		var tx = L.Pad + L.Ring + 12f;
		var tw = L.Width - tx - L.Pad;
		A.AddText(_window, P.FontBook, P.SizeSubHeader, "War Captives", tx, 12f, tw, 28f, P.TipTitle, TextAlignmentOptions.MidlineLeft);
		A.AddText(_window, P.FontMedium, P.SizeSmall, Subtitle(o), tx, 40f, tw, 22f, P.TipNote, TextAlignmentOptions.MidlineLeft);

		var y = L.HeaderHeight + L.IntroTop;
		A.AddText(_window, P.FontMedium, P.SizeMain, Intro(o), L.Pad, y, L.Width - 2f * L.Pad, L.IntroHeight, P.TipBody, TextAlignmentOptions.MidlineLeft, true);
		y += L.IntroHeight;
		foreach (var row in rows)
		{
			var h = RowHeight(row);
			BuildRow(row, y, h);
			y += h + L.RowGap;
		}
		if (_status != null)
			A.AddText(_window, P.FontMedium, P.SizeSmall, _status, L.Pad, y, L.Width - 2f * L.Pad, L.StatusHeight, P.CostBad, TextAlignmentOptions.MidlineLeft, true);
	}

	private sealed class RowModel
	{
		internal Homm3DungeonCaptivesRuntime.Choice Choice;
		internal string Title;
		internal string Effect;
		internal string Detail;
		internal string Blocked;
	}

	private static float RowHeight(RowModel row)
	{
		return L.RowHeight + (row.Detail != null ? L.RowExtraLine : 0f) + (row.Blocked != null ? L.RowExtraLine : 0f);
	}

	private static void BuildRow(RowModel row, float y, float h)
	{
		var enabled = row.Blocked == null;
		var x = L.Pad;
		var w = L.Width - 2f * L.Pad;
		// Disabled rows reuse the button plate greyed: the native Button_NotActive sprite carries a wide transparent margin
		// and would sit inset from the enabled rows.
		var image = A.AddSliced(_window, P.SpriteButton, x, y, w, h, L.RowSliceMultiplier,
			enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		if (image != null && image.sprite != null && !enabled)
			image.color = L.DisabledRowTint;
		if (enabled && image != null)
			Rows.Add((image, row.Choice));
		var ix = x + L.RowTextInset;
		var iw = w - 2f * L.RowTextInset;
		A.AddText(_window, P.FontBook, P.SizeSubHeader, row.Title, ix, y + L.RowTitleTop, L.RowTitleWidth, 28f, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.MidlineLeft);
		var effectX = ix + L.RowTitleWidth;
		A.AddText(_window, P.FontMedium, P.SizeMain, row.Effect, effectX, y + L.RowTitleTop, iw - L.RowTitleWidth, 28f, enabled ? P.TipBody : P.ButtonTextDisabled, TextAlignmentOptions.MidlineLeft);
		var lineY = y + L.RowTitleTop + L.RowDetailOffset;
		if (row.Detail != null)
		{
			A.AddText(_window, P.FontMedium, P.SizeSmall, row.Detail, effectX, lineY, iw - L.RowTitleWidth, 22f, enabled ? P.TipNote : P.ButtonTextDisabled, TextAlignmentOptions.MidlineLeft);
			lineY += L.RowExtraLine;
		}
		if (!enabled)
			A.AddText(_window, P.FontMedium, P.SizeSmall, row.Blocked, effectX, lineY, iw - L.RowTitleWidth, 22f, P.TipWarn, TextAlignmentOptions.MidlineLeft);
	}

	private static List<RowModel> BuildRowModels(Homm3DungeonCaptivesRuntime.Offer o)
	{
		var rows = new List<RowModel>();
		void Add(Homm3DungeonCaptivesRuntime.Choice choice, string title, string effect, string detail)
		{
			Homm3DungeonCaptivesRuntime.IsChoiceAvailable(o, choice, out var reason);
			rows.Add(new RowModel { Choice = choice, Title = title, Effect = effect, Detail = detail, Blocked = reason });
		}

		Add(Homm3DungeonCaptivesRuntime.Choice.Execute, "Execute",
			"+" + N(o.ExecuteXp) + " experience" + (o.ExecuteMana > 0 ? ", +" + N(o.ExecuteMana) + " mana (Interrogation)" : ""), null);
		Add(Homm3DungeonCaptivesRuntime.Choice.Ransom, "Ransom",
			"+" + N(o.RansomGold) + " gold" + (o.SlaveMarkets ? " (Slave Markets +25%)" : ""), null);
		Add(Homm3DungeonCaptivesRuntime.Choice.Eat, "Eat",
			o.EatCreatures > 0 ? "Restore " + N(o.EatCreatures) + " of your fallen creatures" : "Restore part of your losses",
			o.Eat.Count > 0 ? Units(o.Eat) : null);
		var dailyNow = Homm3DungeonCaptivesRuntime.ComputeEnslaveDailyGold(o.EnslavedBefore, o.Rank, o.SlaveMarkets);
		Add(Homm3DungeonCaptivesRuntime.Choice.Enslave, "Enslave",
			"+" + N(o.EnslaveDailyGoldAfter - dailyNow) + " gold every day" + (o.SlaveMarkets ? " (Slave Markets +25%)" : ""),
			o.HasEnslave ? "Daily gold " + N(dailyNow) + " -> " + N(o.EnslaveDailyGoldAfter) + " while this hero serves" : null);
		Add(Homm3DungeonCaptivesRuntime.Choice.Recruit, "Recruit",
			o.RecruitCreatures > 0 ? "Recruit up to " + N(o.RecruitCreatures) + " defeated creatures" : "Recruit some of the defeated",
			o.HasRecruit && o.Recruit.Count > 0 ? Units(o.Recruit) + "; all for " + Homm3DungeonCaptivesRuntime.FormatCost(o.RecruitCost) + ", choose who joins next" : null);
		return rows;
	}

	private static string Subtitle(Homm3DungeonCaptivesRuntime.Offer o)
	{
		return N(o.Captives) + (o.Captives == 1 ? " captive taken" : " captives taken") + (o.DungeonCells ? " (Dungeon Cells +15%)" : "");
	}

	private static string Intro(Homm3DungeonCaptivesRuntime.Offer o)
	{
		var hero = Homm3HeroDisplayNames.Resolve(o.HeroSid);
		return hero + " has taken prisoners. Decide their fate.";
	}

	private static string Units(List<Homm3DungeonCaptivesRuntime.UnitLine> lines)
	{
		var parts = new List<string>();
		foreach (var line in lines)
			parts.Add(Homm3UnitDisplayNames.Resolve(line.Sid) + " x" + N(line.Count));
		return string.Join(", ", parts);
	}

	private static string N(long value) => value.ToString("N0", CultureInfo.InvariantCulture);

	// ---------------------------------------------------------------- recruit panel (native diplomacy join panel clone)

	// The native CanvasDiplomacyUnitsPanel: the hero's army on top, the creatures willing to join below, 7 slots each.
	// Stacks drag between any two slots (merge on the same creature, swap otherwise); clicking a stack opens the
	// split/move buttons around it. Whatever stays in the lower row is released. Rules live in RecruitBoard.
	private static Homm3DungeonCaptivesRuntime.RecruitBoard _board;
	private static readonly List<(RectTransform Rect, bool Top, int Index, UnityImage Hover)> Slots = new();
	private static readonly List<(UnityImage Image, Sprite Normal, Sprite Hover, Action Click)> Buttons = new();
	private static readonly List<(UnityImage Image, Sprite Normal, Sprite Hover, string Hint, Func<string> Act)> RadialButtons = new();
	private static (bool Top, int Index)? _selected;
	private static (bool Top, int Index)? _press;
	private static Vector2 _pressAt;
	private static bool _dragging;
	private static RectTransform _ghost;
	private static TextMeshProUGUI _statusText;
	private static string _recruitStatus;
	private static readonly Dictionary<string, Sprite> PanelSprites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissingPanelSprites = new(StringComparer.Ordinal);

	private static bool OpenRecruitPanel(out string failReason)
	{
		var board = Homm3DungeonCaptivesRuntime.NewRecruitBoard(_offer, out failReason);
		if (board == null)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "recruit panel unavailable: " + failReason);
			failReason = "Unavailable (see the log)";
			return false;
		}
		ResolvePanelSprites();
		_board = board;
		_recruitStatus = null;
		_selected = null;
		Build();
		return true;
	}

	private static void ClearRecruitState()
	{
		Slots.Clear();
		Buttons.Clear();
		RadialButtons.Clear();
		_press = null;
		_dragging = false;
		_ghost = null;
		_statusText = null;
	}

	private static void ResolvePanelSprites()
	{
		var stale = PanelSprites.Count == 0;
		foreach (var sprite in PanelSprites.Values)
			stale |= !sprite;
		if (!stale)
			return;
		PanelSprites.Clear();
		var wanted = new HashSet<string>(L.RecruitSprites, StringComparer.Ordinal);
		var all = Resources.FindObjectsOfTypeAll<Sprite>();
		for (var i = 0; i < all.Length; i++)
		{
			var s = all[i];
			if (!s || s.name == null || !wanted.Contains(s.name))
				continue;
			if (!PanelSprites.TryGetValue(s.name, out var have) || !have || s.rect.width * s.rect.height > have.rect.width * have.rect.height)
				PanelSprites[s.name] = s;
		}
		var missing = new List<string>();
		foreach (var name in L.RecruitSprites)
		{
			if (!PanelSprites.ContainsKey(name) && LoggedMissingPanelSprites.Add(name))
				missing.Add(name);
		}
		if (missing.Count > 0)
			Plugin.LogSource?.LogWarning(LogPrefix + "recruit panel sprites not loaded, using flat fallbacks: " + string.Join(", ", missing));
	}

	private static Sprite PanelSprite(string name) => PanelSprites.TryGetValue(name, out var s) && s ? s : null;

	private static UnityImage PImage(string sprite, float x, float y, float w, float h, Color fallback)
	{
		var image = A.NewImage(sprite, _window, PanelSprite(sprite), fallback);
		A.Place(image.rectTransform, x, y, w, h);
		return image;
	}

	private static UnityImage PSliced(string sprite, float x, float y, float w, float h, float multiplier, Color fallback)
	{
		var image = PImage(sprite, x, y, w, h, fallback);
		if (image.sprite != null)
		{
			image.type = UnityImage.Type.Sliced;
			image.pixelsPerUnitMultiplier = multiplier;
			image.fillCenter = true;
		}
		return image;
	}

	private static UnityImage PCentered(string sprite, float cx, float cy, float w, float h, Color fallback)
	{
		return PImage(sprite, cx - w / 2f, cy - h / 2f, w, h, fallback);
	}

	/// <summary>Mirrors an image left-right (and/or up-down) about its own centre.</summary>
	private static void Flip(UnityImage image, bool x, bool y)
	{
		var rect = image.rectTransform;
		var size = rect.sizeDelta;
		rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition += new Vector2(size.x / 2f, -size.y / 2f);
		rect.localScale = new Vector3(x ? -1f : 1f, y ? -1f : 1f, 1f);
	}

	private static float SlotX(int i) => L.RecruitSlotFirstX + i * L.RecruitSlotPitch;

	private static float RowY(bool top) => top ? L.RecruitArmyRowY : L.RecruitCaptiveRowY;

	private static void BuildRecruit()
	{
		var b = _board;
		var w = L.RecruitWidth;
		var h = L.RecruitHeight;
		_window.sizeDelta = new Vector2(w, h);
		var plate = new Color(0.08f, 0.1f, 0.15f, 0.98f);

		// Popup_full: back, gradient, light bands, bottom separator, back frame, frame + corners, decor.
		PImage(L.SpriteRecruitBack, 0f, 0f, w, h, plate);
		PSliced(L.SpriteRecruitGradient, 0f, 0f, w, h, 1f, Color.clear);
		PImage(L.SpriteRecruitLightBack, (w - L.RecruitBandWidth) / 2f, L.RecruitHeaderHeight / 2f, L.RecruitBandWidth, L.RecruitTopBandHeight, Color.clear);
		PImage(L.SpriteRecruitLightBack, (w - L.RecruitBandWidth) / 2f, h - L.RecruitBottomBandHeight - L.RecruitFrameInset, L.RecruitBandWidth, L.RecruitBottomBandHeight, Color.clear);
		PSliced(L.SpriteRecruitSeparator, (w - L.RecruitSeparatorWidth) / 2f, L.RecruitButtonY - L.RecruitSeparatorHeight / 2f, L.RecruitSeparatorWidth, L.RecruitSeparatorHeight, 1f, Color.clear);
		PSliced(L.SpriteRecruitBackFrame, 0f, 0f, w, h, 1f, Color.clear);
		PSliced(L.SpriteRecruitFrame, 0f, 0f, w, h, 1f, new Color(0.55f, 0.47f, 0.3f, 0.6f));
		var c = L.RecruitCorner;
		PImage(L.SpriteRecruitCorner, 0f, 0f, c, c, Color.clear);
		Flip(PImage(L.SpriteRecruitCorner, w - c, 0f, c, c, Color.clear), true, false);
		Flip(PImage(L.SpriteRecruitCorner, 0f, h - c, c, c, Color.clear), false, true);
		Flip(PImage(L.SpriteRecruitCorner, w - c, h - c, c, c, Color.clear), true, true);
		PCentered(L.SpriteRecruitDecorFooter, w / 2f, h - L.RecruitDecorFooterHeight / 2f, L.RecruitDecorFooterWidth, L.RecruitDecorFooterHeight, Color.clear);

		// Header: title plate, wing ornaments, metal studs, centre decor.
		PSliced(L.SpriteRecruitHeader, -L.RecruitHeaderOverhang / 2f, 0f, w + L.RecruitHeaderOverhang, L.RecruitHeaderHeight, 1f, plate);
		var hy = L.RecruitHeaderHeight / 2f;
		PCentered(L.SpriteRecruitHeaderOrnament, w / 2f + L.RecruitOrnamentX, hy, L.RecruitOrnamentWidth, L.RecruitOrnamentHeight, Color.clear);
		Flip(PCentered(L.SpriteRecruitHeaderOrnament, w / 2f - L.RecruitOrnamentX, hy, L.RecruitOrnamentWidth, L.RecruitOrnamentHeight, Color.clear), true, false);
		PCentered(L.SpriteRecruitHeaderMetal, w / 2f + L.RecruitMetalX, hy, L.RecruitMetalWidth, L.RecruitMetalHeight, Color.clear);
		Flip(PCentered(L.SpriteRecruitHeaderMetal, w / 2f - L.RecruitMetalX, hy, L.RecruitMetalWidth, L.RecruitMetalHeight, Color.clear), true, false);
		PCentered(L.SpriteRecruitDecorHeader, w / 2f, L.RecruitDecorHeaderHeight / 2f - L.RecruitFrameInset, L.RecruitDecorHeaderWidth, L.RecruitDecorHeaderHeight, Color.clear);
		A.AddText(_window, P.FontBook, P.SizeSubHeader, "Recruit Captives", w / 2f - L.RecruitTitleWidth / 2f, 0f, L.RecruitTitleWidth, L.RecruitHeaderHeight, P.TipTitle, TextAlignmentOptions.Center);

		// The two "notification" captions and the two slot rows.
		var hero = Homm3HeroDisplayNames.Resolve(_offer.HeroSid);
		A.AddText(_window, P.FontMedium, P.SizeMain, "Army of " + hero, (w - L.RecruitLabelWidth) / 2f, L.RecruitArmyLabelY - L.RecruitLabelHeight / 2f, L.RecruitLabelWidth, L.RecruitLabelHeight, P.TipTitle, TextAlignmentOptions.Center);
		A.AddText(_window, P.FontMedium, P.SizeMain, "Captives willing to join", (w - L.RecruitLabelWidth) / 2f, L.RecruitCaptiveLabelY - L.RecruitLabelHeight / 2f, L.RecruitLabelWidth, L.RecruitLabelHeight, P.TipTitle, TextAlignmentOptions.Center);
		for (var i = 0; i < Homm3DungeonCaptivesRuntime.MaxArmySlots; i++)
		{
			BuildSlot(true, i);
			BuildSlot(false, i);
		}
		if (_selected is { } sel && b.Sid(sel.Top, sel.Index) != null)
			BuildRadial(sel.Top, sel.Index);
		else
			_selected = null;

		// Price of the arrangement, then the hint / refusal line.
		var cost = b.Cost();
		var recruited = b.RecruitedTotal();
		var released = b.ReleasedTotal();
		var affordable = Homm3DungeonCaptivesRuntime.CanAfford(_offer, cost, out var missing);
		string costLine;
		if (recruited <= 0 && released <= 0)
			costLine = "Drag captives into your army to recruit them. Whatever is left below is released.";
		else if (recruited <= 0)
			costLine = "Releasing " + ReleasedUnits(b) + " from your army";
		else
			costLine = "Recruiting " + RecruitedUnits(b) + " for " + Homm3DungeonCaptivesRuntime.FormatCost(cost) + (affordable ? "" : " (not enough " + missing + ")")
			           + (released > 0 ? "; releasing " + ReleasedUnits(b) : "");
		A.AddText(_window, P.FontMedium, P.SizeMain, costLine, L.RecruitTextInset, L.RecruitCostY, w - 2f * L.RecruitTextInset, L.RecruitLineHeight, recruited > 0 && !affordable ? P.CostBad : P.TipBody, TextAlignmentOptions.Center);
		_statusText = A.AddText(_window, P.FontMedium, P.SizeSmall, _recruitStatus ?? "", L.RecruitTextInset, L.RecruitStatusY, w - 2f * L.RecruitTextInset, L.RecruitLineHeight, P.TipWarn, TextAlignmentOptions.Center);

		// ButtonGroup: Back, the green "Add all Army", and the confirming Recruit.
		var bw = L.RecruitButtonWidth;
		var bx = (w - 3f * bw - 2f * L.RecruitButtonGap) / 2f;
		var by = L.RecruitButtonY - L.RecruitButtonHeight / 2f;
		AddButton("Back", bx, by, L.SpriteRecruitButton, L.SpriteRecruitButtonHover, true, () =>
		{
			_board = null;
			_selected = null;
			Build();
		});
		AddButton("Recruit all", bx + bw + L.RecruitButtonGap, by, L.SpriteRecruitButtonGreen, L.SpriteRecruitButtonGreenHover, true, () =>
		{
			_board.RecruitAll();
			_selected = null;
			_recruitStatus = null;
			Build();
		});
		AddButton("Recruit", bx + 2f * (bw + L.RecruitButtonGap), by, L.SpriteRecruitButton, L.SpriteRecruitButtonHover, b.Changed && affordable, ConfirmRecruit);
	}

	private static string RecruitedUnits(Homm3DungeonCaptivesRuntime.RecruitBoard b)
	{
		var parts = new List<string>();
		foreach (var line in _offer.Recruit)
		{
			var n = b.Recruited(line.Sid);
			if (n > 0)
				parts.Add(Homm3UnitDisplayNames.Resolve(line.Sid) + " x" + N(n));
		}
		return string.Join(", ", parts);
	}

	private static string ReleasedUnits(Homm3DungeonCaptivesRuntime.RecruitBoard b)
	{
		var parts = new List<string>();
		foreach (var sid in b.Own.Keys)
		{
			var n = b.Released(sid);
			if (n > 0)
				parts.Add(Homm3UnitDisplayNames.Resolve(sid) + " x" + N(n));
		}
		return string.Join(", ", parts);
	}

	private static void AddButton(string label, float x, float y, string normal, string hover, bool enabled, Action click)
	{
		var bw = L.RecruitButtonWidth;
		var bh = L.RecruitButtonHeight;
		PImage(L.SpriteRecruitButtonBase, x, y, bw, bh, Color.clear);
		var image = PSliced(enabled ? normal : L.SpriteRecruitButtonDisabled, x, y, bw, bh, L.RecruitButtonSliceMultiplier, enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		if (!enabled && image.sprite == null)
			image.color = L.DisabledRowTint;
		A.AddText(_window, P.FontBook, P.SizeSubHeader, label, x, y, bw, bh, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.Center);
		if (enabled)
			Buttons.Add((image, PanelSprite(normal), PanelSprite(hover), click));
	}

	private static void BuildSlot(bool top, int i)
	{
		var b = _board;
		var cx = SlotX(i);
		var cy = RowY(top);
		var hit = PCentered(L.SpriteRecruitSlotBack, cx, cy, L.RecruitSlotBackWidth, L.RecruitSlotBackHeight, new Color(0.06f, 0.08f, 0.12f, 1f));
		var sid = b.Sid(top, i);
		UnityImage hover;
		if (sid == null)
		{
			PCentered(L.SpriteRecruitSlotEmpty, cx, cy, L.RecruitSlotBackWidth, L.RecruitSlotBackHeight, Color.clear);
			hover = PCentered(L.SpriteRecruitSlotEmptyHover, cx, cy, L.RecruitSlotBackWidth, L.RecruitSlotBackHeight, Color.clear);
		}
		else
		{
			var selected = _selected is { } s && s.Top == top && s.Index == i;
			PCentered(selected ? L.SpriteRecruitCardSelected : L.SpriteRecruitCard, cx, cy, L.RecruitCardWidth, L.RecruitCardHeight, new Color(0.15f, 0.17f, 0.22f, 1f));
			AddPortrait(sid, cx, cy);
			PCentered(L.SpriteRecruitCountOverlay, cx, cy + L.RecruitCountOffset, L.RecruitCountWidth, L.RecruitCountHeight, new Color(0f, 0f, 0f, 0.6f));
			A.AddText(_window, P.FontMedium, P.SizeMain, N(b.Count(top, i)), cx - L.RecruitSlotWidth / 2f, cy + L.RecruitAmountOffset - L.RecruitLineHeight / 2f, L.RecruitSlotWidth, L.RecruitLineHeight, P.TipTitle, TextAlignmentOptions.Center);
			hover = PCentered(L.SpriteRecruitCardHover, cx, cy, L.RecruitCardWidth, L.RecruitCardHeight, Color.clear);
		}
		hover.enabled = false;
		Slots.Add((hit.rectTransform, top, i, hover));
	}

	/// <summary>Unit portrait inside the card's rounded mask (Mask_Frame_Unit_Back), as the native slot draws it.</summary>
	private static void AddPortrait(string sid, float cx, float cy)
	{
		if (!TryUnitPortrait(sid, out var portrait))
		{
			A.AddText(_window, P.FontMedium, P.SizeSmall, Homm3UnitDisplayNames.Resolve(sid), cx - L.RecruitPortraitWidth / 2f, cy - L.RecruitPortraitHeight / 2f, L.RecruitPortraitWidth, L.RecruitPortraitHeight - 20f, P.TipNote, TextAlignmentOptions.Center, true);
			return;
		}
		var maskSprite = PanelSprite(L.SpriteRecruitPortraitMask);
		if (maskSprite == null)
		{
			var plain = A.AddSpriteImage(_window, "Portrait", portrait, cx - L.RecruitPortraitWidth / 2f, cy - L.RecruitPortraitHeight / 2f, L.RecruitPortraitWidth, L.RecruitPortraitHeight);
			plain.preserveAspect = true;
			return;
		}
		var mask = A.AddSpriteImage(_window, "PortraitMask", maskSprite, cx - L.RecruitPortraitWidth / 2f, cy - L.RecruitPortraitHeight / 2f, L.RecruitPortraitWidth, L.RecruitPortraitHeight);
		var m = mask.gameObject.AddComponent<Mask>();
		if (m != null)
			m.showMaskGraphic = false;
		var inner = A.NewImage("Portrait", mask.transform, portrait, Color.clear);
		A.Stretch(inner.rectTransform);
		inner.preserveAspect = false;
		// Cover the mask: scale the portrait to the mask's larger ratio so no card shows at the edges.
		var r = portrait.rect;
		if (r.width > 0f && r.height > 0f)
		{
			var k = Math.Max(L.RecruitPortraitWidth / r.width, L.RecruitPortraitHeight / r.height);
			inner.rectTransform.sizeDelta = new Vector2(r.width * k - L.RecruitPortraitWidth, r.height * k - L.RecruitPortraitHeight);
		}
	}

	/// <summary>The SplitMovePanel buttons around the selected stack: move to the other row, gather, split in half, split one off.</summary>
	private static void BuildRadial(bool top, int i)
	{
		var b = _board;
		var cx = SlotX(i);
		var cy = RowY(top);
		var sid = b.Sid(top, i);
		var count = b.Count(top, i);
		var name = Homm3UnitDisplayNames.Resolve(sid);
		var canSplit = count >= 2 && b.FirstFree(top) >= 0;
		var others = b.Total(top, sid) > count;
		AddRadial(cx - L.RecruitRadialDx, cy - L.RecruitRadialDy, L.SpriteRecruitRadialMove, top ? "Release (move below)" : "Move into your army", () => b.MoveToOtherRow(top, i));
		if (others)
			AddRadial(cx + L.RecruitRadialDx, cy - L.RecruitRadialDy, L.SpriteRecruitRadialGather, "Gather every " + name + " stack here", () => b.Gather(top, i));
		if (canSplit)
		{
			AddRadial(cx - L.RecruitRadialDx, cy + L.RecruitRadialDy, L.SpriteRecruitRadialHalf, "Split in half", () => b.Split(top, i, count / 2));
			AddRadial(cx + L.RecruitRadialDx, cy + L.RecruitRadialDy, L.SpriteRecruitRadialDivide, "Split one off", () => b.Split(top, i, 1));
		}
	}

	private static void AddRadial(float cx, float cy, string sprite, string hint, Func<string> act)
	{
		var image = PCentered(sprite, cx, cy, L.RecruitRadialWidth, L.RecruitRadialHeight, new Color(0.35f, 0.26f, 0.15f, 1f));
		if (image.sprite == null)
			A.AddText(_window, P.FontMedium, P.SizeSmall, hint, cx - 60f, cy - 10f, 120f, 20f, P.ButtonText, TextAlignmentOptions.Center);
		RadialButtons.Add((image, PanelSprite(sprite), PanelSprite(sprite + "_MouseOver"), hint, act));
	}

	private static void ConfirmRecruit()
	{
		var b = _board;
		if (!b.Changed)
		{
			_recruitStatus = "Move a captive into your army, or one of your stacks below to release it.";
			Build();
			return;
		}
		if (!Homm3DungeonCaptivesRuntime.CanAfford(_offer, b.Cost(), out var missing))
		{
			_recruitStatus = "Not enough " + missing + ".";
			Build();
			return;
		}
		Finish(Homm3DungeonCaptivesRuntime.Choice.Recruit, b);
	}

	private static bool Over(RectTransform rect, Vector2 mouse) => rect != null && RectTransformUtility.RectangleContainsScreenPoint(rect, mouse, null);

	private static (bool Top, int Index)? SlotAt(Vector2 mouse)
	{
		foreach (var slot in Slots)
		{
			if (Over(slot.Rect, mouse))
				return (slot.Top, slot.Index);
		}
		return null;
	}

	private static void TickRecruit(Vector2 mouse)
	{
		string hint = null;
		foreach (var (image, normal, hover, _) in Buttons)
		{
			var sprite = Over(image ? image.rectTransform : null, mouse) ? hover : normal;
			if (sprite != null && image.sprite != sprite)
				image.sprite = sprite;
		}
		foreach (var (image, normal, hover, text, _) in RadialButtons)
		{
			var on = Over(image ? image.rectTransform : null, mouse);
			if (on)
				hint = text;
			var sprite = on ? hover : normal;
			if (sprite != null && image.sprite != sprite)
				image.sprite = sprite;
		}
		var under = SlotAt(mouse);
		foreach (var slot in Slots)
		{
			if (slot.Hover != null)
				slot.Hover.enabled = under is { } u && u.Top == slot.Top && u.Index == slot.Index && (_dragging || _board.Sid(slot.Top, slot.Index) != null);
		}
		if (_statusText != null)
		{
			var text = hint ?? _recruitStatus ?? "";
			if (_statusText.text != text)
			{
				_statusText.text = text;
				_statusText.color = hint != null ? P.TipNote : P.TipWarn;
			}
		}

		if (Input.GetMouseButtonDown(0))
		{
			foreach (var (image, _, _, _, act) in RadialButtons)
			{
				if (Over(image ? image.rectTransform : null, mouse))
				{
					var result = act();
					_recruitStatus = string.IsNullOrEmpty(result) ? null : result;
					_selected = null;
					Build();
					return;
				}
			}
			foreach (var (image, _, _, click) in Buttons)
			{
				if (Over(image ? image.rectTransform : null, mouse))
				{
					click();
					return;
				}
			}
			if (under is { } pressed && _board.Sid(pressed.Top, pressed.Index) != null)
			{
				_press = pressed;
				_pressAt = mouse;
				_dragging = false;
				return;
			}
			if (_selected != null)
			{
				_selected = null;
				Build();
			}
			return;
		}

		if (_press is not { } src)
			return;
		if (Input.GetMouseButton(0))
		{
			if (!_dragging && (mouse - _pressAt).magnitude >= L.RecruitDragThreshold)
			{
				_dragging = true;
				_ghost = NewGhost(_board.Sid(src.Top, src.Index));
			}
			if (_dragging && _ghost != null && RectTransformUtility.ScreenPointToLocalPointInRectangle(_window, mouse, null, out var local))
				_ghost.anchoredPosition = local;
			return;
		}

		// Released: a drag moves the whole stack onto the slot under the cursor; a click toggles the split/move buttons.
		_press = null;
		if (_dragging)
		{
			_dragging = false;
			if (under is { } to)
			{
				var result = _board.Move(src.Top, src.Index, to.Top, to.Index);
				_recruitStatus = string.IsNullOrEmpty(result) ? null : result;
			}
			_selected = null;
			Build();
			return;
		}
		_selected = _selected is { } s && s.Top == src.Top && s.Index == src.Index ? null : src;
		_recruitStatus = null;
		Build();
	}

	private static RectTransform NewGhost(string sid) => NewDragGhost(_window, PanelSprite(L.SpriteRecruitCardSelected), sid);

	/// <summary>
	/// The stack-drag ghost (selected card frame + portrait, 85% alpha, no raycasts) centred on <paramref name="parent"/>'s
	/// pivot; the caller moves it to the cursor. Shared with the Conflux Elemental Fusion panel.
	/// </summary>
	internal static RectTransform NewDragGhost(RectTransform parent, Sprite cardSprite, string sid)
	{
		var root = A.NewRect("DragGhost", parent);
		root.anchorMin = root.anchorMax = root.pivot = new Vector2(0.5f, 0.5f);
		root.sizeDelta = new Vector2(L.RecruitCardWidth, L.RecruitCardHeight);
		var card = A.NewImage("Card", root, cardSprite, new Color(0.15f, 0.17f, 0.22f, 0.8f));
		A.Stretch(card.rectTransform);
		if (TryUnitPortrait(sid, out var portrait))
		{
			var image = A.NewImage("Portrait", root, portrait, Color.clear);
			image.rectTransform.anchorMin = image.rectTransform.anchorMax = image.rectTransform.pivot = new Vector2(0.5f, 0.5f);
			image.rectTransform.sizeDelta = new Vector2(L.RecruitPortraitWidth, L.RecruitPortraitHeight);
			image.preserveAspect = true;
		}
		var group = root.gameObject.AddComponent<CanvasGroup>();
		if (group != null)
		{
			group.alpha = 0.85f;
			group.blocksRaycasts = false;
		}
		return root;
	}

	/// <summary>Custom/HoMM3 portraits from the mod's caches, vanilla units from the native sprite resolver (keyed by sid).</summary>
	private static bool TryUnitPortrait(string sid, out Sprite portrait)
	{
		if (Homm3CustomUiIconHook.TryResolveSprite(sid, out portrait) && portrait)
			return true;
		return Homm3NativeSpriteCatalogRegistrar.TryResolveNative(sid, out portrait) && portrait;
	}

	// ---------------------------------------------------------------- canvas

	private static bool EnsureHostType()
	{
		if (_typeRegistered)
			return true;
		if (_typeFailed)
			return false;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3DungeonWarCaptivesWindowHost>();
			_typeRegistered = true;
			A.ResolveNativeSprites();
			return true;
		}
		catch (Exception ex)
		{
			_typeFailed = true;
			Plugin.LogSource?.LogError(LogPrefix + "host type failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	private static bool EnsureCanvas(out string failReason)
	{
		failReason = null;
		if (_canvasObject != null)
			return true;
		if (_typeFailed)
		{
			failReason = "window host type failed to register earlier";
			return false;
		}
		if (!_typeRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3DungeonWarCaptivesWindowHost>();
				_typeRegistered = true;
			}
			catch (Exception ex)
			{
				_typeFailed = true;
				failReason = "window host failed: " + ex.GetType().Name + ": " + ex.Message;
				Plugin.LogSource?.LogError(LogPrefix + failReason);
				return false;
			}
		}
		A.ResolveNativeSprites();

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
		if (canvas == null || scaler == null)
		{
			DestroyCanvas();
			failReason = "window canvas could not be created";
			return false;
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = P.SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
		var canvasRect = go.GetComponent<RectTransform>();

		var block = A.NewImage("Block", canvasRect, null, new Color(0f, 0f, 0f, P.BlockAlpha));
		A.Stretch(block.rectTransform);
		block.raycastTarget = true;

		_window = A.NewRect("Window", canvasRect);
		_window.anchorMin = _window.anchorMax = new Vector2(0.5f, 0.5f);
		_window.pivot = new Vector2(0.5f, 0.5f);
		_window.anchoredPosition = Vector2.zero;
		_window.sizeDelta = new Vector2(L.Width, 600f);

		if (go.AddComponent<Homm3DungeonWarCaptivesWindowHost>() == null)
		{
			DestroyCanvas();
			failReason = "window host component could not be added";
			return false;
		}
		return true;
	}

	private static void DestroyCanvas()
	{
		var canvas = _canvasObject;
		_canvasObject = null;
		_window = null;
		if (canvas == null)
			return;
		try
		{
			UnityObject.Destroy(canvas);
		}
		catch
		{
		}
	}
}

public sealed class Homm3DungeonWarCaptivesWindowHost : MonoBehaviour
{
	public Homm3DungeonWarCaptivesWindowHost(IntPtr ptr) : base(ptr) { }

	private void Update() => Homm3DungeonWarCaptivesWindow.Tick();
}

/// <summary>
/// Geometry of the War Captives window (window space: top-left origin, y down, 1920x1080 reference canvas). Sprites,
/// fonts, sizes and colours come from <see cref="Homm3TowerArtificingPickerLayout"/> (the law-tooltip clone).
/// tools/dungeon_war_captives/window_mockup.py parses these constants; revise values here only.
/// </summary>
internal static class Homm3DungeonWarCaptivesWindowLayout
{
	internal const string SkillIconKey = "skill_faction_homm3_dungeon";
	internal const float Width = 720f;
	internal const float Pad = 22f;
	internal const float HeaderHeight = 74f;
	internal const float FooterHeight = 30f;
	internal const float Ring = 84f;
	internal const float RingIcon = 62f;
	internal const float IntroTop = 16f;
	internal const float IntroHeight = 44f;
	internal const float RowHeight = 64f;
	internal const float RowExtraLine = 26f;
	internal const float RowDetailOffset = 28f;
	internal const float RowGap = 10f;
	internal const float RowTextInset = 22f;
	internal const float RowTitleTop = 14f;
	internal const float RowTitleWidth = 130f;
	internal const float RowSliceMultiplier = 1.4f;
	internal const float StatusHeight = 30f;
	internal const float BottomPad = 14f;
	internal static readonly Color DisabledRowTint = new(0.42f, 0.42f, 0.42f, 1f);

	// Recruit panel: the native CanvasDiplomacyUnitsPanel (level11) geometry, window space (top-left origin, y down).
	internal const float RecruitWidth = 806f;
	internal const float RecruitHeight = 500f;
	internal const float RecruitHeaderHeight = 46f;
	internal const float RecruitHeaderOverhang = 11.8f;
	internal const float RecruitTitleWidth = 300f;
	internal const float RecruitOrnamentX = 150f;
	internal const float RecruitOrnamentWidth = 70.5f;
	internal const float RecruitOrnamentHeight = 31f;
	internal const float RecruitMetalX = 126f;
	internal const float RecruitMetalWidth = 30f;
	internal const float RecruitMetalHeight = 32.4f;
	internal const float RecruitDecorHeaderWidth = 90f;
	internal const float RecruitDecorHeaderHeight = 12f;
	internal const float RecruitDecorFooterWidth = 74f;
	internal const float RecruitDecorFooterHeight = 9f;
	internal const float RecruitBandWidth = 798f;
	internal const float RecruitTopBandHeight = 47.7f;
	internal const float RecruitBottomBandHeight = 59.9f;
	internal const float RecruitFrameInset = 4f;
	internal const float RecruitCorner = 10f;
	internal const float RecruitSeparatorWidth = 797.8f;
	internal const float RecruitSeparatorHeight = 90.9f;
	internal const float RecruitLabelWidth = 543.5f;
	internal const float RecruitLabelHeight = 35.6f;
	internal const float RecruitArmyLabelY = 59f;
	internal const float RecruitArmyRowY = 151f;
	internal const float RecruitCaptiveLabelY = 238f;
	internal const float RecruitCaptiveRowY = 328f;
	internal const float RecruitSlotFirstX = 91f;
	internal const float RecruitSlotPitch = 104f;
	internal const float RecruitSlotWidth = 80f;
	internal const float RecruitSlotBackWidth = 86f;
	internal const float RecruitSlotBackHeight = 100f;
	internal const float RecruitCardWidth = 91f;
	internal const float RecruitCardHeight = 102.5f;
	internal const float RecruitPortraitWidth = 70.5f;
	internal const float RecruitPortraitHeight = 85f;
	internal const float RecruitCountWidth = 80f;
	internal const float RecruitCountHeight = 32f;
	internal const float RecruitCountOffset = 28.9f;
	internal const float RecruitAmountOffset = 31f;
	internal const float RecruitTextInset = 40f;
	internal const float RecruitCostY = 382f;
	internal const float RecruitStatusY = 406f;
	internal const float RecruitLineHeight = 24f;
	internal const float RecruitButtonY = 457f;
	internal const float RecruitButtonWidth = 226.9f;
	internal const float RecruitButtonHeight = 41.2f;
	internal const float RecruitButtonGap = 12f;
	internal const float RecruitButtonSliceMultiplier = 1.92f;
	internal const float RecruitRadialDx = 78f;
	internal const float RecruitRadialDy = 56f;
	internal const float RecruitRadialWidth = 70f;
	internal const float RecruitRadialHeight = 20f;
	internal const float RecruitDragThreshold = 6f;
	internal const string SpriteRecruitBack = "Window_ModalWindow_Back";
	internal const string SpriteRecruitGradient = "Window_ModalWindow_Gradient";
	internal const string SpriteRecruitBackFrame = "Window_ModalWindow_BackFrame";
	internal const string SpriteRecruitLightBack = "Window_ModalWindow_Light_Back";
	internal const string SpriteRecruitSeparator = "Separators_Horizontal";
	internal const string SpriteRecruitFrame = "Window_ModalWindow_Frame";
	internal const string SpriteRecruitCorner = "Window_ModalWindow_FrameCorner";
	internal const string SpriteRecruitDecorFooter = "Window_Decor_Footer";
	internal const string SpriteRecruitDecorHeader = "Window_Decor_Hader";
	internal const string SpriteRecruitHeader = "Window_ModalWindow_Hader";
	internal const string SpriteRecruitHeaderOrnament = "HaderOrnament";
	internal const string SpriteRecruitHeaderMetal = "HeaderMetalOrnament";
	internal const string SpriteRecruitSlotBack = "HUD_DownBar_UnitSlot";
	internal const string SpriteRecruitSlotEmpty = "Frame_Unit_Empty";
	internal const string SpriteRecruitSlotEmptyHover = "Frame_Unit_Empty-1";
	internal const string SpriteRecruitCard = "Property 1=Frame_Unit_Back";
	internal const string SpriteRecruitCardSelected = "Property 1=Frame_Unit_Back_Selected";
	internal const string SpriteRecruitCardHover = "Property 1=Frame_Unit_Top_MauseOver";
	internal const string SpriteRecruitPortraitMask = "Mask_Frame_Unit_Back";
	internal const string SpriteRecruitCountOverlay = "Frame_Unit_NumberOfSquad_Overlay";
	internal const string SpriteRecruitButtonBase = "button_gray";
	internal const string SpriteRecruitButton = "buttom";
	internal const string SpriteRecruitButtonHover = "buttom_MouseOver";
	internal const string SpriteRecruitButtonGreen = "buttom_green";
	internal const string SpriteRecruitButtonGreenHover = "buttom_green_MouseOver";
	internal const string SpriteRecruitButtonDisabled = "Button_NotActive";
	internal const string SpriteRecruitRadialMove = "Property 1=Button_Unit_Move";
	internal const string SpriteRecruitRadialGather = "Property 1=Button_Unit_Union";
	internal const string SpriteRecruitRadialHalf = "Property 1=Button_Unit_Half";
	internal const string SpriteRecruitRadialDivide = "Property 1=Button_Unit_Divide";
	internal static readonly string[] RecruitSprites = { "Window_ModalWindow_Back", "Window_ModalWindow_Gradient", "Window_ModalWindow_BackFrame", "Window_ModalWindow_Light_Back", "Separators_Horizontal", "Window_ModalWindow_Frame", "Window_ModalWindow_FrameCorner", "Window_Decor_Footer", "Window_Decor_Hader", "Window_ModalWindow_Hader", "HaderOrnament", "HeaderMetalOrnament", "HUD_DownBar_UnitSlot", "Frame_Unit_Empty", "Frame_Unit_Empty-1", "Property 1=Frame_Unit_Back", "Property 1=Frame_Unit_Back_Selected", "Property 1=Frame_Unit_Top_MauseOver", "Mask_Frame_Unit_Back", "Frame_Unit_NumberOfSquad_Overlay", "button_gray", "buttom", "buttom_MouseOver", "buttom_green", "buttom_green_MouseOver", "Button_NotActive", "Property 1=Button_Unit_Move", "Property 1=Button_Unit_Move_MouseOver", "Property 1=Button_Unit_Union", "Property 1=Button_Unit_Union_MouseOver", "Property 1=Button_Unit_Half", "Property 1=Button_Unit_Half_MouseOver", "Property 1=Button_Unit_Divide", "Property 1=Button_Unit_Divide_MouseOver" };
}
