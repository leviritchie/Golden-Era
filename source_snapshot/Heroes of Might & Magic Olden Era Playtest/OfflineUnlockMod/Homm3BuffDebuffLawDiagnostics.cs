using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise buff/debuff law work.
/// This observes exact native buff manager add/query/list surfaces so later
/// Fortress, Dungeon, Cove, Rampart Avenger, and counterattack laws can use
/// real battle buffs instead of generic donor stat rows.
/// </summary>
internal static class Homm3BuffDebuffLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_buff_debuff_law_diag.flag";

	private const int LogCap = 140;
	private const int MaxMemberSnapshots = 12;
	private static bool _registered;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
			return;
		_registered = true;

		var patched = 0;
		try
		{
			var type = GameMember.FindType(
				GameSymbols.BuffDebuffLaws.BuffManagerTypeId,
				GameSymbols.BuffDebuffLaws.BuffManagerTypeHint);
			if (type == null)
			{
				log?.LogWarning("HoMM3 buff/debuff law diagnostics: exact dzv buff manager type not found.");
				return;
			}

			patched += PatchExactMethods(harmony, log, type, GameSymbols.BuffDebuffLaws.BuffAdd, 6, "buff-add");
			patched += PatchExactMethods(harmony, log, type, GameSymbols.BuffDebuffLaws.BuffHasBySid, 1, "buff-has-by-sid");
			patched += PatchExactMethods(harmony, log, type, GameSymbols.BuffDebuffLaws.BuffListBySid, 1, "buff-list-by-sid");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 buff/debuff law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			log?.LogWarning("HoMM3 buff/debuff law diagnostics found no exact buff manager surfaces; buff/debuff law gameplay remains disabled.");
			return;
		}

		log?.LogInfo("HoMM3 buff/debuff law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 buff/debuff law diagnostics: traces are observational only; do not implement poison/slow/disable/debuff laws until runtime proof confirms target identity, duration, stacking, and active law-rank access.");
		log?.LogInfo("HoMM3 buff/debuff law diagnostics: exact dzv.ceqy receiver context is logged when present; no reverse owner scans are used.");
		log?.LogInfo("HoMM3 buff/debuff law diagnostics: Rampart Avenger mark SIDs are recognized explicitly, and active-law state is attempted only through the shared exact resolver.");
	}

	private static int PatchExactMethods(Harmony harmony, ManualLogSource log, Type type, GameSymbols.MethodSymbol symbol, int parameterCount, string stage)
	{
		var patched = 0;
		var seen = new HashSet<MethodInfo>();
		foreach (var name in symbol.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var method = ResolveExactMethod(type, name, parameterCount);
			if (method == null)
			{
				log?.LogWarning("HoMM3 buff/debuff law diagnostics: exact " + type.FullName + "." + name + "(" + parameterCount + " args) not found for " + stage + ".");
				continue;
			}
			if (!seen.Add(method))
				continue;

			var postfix = AccessTools.Method(typeof(Homm3BuffDebuffLawDiagnostics), nameof(PostfixBuffTrace));
			if (postfix == null)
			{
				log?.LogWarning("HoMM3 buff/debuff law diagnostics: postfix not found for " + stage + ".");
				continue;
			}
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("HoMM3 buff/debuff law diagnostics: refusing incompatible postfix for " + FormatMethod(method) + ": " + reason);
				continue;
			}

			harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		return patched;
	}

	private static MethodInfo ResolveExactMethod(Type type, string name, int parameterCount)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName || method.ReturnType == typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static void PostfixBuffTrace(object __instance, MethodBase __originalMethod, object[] __args, object __result)
	{
		LogTrace(__instance, __originalMethod, __args, __result);
	}

	private static void LogTrace(object instance, MethodBase method, object[] args, object result)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("buff-debuff-law", method, "buff-debuff-trace");

			Plugin.LogSource?.LogInfo(
				"HoMM3 buff/debuff law diagnostic: method="
				+ FormatMethod(method)
				+ " manager="
				+ DescribeObjectContext(instance)
				+ " args="
				+ DescribeArgs(args)
				+ " result="
				+ DescribeObjectContext(result)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 buff/debuff law diagnostic log failed: " + ex.Message);
		}
	}

	private static string DescribeArgs(object[] args)
	{
		if (args == null || args.Length == 0)
			return "[]";
		var parts = new string[args.Length];
		for (var i = 0; i < args.Length; i++)
			parts[i] = DescribeObjectContext(args[i]);
		return "[" + string.Join(",", parts) + "]";
	}

	private static string DescribeObjectContext(object value)
	{
		if (value == null)
			return "null";
		if (IsSimpleType(value.GetType()))
			return DescribeSimpleValue(value);

		var type = value.GetType();
		var parts = new List<string>(MaxMemberSnapshots + 2)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		AddActiveLawStateSnapshot(value, parts);
		AddBuffManagerReceiverSnapshot(value, type, parts);

		if (value is IEnumerable enumerable && !(value is string))
		{
			parts.Add("count=" + CountEnumerable(enumerable));
			return "{" + string.Join("|", parts) + "}";
		}

		AddNamedSnapshots(value, type, parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static void AddNamedSnapshots(object value, Type type, List<string> parts)
	{
		for (var i = 0; i < GameSymbols.BuffDebuffLaws.BuffPayloadMembers.Length && parts.Count < MaxMemberSnapshots; i++)
		{
			var member = GameSymbols.BuffDebuffLaws.BuffPayloadMembers[i];
			if (TryGetMemberValue(value, type, member, out var memberValue))
			{
				if (memberValue is string sid && GameSymbols.RampartAvengerLaws.TryDescribeMarkBuffSid(sid, out var avengerDescription))
					parts.Add(member + "=" + DescribeSimpleValue(sid) + "(" + avengerDescription + ")");
				else
					parts.Add(member + "=" + DescribeObjectContext(memberValue));
			}
		}
	}

	private static void AddActiveLawStateSnapshot(object value, List<string> parts)
	{
		if (value == null || parts == null)
			return;

		var lawParts = new List<string>(8);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(value, lawIndex, out var state))
				continue;
			lawParts.Add("index=" + state.Index
			             + ",rank=" + state.Rank
			             + ",faction=" + state.FactionSid
			             + ",family=" + state.Family);
			if (lawParts.Count >= 8)
				break;
		}

		parts.Add("activeKnownCustomLawsFromThisObject=" + (lawParts.Count == 0 ? "none-or-unresolved" : "[" + string.Join(";", lawParts) + "]"));
	}

	private static void AddBuffManagerReceiverSnapshot(object value, Type type, List<string> parts)
	{
		if (value == null || type == null || parts == null)
			return;
		foreach (var member in GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers)
		{
			if (!TryGetMemberValue(value, type, member, out var receiver) || receiver == null)
				continue;
			parts.Add("buffReceiver." + member + "=" + DescribeBuffReceiver(receiver));
			return;
		}
	}

	private static string DescribeBuffReceiver(object receiver)
	{
		if (receiver == null)
			return "null";

		var type = receiver.GetType();
		var parts = new List<string>(8)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		AddActiveLawStateSnapshot(receiver, parts);
		AddFirstExactMember(receiver, type, GameSymbols.BuffDebuffLaws.BuffReceiverIdMembers, "receiverId", parts);
		AddFirstExactObject(receiver, type, GameSymbols.BuffDebuffLaws.BuffReceiverSideMembers, "side", parts);
		AddFirstExactHex(receiver, type, GameSymbols.BuffDebuffLaws.BuffReceiverHexMembers, "hex", parts);
		AddFirstExactObject(receiver, type, GameSymbols.BuffDebuffLaws.BuffReceiverObjectMembers, "fieldObject", parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static void AddFirstExactMember(object value, Type type, string[] names, string label, List<string> parts)
	{
		foreach (var name in names)
		{
			if (!TryGetMemberValue(value, type, name, out var memberValue) || memberValue == null)
				continue;
			parts.Add(label + "." + name + "=" + DescribeObjectContext(memberValue));
			return;
		}
	}

	private static void AddFirstExactObject(object value, Type type, string[] names, string label, List<string> parts)
	{
		foreach (var name in names)
		{
			if (!TryGetMemberValue(value, type, name, out var memberValue) || memberValue == null)
				continue;
			parts.Add(label + "." + name + "=" + DescribeObjectHeader(memberValue));
			return;
		}
	}

	private static void AddFirstExactHex(object value, Type type, string[] names, string label, List<string> parts)
	{
		foreach (var name in names)
		{
			if (!TryGetMemberValue(value, type, name, out var hex) || hex == null)
				continue;
			parts.Add(label + "." + name + "=" + DescribeHex(hex));
			return;
		}
	}

	private static string DescribeObjectHeader(object value)
	{
		if (value == null)
			return "null";
		if (IsSimpleType(value.GetType()))
			return DescribeSimpleValue(value);
		var type = value.GetType();
		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (string.IsNullOrEmpty(obfuscated))
			return "{" + (type.FullName ?? type.Name) + "}";
		return "{" + (type.FullName ?? type.Name) + "|obf=" + obfuscated + "}";
	}

	private static string DescribeHex(object hex)
	{
		if (hex == null)
			return "null";
		var type = hex.GetType();
		var parts = new List<string>(5)
		{
			"type=" + (type.FullName ?? type.Name)
		};
		AddFirstExactMember(hex, type, GameSymbols.BattleEventLaws.HexIndexMembers, "index", parts);
		AddFirstExactMember(hex, type, GameSymbols.BattleEventLaws.HexXMembers, "x", parts);
		AddFirstExactMember(hex, type, GameSymbols.BattleEventLaws.HexZMembers, "z", parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static bool TryGetMemberValue(object instance, Type type, string name, out object value)
	{
		value = null;
		if (instance == null || type == null || string.IsNullOrWhiteSpace(name))
			return false;

		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			try
			{
				var prop = current.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
				{
					value = prop.GetValue(instance, null);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var field = current.GetField(name, flags);
				if (field != null)
				{
					value = field.GetValue(instance);
					return true;
				}
			}
			catch
			{
			}
			try
			{
				var method = current.GetMethod(name, flags);
				if (method != null && method.GetParameters().Length == 0)
				{
					value = method.Invoke(instance, Array.Empty<object>());
					return true;
				}
			}
			catch
			{
			}
		}

		return false;
	}

	private static int CountEnumerable(IEnumerable enumerable)
	{
		try
		{
			var count = 0;
			foreach (var ignored in enumerable)
				count++;
			return count;
		}
		catch
		{
			return -1;
		}
	}

	private static string SafeFormatValue(object value)
	{
		if (value == null)
			return "null";
		try
		{
			var text = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
			if (string.IsNullOrEmpty(text))
				text = "(empty)";
			return text.Length <= 96 ? text : text.Substring(0, 96) + "...";
		}
		catch
		{
			return "(err)";
		}
	}

	private static string DescribeSimpleValue(object value)
	{
		var text = SafeFormatValue(value);
		if (value is string sid && GameSymbols.RampartAvengerLaws.TryDescribeMarkBuffSid(sid, out var avengerDescription))
			return "'" + text + "'(" + avengerDescription + ")";
		return text;
	}

	private static bool IsSimpleType(Type type)
	{
		if (type == null)
			return false;
		if (type.IsPrimitive || type.IsEnum)
			return true;
		return type == typeof(string)
		       || type == typeof(decimal)
		       || type == typeof(IntPtr)
		       || type == typeof(UIntPtr);
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
