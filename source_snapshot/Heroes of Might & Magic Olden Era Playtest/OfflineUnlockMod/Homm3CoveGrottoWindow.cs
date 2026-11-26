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
using L = OfflineUnlockMod.Homm3CoveGrottoWindowLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Grotto sacrifice window (building pass 2026-11-22), modelled on <see cref="Homm3DungeonWarCaptivesWindow"/>: the
/// Artificing picker's native law-tooltip sprites, fonts and colours. A persistent ticker shows a small "Grotto" button
/// on the town screen while <see cref="Homm3CoveGrottoRuntime.TryGetContext"/> holds (checked every half second).
/// Clicking it opens a modal window with one row per army stack: name, count, experience per creature, and three
/// buttons ("1", "Half", "All"; All stops at the hero's last creature). Clicking a button closes the window, then
/// hands the sacrifice to <see cref="Homm3CoveGrottoRuntime.Sacrifice"/> and shows its result on the War Captives
/// result banner. Close row or Esc closes without a change.
/// </summary>
internal static class Homm3CoveGrottoWindow
{
	private const string TickerObjectName = "OFFLINE_UNLOCK_MOD_COVE_GROTTO_TICKER";
	private const string ButtonCanvasName = "OFFLINE_UNLOCK_MOD_COVE_GROTTO_BUTTON";
	private const string WindowCanvasName = "OFFLINE_UNLOCK_MOD_COVE_GROTTO_WINDOW";
	private const string LogPrefix = "HoMM3 Cove Grotto window: ";
	private const float ContextCheckInterval = 0.5f;

	private static bool _typeRegistered;
	private static bool _typeFailed;
	private static GameObject _tickerObject;
	private static GameObject _buttonCanvas;
	private static UnityImage _buttonImage;
	private static GameObject _windowCanvas;
	private static RectTransform _window;
	private static Homm3CoveGrottoRuntime.Context _context;
	private static string _status;
	private static int _lastTickFrame = -1;
	private static float _nextContextCheck;
	private static bool _buttonWanted;
	private static int _loggedTickErrors;
	private static readonly List<(UnityImage Image, Action Click)> Buttons = new();

	internal static bool IsOpen => _windowCanvas != null;

	// ---------------------------------------------------------------- ticker

	internal static bool EnsureTicker(out string failReason)
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
			UnityObject.DontDestroyOnLoad(go);
			go.AddComponent<Homm3CoveGrottoWindowHost>();
			_tickerObject = go;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "ticker failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static void Tick()
	{
		var frame = Time.frameCount;
		if (frame == _lastTickFrame)
			return;
		_lastTickFrame = frame;
		try
		{
			if (_windowCanvas != null)
			{
				TickWindow();
				return;
			}
			TickButton();
		}
		catch (Exception ex)
		{
			if (_loggedTickErrors++ < 5)
				Plugin.LogSource?.LogError(LogPrefix + "tick failed; closing: " + ex.GetBaseException().Message);
			Close();
			DestroyButton();
		}
	}

	private static void TickButton()
	{
		var now = Time.unscaledTime;
		if (now >= _nextContextCheck)
		{
			_nextContextCheck = now + ContextCheckInterval;
			_buttonWanted = Homm3CoveGrottoRuntime.TownSceneActive() && Homm3CoveGrottoRuntime.TryGetContext(out _, out _);
		}
		if (!_buttonWanted)
		{
			DestroyButton();
			return;
		}
		if (_buttonCanvas == null && !BuildButton())
			return;
		if (_buttonImage == null)
			return;
		var mouse = (Vector2)Input.mousePosition;
		var over = RectTransformUtility.RectangleContainsScreenPoint(_buttonImage.rectTransform, mouse, null);
		var sprite = A.NativeSprite(over ? P.SpriteButtonHover : P.SpriteButton);
		if (sprite != null && _buttonImage.sprite != sprite)
			_buttonImage.sprite = sprite;
		if (over && Input.GetMouseButtonDown(0))
			Open();
	}

	// ---------------------------------------------------------------- open / close

	private static void Open()
	{
		if (!Homm3CoveGrottoRuntime.TryGetContext(out var context, out var reason))
		{
			Homm3DungeonWarCaptivesWindow.ShowBanner("Grotto: " + reason);
			return;
		}
		if (!Homm3CoveGrottoRuntime.TryResolveLogicHero(context, out reason))
		{
			Homm3DungeonWarCaptivesWindow.ShowBanner("Grotto: the hero could not be reached (" + reason + ").");
			return;
		}
		_context = context;
		_status = null;
		if (!EnsureWindowCanvas(out reason))
		{
			_context = null;
			Plugin.LogSource?.LogError(LogPrefix + "window failed: " + reason);
			return;
		}
		DestroyButton();
		Homm3TowerArtificingPickerInputBlock.Begin();
		Build();
	}

	private static void Close()
	{
		var wasOpen = _windowCanvas != null;
		_context = null;
		Buttons.Clear();
		DestroyWindowCanvas();
		if (wasOpen)
			Homm3TowerArtificingPickerInputBlock.End();
		_nextContextCheck = 0f;
	}

	private static void TickWindow()
	{
		Homm3TowerArtificingPickerInputBlock.Hold();
		if (Input.GetKeyDown(KeyCode.Escape) || ModActions.GetCurrentCityData() == null)
		{
			Close();
			return;
		}
		var mouse = (Vector2)Input.mousePosition;
		foreach (var (image, _) in Buttons)
		{
			if (image == null || image.color == L.DisabledTint)
				continue;
			var sprite = A.NativeSprite(RectTransformUtility.RectangleContainsScreenPoint(image.rectTransform, mouse, null) ? P.SpriteButtonHover : P.SpriteButton);
			if (sprite != null && image.sprite != sprite)
				image.sprite = sprite;
		}
		if (!Input.GetMouseButtonDown(0))
			return;
		foreach (var (image, click) in Buttons)
		{
			if (image != null && click != null && RectTransformUtility.RectangleContainsScreenPoint(image.rectTransform, mouse, null))
			{
				click();
				return;
			}
		}
	}

	private static void Sacrifice(int slot, string sid, int count)
	{
		// Close first: the experience can level the hero up, and the native level-up dialog must not sit under this window.
		var context = _context;
		Close();
		var message = Homm3CoveGrottoRuntime.Sacrifice(context, slot, sid, count);
		Homm3DungeonWarCaptivesWindow.ShowBanner(message, message.Length > 60 ? 2 : 1);
	}

	// ---------------------------------------------------------------- view

	private static void Build()
	{
		Buttons.Clear();
		foreach (var child in _window.GetComponentsInChildren<RectTransform>(true))
		{
			if (child != null && child != _window && child.parent == _window)
				UnityObject.Destroy(child.gameObject);
		}
		var c = _context;
		if (!Homm3CoveGrottoRuntime.TryReadStacks(c, out var stacks, out var total, out var fail))
		{
			stacks = new List<Homm3CoveGrottoRuntime.StackRow>();
			_status = "The army could not be read (" + fail + ").";
		}

		var height = L.HeaderHeight + L.IntroTop + L.IntroHeight + stacks.Count * (L.RowHeight + L.RowGap)
		             + L.CloseHeight + L.RowGap + (_status != null ? L.StatusHeight : 0f) + L.FooterHeight + L.BottomPad;
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
		A.AddText(_window, P.FontBook, P.SizeSubHeader, "Grotto", tx, 12f, tw, 28f, P.TipTitle, TextAlignmentOptions.MidlineLeft);
		A.AddText(_window, P.FontMedium, P.SizeSmall, Subtitle(c), tx, 40f, tw, 22f, P.TipNote, TextAlignmentOptions.MidlineLeft);

		var y = L.HeaderHeight + L.IntroTop;
		A.AddText(_window, P.FontMedium, P.SizeMain,
			"Sacrifice creatures for experience. Each creature gives (its value / 40) x 5 experience. The hero keeps at least one creature.",
			L.Pad, y, L.Width - 2f * L.Pad, L.IntroHeight, P.TipBody, TextAlignmentOptions.MidlineLeft, true);
		y += L.IntroHeight;
		foreach (var row in stacks)
		{
			BuildRow(row, total, y);
			y += L.RowHeight + L.RowGap;
		}
		var closeImage = AddButtonPlate(L.Pad, y, L.Width - 2f * L.Pad, L.CloseHeight, true);
		A.AddText(_window, P.FontBook, P.SizeSubHeader, "Close", L.Pad, y, L.Width - 2f * L.Pad, L.CloseHeight, P.ButtonText, TextAlignmentOptions.Center);
		Buttons.Add((closeImage, new Action(Close)));
		y += L.CloseHeight + L.RowGap;
		if (_status != null)
			A.AddText(_window, P.FontMedium, P.SizeSmall, _status, L.Pad, y, L.Width - 2f * L.Pad, L.StatusHeight, P.CostBad, TextAlignmentOptions.MidlineLeft, true);
	}

	private static string Subtitle(Homm3CoveGrottoRuntime.Context c)
	{
		var level = Homm3CoveGrottoRuntime.HeroLevel(c.DataHero);
		var exp = Homm3CoveGrottoRuntime.HeroExp(c.DataHero);
		var text = c.HeroName;
		if (level > 0)
			text += ", level " + level.ToString(CultureInfo.InvariantCulture);
		if (exp >= 0)
			text += ", " + exp.ToString("N0", CultureInfo.InvariantCulture) + " experience";
		if (!string.IsNullOrEmpty(c.CityName))
			text += " (" + c.CityName + ")";
		return text;
	}

	private static void BuildRow(Homm3CoveGrottoRuntime.StackRow row, int total, float y)
	{
		var x = L.Pad;
		var w = L.Width - 2f * L.Pad;
		var max = Homm3CoveGrottoRuntime.MaxSacrifice(row, total);
		var plate = A.AddSliced(_window, P.SpritePanelBody, x, y, w, L.RowHeight, L.RowSliceMultiplier, new Color(0.16f, 0.17f, 0.22f, 1f));
		if (plate != null && plate.sprite != null)
			plate.color = new Color(0.75f, 0.75f, 0.8f, 1f);

		var textW = w - 3f * (L.PickWidth + L.PickGap) - L.RowTextInset;
		var title = row.Name + " x " + row.Count.ToString("N0", CultureInfo.InvariantCulture);
		A.AddText(_window, P.FontBook, P.SizeSubHeader, title, x + L.RowTextInset, y + 6f, textW, 28f, P.TipTitle, TextAlignmentOptions.MidlineLeft);
		var detail = row.ExpEach > 0
			? row.ExpEach.ToString("N0", CultureInfo.InvariantCulture) + " experience each"
			  + (max > 0 ? "; all that may go: " + ((long)max * row.ExpEach).ToString("N0", CultureInfo.InvariantCulture) : "; the hero's last creature stays")
			: "Worth no experience";
		A.AddText(_window, P.FontMedium, P.SizeSmall, detail, x + L.RowTextInset, y + 34f, textW, 22f, max > 0 ? P.TipNote : P.TipWarn, TextAlignmentOptions.MidlineLeft);

		var picks = new (string Label, int Count)[]
		{
			("1", Math.Min(1, max)),
			("Half", Math.Min(max, Math.Max(1, row.Count / 2))),
			("All", max),
		};
		var bx = x + w - 3f * (L.PickWidth + L.PickGap);
		var by = y + (L.RowHeight - L.PickHeight) / 2f;
		foreach (var (label, count) in picks)
		{
			var enabled = count > 0;
			var image = AddButtonPlate(bx, by, L.PickWidth, L.PickHeight, enabled);
			var text = enabled ? label + "\n" + ((long)count * row.ExpEach).ToString("N0", CultureInfo.InvariantCulture) : label;
			A.AddText(_window, P.FontMedium, P.SizeSmall, text, bx, by, L.PickWidth, L.PickHeight, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.Center, true);
			if (enabled)
			{
				var slot = row.Slot;
				var sid = row.Sid;
				var n = count;
				Buttons.Add((image, () => Sacrifice(slot, sid, n)));
			}
			bx += L.PickWidth + L.PickGap;
		}
	}

	private static UnityImage AddButtonPlate(float x, float y, float w, float h, bool enabled)
	{
		var image = A.AddSliced(_window, P.SpriteButton, x, y, w, h, L.ButtonSliceMultiplier,
			enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		if (image != null && image.sprite != null && !enabled)
			image.color = L.DisabledTint;
		return image;
	}

	// ---------------------------------------------------------------- town button

	private static bool BuildButton()
	{
		try
		{
			_buttonCanvas = NewCanvas(ButtonCanvasName, P.SortingOrder - 10);
			if (_buttonCanvas == null)
				return false;
			var canvasRect = _buttonCanvas.GetComponent<RectTransform>();
			var root = A.NewRect("GrottoButton", canvasRect);
			root.anchorMin = root.anchorMax = new Vector2(0f, 1f);
			root.pivot = new Vector2(0f, 1f);
			root.anchoredPosition = new Vector2(L.TownButtonX, -L.TownButtonY);
			root.sizeDelta = new Vector2(L.TownButtonWidth, L.TownButtonHeight);
			_buttonImage = A.AddSliced(root, P.SpriteButton, 0f, 0f, L.TownButtonWidth, L.TownButtonHeight, L.ButtonSliceMultiplier, new Color(0.35f, 0.26f, 0.15f, 1f));
			if (_buttonImage != null)
				_buttonImage.raycastTarget = true;
			A.AddText(root, P.FontBook, P.SizeSubHeader, "Grotto", 0f, 0f, L.TownButtonWidth, L.TownButtonHeight, P.ButtonText, TextAlignmentOptions.Center);
			return _buttonImage != null;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(LogPrefix + "town button failed: " + ex.GetBaseException().Message);
			DestroyButton();
			_buttonWanted = false;
			_nextContextCheck = Time.unscaledTime + 30f;
			return false;
		}
	}

	private static void DestroyButton()
	{
		var go = _buttonCanvas;
		_buttonCanvas = null;
		_buttonImage = null;
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

	// ---------------------------------------------------------------- canvas

	private static bool EnsureHostType()
	{
		if (_typeRegistered)
			return true;
		if (_typeFailed)
			return false;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3CoveGrottoWindowHost>();
			_typeRegistered = true;
			return true;
		}
		catch (Exception ex)
		{
			_typeFailed = true;
			Plugin.LogSource?.LogError(LogPrefix + "host type failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	private static GameObject NewCanvas(string name, int sortingOrder)
	{
		if (!EnsureHostType())
			return null;
		A.ResolveNativeSprites();
		var go = new GameObject(name, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
			Il2CppType.Of<GraphicRaycaster>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		var canvas = go.GetComponent<Canvas>();
		var scaler = go.GetComponent<CanvasScaler>();
		if (canvas == null || scaler == null)
		{
			UnityObject.Destroy(go);
			return null;
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = sortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
		return go;
	}

	private static bool EnsureWindowCanvas(out string failReason)
	{
		failReason = null;
		if (_windowCanvas != null)
			return true;
		var go = NewCanvas(WindowCanvasName, P.SortingOrder);
		if (go == null)
		{
			failReason = "window canvas could not be created";
			return false;
		}
		_windowCanvas = go;
		var canvasRect = go.GetComponent<RectTransform>();
		var block = A.NewImage("Block", canvasRect, null, new Color(0f, 0f, 0f, P.BlockAlpha));
		A.Stretch(block.rectTransform);
		block.raycastTarget = true;
		_window = A.NewRect("Window", canvasRect);
		_window.anchorMin = _window.anchorMax = new Vector2(0.5f, 0.5f);
		_window.pivot = new Vector2(0.5f, 0.5f);
		_window.anchoredPosition = Vector2.zero;
		_window.sizeDelta = new Vector2(L.Width, 600f);
		return true;
	}

	private static void DestroyWindowCanvas()
	{
		var go = _windowCanvas;
		_windowCanvas = null;
		_window = null;
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
}

public sealed class Homm3CoveGrottoWindowHost : MonoBehaviour
{
	public Homm3CoveGrottoWindowHost(IntPtr ptr) : base(ptr) { }

	private void Update() => Homm3CoveGrottoWindow.Tick();
}

/// <summary>Geometry of the Grotto window and town button (window space: top-left origin, y down, 1920x1080 reference).</summary>
internal static class Homm3CoveGrottoWindowLayout
{
	internal const string SkillIconKey = "skill_faction_homm3_cove";
	internal const float Width = 760f;
	internal const float Pad = 22f;
	internal const float HeaderHeight = 74f;
	internal const float FooterHeight = 30f;
	internal const float Ring = 84f;
	internal const float RingIcon = 62f;
	internal const float IntroTop = 16f;
	internal const float IntroHeight = 52f;
	internal const float RowHeight = 64f;
	internal const float RowGap = 10f;
	internal const float RowTextInset = 18f;
	internal const float RowSliceMultiplier = 1.4f;
	internal const float PickWidth = 92f;
	internal const float PickHeight = 48f;
	internal const float PickGap = 8f;
	internal const float CloseHeight = 44f;
	internal const float ButtonSliceMultiplier = 1.4f;
	internal const float StatusHeight = 30f;
	internal const float BottomPad = 14f;
	// Town button: left edge, below the native top bar. Adjust after the first in-game look.
	internal const float TownButtonX = 24f;
	internal const float TownButtonY = 140f;
	internal const float TownButtonWidth = 180f;
	internal const float TownButtonHeight = 52f;
	internal static readonly Color DisabledTint = new(0.42f, 0.42f, 0.42f, 1f);
}
