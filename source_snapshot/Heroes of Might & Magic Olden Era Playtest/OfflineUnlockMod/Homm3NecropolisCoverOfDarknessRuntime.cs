using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using DataHero = Hex.Session.Data.Hero;
using DataObjCity = Hex.Session.Data.ObjCity;
using DataSide = Hex.Session.Data.Side;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (docs/building_pass_20261122/necropolis.md P4): Necropolis Cover of Darkness.
///
/// The building is the inert <c>cityBonusBanks</c> row <c>Build_Mycelium_Roots</c> in <c>homm3_necropolis_city</c>.
/// HoMM3: enemy players lose sight of the map squares within 20 of the town. Here, at every side's day start
/// (postfix on the side logic OnStartDay, the hook <see cref="Homm3FactoryLogisticsRuntime"/> already uses), every
/// visible node of that side's <c>Side.fogData.visibilityMap</c> within Euclidean radius 20 of a town with the building
/// owned by another side is set to not visible. Nodes around the starting side's own heroes (radius 6) and own towns
/// (radius 5, the city viewRadius) are kept, standing in for the native "re-open what my objects see" pass, which has
/// no proven live symbol.
///
/// The write is to session data in the deterministic side logic (same on every client). It is applied every day,
/// so nothing needs saving: a reload re-applies at the next day start.
///
/// Limits: no ally exclusion (Data.Side has no team field); other owned objects (mines, dwellings, watchtowers) do not
/// protect their surroundings; the fog renderer is not told explicitly (the native redraws on its own vision updates);
/// surface and underground share the grid, so the circle is not clipped to one map view.
/// </summary>
internal static class Homm3NecropolisCoverOfDarknessRuntime
{
	internal const string NecropolisCitySid = "homm3_necropolis_city";
	internal const string CoverBuildingSid = "Build_Mycelium_Roots";
	private const int CoverRadius = 20;
	private const int OwnHeroSightRadius = 6;
	private const int OwnCitySightRadius = 5;

	private static bool _registered;
	private static ManualLogSource _log;
	private static PropertyInfo _sideDataProperty;
	private static int _logged;
	private static readonly HashSet<int> _protected = new();

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var sideLogicType = GameMember.FindType(GameSymbols.SwashbucklerGold.SideLogicTypeId, GameSymbols.SwashbucklerGold.SideLogicTypeHint)
			                    ?? throw new TypeLoadException("side logic type (SwashbucklerGold.SideLogicTypeHint)");
			_sideDataProperty = FindPropertyOfType(sideLogicType, typeof(DataSide))
			                    ?? throw new MissingMemberException(sideLogicType.FullName, "Side property");
			var startDay = sideLogicType.GetMethod(GameSymbols.SwashbucklerGold.SideStartDayName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)
			               ?? throw new MissingMethodException(sideLogicType.FullName, GameSymbols.SwashbucklerGold.SideStartDayName);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3NecropolisCoverOfDarknessRuntime), startDay, null, nameof(PostfixSideStartDay));
			_registered = true;
			log?.LogInfo("HoMM3 Necropolis Cover of Darkness: side day-start hook registered on " + sideLogicType.Name + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Necropolis Cover of Darkness: hook NOT registered (the building has no effect): " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixSideStartDay(object __instance)
	{
		try
		{
			if (__instance == null || _sideDataProperty == null)
				return;
			if (_sideDataProperty.GetValue(__instance) is DataSide side)
				ApplyForSide(side);
		}
		catch (Exception ex)
		{
			if (_logged++ < 8)
				_log?.LogWarning("HoMM3 Necropolis Cover of Darkness: day start failed (no fog change): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>Re-fog the covered squares for <paramref name="side"/>. Returns the number of nodes hidden.</summary>
	internal static int ApplyForSide(DataSide side)
	{
		if (side == null || side.index < 0)
			return 0;
		var fog = side.fogData;
		var visibility = fog?.visibilityMap;
		if (fog == null || visibility == null)
			return 0;
		int w = fog.sizeX, h = fog.sizeZ;
		if (w <= 0 || h <= 0 || visibility.Length != w * h)
			return 0;
		if (!Homm3FactoryLogisticsEffects.TryBuildWorld(out var world, out var fail) || world == null)
		{
			if (_logged++ < 8)
				_log?.LogWarning("HoMM3 Necropolis Cover of Darkness: world unreadable (" + fail + "); no fog change.");
			return 0;
		}

		var sources = new List<int>();
		foreach (var city in world.Cities.Values)
		{
			if (city == null || city.ownerSide < 0 || city.ownerSide == side.index)
				continue;
			if (!Homm3TownBuildingReader.CityHasBuilding(city, CoverBuildingSid) || !Homm3TownBuildingReader.CityMatchesSid(city, NecropolisCitySid))
				continue;
			if (TryNode(world, city.idMapObject, out var node) && node < w * h)
				sources.Add(node);
		}
		if (sources.Count == 0)
			return 0;

		_protected.Clear();
		foreach (var city in world.Cities.Values)
		{
			if (city != null && city.ownerSide == side.index && TryNode(world, city.idMapObject, out var node))
				MarkDisc(node, OwnCitySightRadius, w, h);
		}
		foreach (DataHero hero in Homm3FactoryLogisticsEffects.SideHeroes(world, side.index))
		{
			if (hero != null && hero.node >= 0 && hero.node < w * h)
				MarkDisc(hero.node, OwnHeroSightRadius, w, h);
		}

		var hidden = 0;
		var r2 = CoverRadius * CoverRadius;
		foreach (var center in sources)
		{
			int cx = center % w, cy = center / w;
			for (var y = Math.Max(0, cy - CoverRadius); y <= Math.Min(h - 1, cy + CoverRadius); y++)
			{
				var dy = y - cy;
				for (var x = Math.Max(0, cx - CoverRadius); x <= Math.Min(w - 1, cx + CoverRadius); x++)
				{
					var dx = x - cx;
					if (dx * dx + dy * dy > r2)
						continue;
					var i = x + y * w;
					if (_protected.Contains(i) || !visibility[i])
						continue;
					visibility[i] = false;
					hidden++;
				}
			}
		}
		if (_logged++ < 16)
			_log?.LogInfo("HoMM3 Necropolis Cover of Darkness: side " + side.index + " day " + world.Day + ": hid " + hidden + " node(s) around " + sources.Count + " covered town(s).");
		return hidden;
	}

	private static bool TryNode(Homm3FactoryLogisticsEffects.World world, int objectId, out int node)
	{
		node = -1;
		if (!world.Positions.TryGetValue(objectId, out var p) || p.node < 0)
			return false;
		node = p.node;
		return true;
	}

	private static void MarkDisc(int center, int radius, int w, int h)
	{
		int cx = center % w, cy = center / w;
		var r2 = radius * radius;
		for (var y = Math.Max(0, cy - radius); y <= Math.Min(h - 1, cy + radius); y++)
		{
			for (var x = Math.Max(0, cx - radius); x <= Math.Min(w - 1, cx + radius); x++)
			{
				int dx = x - cx, dy = y - cy;
				if (dx * dx + dy * dy <= r2)
					_protected.Add(x + y * w);
			}
		}
	}

	private static PropertyInfo FindPropertyOfType(Type type, Type propertyType)
	{
		for (var t = type; t != null && t != typeof(object); t = t.BaseType)
		{
			foreach (var property in t.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (property.GetIndexParameters().Length == 0 && property.PropertyType == propertyType && property.GetMethod != null)
					return property;
			}
		}
		return null;
	}
}
