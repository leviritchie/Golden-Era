using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using DataHero = Hex.Session.Data.Hero;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataRoot = Hex.Session.Data.Data;
using LogicHero = Hex.Session.Logic.Hero;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (SFC): shared plumbing for the town-window buildings (Stronghold Freelancer's Guild, Conflux
/// Magic University). No custom building-click route exists (BhBuilding.OnPointerClick is native and unpatched), so,
/// as the brief allows, each building gets a town-screen button: a small overlay plate on the left edge, shown only while
/// the town screen of a local human's town of that faction is open and the building is built
/// (<see cref="Homm3TownBuildingReader.CityHasBuilding"/>). The modal windows reuse the War Captives look (the law
/// tooltip sprites and fonts of <see cref="Homm3TowerArtificingPickerLayout"/>).
/// One DontDestroyOnLoad host ticks both buildings every frame.
/// </summary>
internal static class Homm3TownBuildingWindowKit
{
	internal const string LogPrefix = "HoMM3 town building window: ";
	private const string HostObjectName = "OFFLINE_UNLOCK_MOD_TOWN_BUILDING_WINDOWS";
	private const float CityCheckSeconds = 0.25f;

	private static bool _hostTypeRegistered;
	private static bool _hostTypeFailed;
	private static GameObject _hostObject;
	private static int _lastTickFrame = -1;
	private static ManualLogSource _log;

	internal static void LogInfo(string m) { try { (_log ?? Plugin.LogSource)?.LogInfo(LogPrefix + m); } catch { } }
	internal static void LogWarning(string m) { try { (_log ?? Plugin.LogSource)?.LogWarning(LogPrefix + m); } catch { } }

	/// <summary>Plugin load: registers the host type, creates the ticking host and resolves the party writer.</summary>
	internal static void TryRegister(ManualLogSource log)
	{
		_log = log;
		if (!Homm3PartyArmyWriter.TryResolve(typeof(LogicHero), out var fail))
			LogWarning("party writer unresolved (" + fail + "); Freelancer's Guild sales will be refused.");
		if (EnsureHost())
			LogInfo("registered (Freelancer's Guild, Magic University town buttons).");
	}

	internal static bool EnsureHostType()
	{
		if (_hostTypeRegistered)
			return true;
		if (_hostTypeFailed)
			return false;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3TownBuildingWindowHost>();
			_hostTypeRegistered = true;
			return true;
		}
		catch (Exception ex)
		{
			_hostTypeFailed = true;
			LogWarning("host type failed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static bool EnsureHost()
	{
		if (_hostObject != null)
			return true;
		if (!EnsureHostType())
			return false;
		try
		{
			_hostObject = new GameObject(HostObjectName);
			UnityObject.DontDestroyOnLoad(_hostObject);
			_hostObject.AddComponent<Homm3TownBuildingWindowHost>();
			return true;
		}
		catch (Exception ex)
		{
			_hostObject = null;
			LogWarning("host failed: " + ex.GetBaseException().Message);
			return false;
		}
	}

	internal static void HostDestroyed() => _hostObject = null;

	internal static void Tick()
	{
		var frame = Time.frameCount;
		if (frame == _lastTickFrame)
			return;
		_lastTickFrame = frame;
		RefreshTown();
		Homm3StrongholdFreelancersGuildWindow.Tick();
		Homm3ConfluxMagicUniversityWindow.Tick();
	}

	// ---------------------------------------------------------------- current town (cached a quarter second)

	private static float _nextCityCheck;
	private static DataObjCity _city;
	private static string _cityFaction;

	/// <summary>The open town screen's city and its presentation faction, or null when no town screen is open.</summary>
	internal static DataObjCity CurrentCity(out string faction)
	{
		faction = _cityFaction;
		return _city;
	}

	private static void RefreshTown()
	{
		var now = Time.realtimeSinceStartup;
		if (now < _nextCityCheck)
			return;
		_nextCityCheck = now + CityCheckSeconds;
		try
		{
			var city = ModActions.GetCurrentCityData();
			_city = city != null && city.Pointer != IntPtr.Zero ? city : null;
			_cityFaction = _city == null ? null : ModActions.GetCurrentCityFraction();
		}
		catch
		{
			_city = null;
			_cityFaction = null;
		}
	}

	/// <summary>
	/// The open town if it is a local human's <paramref name="factionSid"/> town with <paramref name="buildingSid"/> built.
	/// </summary>
	internal static bool TryCurrentTownWith(string factionSid, string buildingSid, out DataObjCity city)
	{
		city = CurrentCity(out var faction);
		if (city == null || !string.Equals(faction, factionSid, StringComparison.Ordinal))
		{
			city = null;
			return false;
		}
		try
		{
			if (!Homm3FactoryLogisticsRuntime.IsLocalHuman(city.ownerSide) || !Homm3TownBuildingReader.CityHasBuilding(city, buildingSid))
			{
				city = null;
				return false;
			}
			return true;
		}
		catch
		{
			city = null;
			return false;
		}
	}

	// ---------------------------------------------------------------- heroes in town

	internal sealed class TownHero
	{
		internal DataHero Data;
		internal LogicHero Logic;
		internal bool Visitor;
		internal string Name;
	}

	/// <summary>The garrison hero and the visiting hero of <paramref name="city"/> (garrison first); logic hero may be null.</summary>
	internal static List<TownHero> HeroesInTown(DataObjCity city)
	{
		var result = new List<TownHero>();
		if (city == null || !Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out _))
			return result;
		var ids = new List<(int Id, bool Visitor)>();
		if (city.garnisonHeroId >= 0)
			ids.Add((city.garnisonHeroId, false));
		if (city.visitorHeroId >= 0 && city.visitorHeroId != city.garnisonHeroId)
			ids.Add((city.visitorHeroId, true));
		if (ids.Count == 0)
			return result;
		var heroes = Homm3FactoryLogisticsEffects.SideHeroes(world, city.ownerSide);
		foreach (var (id, visitor) in ids)
		{
			foreach (var hero in heroes)
			{
				if (Homm3FactoryLogisticsEffects.HeroId(hero) != id)
					continue;
				result.Add(new TownHero
				{
					Data = hero,
					Logic = ResolveLogicHero(hero, id),
					Visitor = visitor,
					Name = Homm3HeroDisplayNames.Resolve(hero.configSid),
				});
				break;
			}
		}
		return result;
	}

	// Logic hero lookup: the logistics cache first (filled at day start and on visits), then the logic root's hero
	// registry (Dictionary<int, Logic.Hero>), resolved once by shape: the Hex type with a static property of its own type
	// and an instance property of type Data (the logic root), then its property holding Dictionary<int, Logic.Hero>.
	private static bool _registryAttempted;
	private static PropertyInfo _rootStatic;
	private static PropertyInfo _rootHeroes;
	private static PropertyInfo _heroesDict;

	internal static LogicHero ResolveLogicHero(DataHero hero, int id)
	{
		var cached = Homm3FactoryLogisticsRuntime.CachedLogicHero(hero);
		if (cached != null)
			return cached;
		try
		{
			if (!ResolveRegistry())
				return null;
			var root = _rootStatic.GetValue(null);
			var heroes = root == null ? null : _rootHeroes.GetValue(root);
			var dict = heroes == null ? null : _heroesDict.GetValue(heroes) as Il2CppSystem.Collections.Generic.Dictionary<int, LogicHero>;
			if (dict == null || !dict.ContainsKey(id))
				return null;
			var lh = dict[id];
			if (lh == null || lh.Pointer == IntPtr.Zero)
				return null;
			var dh = Homm3FactoryLogisticsRuntime.DataHeroOf(lh);
			if (dh == null || dh.Pointer != hero.Pointer)
				return null;
			Homm3FactoryLogisticsRuntime.RememberLogicHero(lh, dh);
			return lh;
		}
		catch (Exception ex)
		{
			LogWarning("logic hero lookup failed: " + ex.GetBaseException().Message);
			return null;
		}
	}

	private static bool ResolveRegistry()
	{
		if (_heroesDict != null)
			return true;
		if (_registryAttempted)
			return false;
		_registryAttempted = true;
		const BindingFlags inst = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		const BindingFlags stat = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		var dictType = typeof(Il2CppSystem.Collections.Generic.Dictionary<int, LogicHero>);
		try
		{
			foreach (var type in GameMember.EnumerateHexTypes())
			{
				try
				{
					if (type == null || type.IsAbstract || type.IsValueType)
						continue;
					PropertyInfo self = null;
					foreach (var p in type.GetProperties(stat))
						if (p.PropertyType == type && p.GetIndexParameters().Length == 0) { self = p; break; }
					if (self == null)
						continue;
					var hasData = false;
					foreach (var p in type.GetProperties(inst))
						if (p.PropertyType == typeof(DataRoot)) { hasData = true; break; }
					if (!hasData)
						continue;
					foreach (var p in type.GetProperties(inst))
					{
						if (p.GetIndexParameters().Length != 0 || p.PropertyType.IsValueType || p.PropertyType == typeof(DataRoot))
							continue;
						foreach (var q in p.PropertyType.GetProperties(inst))
						{
							if (q.PropertyType != dictType || q.GetIndexParameters().Length != 0)
								continue;
							_rootStatic = self;
							_rootHeroes = p;
							_heroesDict = q;
							LogInfo("logic hero registry: " + type.Name + "." + self.Name + " -> " + p.Name + "." + q.Name + ".");
							return true;
						}
					}
				}
				catch
				{
					// Types that fail to reflect are not the logic root.
				}
			}
		}
		catch (Exception ex)
		{
			LogWarning("logic hero registry scan failed: " + ex.GetBaseException().Message);
		}
		LogWarning("logic hero registry not found; only heroes cached at day start or on a visit can be served.");
		return false;
	}

	// ---------------------------------------------------------------- town-screen button

	internal sealed class TownButton
	{
		private readonly string _name;
		private readonly string _label;
		private GameObject _go;
		private UnityImage _plate;
		private bool _hover;

		internal TownButton(string objectName, string label)
		{
			_name = objectName;
			_label = label;
		}

		/// <summary>Shows or hides the button; true on the frame it is clicked.</summary>
		internal bool Update(bool shown)
		{
			try
			{
				if (!shown)
				{
					Hide();
					return false;
				}
				if (_go == null && !Build())
					return false;
				if (!_go.activeSelf)
					_go.SetActive(true);
				var over = RectTransformUtility.RectangleContainsScreenPoint(_plate.rectTransform, (Vector2)Input.mousePosition, null);
				if (over != _hover)
				{
					// While the pointer is on the button the town must not take the click.
					_hover = over;
					if (over) Homm3TowerArtificingPickerInputBlock.Begin();
					else Homm3TowerArtificingPickerInputBlock.End();
					var sprite = A.NativeSprite(over ? P.SpriteButtonHover : P.SpriteButton);
					if (sprite != null)
						_plate.sprite = sprite;
				}
				if (over)
					Homm3TowerArtificingPickerInputBlock.Hold();
				return over && Input.GetMouseButtonDown(0);
			}
			catch (Exception ex)
			{
				LogWarning(_label + " button failed: " + ex.GetBaseException().Message);
				Destroy();
				return false;
			}
		}

		/// <summary>The window takes the input block over when it opens from this button.</summary>
		internal void HandOff() => _hover = false;

		internal void Hide()
		{
			if (_hover)
			{
				_hover = false;
				try { Homm3TowerArtificingPickerInputBlock.End(); } catch { }
			}
			if (_go != null && _go.activeSelf)
				_go.SetActive(false);
		}

		private bool Build()
		{
			A.ResolveNativeSprites();
			var go = new GameObject(_name, new Il2CppSystem.Type[]
			{
				Il2CppType.Of<RectTransform>(),
				Il2CppType.Of<Canvas>(),
				Il2CppType.Of<CanvasScaler>(),
			});
			UnityObject.DontDestroyOnLoad(go);
			var canvas = go.GetComponent<Canvas>();
			canvas.renderMode = RenderMode.ScreenSpaceOverlay;
			canvas.overrideSorting = true;
			canvas.sortingOrder = P.SortingOrder - 10;
			var scaler = go.GetComponent<CanvasScaler>();
			scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
			scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
			scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
			scaler.matchWidthOrHeight = 1f;
			var root = A.NewRect("Root", go.transform);
			// Left edge, a third of the way down: clear of the top resource bar and the bottom town panel.
			root.anchorMin = root.anchorMax = new Vector2(0f, 0.66f);
			root.pivot = new Vector2(0f, 0.5f);
			root.anchoredPosition = new Vector2(14f, 0f);
			root.sizeDelta = new Vector2(ButtonWidth, ButtonHeight);
			_plate = A.AddSliced(root, P.SpriteButton, 0f, 0f, ButtonWidth, ButtonHeight, 1.4f, new Color(0.35f, 0.26f, 0.15f, 1f));
			A.AddText(root, P.FontBook, P.SizeMain, _label, 0f, 0f, ButtonWidth, ButtonHeight, P.ButtonText, TextAlignmentOptions.Center);
			_go = go;
			return _plate != null;
		}

		internal void Destroy()
		{
			Hide();
			var go = _go;
			_go = null;
			_plate = null;
			if (go != null)
				try { UnityObject.Destroy(go); } catch { }
		}
	}

	internal const float ButtonWidth = 240f;
	internal const float ButtonHeight = 48f;

	// ---------------------------------------------------------------- modal window

	/// <summary>A blocking overlay canvas with one centred window rect (War Captives geometry and sprites).</summary>
	internal sealed class Modal
	{
		private readonly string _name;
		private GameObject _go;
		internal RectTransform Window { get; private set; }
		internal bool IsOpen => _go != null;

		internal Modal(string objectName) => _name = objectName;

		internal bool Open(float width, out string fail)
		{
			fail = null;
			if (_go != null)
				return true;
			if (!EnsureHostType())
			{
				fail = "window host type failed to register";
				return false;
			}
			try
			{
				A.ResolveNativeSprites();
				var go = new GameObject(_name, new Il2CppSystem.Type[]
				{
					Il2CppType.Of<RectTransform>(),
					Il2CppType.Of<Canvas>(),
					Il2CppType.Of<CanvasScaler>(),
					Il2CppType.Of<GraphicRaycaster>(),
				});
				UnityObject.DontDestroyOnLoad(go);
				_go = go;
				var canvas = go.GetComponent<Canvas>();
				var scaler = go.GetComponent<CanvasScaler>();
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
				Window = A.NewRect("Window", canvasRect);
				Window.anchorMin = Window.anchorMax = new Vector2(0.5f, 0.5f);
				Window.pivot = new Vector2(0.5f, 0.5f);
				Window.anchoredPosition = Vector2.zero;
				Window.sizeDelta = new Vector2(width, 600f);
				Homm3TowerArtificingPickerInputBlock.Begin();
				return true;
			}
			catch (Exception ex)
			{
				fail = "window failed: " + ex.GetBaseException().Message;
				Close();
				return false;
			}
		}

		/// <summary>Removes every child of the window (before a rebuild).</summary>
		internal void Clear()
		{
			if (Window == null)
				return;
			foreach (var child in Window.GetComponentsInChildren<RectTransform>(true))
				if (child != null && child != Window && child.parent == Window)
					UnityObject.Destroy(child.gameObject);
		}

		internal void Close()
		{
			var go = _go;
			_go = null;
			Window = null;
			try { Homm3TowerArtificingPickerInputBlock.End(); } catch { }
			if (go != null)
				try { UnityObject.Destroy(go); } catch { }
		}
	}

	// Window geometry (window space: top-left origin, y down; War Captives values).
	internal const float Pad = 22f;
	internal const float HeaderHeight = 74f;
	internal const float FooterHeight = 30f;
	internal const float Ring = 84f;
	internal const float RingIcon = 62f;
	internal const float RowHeight = 64f;
	internal const float RowGap = 10f;
	internal const float RowTextInset = 22f;
	internal const float SmallButtonWidth = 86f;
	internal const float SmallButtonHeight = 40f;
	internal static readonly Color Plate = new(0.1f, 0.12f, 0.18f, 0.97f);
	internal static readonly Color RowColor = new(0.35f, 0.26f, 0.15f, 1f);
	internal static readonly Color RowDisabled = new(0.2f, 0.2f, 0.2f, 1f);
	internal static readonly Color DisabledTint = new(0.42f, 0.42f, 0.42f, 1f);

	/// <summary>Panel body, header and footer plates, the header ring with the faction skill icon, title and subtitle.</summary>
	internal static void Chrome(RectTransform window, float width, float height, string iconKey, string title, string subtitle)
	{
		window.sizeDelta = new Vector2(width, height);
		A.AddSliced(window, P.SpritePanelBody, 0f, HeaderHeight - 12f, width, height - HeaderHeight - FooterHeight + 24f, P.PanelSliceMultiplier, Plate);
		A.AddSliced(window, P.SpritePanelHeader, 0f, 0f, width, HeaderHeight, P.PanelSliceMultiplier, Plate);
		A.AddSliced(window, P.SpritePanelFooter, 0f, height - FooterHeight, width, FooterHeight, P.PanelSliceMultiplier, Plate);
		var ringCx = Pad + Ring / 2f;
		var ringCy = HeaderHeight / 2f;
		if (iconKey != null && Homm3FactionSkillIconSpriteCache.TryGetOrCreateSprite(iconKey, out var icon) && icon)
		{
			var image = A.AddSpriteImage(window, "Icon", icon, ringCx - RingIcon / 2f, ringCy - RingIcon / 2f, RingIcon, RingIcon);
			image.preserveAspect = true;
		}
		A.AddCentered(window, P.SpritePanelRing, ringCx, ringCy, Ring, Ring, P.TipTitle);
		var tx = Pad + Ring + 12f;
		var tw = width - tx - Pad;
		A.AddText(window, P.FontBook, P.SizeSubHeader, title, tx, 12f, tw, 28f, P.TipTitle, TextAlignmentOptions.MidlineLeft);
		A.AddText(window, P.FontMedium, P.SizeSmall, subtitle, tx, 40f, tw, 22f, P.TipNote, TextAlignmentOptions.MidlineLeft);
	}

	/// <summary>A button plate with a centred label; returns the plate image when enabled (for hit tests), else null.</summary>
	internal static UnityImage Button(RectTransform window, string label, float x, float y, float w, float h, bool enabled, bool selected = false)
	{
		var image = A.AddSliced(window, P.SpriteButton, x, y, w, h, 1.4f, enabled ? RowColor : RowDisabled);
		if (image != null && image.sprite != null)
		{
			if (!enabled)
				image.color = DisabledTint;
			else if (selected)
				image.color = new Color(1f, 0.9f, 0.6f, 1f);
		}
		A.AddText(window, P.FontMedium, P.SizeMain, label, x, y, w, h, enabled ? P.ButtonText : P.ButtonTextDisabled, TextAlignmentOptions.Center);
		return enabled ? image : null;
	}

	/// <summary>Swaps hover sprites on enabled plates; returns the index of the plate clicked this frame, or -1.</summary>
	internal static int HoverAndClick(List<UnityImage> plates)
	{
		var mouse = (Vector2)Input.mousePosition;
		var clicked = -1;
		var down = Input.GetMouseButtonDown(0);
		for (var i = 0; i < plates.Count; i++)
		{
			var image = plates[i];
			if (image == null)
				continue;
			var over = RectTransformUtility.RectangleContainsScreenPoint(image.rectTransform, mouse, null);
			var sprite = A.NativeSprite(over ? P.SpriteButtonHover : P.SpriteButton);
			if (sprite != null && image.sprite != sprite)
				image.sprite = sprite;
			if (over && down && clicked < 0)
				clicked = i;
		}
		return clicked;
	}
}

public sealed class Homm3TownBuildingWindowHost : MonoBehaviour
{
	public Homm3TownBuildingWindowHost(IntPtr ptr) : base(ptr) { }

	private void Update() => Homm3TownBuildingWindowKit.Tick();

	private void OnDestroy() => Homm3TownBuildingWindowKit.HostDestroyed();
}
