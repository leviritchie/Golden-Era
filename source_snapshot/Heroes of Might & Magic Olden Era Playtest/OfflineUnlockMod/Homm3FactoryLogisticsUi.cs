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
using W = OfflineUnlockMod.Homm3DungeonWarCaptivesWindowLayout;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Shared widgets of the two Factory Logistics Network panels (lane UI of docs/factory_logistics_runtime_contract.md):
/// <see cref="Homm3FactoryLogisticsUpgradePanel"/> (hero visits a building) and <see cref="Homm3FactoryLogisticsViewer"/>
/// (the free "Logistics Network" spell). Both reuse the War Captives recruit shell (native modal-window sprites) and the
/// Artificing picker's fonts, colours, canvas settings and input gates, as the Elemental Fusion panel does.
/// The panels only display what <see cref="Homm3FactoryLogistics"/> returns and call its commands; they hold no game state.
/// Visual target: V:/olden_port_work/factory_logistics/mockups (tools/factory_logistics/*_mockup.py).
/// Proof tier: source/static until the plugin compiles; runtime unproven.
/// </summary>
internal static class Homm3FactoryLogisticsUi
{
	internal const string LogPrefix = "[FactoryLogistics] ui: ";

	internal const string SpriteTab = "Button_Tab_Dark";
	internal const string SpriteTabSelected = "Button_Tab_Dark_Selected";
	internal const string SpriteTabHover = "Button_Tab_Dark_MouseOver";
	internal const string SpriteRow = "tab_1";
	internal const string SpriteRowSelected = "tab_selected_1";
	internal const string SpritePlus = "button_plus";
	internal const string SpriteMinus = "button_minus";

	/// <summary>Top-bar resource icons, keyed by a lower-case fragment of the resource sid.</summary>
	private static readonly (string Fragment, string Sprite, string Name)[] Resources_ =
	{
		("gold", "Icon_Resource_Gold", "gold"),
		("wood", "Icon_Resource_Wood", "wood"),
		(GameSymbols.CovePlunder.OreResourceName, "Icon_Resource_Iron", GameSymbols.CovePlunder.OreResourceName),
		("crystal", "Icon_Resource_\u0421rystal", "crystal"),   // the native sprite name starts with a Cyrillic "С"
		("mercury", "Icon_Resource_Mercury", "mercury"),
		("gemstone", "Icon_Resource_GemStone", "gems"),
		("dust", "Icon_Resource_AlchemicalDust", "dust"),
	};

	/// <summary>Placeholder enhancement icons (vanilla town-building art, as the approved mockups), by id / name fragment.</summary>
	private static readonly (string Fragment, string Sprite)[] EnhancementIcons =
	{
		("byproduct", "H_build_Treasury"),
		("export", "H_build_Merchant"),
		("power", "N_build_Resource_Silo"),
		("arcane", "U_build_Mage_Guild_Level_3"),
		("synth", "U_build_Mage_Guild_Level_3"),
		("warehouse", "H_build_Resource_Depot"),
		("logistics_hub", "H_build_Resource_Depot"),
		("station", "U_build_Portal_Summoning"),
		("rail", "U_build_Portal_Summoning"),
		("food", "H_build_Tavern"),
		("housing", "H_build_Main_Level_1"),
		("merc", "H_build_Training_Range"),
		("support", "H_build_Tavern"),
	};

	private static readonly (string Fragment, string Sprite)[] MineIcons =
	{
		("gold", "mine_gold"),
		("crystal", "mine_crystals"),
		("gemstone", "mine_gemstones"),
		// 2026-11-16 playtest: Sawmill / Ore Pit markers were empty frames (no entry). Native sprite names as the mockups use.
		("wood", "mine_wood"),
		("sawmill", "mine_wood"),
		(GameSymbols.CovePlunder.OreResourceName, "mine_ore"),
		("mercury", "mine_mercury"),
		("alchemist", "mine_mercury"),
	};

	private static readonly string[] ExtraSprites =
	{
		SpriteTab, SpriteTabSelected, SpriteTabHover, SpriteRow, SpriteRowSelected, SpritePlus, SpriteMinus,
		P.SpritePanelRing, P.SpritePanelHeader, P.SpritePanelBody, P.SpritePanelFooter, P.SpriteCellBack, P.SpriteCellFrame,
		P.SpriteTierBadge, P.SpriteClose, P.SpriteCloseHover, "Knob",
	};

	private static readonly Dictionary<string, Sprite> Sprites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMissing = new(StringComparer.Ordinal);
	private static bool _typeRegistered;
	private static bool _typeFailed;

	internal sealed class Clickable
	{
		public RectTransform Rect;
		public UnityImage Image;
		public Sprite Normal;
		public Sprite Hover;
		public Action Click;
	}

	internal static void LogInfo(string message) => Plugin.LogSource?.LogInfo(LogPrefix + message);

	internal static void LogWarning(string message) => Plugin.LogSource?.LogWarning(LogPrefix + message);

	internal static string N(long value) => value.ToString("N0", CultureInfo.InvariantCulture);

	internal static bool Over(RectTransform rect, Vector2 mouse) => rect != null && RectTransformUtility.RectangleContainsScreenPoint(rect, mouse, null);

	/// <summary>Rough single-line width of a label in the panel fonts (generous: the fonts average about half an em per glyph, and a too-narrow box would shorten the text).</summary>
	internal static float TextWidth(string text, float size) => string.IsNullOrEmpty(text) ? 0f : text.Length * size * 0.56f + 2f;

	// ---------------------------------------------------------------- sprites

	internal static void ResolveSprites()
	{
		var wanted = new HashSet<string>(W.RecruitSprites, StringComparer.Ordinal);
		foreach (var name in ExtraSprites)
			wanted.Add(name);
		foreach (var r in Resources_)
			wanted.Add(r.Sprite);
		foreach (var e in EnhancementIcons)
			wanted.Add(e.Sprite);
		foreach (var m in MineIcons)
			wanted.Add(m.Sprite);
		var stale = Sprites.Count < wanted.Count;
		foreach (var sprite in Sprites.Values)
			stale |= !sprite;
		if (!stale)
			return;
		Sprites.Clear();
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
		foreach (var name in wanted)
		{
			if (!Sprites.ContainsKey(name) && LoggedMissing.Add(name))
				missing.Add(name);
		}
		if (missing.Count > 0)
			LogWarning("sprites not loaded, using flat fallbacks: " + string.Join(", ", missing));
	}

	internal static Sprite Sprite(string name) => name != null && Sprites.TryGetValue(name, out var s) && s ? s : null;

	private static string Lookup((string Fragment, string Sprite)[] table, string key)
	{
		if (string.IsNullOrEmpty(key))
			return null;
		var lower = key.ToLowerInvariant();
		foreach (var (fragment, sprite) in table)
		{
			if (lower.Contains(fragment))
				return sprite;
		}
		return null;
	}

	internal static Sprite ResourceIcon(string sid)
	{
		var lower = (sid ?? "").ToLowerInvariant();
		foreach (var r in Resources_)
		{
			if (lower.Contains(r.Fragment))
				return Sprite(r.Sprite);
		}
		return null;
	}

	internal static string ResourceName(string sid)
	{
		var lower = (sid ?? "").ToLowerInvariant();
		foreach (var r in Resources_)
		{
			if (lower.Contains(r.Fragment))
				return r.Name;
		}
		return sid ?? "?";
	}

	internal static Sprite EnhancementIcon(string id, string name) => Sprite(Lookup(EnhancementIcons, id) ?? Lookup(EnhancementIcons, name));

	/// <summary>The unit's portrait (custom icon registry, then the native sprite catalog); null when neither resolves.</summary>
	internal static Sprite UnitPortrait(string unitSid)
	{
		if (string.IsNullOrEmpty(unitSid))
			return null;
		if (Homm3CustomUiIconHook.TryResolveSprite(unitSid, out var portrait) && portrait)
			return portrait;
		if (Homm3NativeSpriteCatalogRegistrar.TryResolveNative(unitSid, out portrait) && portrait)
			return portrait;
		return null;
	}

	/// <summary>Mines: the native mine icon of the resource; dwellings: the unit portrait. Null when neither resolves.</summary>
	internal static Sprite BuildingIcon(LogisticsBuildingView b)
	{
		if (b == null)
			return null;
		if (b.Kind == LogisticsBuildingKind.Dwelling && !string.IsNullOrEmpty(b.UnitSid))
			return UnitPortrait(b.UnitSid);
		return Sprite(Lookup(MineIcons, b.ResourceSid) ?? Lookup(MineIcons, b.DisplayName));
	}

	// ---------------------------------------------------------------- primitives (window space: top-left origin, y down)

	internal static UnityImage Image(Transform parent, string sprite, float x, float y, float w, float h, Color fallback)
	{
		var image = A.NewImage(sprite ?? "Flat", parent, Sprite(sprite), fallback);
		A.Place(image.rectTransform, x, y, w, h);
		return image;
	}

	internal static UnityImage Flat(Transform parent, float x, float y, float w, float h, Color color)
	{
		var image = A.NewImage("Flat", parent, null, color);
		A.Place(image.rectTransform, x, y, w, h);
		return image;
	}

	internal static UnityImage Sliced(Transform parent, string sprite, float x, float y, float w, float h, float multiplier, Color fallback)
	{
		var image = Image(parent, sprite, x, y, w, h, fallback);
		if (image.sprite != null)
		{
			image.type = UnityImage.Type.Sliced;
			image.pixelsPerUnitMultiplier = multiplier;
			image.fillCenter = true;
		}
		return image;
	}

	internal static UnityImage Centered(Transform parent, string sprite, float cx, float cy, float w, float h, Color fallback) =>
		Image(parent, sprite, cx - w / 2f, cy - h / 2f, w, h, fallback);

	internal static UnityImage SpriteImage(Transform parent, Sprite sprite, float x, float y, float w, float h, bool preserveAspect = true)
	{
		var image = A.AddSpriteImage(parent, "Icon", sprite, x, y, w, h);
		image.preserveAspect = preserveAspect;
		return image;
	}

	internal static TextMeshProUGUI Text(Transform parent, string font, float size, string text, float x, float y, float w, float h, Color color,
		TextAlignmentOptions align = TextAlignmentOptions.Left, bool wrap = false) =>
		A.AddText(parent, font, size, text, x, y, w, h, color, align, wrap);

	/// <summary>A straight segment between two window-space points: a flat image rotated around its start.</summary>
	internal static UnityImage Line(Transform parent, float x0, float y0, float x1, float y1, float thickness, Color color)
	{
		var image = A.NewImage("Line", parent, null, color);
		var rect = image.rectTransform;
		rect.anchorMin = rect.anchorMax = new Vector2(0f, 1f);
		rect.pivot = new Vector2(0f, 0.5f);
		var dx = x1 - x0;
		var dy = y1 - y0;
		rect.sizeDelta = new Vector2(Mathf.Sqrt(dx * dx + dy * dy), thickness);
		rect.anchoredPosition = new Vector2(x0, -y0);
		rect.localRotation = Quaternion.Euler(0f, 0f, Mathf.Atan2(-dy, dx) * Mathf.Rad2Deg);
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

	/// <summary>
	/// The native modal window (Popup_full), as the War Captives recruit panel draws it, at any size, with the Factory
	/// faction skill icon as the header medallion. <paramref name="separatorY"/> &lt;= 0 leaves out the button separator.
	/// </summary>
	internal static void Shell(RectTransform window, float w, float h, string title, float separatorY)
	{
		window.sizeDelta = new Vector2(w, h);
		var plate = new Color(0.08f, 0.1f, 0.15f, 0.98f);
		var band = w - 8f;
		Image(window, W.SpriteRecruitBack, 0f, 0f, w, h, plate);
		Sliced(window, W.SpriteRecruitGradient, 0f, 0f, w, h, 1f, Color.clear);
		Image(window, W.SpriteRecruitLightBack, (w - band) / 2f, W.RecruitHeaderHeight / 2f, band, W.RecruitTopBandHeight, Color.clear);
		Image(window, W.SpriteRecruitLightBack, (w - band) / 2f, h - W.RecruitBottomBandHeight - W.RecruitFrameInset, band, W.RecruitBottomBandHeight, Color.clear);
		if (separatorY > 0f)
			Sliced(window, W.SpriteRecruitSeparator, (w - W.RecruitSeparatorWidth) / 2f, separatorY - W.RecruitSeparatorHeight / 2f, W.RecruitSeparatorWidth, W.RecruitSeparatorHeight, 1f, Color.clear);
		Sliced(window, W.SpriteRecruitBackFrame, 0f, 0f, w, h, 1f, Color.clear);
		Sliced(window, W.SpriteRecruitFrame, 0f, 0f, w, h, 1f, new Color(0.55f, 0.47f, 0.3f, 0.6f));
		var c = W.RecruitCorner;
		Image(window, W.SpriteRecruitCorner, 0f, 0f, c, c, Color.clear);
		Flip(Image(window, W.SpriteRecruitCorner, w - c, 0f, c, c, Color.clear), true, false);
		Flip(Image(window, W.SpriteRecruitCorner, 0f, h - c, c, c, Color.clear), false, true);
		Flip(Image(window, W.SpriteRecruitCorner, w - c, h - c, c, c, Color.clear), true, true);
		Centered(window, W.SpriteRecruitDecorFooter, w / 2f, h - W.RecruitDecorFooterHeight / 2f, W.RecruitDecorFooterWidth, W.RecruitDecorFooterHeight, Color.clear);
		Sliced(window, W.SpriteRecruitHeader, -W.RecruitHeaderOverhang / 2f, 0f, w + W.RecruitHeaderOverhang, W.RecruitHeaderHeight, 1f, plate);
		var hy = W.RecruitHeaderHeight / 2f;
		Centered(window, W.SpriteRecruitHeaderOrnament, w / 2f + W.RecruitOrnamentX, hy, W.RecruitOrnamentWidth, W.RecruitOrnamentHeight, Color.clear);
		Flip(Centered(window, W.SpriteRecruitHeaderOrnament, w / 2f - W.RecruitOrnamentX, hy, W.RecruitOrnamentWidth, W.RecruitOrnamentHeight, Color.clear), true, false);
		Centered(window, W.SpriteRecruitHeaderMetal, w / 2f + W.RecruitMetalX, hy, W.RecruitMetalWidth, W.RecruitMetalHeight, Color.clear);
		Flip(Centered(window, W.SpriteRecruitHeaderMetal, w / 2f - W.RecruitMetalX, hy, W.RecruitMetalWidth, W.RecruitMetalHeight, Color.clear), true, false);
		Centered(window, W.SpriteRecruitDecorHeader, w / 2f, W.RecruitDecorHeaderHeight / 2f - W.RecruitFrameInset, W.RecruitDecorHeaderWidth, W.RecruitDecorHeaderHeight, Color.clear);
		Text(window, P.FontBook, P.SizeSubHeader, title, w / 2f - W.RecruitTitleWidth / 2f, 0f, W.RecruitTitleWidth, W.RecruitHeaderHeight, P.TipTitle, TextAlignmentOptions.Center);
		const float iconX = 58f, ring = 58f, iconSize = 42f;
		if (Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite("skill_faction_homm3_factory", out var icon) && icon)
			SpriteImage(window, icon, iconX - iconSize / 2f, hy - iconSize / 2f, iconSize, iconSize);
		Centered(window, P.SpritePanelRing, iconX, hy, ring, ring, P.TipTitle);
	}

	/// <summary>The recruit panel's button (grey base, brown or green face, hover sprite); disabled ones are not clickable.</summary>
	internal static void Button(Transform parent, List<Clickable> into, string label, float x, float y, float bw, float bh, bool enabled, bool green, Action click, float fontSize = 0f)
	{
		var normal = green ? W.SpriteRecruitButtonGreen : W.SpriteRecruitButton;
		var hover = green ? W.SpriteRecruitButtonGreenHover : W.SpriteRecruitButtonHover;
		Image(parent, W.SpriteRecruitButtonBase, x, y, bw, bh, Color.clear);
		var image = Sliced(parent, enabled ? normal : W.SpriteRecruitButtonDisabled, x, y, bw, bh, W.RecruitButtonSliceMultiplier * (bh < 36f ? 1.6f : 1f),
			enabled ? new Color(0.35f, 0.26f, 0.15f, 1f) : new Color(0.2f, 0.2f, 0.2f, 1f));
		if (!enabled && image.sprite == null)
			image.color = W.DisabledRowTint;
		Text(parent, P.FontBook, fontSize > 0f ? fontSize : P.SizeSubHeader, label, x, y, bw, bh, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.Center);
		if (enabled)
			into.Add(new Clickable { Rect = image.rectTransform, Image = image, Normal = Sprite(normal), Hover = Sprite(hover), Click = click });
	}

	/// <summary>A dark tab (selected / plain / hover sprites) with a centred label.</summary>
	internal static void Tab(Transform parent, List<Clickable> into, string label, float x, float y, float w, float h, bool selected, Action click)
	{
		var image = Image(parent, selected ? SpriteTabSelected : SpriteTab, x, y, w, h, selected ? new Color(0.2f, 0.22f, 0.3f, 1f) : new Color(0.1f, 0.12f, 0.18f, 1f));
		Text(parent, P.FontMedium, P.SizeSmall, label, x, y, w, h, selected ? P.TipTitle : P.ButtonText, TextAlignmentOptions.Center);
		if (!selected)
			into.Add(new Clickable { Rect = image.rectTransform, Image = image, Normal = Sprite(SpriteTab), Hover = Sprite(SpriteTabHover), Click = click });
	}

	/// <summary>Cost icons + amounts on one line, centred in [x, x + width]. Unaffordable costs are drawn in the refusal colour.</summary>
	internal static void Cost(Transform parent, IReadOnlyDictionary<string, int> cost, float x, float cy, float width, float icon, float size, Color color)
	{
		if (cost == null || cost.Count == 0)
		{
			Text(parent, P.FontMedium, size, "Free", x, cy - 13f, width, 26f, color, TextAlignmentOptions.Center);
			return;
		}
		var total = 0f;
		foreach (var kv in cost)
			total += icon + 4f + TextWidth(N(kv.Value), size) + 12f;
		total -= 12f;
		var cx = x + Math.Max(0f, (width - total) / 2f);
		foreach (var kv in cost)
		{
			var sprite = ResourceIcon(kv.Key);
			var amount = N(kv.Value);
			if (sprite != null)
				SpriteImage(parent, sprite, cx, cy - icon / 2f, icon, icon);
			else
				amount += " " + ResourceName(kv.Key);
			cx += icon + 4f;
			var tw = TextWidth(amount, size);
			Text(parent, P.FontMedium, size, amount, cx, cy - 13f, tw + 40f, 26f, color);
			cx += tw + 12f;
		}
	}

	internal static void HoverButtons(List<Clickable> buttons, Vector2 mouse)
	{
		foreach (var b in buttons)
		{
			if (b.Image == null || b.Normal == null && b.Hover == null)
				continue;
			var sprite = Over(b.Rect, mouse) ? b.Hover ?? b.Normal : b.Normal;
			if (sprite != null && b.Image.sprite != sprite)
				b.Image.sprite = sprite;
		}
	}

	/// <summary>Runs the first clickable under the mouse (later entries are on top, so the list is walked backwards).</summary>
	internal static bool ClickButtons(List<Clickable> buttons, Vector2 mouse)
	{
		for (var i = buttons.Count - 1; i >= 0; i--)
		{
			if (!Over(buttons[i].Rect, mouse))
				continue;
			buttons[i].Click?.Invoke();
			return true;
		}
		return false;
	}

	internal static void ClearChildren(RectTransform parent)
	{
		if (parent == null)
			return;
		foreach (var child in parent.GetComponentsInChildren<RectTransform>(true))
		{
			if (child != null && child != parent && child.parent == parent)
				UnityObject.Destroy(child.gameObject);
		}
	}

	// ---------------------------------------------------------------- canvas

	/// <summary>A screen-space overlay canvas (1920x1080 reference) with a dimming blocker and a centred window rect.</summary>
	internal static bool TryCreateCanvas(string name, float w, float h, out GameObject canvasObject, out RectTransform window, out string fail)
	{
		canvasObject = null;
		window = null;
		fail = null;
		if (_typeFailed)
		{
			fail = "panel host type failed to register earlier";
			return false;
		}
		if (!_typeRegistered)
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FactoryLogisticsUiHost>();
				_typeRegistered = true;
			}
			catch (Exception ex)
			{
				_typeFailed = true;
				fail = "panel host failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}
		A.ResolveNativeSprites();
		ResolveSprites();
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
			fail = "panel canvas could not be created";
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
		window = A.NewRect("Window", canvasRect);
		window.anchorMin = window.anchorMax = new Vector2(0.5f, 0.5f);
		window.pivot = new Vector2(0.5f, 0.5f);
		window.anchoredPosition = Vector2.zero;
		window.sizeDelta = new Vector2(w, h);
		if (go.AddComponent<Homm3FactoryLogisticsUiHost>() == null)
		{
			UnityObject.Destroy(go);
			window = null;
			fail = "panel host component could not be added";
			return false;
		}
		canvasObject = go;
		return true;
	}

	internal static void DestroyCanvas(GameObject canvas)
	{
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

	/// <summary>Mouse position in window space (top-left origin, y down, canvas units).</summary>
	internal static bool TryWindowPoint(RectTransform window, Vector2 mouse, out Vector2 point)
	{
		point = default;
		if (window == null || !RectTransformUtility.ScreenPointToLocalPointInRectangle(window, mouse, null, out var local))
			return false;
		var size = window.sizeDelta;
		point = new Vector2(local.x + size.x / 2f, size.y / 2f - local.y);
		return true;
	}

	/// <summary>Plugin.cs calls this once: the upgrade panel opens on the facade's visit event.</summary>
	internal static void TryRegister()
	{
		try
		{
			Homm3FactoryLogistics.VisitRequested += Homm3FactoryLogisticsUpgradePanel.OnVisitRequested;
			LogInfo("registered (upgrade panel on VisitRequested; viewer via Homm3FactoryLogisticsViewer.Open)");
		}
		catch (Exception ex)
		{
			LogWarning("registration failed, panels will not open: " + ex.GetBaseException().Message);
		}
	}
}

/// <summary>Per-canvas host: ticks whichever Logistics panel is open.</summary>
public sealed class Homm3FactoryLogisticsUiHost : MonoBehaviour
{
	public Homm3FactoryLogisticsUiHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		Homm3FactoryLogisticsUpgradePanel.Tick();
		Homm3FactoryLogisticsViewer.Tick();
	}

	private void OnDestroy()
	{
		Homm3FactoryLogisticsUpgradePanel.HostDestroyed();
		Homm3FactoryLogisticsViewer.HostDestroyed();
	}
}
