using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Map;
using Hex.Session.Data;

namespace OfflineUnlockMod;

internal static class Homm3RandomHireResolverHook
{
	private const string RandomHirePrefix = "random_hire_";
	private const string BarracksPrefix = "barracks_";

	private static readonly HashSet<string> LoggedRewrites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMapObjectRewrites = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedMapObjectRefusals = new(StringComparer.Ordinal);
	private static bool _registered;
	private static ManualLogSource _log;

	internal static bool IsRegistered => _registered;

	internal static void TryRegisterReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeSlice(harmony, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		RegisterReleaseSafeSlice(harmony, log, required: true);
	}

	private static void RegisterReleaseSafeSlice(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_registered)
			return;
		if (harmony == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized.");
			return;
		}

		_log = log;
		var resolverType = GameMember.FindType(
			GameSymbols.CustomDwellingRandomHire.RandomHireResolverTypeId,
			GameSymbols.CustomDwellingRandomHire.RandomHireResolverTypeHint);
		if (resolverType == null)
		{
			if (required)
				throw new InvalidOperationException("HoMM3 random-hire resolver type was not found.");
			log?.LogWarning("HoMM3 random-hire resolver hook skipped: resolver type missing.");
			return;
		}

		var resolverMethods = FindFactionTierResolverMethods(resolverType, log);
		var mapObjectMethods = FindHireMapObjectSpawnerMethods(resolverType, log);
		if (resolverMethods.Length == 0 && mapObjectMethods.Length == 0)
		{
			if (required)
				throw new InvalidOperationException("HoMM3 random-hire resolver methods were not found on " + resolverType.FullName + ".");
			log?.LogWarning("HoMM3 random-hire resolver hook skipped: no resolver methods matched.");
			return;
		}

		var resolverPrefix = new HarmonyMethod(typeof(Homm3RandomHireResolverHook), nameof(PrefixFactionTierResolver));
		foreach (var method in resolverMethods)
			harmony.Patch(method, prefix: resolverPrefix);

		var mapObjectPrefix = new HarmonyMethod(typeof(Homm3RandomHireResolverHook), nameof(PrefixHireMapObjectSpawner));
		foreach (var method in mapObjectMethods)
			harmony.Patch(method, prefix: mapObjectPrefix);

		_registered = true;
		log?.LogInfo(
			"HoMM3 random-hire resolver hook registered "
			+ resolverMethods.Length
			+ " faction-tier resolver patch(es) and "
			+ mapObjectMethods.Length
			+ " hire map-object spawner patch(es).");
	}

	private static MethodInfo[] FindFactionTierResolverMethods(Type resolverType, ManualLogSource log)
	{
		var exactTypes = new[] { typeof(FractionConfig), typeof(string), typeof(int), typeof(Side) };
		var methods = GameMember.FindMethodsByNames(
			resolverType,
			exactTypes,
			GameSymbols.CustomDwellingRandomHire.RandomHireFactionTierResolvers);
		if (methods.Length > 0)
			return methods;

		var matches = new List<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		foreach (var method in resolverType.GetMethods(flags))
		{
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != exactTypes.Length)
				continue;
			if (!TypeNameMatches(parameters[0].ParameterType, "FractionConfig")
				|| parameters[1].ParameterType != typeof(string)
				|| parameters[2].ParameterType != typeof(int)
				|| !TypeNameMatches(parameters[3].ParameterType, "Side"))
			{
				continue;
			}
			matches.Add(method);
		}

		matches.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
		if (matches.Count > 0)
		{
			log?.LogWarning(
				"HoMM3 random-hire resolver hook: centralized name hints missed; exact semantic shape resolved "
				+ matches.Count
				+ " method(s): "
				+ string.Join(",", matches.ConvertAll(m => m.Name)));
		}
		return matches.ToArray();
	}

	private static MethodInfo[] FindHireMapObjectSpawnerMethods(Type resolverType, ManualLogSource log)
	{
		var exactTypes = new[] { typeof(Side), typeof(MapObjectInfo) };
		var methods = GameMember.FindMethodsByNames(
			resolverType,
			exactTypes,
			GameSymbols.CustomDwellingRandomHire.HireMapObjectSpawners);
		if (methods.Length > 0)
			return methods;

		var matches = new List<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly;
		foreach (var method in resolverType.GetMethods(flags))
		{
			if (method.ReturnType != typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != exactTypes.Length)
				continue;
			if (!TypeNameMatches(parameters[0].ParameterType, "Side")
				|| !TypeNameMatches(parameters[1].ParameterType, "MapObjectInfo"))
			{
				continue;
			}
			matches.Add(method);
		}

		matches.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
		if (matches.Count > 0)
		{
			log?.LogWarning(
				"HoMM3 random-hire resolver hook: centralized map-object spawner hints missed; exact semantic shape resolved "
				+ matches.Count
				+ " method(s): "
				+ string.Join(",", matches.ConvertAll(m => m.Name)));
		}
		return matches.ToArray();
	}

	private static bool TypeNameMatches(Type type, string expectedName)
	{
		return type != null && string.Equals(type.Name, expectedName, StringComparison.Ordinal);
	}

	private static void PrefixFactionTierResolver(MethodBase __originalMethod, FractionConfig __0, ref string __1, int __2, Side __3)
	{
		if (!TryParseRandomHireTier(__1, out var tier))
			return;

		var factionSid = ResolveFactionSid(__0, __3);
		if (string.IsNullOrWhiteSpace(factionSid))
			return;
		if (!Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
			return;

		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid, tier, out var dwellingSid))
			throw new InvalidOperationException(
				"HoMM3 random-hire resolver found exact custom faction '"
				+ factionSid
				+ "' for "
				+ __1
				+ " but no manifest-owned direct dwelling tier "
				+ tier
				+ ".");

		var originalSid = __1;
		__1 = dwellingSid;
		var logKey = factionSid + "|" + tier + "|" + (__originalMethod?.Name ?? "?");
		if (LoggedRewrites.Add(logKey))
		{
			_log?.LogInfo(
				"HoMM3 random-hire resolver: "
				+ (__originalMethod?.DeclaringType?.Name ?? "?")
				+ "."
				+ (__originalMethod?.Name ?? "?")
				+ " rewrote "
				+ originalSid
				+ " -> "
				+ dwellingSid
				+ " for faction="
				+ factionSid
				+ " tier="
				+ tier
				+ " argTier="
				+ __2
				+ ".");
		}
	}

	private static void PrefixHireMapObjectSpawner(MethodBase __originalMethod, Side __0, ref MapObjectInfo __1)
	{
		if (!DeobfInteropCompat.TryGetMapObjectInfoSid(__1, out var originalSid))
			return;
		if (!TryParseBarracksTier(originalSid, out var tier))
			return;
		if (IsDirectCustomDwellingSid(originalSid))
			return;

		var factionSid = ResolveFactionSid(null, __0);
		if (string.IsNullOrWhiteSpace(factionSid) || !Homm3CustomFactionRegistry.IsCustomFactionSid(factionSid))
		{
			var refusalKey = originalSid + "|" + (__originalMethod?.Name ?? "?");
			if (LoggedMapObjectRefusals.Add(refusalKey))
			{
				_log?.LogInfo(
					"HoMM3 random-hire resolver: leaving donor map object sid='"
					+ originalSid
					+ "' unchanged in "
					+ (__originalMethod?.DeclaringType?.Name ?? "?")
					+ "."
					+ (__originalMethod?.Name ?? "?")
					+ " because the Side did not resolve to an exact custom faction.");
			}
			return;
		}

		if (!Homm3CustomFactionRegistry.TryGetDirectDwellingSidForFactionTier(factionSid, tier, out var dwellingSid))
			throw new InvalidOperationException(
				"HoMM3 random-hire resolver found exact custom faction '"
				+ factionSid
				+ "' for donor map object '"
				+ originalSid
				+ "' but no manifest-owned direct dwelling tier "
				+ tier
				+ ".");

		DeobfInteropCompat.SetMapObjectInfoSid(ref __1, dwellingSid);
		var logKey = factionSid + "|" + tier + "|" + originalSid + "|" + (__originalMethod?.Name ?? "?");
		if (LoggedMapObjectRewrites.Add(logKey))
		{
			_log?.LogInfo(
				"HoMM3 random-hire resolver: "
				+ (__originalMethod?.DeclaringType?.Name ?? "?")
				+ "."
				+ (__originalMethod?.Name ?? "?")
				+ " rewrote map object "
				+ originalSid
				+ " -> "
				+ dwellingSid
				+ " for faction="
				+ factionSid
				+ " tier="
				+ tier
				+ " id="
				+ DeobfInteropCompat.GetMapObjectInfoId(__1)
				+ ".");
		}
	}

	private static bool TryParseRandomHireTier(string sid, out int tier)
	{
		tier = 0;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		if (!key.StartsWith(RandomHirePrefix, StringComparison.Ordinal))
			return false;
		return int.TryParse(key.Substring(RandomHirePrefix.Length), out tier) && tier >= 1 && tier <= 7;
	}

	private static bool TryParseBarracksTier(string sid, out int tier)
	{
		tier = 0;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var key = sid.Trim();
		if (!key.StartsWith(BarracksPrefix, StringComparison.Ordinal))
			return false;
		var index = key.LastIndexOf('_');
		return index > BarracksPrefix.Length
			&& index + 1 < key.Length
			&& int.TryParse(key.Substring(index + 1), out tier)
			&& tier >= 1
			&& tier <= 7;
	}

	private static bool IsDirectCustomDwellingSid(string sid)
	{
		return !string.IsNullOrWhiteSpace(sid)
			&& sid.Trim().StartsWith("barracks_homm3_", StringComparison.Ordinal);
	}

	private static string ResolveFactionSid(FractionConfig fractionConfig, Side side)
	{
		var sid = ReadFractionConfigId(fractionConfig);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();

		sid = GetFirstMemberValue(side, GameSymbols.CustomDwellingRandomHire.SideFactionFields) as string;
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();

		var sideFractionConfig = GetFirstMemberValue(side, GameSymbols.CustomDwellingRandomHire.SideFractionConfigFields);
		sid = ReadFractionConfigId(sideFractionConfig);
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string ReadFractionConfigId(object fractionConfig)
	{
		// The id lives on ConfigElementBase<string> (field_Public_IDType_0 on current builds), which the name list cannot reach.
		if (fractionConfig != null && DeobfInteropCompat.TryGetConfigElementId(fractionConfig, out var id) && !string.IsNullOrWhiteSpace(id))
			return id;
		return GetFirstMemberValue(fractionConfig, GameSymbols.CustomDwellingRandomHire.FractionConfigIdFields) as string;
	}

	private static object GetFirstMemberValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetMemberValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object GetMemberValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (p != null)
				return p.GetValue(obj);
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			if (f != null)
				return f.GetValue(obj);
		}
		return null;
	}
}
