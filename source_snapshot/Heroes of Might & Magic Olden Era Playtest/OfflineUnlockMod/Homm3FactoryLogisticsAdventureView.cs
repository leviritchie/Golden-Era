using System;
using System.Collections.Generic;
using System.Reflection;
using Il2CppInterop.Runtime;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using DataHero = Hex.Session.Data.Hero;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure-map view check for the Logistics Network Ctrl+L hotkey (UX item 21). The map badges of item 17 were removed
/// at the owner's request (2026-11-16): no Logistics text over buildings on the adventure map.
/// </summary>
internal static class Homm3FactoryLogisticsAdventureView
{
	private static bool _failedOnce;

	// Native world camera (BhWorldCamera), resolved once.
	private static Type _worldCameraType;
	private static MethodInfo _cameraSingleton, _cameraCurrentMap;
	private static bool _cameraResolveFailed;

	/// <summary>
	/// Adventure map on screen: the world camera's Unity camera is enabled, the active scene is not a town interior, no
	/// battle view, no native hire window. Throttled by the caller.
	/// </summary>
	internal static bool TryAdventureView(out Camera camera, out object map)
	{
		camera = null;
		map = null;
		try
		{
			if (ModActions.IsActiveSceneCityInterior() || TempleSwordsmanBillboardPrototype.IsBattleViewActive() || Homm3FactoryLogisticsRuntime.HireWindowOpen())
				return false;
			if (!ResolveCameraMembers())
				return false;
			var worldCamera = _cameraSingleton.Invoke(null, Array.Empty<object>());
			if (worldCamera == null)
				return false;
			map = _cameraCurrentMap.Invoke(worldCamera, Array.Empty<object>());
			if (map == null)
				return false;
			camera = Homm3TowerArtificingRuntime.ReadMember(worldCamera, GameSymbols.AiDriverScreenDump.WorldCameraUnityCameraMembers) as Camera;
			if (camera == null || !camera.isActiveAndEnabled)
			{
				camera = null;
				return false;
			}
			return true;
		}
		catch (Exception ex)
		{
			camera = null;
			map = null;
			if (!_failedOnce)
			{
				_failedOnce = true;
				Homm3FactoryLogisticsRuntime.LogWarning("hotkey: adventure view read threw " + ex.GetBaseException().Message + " (the hotkey stays off while it fails).");
			}
			return false;
		}
	}

	private static bool ResolveCameraMembers()
	{
		if (_cameraSingleton != null && _cameraCurrentMap != null)
			return true;
		if (_cameraResolveFailed)
			return false;
		foreach (var hint in GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeHints)
		{
			_worldCameraType = GameMember.FindType(GameSymbols.HomecomingLayerViewToggle.WorldCameraTypeId + "." + hint, hint);
			if (_worldCameraType != null)
				break;
		}
		if (_worldCameraType != null)
		{
			_cameraSingleton = GameMember.FindFirstMethodByNames(_worldCameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraSingleton);
			_cameraCurrentMap = GameMember.FindFirstMethodByNames(_worldCameraType, Type.EmptyTypes, GameSymbols.HomecomingLayerViewToggle.WorldCameraCurrentMap);
		}
		if (_cameraSingleton == null || !_cameraSingleton.IsStatic || _cameraCurrentMap == null)
		{
			_cameraSingleton = _cameraCurrentMap = null;
			_cameraResolveFailed = true;
			Homm3FactoryLogisticsRuntime.LogWarning("hotkey: world camera members unresolved (HomecomingLayerViewToggle.WorldCamera*); the Ctrl+L hotkey is off.");
			return false;
		}
		return true;
	}
}

/// <summary>
/// Item 21: Ctrl+L on the adventure map opens the Logistics Network viewer without the spellbook. The key is checked once
/// per frame (one GetKeyDown); everything else runs only on the press. F8/F9/F10 are taken by debug tools in this plugin;
/// Ctrl+L is used by nothing in this codebase. Not while a text field has focus, in a town, in battle or with a panel open.
/// </summary>
internal static class Homm3FactoryLogisticsMapHotkey
{
	internal const KeyCode Key = KeyCode.L;

	internal static void Tick()
	{
		if (!Input.GetKeyDown(Key) || !(Input.GetKey(KeyCode.LeftControl) || Input.GetKey(KeyCode.RightControl)))
			return;
		try
		{
			if (Homm3FactoryLogisticsUpgradePanel.IsOpen || Homm3FactoryLogisticsViewer.IsOpen || TextFieldFocused())
				return;
			if (!Homm3FactoryLogisticsAdventureView.TryAdventureView(out _, out _))
				return;
			if (!TryPickHero(out var hero, out var side, out var fail))
			{
				Homm3DungeonWarCaptivesWindow.ShowBanner("Logistics Network: " + fail);
				return;
			}
			Homm3FactoryLogistics.NoteSide(side);
			Homm3FactoryLogisticsState.FlushDirty(side);
			if (!Homm3FactoryLogisticsViewer.Open(hero, out fail))
			{
				Homm3FactoryLogisticsRuntime.LogWarning("hotkey: viewer not opened: " + fail);
				Homm3DungeonWarCaptivesWindow.ShowBanner("Logistics Network: " + fail);
				return;
			}
			Homm3FactoryLogisticsRuntime.LogEvent("viewer opened by Ctrl+L for hero " + hero.configSid + ".");
		}
		catch (Exception ex)
		{
			Homm3FactoryLogisticsRuntime.LogOncePerDay("hotkey", "hotkey threw " + ex.GetBaseException().Message);
		}
	}

	private static bool TextFieldFocused()
	{
		try
		{
			var selected = UnityEngine.EventSystems.EventSystem.current?.currentSelectedGameObject;
			return selected != null && (selected.GetComponent<TMP_InputField>() != null || selected.GetComponent<InputField>() != null);
		}
		catch
		{
			return false;
		}
	}

	/// <summary>The local side's last casting/visiting hero with the skill, else its highest-ranked skilled hero on the map.</summary>
	private static bool TryPickHero(out DataHero hero, out int side, out string fail)
	{
		hero = null;
		side = -1;
		if (!Homm3FactoryLogistics.TryGetViewerSide(out side))
		{
			fail = "no local player found.";
			return false;
		}
		if (!Homm3FactoryLogisticsConfig.TryLoad(out var config, out var cfgFail))
		{
			fail = "configuration not loaded (" + cfgFail + ").";
			return false;
		}
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out var worldFail))
		{
			fail = "game state unreadable (" + worldFail + ").";
			return false;
		}
		var heroes = Homm3FactoryLogisticsEffects.SideHeroes(world, side);
		var lastId = Homm3FactoryLogisticsRuntime.LastSkilledHeroId(side);
		var bestRank = 0;
		foreach (var h in heroes)
		{
			var rank = Homm3FactoryLogisticsRuntime.SkillRank(h, config.SkillSid);
			if (rank <= 0)
				continue;
			if (lastId >= 0 && Homm3FactoryLogisticsEffects.HeroId(h) == lastId)
			{
				hero = h;
				break;
			}
			if (rank > bestRank)
			{
				bestRank = rank;
				hero = h;
			}
		}
		fail = hero == null ? "you have no hero with Logistics Network on the map." : null;
		return hero != null;
	}
}
