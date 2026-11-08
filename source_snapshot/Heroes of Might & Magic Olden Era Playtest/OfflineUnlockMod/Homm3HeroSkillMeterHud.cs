using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>What a skill meter shows for one hero right now.</summary>
internal sealed class Homm3HeroSkillMeterState
{
	/// <summary>Core progress, 0..1 (vertical fill, bottom up, like the vanilla necromancy energy).</summary>
	internal float Fill;
	/// <summary>Milestone marks as fill fractions (0..1, exclusive).</summary>
	internal float[] Ticks = Array.Empty<float>();
	/// <summary>Distinct "used up" state (e.g. this week's restock spent): spent fill colour, dimmed icon.</summary>
	internal bool Spent;
	/// <summary>Mod skill-icon key for the socket (Homm3FactionSkillIconSpriteCache); null = the spec's icon.</summary>
	internal string IconKey;
	/// <summary>TMP rich text for the native hover tooltip.</summary>
	internal string Tooltip;
	internal string LogSummary;
}

/// <summary>
/// Reads the meter for a Logic.Hero. Returns true with state == null when the hero simply lacks the skill (meter
/// hidden, nothing logged); false with a reason when the state cannot be read (meter hidden, logged).
/// </summary>
internal delegate bool Homm3HeroSkillMeterReader(object logicHero, out Homm3HeroSkillMeterState state, out string failReason);

/// <summary>One per skill; configured by its owner (Captives, Hunting Grounds) and registered once.</summary>
internal sealed class Homm3HeroSkillMeterSpec
{
	internal string Key;
	/// <summary>Stacking order when several meters show for one hero (lower = closer to the portrait).</summary>
	internal int Order;
	internal string IconKey;
	internal Color FillColor;
	internal Color SpentFillColor;
	internal Homm3HeroSkillMeterReader Read;
}

/// <summary>
/// All meter geometry, in units of the native 1920x1080 hero-HUD canvas, local to BhHeroHUDPanel.heroView
/// ("HERO VIEW HUD", centre origin, y up). Slot 0 copies the vanilla necromancy meter exactly
/// (level12 CanvasHeroHUDPanel / HERO VIEW HUD / ContainerEnergy: back "Image" 54x144 at (-61.8,-14.6),
/// fill "Energy" 50x110 at (-62.4,-1.2), Filled Vertical origin Bottom; icon socket of BOTFrameWithEnergy,
/// 23.7 at (-54.8,-66.85)). tools/homm3_hero_skill_meter_mockup.py parses this class; edit values here only.
/// </summary>
internal static class Homm3HeroSkillMeterLayout
{
	internal const string NativeContainerName = "ContainerEnergy";
	internal const string NativeBackChildName = "Image";
	internal const string NativeFillChildName = "Energy";

	internal const float BackX = -61.8f;
	internal const float BackY = -14.6f;
	internal const float BackWidth = 54f;
	internal const float BackHeight = 144f;
	internal const float FillX = -62.4f;
	internal const float FillY = -1.2f;
	internal const float FillWidth = 50f;
	internal const float FillHeight = 110f;
	internal const float IconX = -54.8f;
	internal const float IconY = -66.85f;
	internal const float IconSize = 23.7f;

	/// <summary>Each further meter (or every meter, when the vanilla necromancy/Schism meter is showing) moves out by this.</summary>
	internal const float StackOffsetX = -38f;

	internal const float TickThickness = 2.4f;
	internal const float TickOverhang = 1.5f;
	internal const byte TickAlphaThreshold = 96;
	internal static readonly Color TickColor = new(0.10f, 0.08f, 0.06f, 0.95f);
	internal static readonly Color SpentIconColor = new(0.62f, 0.62f, 0.62f, 1f);

	internal const string TooltipTitleColor = "#D6BC7C";
	internal const string TooltipNoteColor = "#B4ADA3";
}

/// <summary>
/// Shared hero-skill meter: a native-look gauge beside the adventure hero-bar portrait, one per registered skill,
/// built from the vanilla necromancy meter's own loaded sprites (housing + energy fill, the fill recoloured
/// through a one-time greyscale copy so each skill can tint it) and the skill's icon in the socket. No text on
/// screen; hovering shows the native BhTooltips single-text tooltip (the call BhFrameEnergyHero.Show makes).
/// Refreshed by the native BhHeroHUDPanel refresh postfixes and by owners after a state change.
/// </summary>
internal static class Homm3HeroSkillMeterHud
{
	private const string RootPrefix = "HOMM3_SKILL_METER_";
	private static readonly List<Homm3HeroSkillMeterSpec> Specs = new();
	private static readonly Dictionary<string, View> Views = new(StringComparer.Ordinal);
	private static readonly List<Component> Panels = new();
	private static readonly Dictionary<string, string> _lastOutcome = new(StringComparer.Ordinal);

	private static bool _registered;
	private static bool _pumpCreated;
	private static ManualLogSource _log;
	private static int _loggedSkips;
	private static int _loggedApplies;

	private static Sprite _greyFill;
	private static int[] _rowMinX;
	private static int[] _rowMaxX;
	private static bool _greyFillFailed;

	private static object _tooltips;
	private static MethodInfo _tooltipShow;
	private static MethodInfo _tooltipHide;
	private static object _snapLeft;
	private static string _hoverKey;

	private sealed class View
	{
		internal string Key;
		internal Homm3HeroSkillMeterSpec Spec;
		internal Component Panel;
		internal object LogicHero;
		internal GameObject Root;
		internal RectTransform Rect;
		internal Image Fill;
		internal Image Icon;
		internal readonly List<Image> Ticks = new();
		internal Homm3HeroSkillMeterState State;
	}

	/// <summary>Adds a skill meter; the first call also binds the HUD refresh postfixes, the tooltip bridge and the hover pump.</summary>
	internal static bool Register(Homm3HeroSkillMeterSpec spec, Harmony harmony, ManualLogSource log)
	{
		if (spec == null || spec.Read == null || string.IsNullOrEmpty(spec.Key))
			return false;
		_log ??= log;
		if (!_registered && !TryRegisterHost(harmony))
			return false;
		foreach (var existing in Specs)
		{
			if (string.Equals(existing.Key, spec.Key, StringComparison.Ordinal))
				return true;
		}
		Specs.Add(spec);
		Specs.Sort((a, b) => a.Order.CompareTo(b.Order));
		_log?.LogInfo("HoMM3 hero skill meter: '" + spec.Key + "' registered (order " + spec.Order + ", icon " + spec.IconKey + ").");
		return true;
	}

	private static bool TryRegisterHost(Harmony harmony)
	{
		if (harmony == null)
			return false;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var panelType = hexAssembly.GetType("Hex.Session.Hud.BhHeroHUDPanel")
			                ?? throw new TypeLoadException("Missing Hex.Session.Hud.BhHeroHUDPanel");
			ResolveTooltipBridge(hexAssembly);
			const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
			var patched = new List<string>();
			foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelRefresh.NameHints)
			{
				var method = panelType.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method == null || method.ReturnType != typeof(void))
					continue;
				Patch(harmony, method, nameof(PostfixHeroHudRefresh));
				patched.Add(method.Name);
			}
			foreach (var name in GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh.NameHints)
			{
				foreach (var method in panelType.GetMethods(flags))
				{
					var parameters = method.GetParameters();
					if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void) || parameters.Length != 1
					    || !IsSessionHeroType(parameters[0].ParameterType))
						continue;
					Patch(harmony, method, nameof(PostfixHeroHudHeroArgRefresh));
					patched.Add(method.Name + "(hero)");
				}
			}
			if (patched.Count == 0)
				throw new MissingMethodException("no BhHeroHUDPanel refresh method from " + GameSymbols.ImportVisuals.HeroHudPanelRefresh.Id + " / " + GameSymbols.ImportVisuals.HeroHudPanelHeroArgRefresh.Id);
			EnsureHoverPump();
			_registered = true;
			_log?.LogInfo("HoMM3 hero skill meter host registered: BhHeroHUDPanel." + string.Join(", ", patched) + " postfixes; tooltip "
				+ _tooltipShow.Name + "/" + _tooltipHide.Name + " (snap " + _snapLeft + "). Proof tier: build; runtime unproven.");
			return true;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 hero skill meter host not registered (fail closed, no meters): " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static void ResolveTooltipBridge(Assembly hexAssembly)
	{
		var tooltipsType = hexAssembly.GetType(GameSymbols.HeroSkillMeter.TooltipsTypeName)
		                   ?? throw new TypeLoadException("Missing " + GameSymbols.HeroSkillMeter.TooltipsTypeName);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in GameSymbols.HeroSkillMeter.TooltipsShowText.NameHints)
		{
			foreach (var method in tooltipsType.GetMethods(flags))
			{
				var p = method.GetParameters();
				if (string.Equals(method.Name, name, StringComparison.Ordinal) && method.ReturnType == typeof(void) && p.Length == 4
				    && p[0].ParameterType == typeof(string) && p[1].ParameterType == typeof(RectTransform) && p[2].ParameterType.IsEnum && p[3].ParameterType == typeof(bool))
				{
					_tooltipShow = method;
					_snapLeft = Enum.Parse(p[2].ParameterType, GameSymbols.HeroSkillMeter.SnapDirectionName);
					break;
				}
			}
			if (_tooltipShow != null)
				break;
		}
		if (_tooltipShow == null)
			throw new MissingMethodException(GameSymbols.HeroSkillMeter.TooltipsShowText.Id + " (string, RectTransform, ESnapDirection, bool) not found");
		foreach (var name in GameSymbols.HeroSkillMeter.TooltipsHide.NameHints)
		{
			_tooltipHide = tooltipsType.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (_tooltipHide != null && _tooltipHide.ReturnType == typeof(void))
				break;
			_tooltipHide = null;
		}
		if (_tooltipHide == null)
			throw new MissingMethodException(GameSymbols.HeroSkillMeter.TooltipsHide.Id + " () not found");
		var hasInstance = false;
		foreach (var name in GameSymbols.HeroSkillMeter.TooltipsInstanceMembers)
		{
			var property = tooltipsType.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
			if (property != null && property.PropertyType == tooltipsType && property.GetGetMethod(true) != null)
			{
				hasInstance = true;
				_tooltips = property;
				break;
			}
		}
		if (!hasInstance)
			throw new MissingMemberException(GameSymbols.HeroSkillMeter.TooltipsTypeName, "static singleton (HeroSkillMeter.TooltipsInstanceMembers)");
	}

	private static object TooltipsInstance()
	{
		return _tooltips is PropertyInfo property ? property.GetValue(null) : null;
	}

	/// <summary>Re-applies every live meter after an owner changed the buff-backed state.</summary>
	internal static void NotifyStateChanged(string reason)
	{
		if (!_registered)
			return;
		var panels = new List<Component>();
		foreach (var panel in Panels)
		{
			if (panel)
				panels.Add(panel);
		}
		foreach (var panel in panels)
			TryRefresh(panel, null, reason);
	}

	private static void PostfixHeroHudRefresh(object __instance)
	{
		TryRefresh(__instance as Component, null, "hud refresh");
	}

	private static void PostfixHeroHudHeroArgRefresh(object __instance, [HarmonyArgument(0)] object hero)
	{
		TryRefresh(__instance as Component, hero, "hud hero refresh");
	}

	private static bool IsSessionHeroType(Type type)
	{
		if (type == null || type.IsValueType)
			return false;
		foreach (var hint in GameSymbols.HeroMap.SessionHeroTypeHints)
		{
			if (!string.IsNullOrEmpty(hint) && (string.Equals(type.Name, hint, StringComparison.Ordinal) || string.Equals(type.FullName, hint, StringComparison.Ordinal)))
				return true;
		}
		return false;
	}

	private static void TryRefresh(Component panel, object sessionHero, string source)
	{
		if (!panel || Specs.Count == 0)
			return;
		if (!Panels.Contains(panel))
			Panels.Add(panel);
		object logicHero = null;
		Transform heroView = null;
		Transform native = null;
		var vanillaVisible = false;
		try
		{
			sessionHero ??= Homm3FactorySplitAssemblyArmyStripHud.TryResolveSessionHeroFromPanel(panel);
			logicHero = sessionHero == null ? null : Homm3DungeonCaptivesHud.ReadMember(sessionHero, GameSymbols.HeroMap.SessionHeroLogicFields);
			heroView = (Homm3DungeonCaptivesHud.ReadMember(panel, GameSymbols.ImportVisuals.HeroHudPanelHeroViewFields) as Component)?.transform;
			native = heroView ? heroView.Find(Homm3HeroSkillMeterLayout.NativeContainerName) : null;
			if (native && native.gameObject.activeInHierarchy)
			{
				var group = native.GetComponent<CanvasGroup>();
				vanillaVisible = !group || group.alpha > 0.01f;
			}
		}
		catch (Exception ex)
		{
			HideAll(panel, source, "hero/HUD unreadable: " + ex.GetBaseException().Message);
			return;
		}

		var slot = vanillaVisible ? 1 : 0;
		foreach (var spec in Specs)
		{
			var key = ViewKey(panel, spec);
			try
			{
				if (logicHero == null)
				{
					LogTransition(key, "hero unresolved: session hero " + (sessionHero == null ? "null" : sessionHero.GetType().Name + " without a Logic.Hero (HeroMap.SessionHeroLogicFields)") + "; meter hidden");
					Hide(key, null);
					continue;
				}
				if (!spec.Read(logicHero, out var state, out var failReason))
				{
					Hide(key, spec.Key + " (" + source + "): " + failReason);
					continue;
				}
				if (state == null)
				{
					LogTransition(key, "hidden: selected hero lacks the skill");
					Hide(key, null);
					continue;
				}
				if (!TryEnsureView(panel, heroView, native, spec, key, out var view, out var viewFail))
				{
					Hide(key, spec.Key + " (" + source + "): " + viewFail);
					continue;
				}
				view.LogicHero = logicHero;
				Apply(view, state, slot);
				slot++;
				LogTransition(key, "applied (slot " + (slot - 1) + (vanillaVisible ? ", vanilla meter shown" : "") + "): " + state.LogSummary);
			}
			catch (Exception ex)
			{
				Hide(key, spec.Key + " (" + source + ") failed closed: " + ex.GetBaseException().Message);
			}
		}
	}

	/// <summary>
	/// Logs a meter outcome only when it changes for that panel/meter (refreshes are frequent). Greppable:
	/// "HoMM3 hero skill meter &lt;key&gt; applied" / "... hero unresolved".
	/// </summary>
	private static void LogTransition(string key, string outcome)
	{
		if (_lastOutcome.TryGetValue(key, out var last) && string.Equals(last, outcome, StringComparison.Ordinal))
			return;
		_lastOutcome[key] = outcome;
		if (_loggedApplies++ >= 200)
			return;
		var slash = key.IndexOf('/');
		_log?.LogInfo("HoMM3 hero skill meter " + (slash >= 0 ? key.Substring(slash + 1) : key) + " " + outcome + ".");
	}

	private static string ViewKey(Component panel, Homm3HeroSkillMeterSpec spec)
	{
		var ptr = panel is Il2CppObjectBase native ? native.Pointer.ToInt64() : panel.GetInstanceID();
		return ptr.ToString("x") + "/" + spec.Key;
	}

	private static void HideAll(Component panel, string source, string reason)
	{
		foreach (var spec in Specs)
			Hide(ViewKey(panel, spec), spec.Key + " (" + source + "): " + reason);
	}

	private static void Hide(string key, string reason)
	{
		if (Views.TryGetValue(key, out var view) && view?.Root)
			view.Root.SetActive(false);
		if (_hoverKey == key)
			HideTooltip();
		if (!string.IsNullOrEmpty(reason) && _loggedSkips++ < 32)
			_log?.LogWarning("HoMM3 hero skill meter hidden: " + reason);
	}

	private static bool TryEnsureView(Component panel, Transform heroView, Transform native, Homm3HeroSkillMeterSpec spec, string key, out View view, out string failReason)
	{
		failReason = null;
		if (Views.TryGetValue(key, out view) && view?.Root && heroView && view.Root.transform.parent == heroView)
			return true;
		view = null;
		if (!heroView)
		{
			failReason = "BhHeroHUDPanel.heroView missing";
			return false;
		}
		var nativeBack = native ? native.Find(Homm3HeroSkillMeterLayout.NativeBackChildName)?.GetComponent<Image>() : null;
		var nativeFill = native ? native.Find(Homm3HeroSkillMeterLayout.NativeFillChildName)?.GetComponent<Image>() : null;
		if (!nativeBack || !nativeBack.sprite || !nativeFill || !nativeFill.sprite)
		{
			failReason = "vanilla " + Homm3HeroSkillMeterLayout.NativeContainerName + " back/fill sprites not found under heroView";
			return false;
		}
		var fillSprite = GreyFillSprite(nativeFill.sprite);
		if (!Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(spec.IconKey, out var icon) || !icon)
		{
			failReason = "skill icon " + spec.IconKey + " not loadable";
			return false;
		}

		var stale = heroView.Find(RootPrefix + spec.Key);
		if (stale)
			UnityEngine.Object.Destroy(stale.gameObject);
		var root = new GameObject(RootPrefix + spec.Key);
		root.layer = heroView.gameObject.layer;
		root.transform.SetParent(heroView, false);
		root.transform.SetSiblingIndex(native.GetSiblingIndex() + 1);
		var rect = root.AddComponent<RectTransform>();
		rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0.5f, 0.5f);
		rect.sizeDelta = new Vector2(Homm3HeroSkillMeterLayout.BackWidth, Homm3HeroSkillMeterLayout.BackHeight);
		rect.localScale = Vector3.one;

		view = new View { Key = key, Spec = spec, Panel = panel, Root = root, Rect = rect };
		var back = AddImage(root.transform, "back", nativeBack.sprite, 0f, 0f, Homm3HeroSkillMeterLayout.BackWidth, Homm3HeroSkillMeterLayout.BackHeight);
		back.preserveAspect = nativeBack.preserveAspect;
		view.Fill = AddImage(root.transform, "fill", fillSprite ?? nativeFill.sprite, Homm3HeroSkillMeterLayout.FillX - Homm3HeroSkillMeterLayout.BackX,
			Homm3HeroSkillMeterLayout.FillY - Homm3HeroSkillMeterLayout.BackY, Homm3HeroSkillMeterLayout.FillWidth, Homm3HeroSkillMeterLayout.FillHeight);
		view.Fill.type = Image.Type.Filled;
		view.Fill.fillMethod = nativeFill.fillMethod;
		view.Fill.fillOrigin = nativeFill.fillOrigin;
		view.Icon = AddImage(root.transform, "icon", icon, Homm3HeroSkillMeterLayout.IconX - Homm3HeroSkillMeterLayout.BackX,
			Homm3HeroSkillMeterLayout.IconY - Homm3HeroSkillMeterLayout.BackY, Homm3HeroSkillMeterLayout.IconSize, Homm3HeroSkillMeterLayout.IconSize);
		view.Icon.preserveAspect = true;
		Views[key] = view;
		_log?.LogInfo("HoMM3 hero skill meter " + spec.Key + " built under " + heroView.name + " (back " + nativeBack.sprite.name + ", fill "
			+ nativeFill.sprite.name + (fillSprite ? " greyscale copy" : " native, tinted") + ").");
		return true;
	}

	private static Image AddImage(Transform parent, string name, Sprite sprite, float x, float y, float w, float h)
	{
		var go = new GameObject(name);
		go.layer = parent.gameObject.layer;
		go.transform.SetParent(parent, false);
		var rect = go.AddComponent<RectTransform>();
		rect.anchorMin = rect.anchorMax = rect.pivot = new Vector2(0.5f, 0.5f);
		rect.anchoredPosition = new Vector2(x, y);
		rect.sizeDelta = new Vector2(w, h);
		var image = go.AddComponent<Image>();
		image.sprite = sprite;
		image.raycastTarget = false;
		return image;
	}

	private static void Apply(View view, Homm3HeroSkillMeterState state, int slot)
	{
		view.State = state;
		view.Root.SetActive(true);
		view.Rect.anchoredPosition = new Vector2(Homm3HeroSkillMeterLayout.BackX + slot * Homm3HeroSkillMeterLayout.StackOffsetX, Homm3HeroSkillMeterLayout.BackY);
		view.Fill.fillAmount = Mathf.Clamp01(state.Fill);
		view.Fill.color = state.Spent ? view.Spec.SpentFillColor : view.Spec.FillColor;
		var iconKey = state.IconKey ?? view.Spec.IconKey;
		if (Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(iconKey, out var icon) && icon)
			view.Icon.sprite = icon;
		view.Icon.color = state.Spent ? Homm3HeroSkillMeterLayout.SpentIconColor : Color.white;
		ApplyTicks(view, state.Ticks ?? Array.Empty<float>());
		if (_hoverKey == view.Key)
			ShowTooltip(view);
	}

	private static void ApplyTicks(View view, float[] ticks)
	{
		while (view.Ticks.Count < ticks.Length)
		{
			var tick = AddImage(view.Root.transform, "tick", null, 0f, 0f, 1f, 1f);
			tick.color = Homm3HeroSkillMeterLayout.TickColor;
			view.Ticks.Add(tick);
		}
		for (var i = 0; i < view.Ticks.Count; i++)
		{
			var tick = view.Ticks[i];
			if (i >= ticks.Length || !TickSpan(ticks[i], out var left, out var right))
			{
				tick.gameObject.SetActive(false);
				continue;
			}
			// Tick spans the fill crescent's opaque width at that height (from the fill sprite's own alpha rows).
			var y0 = Homm3HeroSkillMeterLayout.FillY - Homm3HeroSkillMeterLayout.BackY - Homm3HeroSkillMeterLayout.FillHeight * 0.5f;
			var rect = tick.rectTransform;
			rect.anchoredPosition = new Vector2(Homm3HeroSkillMeterLayout.FillX - Homm3HeroSkillMeterLayout.BackX - Homm3HeroSkillMeterLayout.FillWidth * 0.5f + (left + right) * 0.5f,
				y0 + Mathf.Clamp01(ticks[i]) * Homm3HeroSkillMeterLayout.FillHeight);
			rect.sizeDelta = new Vector2(right - left + 2f * Homm3HeroSkillMeterLayout.TickOverhang, Homm3HeroSkillMeterLayout.TickThickness);
			tick.gameObject.SetActive(true);
		}
	}

	/// <summary>Opaque horizontal extent (fill-rect units from its left edge) of the fill sprite at a fill fraction.</summary>
	private static bool TickSpan(float fraction, out float left, out float right)
	{
		left = 0f;
		right = Homm3HeroSkillMeterLayout.FillWidth;
		if (_rowMinX == null || _rowMinX.Length == 0)
			return true;
		var rows = _rowMinX.Length;
		var row = Mathf.Clamp(Mathf.RoundToInt(Mathf.Clamp01(fraction) * (rows - 1)), 0, rows - 1);
		if (_rowMaxX[row] < _rowMinX[row])
			return false;
		var scale = Homm3HeroSkillMeterLayout.FillWidth / _rowWidth;
		left = _rowMinX[row] * scale;
		right = (_rowMaxX[row] + 1) * scale;
		return true;
	}

	private static float _rowWidth = 1f;

	/// <summary>
	/// One-time greyscale copy of the native energy fill (GPU blit of its atlas region, then a luminance pass over
	/// ~14k pixels), so each meter tints it with its own colour; also records the opaque span of every row for ticks.
	/// Falls back to the native (green) sprite with a multiply tint, logged once.
	/// </summary>
	private static Sprite GreyFillSprite(Sprite native)
	{
		if (_greyFill)
			return _greyFill;
		if (_greyFillFailed)
			return null;
		RenderTexture rt = null;
		var previous = RenderTexture.active;
		try
		{
			var source = native.texture;
			var region = native.textureRect;
			int w = Mathf.RoundToInt(region.width), h = Mathf.RoundToInt(region.height);
			if (!source || w <= 0 || h <= 0 || native.packed && native.packingRotation != SpritePackingRotation.None)
				throw new InvalidOperationException("fill sprite region unusable (rotated or empty)");
			rt = RenderTexture.GetTemporary(source.width, source.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
			Graphics.Blit(source, rt);
			RenderTexture.active = rt;
			var copy = new Texture2D(w, h, TextureFormat.RGBA32, false);
			copy.ReadPixels(new Rect(region.x, region.y, w, h), 0, 0);
			var pixels = copy.GetPixels32();
			var maxLum = 1f;
			for (var i = 0; i < pixels.Length; i++)
			{
				var p = pixels[i];
				if (p.a > Homm3HeroSkillMeterLayout.TickAlphaThreshold)
					maxLum = Mathf.Max(maxLum, 0.299f * p.r + 0.587f * p.g + 0.114f * p.b);
			}
			_rowMinX = new int[h];
			_rowMaxX = new int[h];
			for (var y = 0; y < h; y++)
			{
				_rowMinX[y] = w;
				_rowMaxX[y] = -1;
			}
			for (var i = 0; i < pixels.Length; i++)
			{
				var p = pixels[i];
				var v = (byte)Mathf.Clamp(Mathf.RoundToInt((0.299f * p.r + 0.587f * p.g + 0.114f * p.b) * 255f / maxLum), 0, 255);
				pixels[i] = new Color32(v, v, v, p.a);
				if (p.a > Homm3HeroSkillMeterLayout.TickAlphaThreshold)
				{
					int x = i % w, y = i / w;
					_rowMinX[y] = Math.Min(_rowMinX[y], x);
					_rowMaxX[y] = Math.Max(_rowMaxX[y], x);
				}
			}
			_rowWidth = w;
			copy.SetPixels32(pixels);
			copy.Apply(false, true);
			copy.name = "homm3_skill_meter_fill_grey";
			_greyFill = Sprite.Create(copy, new Rect(0f, 0f, w, h), new Vector2(0.5f, 0.5f), native.pixelsPerUnit, 0, SpriteMeshType.FullRect);
			_greyFill.name = "homm3_skill_meter_fill_grey";
			return _greyFill;
		}
		catch (Exception ex)
		{
			_greyFillFailed = true;
			_rowMinX = _rowMaxX = null;
			_log?.LogWarning("HoMM3 hero skill meter: greyscale fill copy failed (" + ex.GetBaseException().Message + "); using the native fill with a multiply tint.");
			return null;
		}
		finally
		{
			RenderTexture.active = previous;
			if (rt)
				RenderTexture.ReleaseTemporary(rt);
		}
	}

	// ---------------------------------------------------------------- hover / native tooltip

	internal static void TickHover()
	{
		if (!_registered || Views.Count == 0)
			return;
		string hovered = null;
		try
		{
			var mouse = Input.mousePosition;
			foreach (var pair in Views)
			{
				var view = pair.Value;
				if (view?.Root == null || !view.Root.activeInHierarchy || view.State == null)
					continue;
				var canvas = view.Root.GetComponentInParent<Canvas>();
				var camera = canvas && canvas.renderMode != RenderMode.ScreenSpaceOverlay ? canvas.worldCamera : null;
				if (RectTransformUtility.RectangleContainsScreenPoint(view.Rect, new Vector2(mouse.x, mouse.y), camera))
				{
					hovered = pair.Key;
					break;
				}
			}
		}
		catch (Exception ex)
		{
			if (_loggedSkips++ < 32)
				_log?.LogWarning("HoMM3 hero skill meter hover check failed: " + ex.GetBaseException().Message);
			return;
		}
		if (hovered == _hoverKey)
			return;
		if (_hoverKey != null)
			HideTooltip();
		if (hovered != null && Views.TryGetValue(hovered, out var target))
		{
			_hoverKey = hovered;
			RefreshHoveredState(target);
			ShowTooltip(target);
		}
	}

	private static void RefreshHoveredState(View view)
	{
		try
		{
			if (view.LogicHero != null && view.Spec.Read(view.LogicHero, out var state, out _) && state != null)
				view.State = state;
		}
		catch
		{
			// keep the state from the last HUD refresh
		}
	}

	private static void ShowTooltip(View view)
	{
		try
		{
			var tooltips = TooltipsInstance();
			if (tooltips == null || string.IsNullOrEmpty(view.State?.Tooltip))
				return;
			_tooltipShow.Invoke(tooltips, new[] { view.State.Tooltip, view.Rect, _snapLeft, (object)false });
		}
		catch (Exception ex)
		{
			if (_loggedSkips++ < 32)
				_log?.LogWarning("HoMM3 hero skill meter: native tooltip show failed: " + ex.GetBaseException().Message);
		}
	}

	private static void HideTooltip()
	{
		_hoverKey = null;
		try
		{
			var tooltips = TooltipsInstance();
			if (tooltips != null)
				_tooltipHide.Invoke(tooltips, Array.Empty<object>());
		}
		catch (Exception ex)
		{
			if (_loggedSkips++ < 32)
				_log?.LogWarning("HoMM3 hero skill meter: native tooltip hide failed: " + ex.GetBaseException().Message);
		}
	}

	private static void EnsureHoverPump()
	{
		if (_pumpCreated)
			return;
		ClassInjector.RegisterTypeInIl2Cpp<Homm3HeroSkillMeterHoverPump>();
		var go = new GameObject("Homm3HeroSkillMeterHoverPump");
		go.AddComponent<Homm3HeroSkillMeterHoverPump>();
		UnityEngine.Object.DontDestroyOnLoad(go);
		_pumpCreated = true;
	}

	private static void Patch(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = typeof(Homm3HeroSkillMeterHud).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + target.DeclaringType?.FullName + "." + target.Name + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}
}

internal sealed class Homm3HeroSkillMeterHoverPump : MonoBehaviour
{
	public Homm3HeroSkillMeterHoverPump(IntPtr pointer) : base(pointer)
	{
	}

	private void LateUpdate()
	{
		Homm3HeroSkillMeterHud.TickHover();
	}
}
