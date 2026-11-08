using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only probe for the next Homecoming port blocker. It observes native placed-object
/// initialization and reports whether the loaded map exposes a real placed-object insertion surface.
/// It must not create, add, remove, or mutate native map objects.
/// </summary>
internal static class Homm3HomecomingMapEmissionFeasibilityProbe
{
	internal const string DiagnosticFlag = "homm3_homecoming_map_emission_feasibility_probe.flag";
	private const string LogPrefix = "HOMM3_HOMECOMING_MAP_EMISSION_FEASIBILITY_PROBE";
	private const int MaxSamples = 12;
	private const string NoInsertionSurfaceBlocker = "no_runtime_placed_object_insertion_surface";
	private const string CandidateMutatorBlocker = "candidate_mutator_requires_separate_safe_insertion_proof";
	private static bool _registered;
	private static int _samples;
	private static bool _summaryLogged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;

		try
		{
			var metaType = ResolveMapMetaType();
			var objectType = GameMember.FindPlacedObjectType(
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints,
				GetHexType);
			if (objectType == null)
				throw new InvalidOperationException("placed-object type was not resolved.");

			var patched = 0;
			foreach (var method in GameMember.FindPlacedObjectInitMethods(objectType, metaType))
			{
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3HomecomingMapEmissionFeasibilityProbe), nameof(PostfixPlacedObjectInit)));
				patched++;
			}
			if (patched == 0)
				throw new InvalidOperationException("placed-object init surface was not resolved.");

			_registered = true;
			log?.LogInfo(LogPrefix + " registered placed-object init probe patched=" + patched + " nativeMapMutation=false playable=false blocker=map_insertion_surface_unproven");
		}
		catch (Exception ex)
		{
			log?.LogWarning(LogPrefix + " failed closed during registration: " + ex);
		}
	}

	private static void PostfixPlacedObjectInit(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		try
		{
			var map = __args != null && __args.Length > 0 ? __args[0] : null;
			var meta = __args != null && __args.Length > 1 ? __args[1] : null;
			var nodeArg = TryReadArgInt(__args, 2);
			var rotationArg = TryReadArgFloat(__args, 4);
			var objectId = Homm3MapObjectPropCityResolver.TryGetIntMember(__instance, GameSymbols.CustomTownMapBillboard.PlacedObjectIdFields) ?? 0;
			var nodeId = nodeArg ?? Homm3MapObjectPropCityResolver.TryGetIntMember(__instance, GameSymbols.CustomTownMapBillboard.PlacedObjectNodeFields);
			var sid = ReadFirstString(__instance, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) ?? ReadMetaConfigSid(meta) ?? "";
			var rootName = TryReadRootName(__instance) ?? "";
			var objectsProperties = Homm3MapObjectPropCityResolver.ResolveObjectsProperties(map);
			var mutators = DiscoverPlacedObjectMutators(map, __instance?.GetType());

			if (_samples < MaxSamples)
			{
				_samples++;
				Plugin.LogSource?.LogInfo(LogPrefix
					+ " sample=" + _samples.ToString(CultureInfo.InvariantCulture)
					+ " method=" + (__originalMethod != null ? __originalMethod.Name : "<unknown>")
					+ " mapType=" + TypeName(map)
					+ " placedType=" + TypeName(__instance)
					+ " metaType=" + TypeName(meta)
					+ " objectId=" + objectId.ToString(CultureInfo.InvariantCulture)
					+ " nodeId=" + (nodeId.HasValue ? nodeId.Value.ToString(CultureInfo.InvariantCulture) : "<none>")
					+ " rotation=" + (rotationArg.HasValue ? rotationArg.Value.ToString(CultureInfo.InvariantCulture) : "<none>")
					+ " sid='" + Sanitize(sid) + "'"
					+ " root='" + Sanitize(rootName) + "'"
					+ " objectsPropertiesType=" + TypeName(objectsProperties)
					+ " mapPlacedObjectMutatorCount=" + mutators.Count.ToString(CultureInfo.InvariantCulture)
					+ " mapPlacedObjectMutators='" + Sanitize(string.Join(",", mutators)) + "'"
					+ " nativeMapMutation=false playable=false blocker=" + (mutators.Count == 0 ? NoInsertionSurfaceBlocker : CandidateMutatorBlocker));
			}

			if (!_summaryLogged && _samples >= MaxSamples)
			{
				_summaryLogged = true;
				Plugin.LogSource?.LogInfo(LogPrefix + " summary samples=" + _samples.ToString(CultureInfo.InvariantCulture)
					+ " nativeMapMutation=false playable=false blocker=layer_aware_map_emission_still_unproven");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + " sample failed closed: " + ex.Message);
		}
	}

	private static List<string> DiscoverPlacedObjectMutators(object map, Type placedType)
	{
		var result = new List<string>();
		if (map == null || placedType == null)
			return result;

		foreach (var method in map.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (method.IsSpecialName || method.ReturnType != typeof(void))
				continue;
			ParameterInfo[] parameters;
			try { parameters = method.GetParameters(); }
			catch { continue; }
			if (parameters.Length != 1)
				continue;
			var parameterType = parameters[0].ParameterType;
			if (parameterType == null)
				continue;
			if (!parameterType.IsAssignableFrom(placedType) && !StringContainsPlacedObjectType(parameterType.FullName ?? parameterType.Name))
				continue;
			result.Add(method.Name + "(" + (parameterType.FullName ?? parameterType.Name) + ")");
			if (result.Count >= 8)
				break;
		}
		return result;
	}

	private static bool StringContainsPlacedObjectType(string value)
	{
		if (string.IsNullOrEmpty(value))
			return false;
		foreach (var hint in GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints)
			if (!string.IsNullOrEmpty(hint) && value.IndexOf(hint, StringComparison.Ordinal) >= 0)
				return true;
		return false;
	}

	private static Type ResolveMapMetaType()
	{
		foreach (var hint in GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId + "." + hint, hint, () => GetHexType(hint));
			if (type != null)
				return type;
		}
		return null;
	}

	private static Type GetHexType(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return null;
		return AccessTools.TypeByName(name) ?? AccessTools.TypeByName("Hex." + name);
	}

	private static int? TryReadArgInt(object[] args, int index)
	{
		if (args == null || args.Length <= index || args[index] == null)
			return null;
		try { return Convert.ToInt32(args[index], CultureInfo.InvariantCulture); }
		catch { return null; }
	}

	private static float? TryReadArgFloat(object[] args, int index)
	{
		if (args == null || args.Length <= index || args[index] == null)
			return null;
		try { return Convert.ToSingle(args[index], CultureInfo.InvariantCulture); }
		catch { return null; }
	}

	private static string ReadFirstString(object instance, IEnumerable<string> names)
	{
		if (instance == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = ReadMember(instance, name) as string;
			if (!string.IsNullOrWhiteSpace(value))
				return value;
		}
		return null;
	}

	private static string ReadMetaConfigSid(object meta)
	{
		var config = ReadFirstMember(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		return ReadFirstString(config, GameSymbols.CustomTownMapBillboard.ConfigIdFields);
	}

	private static object ReadFirstMember(object instance, IEnumerable<string> names)
	{
		if (instance == null || names == null)
			return null;
		foreach (var name in names)
		{
			var value = ReadMember(instance, name);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object ReadMember(object instance, string name)
	{
		if (instance == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var type = instance.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(instance);
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(instance, null);
			}
			catch { }
		}
		return null;
	}

	private static string TryReadRootName(object placedInstance)
	{
		var root = ReadFirstMember(placedInstance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields);
		var nameProperty = root?.GetType().GetProperty("name", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		try { return nameProperty?.GetValue(root, null) as string; }
		catch { return null; }
	}

	private static string TypeName(object instance)
	{
		return instance == null ? "<null>" : instance.GetType().FullName ?? instance.GetType().Name;
	}

	private static string Sanitize(string value)
	{
		if (string.IsNullOrEmpty(value))
			return "";
		return value.Replace("'", "_").Replace("\r", " ").Replace("\n", " ");
	}
}