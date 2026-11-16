using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.Session.Data;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// HoMM3 Dungeon faction-skill battle slice (file name kept for config/plugin compatibility). War Captives
/// (2026-11-14) retired the Imperial Menagerie morale and Terror Mandate enemy-morale effects that lived here.
/// This hook keeps the TransferHero -> Data.Hero index and exposes the faction-skill
/// rank / subskill / unit-config helpers shared with War Captives, Factory, Inferno and Necromancy.
/// The escape click is native: no Dungeon code patches it.
/// </summary>
internal static class Homm3DungeonDraconicDominionHook
{
	private const string DungeonFactionSkillSid = "skill_faction_homm3_dungeon";

	private static bool _registered;
	private static ManualLogSource _log;
	private static Type _configRootType;
	private static MemberInfo _battleLogicHeroDataMember;
	private static object _unitLogicConfigTable;
	private static int _loggedResolveSkips;
	private static readonly Dictionary<string, Hero> TransferHeroDataHeroesBySid = new(StringComparer.Ordinal);

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before the Dungeon battle slice registration.");

		_log = log;
		var hexAssembly = typeof(Hero).Assembly;
		_battleLogicHeroDataMember = ResolveRequiredExactMember(
			typeof(LogicHero),
			typeof(Hero),
			GameSymbols.DraconicDominion.BattleLogicHeroDataHeroMembers,
			"homm3.dungeon.draconicDominion.battleLogicHero.dataHero");
		var transferHeroBuilderMethods = ResolveRequiredTransferHeroDataHeroBuilderMethods();

		foreach (var transferHeroBuilderMethod in transferHeroBuilderMethods)
			PatchPostfix(harmony, transferHeroBuilderMethod, nameof(PostfixTransferHeroFromDataHero));

		_registered = true;
		_log?.LogInfo(
			"HoMM3 Dungeon battle slice: battle-logic-hero-data="
			+ _battleLogicHeroDataMember.Name
			+ ", transfer-hero-builders="
			+ transferHeroBuilderMethods.Count
			+ ". Imperial Menagerie / Terror Mandate morale retired for War Captives; escape click native.");
	}

	private static void PostfixTransferHeroFromDataHero(LogicHero __0, TransferHero __result)
	{
		// Index Configs.Hero from battle LogicHero only. Never patch the StoryHub.Logic.Hero
		// overload (becd): GameMember.TypesEquivalent matches by short name "Hero", and an
		// IL2CPP Harmony postfix on that overload stack-overflows portrait clicks.
		IndexTransferHeroDataHero(ResolveDataHero(__0), __result);
	}

	private static TransferSide ResolveTransferSide(object transferSide)
	{
		return transferSide as TransferSide;
	}

	private static TransferHero ResolveTransferHero(object transferSide)
	{
		return ResolveTransferSide(transferSide)?.hero;
	}

	private static Hero ResolveTransferSideDataHero(object transferSide)
	{
		// Prefer the side's live battle LogicHero (as Bulwark/Castle do). The configId-keyed index is only
		// filled by the TransferHero builder postfix, which may not fire, and is never cleared across
		// loads, so a same-sid hero from an earlier session could otherwise supply stale subskills.
		if (ResolveTransferSide(transferSide)?.logicHero is LogicHero sideLogicHero)
		{
			var fromLogic = ResolveDataHero(sideLogicHero);
			if (fromLogic != null)
				return fromLogic;
		}
		var transferHero = ResolveTransferHero(transferSide);
		if (transferHero == null)
			return null;
		var sid = NormalizeSid(transferHero.configId);
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		lock (TransferHeroDataHeroesBySid)
		{
			return TransferHeroDataHeroesBySid.TryGetValue(sid, out var hero) ? hero : null;
		}
	}

	private static IEnumerable<TransferUnit> ResolveTransferSideUnits(object transferSide)
	{
		var units = ResolveTransferSide(transferSide)?.units;
		if (units == null)
			yield break;
		foreach (var unit in units)
		{
			if (unit != null)
				yield return unit;
		}
	}

	private static string ResolveTransferUnitFaction(TransferUnit transferUnit)
	{
		if (transferUnit == null)
			return null;
		var logicConfig = ResolveUnitLogicConfigBySid(transferUnit.configSid);
		return NormalizeSid(logicConfig?.fraction);
	}

	internal static UnitLogicConfig ResolveUnitLogicConfigBySid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var table = ResolveUnitLogicConfigTable();
		if (table == null)
			return null;
		return TryLookupConfigBySid(table, sid.Trim(), out UnitLogicConfig logicConfig) ? logicConfig : null;
	}

	private static object ResolveUnitLogicConfigTable()
	{
		if (_unitLogicConfigTable != null)
			return _unitLogicConfigTable;

		var rootType = _configRootType ?? ResolveTypeByNames(typeof(TransferSide).Assembly, GameSymbols.UnitPreviewAbilityIcons.ConfigRootTypeNames);
		if (rootType == null)
			return null;
		_configRootType = rootType;

		var root = ReadStaticMember(rootType, GameSymbols.UnitPreviewAbilityIcons.ConfigRootMembers);
		if (root == null)
			return null;

		_unitLogicConfigTable = ReadMember(root, GameSymbols.UnitPreviewAbilityIcons.UnitLogicConfigTables);
		return _unitLogicConfigTable;
	}

	private static bool TryLookupConfigBySid<T>(object table, string sid, out T value) where T : class
	{
		value = null;
		if (table == null || string.IsNullOrWhiteSpace(sid))
			return false;
		try
		{
			var method = FindConfigTableTryGetMethod(table.GetType(), typeof(T));
			if (method == null)
				return false;
			var args = new object[] { sid, null };
			if (!(method.Invoke(table, args) is bool found) || !found)
				return false;
			value = args[1] as T;
			return value != null;
		}
		catch
		{
			return false;
		}
	}

	private static void IndexTransferHeroDataHero(Hero dataHero, TransferHero transferHero)
	{
		if (dataHero == null || transferHero == null)
			return;
		var sid = NormalizeSid(transferHero.configId);
		if (string.IsNullOrWhiteSpace(sid))
			return;
		lock (TransferHeroDataHeroesBySid)
		{
			TransferHeroDataHeroesBySid[sid] = dataHero;
		}
	}

	private static MethodInfo FindConfigTableTryGetMethod(Type tableType, Type valueType)
	{
		if (tableType == null || valueType == null)
			return null;
		foreach (var method in SafeGetMethods(tableType))
		{
			if (method == null || method.ReturnType != typeof(bool) || !MethodMatchesName(method, GameSymbols.UnitPreviewAbilityIcons.ConfigTableTryGet.NameHints))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 2 || parameters[0].ParameterType != typeof(string))
				continue;
			if (!parameters[1].ParameterType.IsByRef || parameters[1].ParameterType.GetElementType() != valueType)
				continue;
			return method;
		}
		return null;
	}

	private static string FormatSigned(int value)
	{
		return value > 0 ? "+" + value : value.ToString();
	}

	private static Hero ResolveDataHero(LogicHero logicHero)
	{
		if (logicHero == null)
			return null;
		return ReadResolvedMember(logicHero, _battleLogicHeroDataMember) as Hero;
	}

	/// <summary>Faction-skill rank 1..3 of skill_faction_homm3_dungeon, 0 when absent. Shared with Captives.</summary>
	internal static int ResolveFactionSkillRank(Hero dataHero)
	{
		return ResolveHeroSkillRank(dataHero, DungeonFactionSkillSid);
	}

	/// <summary>Rank 1..3 of any hero skill sid, 0 when the hero does not have it.</summary>
	internal static int ResolveHeroSkillRank(Hero dataHero, string skillSid)
	{
		if (dataHero == null || string.IsNullOrWhiteSpace(skillSid))
			return 0;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, skillSid, StringComparison.Ordinal))
				continue;
			var level = ReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers);
			return Math.Max(1, Math.Min(3, level));
		}
		return 0;
	}

	internal static bool HasHeroSubSkill(Hero dataHero, string subSkillSid)
	{
		if (dataHero == null || string.IsNullOrWhiteSpace(subSkillSid))
			return false;
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
			foreach (var subSkill in EnumerateObjects(subSkills))
			{
				var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers));
				if (string.Equals(sid, subSkillSid, StringComparison.Ordinal) && IsSubSkillActive(subSkill))
					return true;
			}
		}
		return false;
	}

	/// <summary>
	/// Data.HeroSkill.subSkills lists every subskill the skill offers, picked or not (a rank-1 hero carries all six
	/// rows). Only rows whose status is not Inactive were actually chosen (or are granted temporarily).
	/// </summary>
	/// <summary>Diagnostic: "sid=status" for every subskill row of every hero skill whose rows mention the prefix.</summary>
	internal static string DescribeSubSkillRows(Hero dataHero, string sidPrefix)
	{
		var parts = new List<string>();
		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var subSkills = ReadMember(heroSkill, GameSymbols.DraconicDominion.HeroSkillSubSkillsMembers);
			foreach (var subSkill in EnumerateObjects(subSkills))
			{
				var sid = NormalizeSid(TryReadString(subSkill, GameSymbols.DraconicDominion.HeroSubSkillSidMembers));
				if (sid == null || !sid.StartsWith(sidPrefix, StringComparison.Ordinal))
					continue;
				parts.Add(sid.Substring(sidPrefix.Length) + "=" + (subSkill is Hex.Session.Data.HeroSubSkill row ? row.status + "/L" + row.level : "?"));
			}
		}
		return string.Join(", ", parts);
	}

	internal static bool IsSubSkillActive(object subSkill)
	{
		if (subSkill is Hex.Session.Data.HeroSubSkill row)
			return row.status != Hex.Session.Data.HeroSubSkill.EStatus.Inactive;
		return false;
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new TypeLoadException("Missing " + symbolId + " type " + fullName + ".");
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			foreach (var type in SafeGetTypes(assembly))
			{
				if (type == null)
					continue;
				if (string.Equals(type.FullName, hint, StringComparison.Ordinal)
				    || string.Equals(type.Name, hint, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(type), hint, StringComparison.Ordinal))
					return type;
			}
		}
		throw new TypeLoadException("Missing " + symbolId + " type with configured hints.");
	}

	private static List<MethodInfo> ResolveRequiredTransferHeroDataHeroBuilderMethods()
	{
		var matches = new List<MethodInfo>();
		foreach (var method in SafeGetMethods(typeof(TransferHero)))
		{
			if (method == null || method.IsSpecialName)
				continue;
			if (!MethodMatchesName(method, GameSymbols.DraconicDominion.TransferHeroFromDataHero.NameHints))
				continue;
			if (!method.IsStatic)
				continue;
			if (!TypesEquivalentByFullName(typeof(TransferHero), method.ReturnType))
				continue;
			// Exact FullName only: Session.Logic.Hero (becc). Name-equivalent matching would
			// also bind StoryHub.Logic.Hero (becd) and crash StoryHub portrait UI.
			if (!ParametersMatchExactFullName(method, new[] { typeof(LogicHero) }))
				continue;
			if (!matches.Contains(method))
				matches.Add(method);
		}
		if (matches.Count == 0)
			throw new MissingMethodException(typeof(TransferHero).FullName, GameSymbols.DraconicDominion.TransferHeroFromDataHero.Id);
		if (matches.Count != 1)
			throw new AmbiguousMatchException(
				GameSymbols.DraconicDominion.TransferHeroFromDataHero.Id
				+ " expected exactly one Session.Logic.Hero TransferHero builder, found "
				+ matches.Count);
		return matches;
	}

	private static bool ParametersMatchExactFullName(MethodInfo method, Type[] parameterTypes)
	{
		var parameters = method.GetParameters();
		if (parameters.Length != parameterTypes.Length)
			return false;
		for (var i = 0; i < parameterTypes.Length; i++)
		{
			var expected = parameterTypes[i];
			if (expected != null && !TypesEquivalentByFullName(expected, parameters[i].ParameterType))
				return false;
		}
		return true;
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(
		Type type,
		Type returnType,
		Type[] parameterTypes,
		string methodName,
		string symbolId,
		Predicate<MethodInfo> extraPredicate)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			throw new MissingMethodException(type?.FullName ?? "?", symbolId);

		var matches = new List<MethodInfo>();
		foreach (var method in SafeGetMethods(type))
		{
			if (method == null || method.IsSpecialName)
				continue;
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (returnType != null && !GameMember.TypesEquivalent(returnType, method.ReturnType))
				continue;
			if (parameterTypes != null && !ParametersMatch(method, parameterTypes))
				continue;
			if (extraPredicate != null && !extraPredicate(method))
				continue;
			matches.Add(method);
		}

		if (matches.Count == 1)
			return matches[0];
		if (matches.Count > 1)
			throw new AmbiguousMatchException(symbolId + " matched " + matches.Count + " exact-named methods on " + type.FullName + ".");
		throw new MissingMethodException(type.FullName, symbolId);
	}

	private static MemberInfo ResolveRequiredExactMember(Type type, Type valueType, string[] names, string symbolId)
	{
		foreach (var name in names ?? Array.Empty<string>())
		{
			var member = TryResolveExactMemberByName(type, valueType, name);
			if (member != null)
				return member;
		}
		throw new MissingMemberException(type?.FullName ?? "?", symbolId);
	}

	private static MemberInfo TryResolveExactMemberByName(Type type, Type valueType, string name)
	{
		if (type == null || valueType == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

		var field = type.GetField(name, flags);
		if (field != null && GameMember.TypesEquivalent(valueType, field.FieldType))
			return field;

		var property = type.GetProperty(name, flags);
		if (property?.GetMethod != null
		    && property.GetIndexParameters().Length == 0
		    && GameMember.TypesEquivalent(valueType, property.PropertyType))
			return property;

		var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
		if (method != null
		    && !method.IsStatic
		    && GameMember.TypesEquivalent(valueType, method.ReturnType))
			return method;

		return null;
	}

	private static bool TypesEquivalentByFullName(Type expected, Type actual)
	{
		if (expected == null || actual == null)
			return expected == actual;
		if (expected == actual)
			return true;
		try
		{
			if (expected.IsAssignableFrom(actual) || actual.IsAssignableFrom(expected))
				return true;
		}
		catch { }
		return string.Equals(expected.FullName, actual.FullName, StringComparison.Ordinal);
	}

	private static bool ParametersMatch(MethodInfo method, Type[] parameterTypes)
	{
		return ParametersMatch(method.GetParameters(), parameterTypes);
	}

	private static bool ParametersMatch(ParameterInfo[] parameters, Type[] parameterTypes)
	{
		if (parameters.Length != parameterTypes.Length)
			return false;
		for (var i = 0; i < parameterTypes.Length; i++)
		{
			var expected = parameterTypes[i];
			if (expected != null && !GameMember.TypesEquivalent(expected, parameters[i].ParameterType))
				return false;
		}
		return true;
	}

	private static object ReadResolvedMember(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return null;
		if (member is FieldInfo field)
			return field.GetValue(instance);
		if (member is PropertyInfo property)
			return property.GetValue(instance, null);
		if (member is MethodInfo method)
			return method.Invoke(instance, Array.Empty<object>());
		return null;
	}

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible postfix: " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName, int priority = -1)
	{
		var prefix = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible prefix: " + reason);
		var harmonyPrefix = new HarmonyMethod(prefix);
		if (priority >= 0)
			harmonyPrefix.priority = priority;
		harmony.Patch(target, prefix: harmonyPrefix);
	}

	private static void PatchFinalizer(Harmony harmony, MethodInfo target, string finalizerName)
	{
		var finalizer = AccessTools.Method(typeof(Homm3DungeonDraconicDominionHook), finalizerName);
		if (!GameMember.IsHarmonyPatchCompatible(target, finalizer, out var reason))
			throw new MissingMethodException(target.DeclaringType?.FullName ?? "?", target.Name + " incompatible finalizer: " + reason);
		harmony.Patch(target, finalizer: new HarmonyMethod(finalizer));
	}

	private static bool MethodMatchesName(MethodInfo method, string[] names)
	{
		if (method == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (string.Equals(method.Name, name, StringComparison.Ordinal))
				return true;
			if (string.Equals(GameMember.ReadObfuscatedName(method), name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static Type ResolveTypeByNames(Assembly assembly, string[] names)
	{
		if (assembly == null || names == null)
			return null;
		foreach (var type in SafeGetTypes(assembly))
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				if (string.Equals(type.FullName, name, StringComparison.Ordinal)
				    || string.Equals(type.Name, name, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(type), name, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static object ReadStaticMember(Type type, params string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(null, null);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(null, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static IEnumerable<Type> SafeGetTypes(Assembly assembly)
	{
		if (assembly == null)
			yield break;
		Type[] types;
		try { types = assembly.GetTypes(); }
		catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
		catch { yield break; }
		foreach (var type in types)
			if (type != null)
				yield return type;
	}

	private static IEnumerable<MethodInfo> SafeGetMethods(Type type)
	{
		if (type == null)
			return Array.Empty<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
		try { return type.GetMethods(flags); }
		catch { return Array.Empty<MethodInfo>(); }
	}

	private static IEnumerable<FieldInfo> SafeGetFields(Type type)
	{
		if (type == null)
			return Array.Empty<FieldInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		try { return type.GetFields(flags); }
		catch { return Array.Empty<FieldInfo>(); }
	}

	private static IEnumerable<PropertyInfo> SafeGetProperties(Type type)
	{
		if (type == null)
			return Array.Empty<PropertyInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		try { return type.GetProperties(flags); }
		catch { return Array.Empty<PropertyInfo>(); }
	}

	private static IEnumerable<object> EnumerateObjects(object value)
	{
		if (value == null)
			yield break;

		if (value is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}

		var type = value.GetType();
		var count = TryReadCount(value, type);
		var indexer = ResolveIntIndexer(type);
		if (count == null || count.Value <= 0 || indexer == null)
			yield break;

		for (var i = 0; i < count.Value; i++)
		{
			object item = null;
			try { item = indexer.Invoke(value, new object[] { i }); }
			catch { }
			if (item != null)
				yield return item;
		}
	}

	private static int? TryReadCount(object value, Type type)
	{
		if (value == null || type == null)
			return null;
		try
		{
			var property = type.GetProperty("Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (property != null && property.GetIndexParameters().Length == 0 && property.GetValue(value, null) is int propertyCount)
				return propertyCount;
		}
		catch { }
		try
		{
			var method = type.GetMethod("get_Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method != null && method.GetParameters().Length == 0 && method.Invoke(value, Array.Empty<object>()) is int methodCount)
				return methodCount;
		}
		catch { }
		return null;
	}

	private static MethodInfo ResolveIntIndexer(Type type)
	{
		if (type == null)
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (method == null || method.ReturnType == typeof(void))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length == 1
			    && parameters[0].ParameterType == typeof(int)
			    && (string.Equals(method.Name, "get_Item", StringComparison.Ordinal)
			        || string.Equals(method.Name, "get_ItemOf", StringComparison.Ordinal)))
				return method;
		}
		return null;
	}

	private static object ReadMember(object obj, params string[] names)
	{
		if (obj == null || names == null)
			return null;
		var type = obj.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(obj, null);
			}
			catch { }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(obj);
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void))
					return method.Invoke(obj, Array.Empty<object>());
			}
			catch { }
		}
		return null;
	}

	private static string TryReadString(object obj, params string[] names)
	{
		return ReadMember(obj, names) as string;
	}

	private static int ReadInt(object obj, params string[] names)
	{
		var value = ReadMember(obj, names);
		if (value is int direct)
			return direct;
		try { return Convert.ToInt32(value); }
		catch { return 0; }
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "null";
		return (method.DeclaringType?.FullName ?? method.DeclaringType?.Name ?? "?") + "." + method.Name;
	}

	private static void LogResolveSkip(string message)
	{
		if (_loggedResolveSkips++ < 8)
			_log?.LogWarning("HoMM3 Dungeon Captives morale: " + message);
	}
}
