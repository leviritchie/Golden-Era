using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes;
using DataObjCity = Hex.Session.Data.ObjCity;

namespace OfflineUnlockMod;

/// <summary>
/// Building pass 2026-11-22 (docs/building_pass_20261122/inferno.md P2, REVIEW 2): Inferno Castle Gate.
///
/// The building is the native <c>myceliumRoots</c> row <c>Build_Mycelium_Roots</c> in <c>homm3_inferno_city</c>; the
/// native travel window (<c>Hex.Session.UI.BhMyceliumRoots</c>) offers every owned city without a visitor. HoMM3's
/// Castle Gate only reaches towns that also have a Castle Gate, so when the window is opened from an Inferno town
/// this blocks every destination whose town has no constructed teleport row of its own.
///
/// Hook: prefix on the real-named <c>BhViewElementMyceliumRoots.Show(&lt;world object&gt;, bool _active)</c>, the
/// per-destination list entry; <c>_active == false</c> makes the native call <c>SetupBlocked(true)</c>, so the pool
/// index stays aligned with the native city list and the native Apply button refuses the entry. The destination's
/// data city is the world object's <c>DataObject</c> property, found by type. The origin is the open town screen
/// (<see cref="ModActions.GetCurrentCityData"/>).
///
/// Limits: the filter is UI-only. AI teleports and a command issued without the window are not filtered (no proven
/// live symbol for the mycelium apply command). When the origin town cannot be read the native list is left as is.
/// Vanilla Nature towns are untouched: the filter keys on the origin being <c>homm3_inferno_city</c>.
/// </summary>
internal static class Homm3InfernoCastleGateRuntime
{
	internal const string InfernoCitySid = "homm3_inferno_city";
	internal const string CastleGateBuildingSid = "Build_Mycelium_Roots";

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _logged;
	private static Type _dataObjectType;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var viewType = typeof(Hex.Session.UI.BhViewElementMyceliumRoots);
			MethodInfo show = null;
			foreach (var method in viewType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, "Show", StringComparison.Ordinal))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length == 2 && parameters[1].ParameterType == typeof(bool) && !parameters[0].ParameterType.IsValueType)
				{
					show = method;
					break;
				}
			}
			if (show == null)
			{
				log?.LogWarning("HoMM3 Inferno Castle Gate: BhViewElementMyceliumRoots.Show(object, bool) not found; destinations stay native (any owned city).");
				return;
			}
			_dataObjectType = typeof(Hex.Session.Data.DataObject);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3InfernoCastleGateRuntime), show, nameof(ShowPrefix), null);
			_registered = true;
			log?.LogInfo("HoMM3 Inferno Castle Gate: destination filter registered on " + viewType.FullName + ".Show.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Inferno Castle Gate: registration failed, destinations stay native: " + ex.GetBaseException().Message);
		}
	}

	private static void ShowPrefix(object __0, ref bool __1)
	{
		try
		{
			if (!__1 || __0 == null)
				return;
			var origin = ModActions.GetCurrentCityData();
			if (origin == null || !HasTeleportRow(origin) || !Homm3TownBuildingReader.CityMatchesSid(origin, InfernoCitySid))
				return;
			var target = ResolveTargetCity(__0);
			if (target == null)
				return; // unreadable destination: leave the native decision
			if (target.idMapObject == origin.idMapObject)
				return;
			if (HasTeleportRow(target))
				return;
			__1 = false;
			if (_logged++ < 8)
				_log?.LogInfo("HoMM3 Inferno Castle Gate: blocked destination city id=" + target.idMapObject + " (no Castle Gate) from city id=" + origin.idMapObject + ".");
		}
		catch (Exception ex)
		{
			if (_logged++ < 8)
				_log?.LogWarning("HoMM3 Inferno Castle Gate: filter failed open: " + ex.GetBaseException().Message);
		}
	}

	/// <summary>True when the town has a constructed native teleport row (myceliumRoots section): an Inferno Castle Gate or a vanilla Mycelium Roots.</summary>
	internal static bool HasTeleportRow(DataObjCity city)
	{
		var list = city?.buildings?.myceliumRoots;
		if (list == null)
			return false;
		for (var i = 0; i < list.Count; i++)
		{
			var row = list[i];
			if (row != null && row.isConstructed && row.level > 0)
				return true;
		}
		return false;
	}

	/// <summary>The destination entry's data city: the world object's DataObject-typed property, cast to ObjCity.</summary>
	private static DataObjCity ResolveTargetCity(object worldObject)
	{
		if (worldObject is DataObjCity direct)
			return direct;
		foreach (var property in worldObject.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public))
		{
			if (property.GetIndexParameters().Length != 0 || !_dataObjectType.IsAssignableFrom(property.PropertyType))
				continue;
			object value;
			try
			{
				value = property.GetValue(worldObject);
			}
			catch
			{
				continue;
			}
			if (value is DataObjCity city)
				return city;
			if (value is Il2CppObjectBase baseObj && baseObj.Pointer != IntPtr.Zero)
			{
				try
				{
					var cast = baseObj.TryCast<DataObjCity>();
					if (cast != null)
						return cast;
				}
				catch
				{
					// not a city
				}
			}
		}
		return null;
	}
}
