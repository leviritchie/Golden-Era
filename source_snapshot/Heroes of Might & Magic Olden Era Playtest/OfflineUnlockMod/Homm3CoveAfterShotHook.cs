using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

internal static class Homm3CoveAfterShotHook
{
	private const string BasicWeaknessSid = "magic_unnatural_calm_effect_0";
	private const string AdvancedWeaknessSid = "magic_unnatural_calm_effect_1";
	private const string BasicDisruptingRaySid = "homm3_cove_disrupting_ray_effect_0";
	private const string AdvancedDisruptingRaySid = "homm3_cove_disrupting_ray_effect_1";

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo[] _buffListMethods = Array.Empty<MethodInfo>();
	private static int _loggedRewrites;
	private static int _loggedUnresolvedCasters;
	private static int _loggedUnreadableBuffLists;

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Cove after-shot registration.");

		_log = log;
		var buffManagerType = GameMember.FindType(
			GameSymbols.CoveAfterShot.BuffManagerTypeId,
			GameSymbols.CoveAfterShot.BuffManagerTypeHint);
		if (buffManagerType == null)
			throw new MissingMemberException("Could not resolve Cove after-shot buff manager type.");
		_buffListMethods = ResolveRequiredBuffListMethods(buffManagerType);

		var prefixMethod = AccessTools.Method(typeof(Homm3CoveAfterShotHook), nameof(PrefixBuffAdd));
		var prefix = new HarmonyMethod(prefixMethod);
		var buffAddMethods = ResolveRequiredBuffAddMethods(buffManagerType);
		var patched = 0;
		foreach (var method in buffAddMethods)
		{
			if (!GameMember.IsHarmonyPatchCompatible(method, prefixMethod, out var reason))
				throw new MissingMethodException(buffManagerType.FullName, method.Name + " incompatible prefix: " + reason);
			harmony.Patch(method, prefix: prefix);
			patched++;
		}
		if (patched == 0)
			throw new MissingMethodException(buffManagerType.FullName, "no Cove after-shot buff-add methods matched current release symbols");

		_registered = true;
		_log?.LogInfo("HoMM3 Cove after-shot: registered Disrupting Ray rewrite on " + patched + " dzv buff-add method(s).");
	}

	private static void PrefixBuffAdd(object __instance, [HarmonyArgument(0)] ref string sid, [HarmonyArgument(3)] object caster)
	{
		try
		{
			if (__instance == null || !TryGetDisruptingRaySid(sid, out var disruptingRaySid))
				return;
			if (!HasExistingWeakness(__instance))
				return;
			if (!IsCoveAfterShotCaster(caster))
			{
				if (_loggedUnresolvedCasters++ < 8)
					_log?.LogInfo("HoMM3 Cove after-shot: skipped repeated Weakness rewrite for non-Cove or unresolved caster sid=" + (ExtractSid(caster) ?? "?") + ".");
				return;
			}

			sid = disruptingRaySid;
			if (_loggedRewrites++ < 8)
				_log?.LogInfo("HoMM3 Cove after-shot: repeated Weakness from " + (ExtractSid(caster) ?? "?") + " became cumulative Disrupting Ray.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Cove after-shot: refusing Disrupting Ray rewrite after buff-manager error: " + ex.Message);
		}
	}

	private static MethodInfo[] ResolveRequiredBuffListMethods(Type buffManagerType)
	{
		var methods = new List<MethodInfo>();
		var missing = 0;
		for (var i = 0; i < GameSymbols.CoveAfterShot.BuffListMethods.Length; i++)
		{
			var symbol = GameSymbols.CoveAfterShot.BuffListMethods[i];
			var method = GameMember.FindFirstMethodByNames(
				buffManagerType,
				new[] { typeof(string) },
				symbol);
			if (method == null || method.ReturnType == typeof(void))
			{
				missing++;
				continue;
			}
			methods.Add(method);
		}

		if (methods.Count == 0)
		{
			var listHints = FlattenNameHints(GameSymbols.CoveAfterShot.BuffListMethods);
			var boolProbe = GameMember.FindFirstMethod(
				buffManagerType,
				typeof(bool),
				new[] { typeof(string) },
				GameSymbols.CoveAfterShot.BuffListHasBool);
			if (boolProbe != null)
				methods.Add(boolProbe);

			var listProbe = GameMember.FindFirstMethod(
				buffManagerType,
				null,
				new[] { typeof(string) },
				GameSymbols.CoveAfterShot.BuffListBySid);
			if (listProbe != null
			    && listProbe.ReturnType != typeof(void)
			    && listProbe.ReturnType != typeof(string)
			    && listProbe.ReturnType != typeof(bool)
			    && !methods.Contains(listProbe))
				methods.Add(listProbe);

			if (methods.Count == 0 && listHints.Length > 0)
			{
				var shapeMatches = GameMember.FindMethods(
					buffManagerType,
					null,
					new[] { typeof(string) },
					GameSymbols.CoveAfterShot.BuffListBySid.Id,
					listHints);
				foreach (var candidate in shapeMatches)
				{
					if (candidate.ReturnType == typeof(void) || candidate.ReturnType == typeof(string))
						continue;
					if (candidate.ReturnType == typeof(bool))
					{
						if (!methods.Contains(candidate))
							methods.Add(candidate);
						continue;
					}
					if (!methods.Contains(candidate))
					{
						methods.Add(candidate);
						break;
					}
				}
			}
		}

		if (methods.Count == 0)
			throw new MissingMethodException(buffManagerType.FullName, "no Cove after-shot buff-list methods matched current release symbols");
		_log?.LogInfo("HoMM3 Cove after-shot: resolved " + methods.Count + " dzv buff-list methods; skipped " + missing + " absent name candidates.");
		return methods.ToArray();
	}

	private static MethodInfo[] ResolveRequiredBuffAddMethods(Type buffManagerType)
	{
		var methods = new List<MethodInfo>();
		var missing = 0;
		foreach (var symbol in GameSymbols.CoveAfterShot.BuffAddMethods)
		{
			var method = GameMember.FindFirstMethodByNames(
				buffManagerType,
				new[] { typeof(string), typeof(int), typeof(int), null, typeof(int), typeof(bool) },
				symbol);
			if (method == null || method.ReturnType == typeof(void))
			{
				missing++;
				continue;
			}
			methods.Add(method);
		}

		if (methods.Count == 0)
		{
			var shapeMatch = GameMember.FindFirstMethod(
				buffManagerType,
				null,
				new[] { typeof(string), typeof(int), typeof(int), null, typeof(int), typeof(bool) },
				GameSymbols.CoveAfterShot.BuffAddShape);
			if (shapeMatch != null && shapeMatch.ReturnType != typeof(void))
				methods.Add(shapeMatch);
		}

		if (methods.Count == 0)
			return Array.Empty<MethodInfo>();

		_log?.LogInfo("HoMM3 Cove after-shot: resolved " + methods.Count + " dzv buff-add methods; skipped " + missing + " absent name candidates.");
		return methods.ToArray();
	}

	private static string[] FlattenNameHints(params GameSymbols.MethodSymbol[] symbols)
	{
		if (symbols == null || symbols.Length == 0)
			return Array.Empty<string>();
		var hints = new List<string>();
		foreach (var symbol in symbols)
		{
			var nameHints = symbol.NameHints;
			if (nameHints == null)
				continue;
			foreach (var hint in nameHints)
			{
				if (!string.IsNullOrWhiteSpace(hint))
					hints.Add(hint);
			}
		}
		return hints.ToArray();
	}

	private static bool HasExistingWeakness(object buffManager)
	{
		return HasBuff(buffManager, BasicWeaknessSid) || HasBuff(buffManager, AdvancedWeaknessSid);
	}

	private static bool HasBuff(object buffManager, string sid)
	{
		foreach (var method in _buffListMethods)
		{
			var result = method.Invoke(buffManager, new object[] { sid });
			if (result == null)
				continue;
			if (result is bool hasBuff)
				return hasBuff;
			if (ListHasAny(result))
				return true;
		}
		return false;
	}

	private static bool ListHasAny(object list)
	{
		if (list is System.Collections.IEnumerable clrEnumerable)
		{
			var enumerator = clrEnumerable.GetEnumerator();
			try { return enumerator != null && enumerator.MoveNext(); }
			finally
			{
				if (enumerator is IDisposable disposable)
					disposable.Dispose();
			}
		}

		if (list is Il2CppSystem.Collections.IEnumerable il2CppEnumerable)
		{
			var enumerator = il2CppEnumerable.GetEnumerator();
			try { return enumerator != null && enumerator.MoveNext(); }
			finally
			{
				if (enumerator is IDisposable disposable)
					disposable.Dispose();
			}
		}

		var count = ReadInt(list, "Count", "count", "_size", "size");
		if (count >= 0)
			return count > 0;
		count = InvokeIntNoArg(list, "get_Count", "get_count", "Count");
		if (count >= 0)
			return count > 0;

		if (_loggedUnreadableBuffLists++ < 4)
			_log?.LogWarning("HoMM3 Cove after-shot: buff-list result type is not enumerable/count-readable: " + list.GetType().FullName);
		return false;
	}

	private static bool TryGetDisruptingRaySid(string weaknessSid, out string disruptingRaySid)
	{
		if (string.Equals(weaknessSid, BasicWeaknessSid, StringComparison.Ordinal))
		{
			disruptingRaySid = BasicDisruptingRaySid;
			return true;
		}
		if (string.Equals(weaknessSid, AdvancedWeaknessSid, StringComparison.Ordinal))
		{
			disruptingRaySid = AdvancedDisruptingRaySid;
			return true;
		}

		disruptingRaySid = null;
		return false;
	}

	private static bool IsCoveAfterShotCaster(object caster)
	{
		var sid = ExtractSid(caster);
		return string.Equals(sid, "h3_sea_witch", StringComparison.Ordinal)
		       || string.Equals(sid, "h3_sorceress", StringComparison.Ordinal)
		       || string.Equals(sid, "h3_sea_witch_upg_alt", StringComparison.Ordinal);
	}

	private static string ExtractSid(object owner)
	{
		return ExtractSid(owner, new HashSet<object>(), 0);
	}

	private static string ExtractSid(object owner, HashSet<object> seen, int depth)
	{
		// The law-owner registry holds the custom sid by native unit pointer; raw configSid is the donor sid.
		if (Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(owner, out var registeredSid)
		    && !string.IsNullOrWhiteSpace(registeredSid))
			return registeredSid.Trim();
		var sid = ReadString(owner, GameSymbols.BattleCommand.UnitSidFields);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();

		foreach (var nestedName in GameSymbols.BattleCommand.UnitNestedConfigFields)
		{
			var nested = ReadMember(owner, nestedName);
			sid = ReadString(nested, GameSymbols.BattleCommand.UnitConfigSidMembers);
			if (!string.IsNullOrWhiteSpace(sid))
				return sid.Trim();
		}

		if (owner == null || depth >= 4 || !seen.Add(owner))
			return null;

		sid = ExtractSid(InvokeNoArg(owner, GameSymbols.CoveAfterShot.CasterBattleObject), seen, depth + 1);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();
		sid = ExtractSid(InvokeNoArg(owner, GameSymbols.CoveAfterShot.CasterRoot), seen, depth + 1);
		if (!string.IsNullOrWhiteSpace(sid))
			return sid.Trim();
		return null;
	}

	private static object InvokeNoArg(object owner, GameSymbols.MethodSymbol symbol)
	{
		if (owner == null)
			return null;
		foreach (var name in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var method = AccessTools.Method(owner.GetType(), name, Type.EmptyTypes);
				if (method != null)
					return method.Invoke(owner, null);
			}
			catch { }
		}
		return null;
	}

	private static string ReadString(object owner, params string[] names)
	{
		return ReadMember(owner, names) as string;
	}

	private static int ReadInt(object owner, params string[] names)
	{
		var value = ReadMember(owner, names);
		return value is int intValue ? intValue : -1;
	}

	private static int InvokeIntNoArg(object owner, params string[] names)
	{
		var value = InvokeNoArg(owner, names);
		return value is int intValue ? intValue : -1;
	}

	private static object InvokeNoArg(object owner, params string[] names)
	{
		if (owner == null || names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var method = AccessTools.Method(owner.GetType(), name, Type.EmptyTypes);
				if (method != null)
					return method.Invoke(owner, null);
			}
			catch { }
		}
		return null;
	}

	private static object ReadMember(object owner, params string[] names)
	{
		if (owner == null || names == null)
			return null;
		var type = owner.GetType();
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var field = FindField(type, name);
				if (field != null)
					return field.GetValue(owner);
			}
			catch { }
			try
			{
				var property = FindProperty(type, name);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(owner);
			}
			catch { }
		}
		return null;
	}

	private static FieldInfo FindField(Type type, string name)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = type; current != null; current = current.BaseType)
		{
			var field = current.GetField(name, flags);
			if (field != null)
				return field;
		}
		return null;
	}

	private static PropertyInfo FindProperty(Type type, string name)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = type; current != null; current = current.BaseType)
		{
			var property = current.GetProperty(name, flags);
			if (property != null)
				return property;
		}
		return null;
	}
}
