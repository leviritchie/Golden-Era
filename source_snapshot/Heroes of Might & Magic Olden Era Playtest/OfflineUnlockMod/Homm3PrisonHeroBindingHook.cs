using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using Hex.Map;
using Hex.Session.Data;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Binds a ported HoMM3 prison to its placed hero before native prison initialization.
///
/// Native prison logic owns the cached Hero field and selects it from ObjPrison.heroSid
/// during its own Init(). The ObjPrison DataObject property-init postfix uses the exact
/// ObjectsProperties argument when available; the logic Init prefix remains the final
/// preselection boundary and also resolves the loaded map property surface.
/// </summary>
internal static class Homm3PrisonHeroBindingHook
{
	private const string LogPrefix = "HoMM3 prison hero binding";
	private static readonly object LogGate = new();
	private static readonly HashSet<string> LoggedDiagnostics = new(StringComparer.Ordinal);
	private static bool _registered;
	private static MemberInfo _prisonMember;
	private static ManualLogSource _log;

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		_log = log;
		try
		{
			var logicType = ResolvePrisonLogicType();
			if (logicType == null)
				throw new InvalidOperationException("native prison logic type was not resolved.");

			var initMethods = GameMember.FindMethodsByNames(
				logicType,
				Type.EmptyTypes,
				GameSymbols.PrisonHeroBinding.LogicInit);
			if (initMethods.Length == 0)
				throw new InvalidOperationException(
					"native prison logic Init() was not resolved on " + logicType.FullName + ".");

			var prisonMember = FindPrisonMember(logicType);
			if (prisonMember == null)
				throw new InvalidOperationException(
					"native prison logic must expose exactly one unambiguous ObjPrison field/property on "
					+ logicType.FullName
					+ ".");
			_prisonMember = prisonMember;

			var prefixMethod = AccessTools.Method(
				typeof(Homm3PrisonHeroBindingHook),
				nameof(PrefixPrisonInit));
			if (prefixMethod == null)
				throw new MissingMethodException(
					typeof(Homm3PrisonHeroBindingHook).FullName,
					nameof(PrefixPrisonInit));
			var prefix = new HarmonyMethod(prefixMethod);
			foreach (var method in initMethods)
			{
				if (!GameMember.IsHarmonyPatchCompatible(method, prefixMethod, out var reason))
					throw new InvalidOperationException(
						"prison Init patch is incompatible with "
						+ method.Name
						+ ": "
						+ (reason ?? "unknown reason"));
				harmony.Patch(method, prefix: prefix);
			}

			var dataInitMethods = FindDataObjectPropertiesInitMethods();
			var dataPostfixMethod = AccessTools.Method(
				typeof(Homm3PrisonHeroBindingHook),
				nameof(PostfixDataObjectPropertiesInit));
			if (dataInitMethods.Count > 0 && dataPostfixMethod != null)
			{
				var dataPostfix = new HarmonyMethod(dataPostfixMethod);
				foreach (var method in dataInitMethods)
				{
					if (!GameMember.IsHarmonyPatchCompatible(
						    method,
						    dataPostfixMethod,
						    out var reason))
					{
						throw new InvalidOperationException(
							"prison data-object property patch is incompatible with "
							+ method.Name
							+ ": "
							+ (reason ?? "unknown reason"));
					}
					harmony.Patch(method, postfix: dataPostfix);
				}
			}

			_registered = true;
			_log?.LogInfo(
				LogPrefix
				+ ": registered "
				+ initMethods.Length
				+ " Init() prefix(es) on "
				+ logicType.FullName
				+ " and "
				+ dataInitMethods.Count
				+ " DataObject property-init postfix(es); generated propHeroes rows will "
				+ "be applied before native hero selection.");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + ": registration failed closed: " + ex);
			throw;
		}
	}

	private static Type ResolvePrisonLogicType()
	{
		return GameMember.FindTypeFromHints(
			GameSymbols.PrisonHeroBinding.LogicTypeId,
			GameSymbols.PrisonHeroBinding.LogicTypeHints);
	}

	private static MemberInfo FindPrisonMember(Type logicType)
	{
		if (logicType == null)
			return null;

		const BindingFlags flags = BindingFlags.Public
			| BindingFlags.NonPublic
			| BindingFlags.Instance
			| BindingFlags.DeclaredOnly;
		var candidates = new List<MemberInfo>();

		for (var current = logicType; current != null; current = current.BaseType)
		{
			FieldInfo[] fields;
			try { fields = current.GetFields(flags); }
			catch { fields = Array.Empty<FieldInfo>(); }
			foreach (var field in fields)
			{
				if (!IsPrisonMemberType(field.FieldType))
					continue;
				if (MatchesPrisonMemberHint(field.Name, field))
					return field;
				candidates.Add(field);
			}

			PropertyInfo[] properties;
			try { properties = current.GetProperties(flags); }
			catch { properties = Array.Empty<PropertyInfo>(); }
			foreach (var property in properties)
			{
				if (!IsPrisonMemberType(property.PropertyType)
				    || property.GetMethod == null
				    || property.GetIndexParameters().Length != 0)
				{
					continue;
				}
				if (MatchesPrisonMemberHint(property.Name, property))
					return property;
				candidates.Add(property);
			}
		}

		return candidates.Count == 1 ? candidates[0] : null;
	}

	private static bool IsPrisonMemberType(Type type)
	{
		return type == typeof(ObjPrison)
		       || (type != null && string.Equals(type.Name, nameof(ObjPrison), StringComparison.Ordinal));
	}

	private static bool MatchesPrisonMemberHint(string name, MemberInfo member)
	{
		foreach (var hint in GameSymbols.PrisonHeroBinding.LogicPrisonFieldHints)
		{
			if (string.Equals(name, hint, StringComparison.Ordinal)
			    || string.Equals(GameMember.ReadObfuscatedName(member), hint, StringComparison.Ordinal))
			{
				return true;
			}
		}
		return false;
	}

	private static ObjPrison ReadPrison(object instance)
	{
		if (instance == null || _prisonMember == null)
			return null;
		try
		{
			if (_prisonMember is FieldInfo field)
				return field.GetValue(instance) as ObjPrison;
			if (_prisonMember is PropertyInfo property)
				return property.GetValue(instance, null) as ObjPrison;
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + ": could not read the native ObjPrison member: " + ex);
		}
		return null;
	}

	private static List<MethodInfo> FindDataObjectPropertiesInitMethods()
	{
		var matches = new List<MethodInfo>();
		var seen = new HashSet<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public
			| BindingFlags.NonPublic
			| BindingFlags.Instance
			| BindingFlags.DeclaredOnly;

		for (var current = typeof(ObjPrison); current != null; current = current.BaseType)
		{
			MethodInfo[] methods;
			try { methods = current.GetMethods(flags); }
			catch { continue; }
			foreach (var method in methods)
			{
				if (!seen.Add(method) || method.IsStatic || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 1)
					continue;
				var parameterType = parameters[0].ParameterType;
				if (parameterType == typeof(ObjectsProperties)
				    || string.Equals(parameterType?.Name, nameof(ObjectsProperties), StringComparison.Ordinal))
				{
					matches.Add(method);
				}
			}
		}

		matches.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
		return matches;
	}

	private static void PostfixDataObjectPropertiesInit(object __instance, ObjectsProperties __0)
	{
		if (!(__instance is ObjPrison prison) || __0 == null)
			return;

		try
		{
			var objectId = DeobfInteropCompat.GetIntMember(
				prison,
				GameSymbols.PrisonHeroBinding.PrisonIdFields);
			if (objectId <= 0)
				return;
			if (!Homm3CampaignSpawnParityHook.TryResolvePropHeroSidFromObjectsProperties(
				    __0,
				    objectId,
				    out var desiredHeroSid)
			    || string.IsNullOrWhiteSpace(desiredHeroSid))
			{
				return;
			}
			TryWriteHeroSid(prison, objectId, desiredHeroSid, "DataObject property initialization");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + ": DataObject property-init postfix failed: " + ex);
		}
	}

	private static void PrefixPrisonInit(object __instance)
	{
		try
		{
			var prison = ReadPrison(__instance);
			if (prison == null)
				return;

			var objectId = DeobfInteropCompat.GetIntMember(
				prison,
				GameSymbols.PrisonHeroBinding.PrisonIdFields);
			if (objectId <= 0)
			{
				LogOnce(
					"invalid-id:" + (objectId.ToString()),
					LogLevel.Warning,
					"native prison Init exposed an invalid idMapObject; deterministic H3 binding was skipped.");
				return;
			}

			// A propHeroes row is the explicit generator contract for a deterministic
			// H3 prison. No row means this is a normal OE random prison; preserve it.
			if (!Homm3CampaignSpawnParityHook.TryResolvePropHeroSidForObject(
				    objectId,
				    out var desiredHeroSid)
			    || string.IsNullOrWhiteSpace(desiredHeroSid))
			{
				LogOnce(
					"unresolved-prop-hero:" + objectId.ToString(),
					LogLevel.Warning,
					"native prison Init found no defined propHeroes row for id="
					+ objectId
					+ "; native random-hero selection was left unchanged.");
				return;
			}

			TryWriteHeroSid(prison, objectId, desiredHeroSid, "native prison Init");
		}
		catch (Exception ex)
		{
			// This is a diagnostic prefix. Do not let one optional ported prison brick
			// Loader; an unbound prison remains visible in the log as a failed contract.
			_log?.LogError(LogPrefix + ": prefix failed closed: " + ex);
		}
	}

	private static void TryWriteHeroSid(
		ObjPrison prison,
		int objectId,
		string desiredHeroSid,
		string source)
	{
		var currentHeroSid = DeobfInteropCompat.TryReadNativeStringMember(
			prison,
			GameSymbols.PrisonHeroBinding.PrisonHeroSidFields);
		if (string.Equals(currentHeroSid, desiredHeroSid, StringComparison.Ordinal))
			return;

		if (!DeobfInteropCompat.TryWriteNativeStringMember(
			    prison,
			    desiredHeroSid,
			    GameSymbols.PrisonHeroBinding.PrisonHeroSidFields))
		{
			throw new MissingMemberException(
				typeof(ObjPrison).FullName,
				string.Join("/", GameSymbols.PrisonHeroBinding.PrisonHeroSidFields));
		}

		var verifiedHeroSid = DeobfInteropCompat.TryReadNativeStringMember(
			prison,
			GameSymbols.PrisonHeroBinding.PrisonHeroSidFields);
		if (!string.Equals(verifiedHeroSid, desiredHeroSid, StringComparison.Ordinal))
		{
			throw new InvalidOperationException(
				"ObjPrison.heroSid write did not verify for id="
				+ objectId
				+ " desired="
				+ desiredHeroSid
				+ " observed="
				+ (verifiedHeroSid ?? "<empty>"));
		}

		_log?.LogInfo(
			LogPrefix
			+ ": preselected heroSid="
			+ desiredHeroSid
			+ " for prison id="
			+ objectId
			+ " during "
			+ source
			+ ".");
	}

	private static void LogOnce(string key, LogLevel level, string message)
	{
		lock (LogGate)
		{
			if (!LoggedDiagnostics.Add(key))
				return;
			if (level == LogLevel.Warning)
				_log?.LogWarning(LogPrefix + ": " + message);
			else
				_log?.LogInfo(LogPrefix + ": " + message);
		}
	}
}
