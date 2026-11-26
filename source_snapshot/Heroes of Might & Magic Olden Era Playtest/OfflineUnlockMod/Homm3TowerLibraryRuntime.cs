using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;
using DataBuildingBank = Hex.Session.Data.BuildingBank;
using DataBuildingData = Hex.Session.Data.BuildingData;
using DataBuildingMagicGuild = Hex.Session.Data.BuildingMagicGuild;

namespace OfflineUnlockMod;

/// <summary>
/// Tower Library (building pass 2026-11-22, docs/building_pass_20261122/tower.md): +1 spell on every Mage Guild level
/// of the city that has <c>Build_Library</c>, stacking with the Observatory Network law.
/// - A postfix on the guild logic's GetMagicsCountForRank(rank) adds 1 when the guild's city has the Library, so every
///   level rolled after that (new guild levels) gets the extra spell natively.
/// - When the Library is built (postfix on the bank logic's OnConstruct override, filtered to the SID), the city's guild
///   runs LearnMagicAddition(1), the native call the law uses, so already-open levels get their spell at once. It only
///   runs when an open level is below its (Library-raised) count, so a repeat call cannot add a second spell.
/// No save state: the count is computed, and the guild's spells are native save data.
///
/// Hook choice: the logic Building base's empty virtuals (HeroVisit, OnConstruct, ...) are identical-code-folded stubs
/// on the live build (CallerCount 28355 each), so nothing here patches a base virtual; only type-specific overrides
/// and the guild's own private count method are patched. Members are found by shape from deobfuscated data types
/// (BuildingMagicGuild / BuildingBank fields), the real name Init, and Il2CppInterop CallerCount; anything ambiguous
/// refuses to register.
/// </summary>
internal static class Homm3TowerLibraryRuntime
{
	internal const string LibrarySid = "Build_Library";
	private const string LogPrefix = "HoMM3 Tower Library: ";

	private static ManualLogSource _log;
	private static bool _attempted;
	private static bool _active;
	private static int _logged;
	private static MethodInfo _magicsCountForRank;
	private static MethodInfo _learnMagicAddition;
	private static MemberInfo _guildDataField;
	private static readonly Dictionary<IntPtr, Il2CppObjectBase> GuildByCity = new();

	private static void Info(string message)
	{
		if (_logged++ < 120)
			_log?.LogInfo(LogPrefix + message);
	}

	private static void Warn(string message)
	{
		if (_logged++ < 120)
			_log?.LogWarning(LogPrefix + message);
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_attempted || harmony == null)
			return;
		_attempted = true;
		_log = log;
		try
		{
			if (!Homm3LogicBuildingShape.TryResolve(out var shapeFail))
				throw new MissingMemberException(shapeFail);
			var guildType = Homm3LogicBuildingShape.FindLogicTypeHoldingData(typeof(DataBuildingMagicGuild))
			                ?? throw new TypeLoadException("guild logic type (field of type BuildingMagicGuild) not found or ambiguous");
			var bankType = Homm3LogicBuildingShape.FindLogicTypeHoldingData(typeof(DataBuildingBank))
			               ?? throw new TypeLoadException("bank logic type (field of type BuildingBank) not found or ambiguous");
			_guildDataField = Homm3LogicBuildingShape.FindDeclaredField(guildType, typeof(DataBuildingMagicGuild))
			                  ?? throw new MissingFieldException(guildType.FullName, "BuildingMagicGuild data field");

			// GetMagicsCountForRank: the only declared private int(int) on the guild logic with real callers (the other
			// four same-shape methods are CallerCount 0 clones on the 2026-11 build).
			_magicsCountForRank = Homm3LogicBuildingShape.FindUniqueCalled(guildType, typeof(int), new[] { typeof(int) }, m => m.IsPrivate && !m.IsVirtual)
			                      ?? throw new MissingMethodException(guildType.FullName, "GetMagicsCountForRank (unique private int(int) with CallerCount > 0)");
			// LearnMagicAddition: the only declared public non-virtual void(int).
			_learnMagicAddition = Homm3LogicBuildingShape.FindUniqueDeclared(guildType, typeof(void), new[] { typeof(int) }, m => m.IsPublic && !m.IsVirtual)
			                      ?? throw new MissingMethodException(guildType.FullName, "LearnMagicAddition (unique public void(int))");
			var guildInit = Homm3LogicBuildingShape.FindDeclaredInit(guildType)
			                ?? throw new MissingMethodException(guildType.FullName, "Init(BuildingData, city) override");
			var bankConstruct = Homm3LogicBuildingShape.FindDeclaredOnConstruct(bankType)
			                    ?? throw new MissingMethodException(bankType.FullName, "OnConstruct override (protected virtual void())");

			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3TowerLibraryRuntime), _magicsCountForRank, null, nameof(PostfixMagicsCountForRank));
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3TowerLibraryRuntime), guildInit, null, nameof(PostfixGuildInit));
			Homm3TowerArtificingRuntime.PatchOwned(harmony, typeof(Homm3TowerLibraryRuntime), bankConstruct, null, nameof(PostfixBankConstruct));
			_active = true;
			_log?.LogInfo(LogPrefix + "registered: count " + guildType.FullName + "." + _magicsCountForRank.Name
				+ ", learn " + _learnMagicAddition.Name + ", guild Init, bank OnConstruct " + bankType.FullName + "." + bankConstruct.Name + ".");
		}
		catch (Exception ex)
		{
			_active = false;
			_log?.LogWarning(LogPrefix + "NOT registered (the Library adds no spells): " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixGuildInit(object __instance)
	{
		try
		{
			if (__instance is not Il2CppObjectBase guild || Homm3LogicBuildingShape.CityOf(__instance) is not Il2CppObjectBase city || city.Pointer == IntPtr.Zero)
				return;
			GuildByCity[city.Pointer] = guild;
		}
		catch
		{
			// The registry only serves the construction-time top-up; the count postfix does not need it.
		}
	}

	private static bool CityHasLibrary(object city)
	{
		return city != null && Homm3TownBuildingReader.CityHasBuilding(city, LibrarySid);
	}

	private static void PostfixMagicsCountForRank(object __instance, int __0, ref int __result)
	{
		if (!_active)
			return;
		try
		{
			var city = Homm3LogicBuildingShape.CityOf(__instance);
			if (!CityHasLibrary(city))
				return;
			__result += 1;
			Info("guild level " + __0 + " count +1 (Library) -> " + __result + ".");
		}
		catch (Exception ex)
		{
			Warn("count postfix threw " + ex.GetBaseException().Message + "; no extra spell this call.");
		}
	}

	private static void PostfixBankConstruct(object __instance)
	{
		if (!_active)
			return;
		try
		{
			if (!Homm3LogicBuildingShape.TryReadIdentity(__instance, out var sid, out _, out _)
			    || !string.Equals(sid, LibrarySid, StringComparison.Ordinal))
				return;
			if (Homm3LogicBuildingShape.CityOf(__instance) is not Il2CppObjectBase city || city.Pointer == IntPtr.Zero)
			{
				Warn("Library built but its city is unreadable; open guild levels get no spell until they re-roll.");
				return;
			}
			if (!GuildByCity.TryGetValue(city.Pointer, out var guild) || guild == null || guild.Pointer == IntPtr.Zero
			    || Homm3LogicBuildingShape.CityOf(guild) is not Il2CppObjectBase guildCity || guildCity.Pointer != city.Pointer)
			{
				Warn("Library built but this city's Mage Guild logic was not seen at Init; open levels get no extra spell now (new levels still do).");
				return;
			}
			if (!TryHasOpenLevelBelowCount(guild, out var detail))
			{
				Info("Library built; no open guild level is below its count (" + detail + "), so nothing is learned.");
				return;
			}
			_learnMagicAddition.Invoke(guild, new object[] { 1 });
			Info("Library built; LearnMagicAddition(1) on the city's guild (" + detail + ").");
		}
		catch (Exception ex)
		{
			Warn("construction top-up threw " + ex.GetBaseException().Message + ".");
		}
	}

	/// <summary>True when some open guild level holds fewer spells than its Library-raised count. Fails closed.</summary>
	private static bool TryHasOpenLevelBelowCount(object guild, out string detail)
	{
		detail = "";
		var data = Homm3LogicBuildingShape.ReadMember(_guildDataField, guild) as DataBuildingMagicGuild;
		var infos = data?.magicGuildsInfo;
		if (infos == null)
		{
			detail = "guild data unreadable";
			return false;
		}
		var below = false;
		var parts = new List<string>();
		for (var i = 0; i < infos.Length; i++)
		{
			var info = infos[i];
			var dict = info?.magicsDict;
			if (dict == null)
				continue;
			var have = Homm3LogicBuildingShape.ReadCount(dict);
			if (have <= 0)
				continue;
			var want = (int)_magicsCountForRank.Invoke(guild, new object[] { i + 1 });
			parts.Add("L" + (i + 1) + " " + have + "/" + want);
			if (have < want)
				below = true;
		}
		detail = parts.Count == 0 ? "no open level" : string.Join(", ", parts);
		return below;
	}
}

/// <summary>
/// Shape resolution for the logic city-building classes shared by the CRT building-pass runtimes. Everything is found
/// from deobfuscated anchors (Hex.Session.Data building types, the real method name Init, Hex.Session.Logic.Hero) and
/// Il2CppInterop's CallerCount, so no obfuscated name is hard-coded here. Ambiguity returns null.
/// </summary>
internal static class Homm3LogicBuildingShape
{
	private const BindingFlags Declared = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
	private static bool _resolved;
	private static string _fail;
	private static Type _baseType;
	private static PropertyInfo _dataProperty;
	private static PropertyInfo _cityProperty;

	internal static Type BaseType => _baseType;

	/// <summary>Resolves the logic Building base from the bank logic class (a field of type BuildingBank).</summary>
	internal static bool TryResolve(out string fail)
	{
		if (_resolved)
		{
			fail = _fail;
			return _fail == null;
		}
		_resolved = true;
		try
		{
			var bank = FindLogicTypeHoldingData(typeof(DataBuildingBank)) ?? throw new TypeLoadException("bank logic type not found or ambiguous");
			_baseType = bank.BaseType ?? throw new TypeLoadException("bank logic has no base type");
			var init = FindInit(_baseType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly)
			           ?? throw new MissingMethodException(_baseType.FullName, "Init(BuildingData, city)");
			var cityType = init.GetParameters()[1].ParameterType;
			_dataProperty = UniqueProperty(_baseType, typeof(DataBuildingData)) ?? throw new MissingMemberException(_baseType.FullName, "BuildingData property");
			_cityProperty = UniqueProperty(_baseType, cityType) ?? throw new MissingMemberException(_baseType.FullName, "logic city property");
			_fail = null;
		}
		catch (Exception ex)
		{
			_fail = "logic building shape: " + ex.GetBaseException().Message;
		}
		fail = _fail;
		return _fail == null;
	}

	private static IEnumerable<Type> HexTypes()
	{
		Type[] types;
		var asm = typeof(TransferBattle).Assembly;
		try { types = asm.GetTypes(); }
		catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
		foreach (var t in types)
			if (t != null)
				yield return t;
	}

	private static MethodInfo FindInit(Type type, BindingFlags flags)
	{
		MethodInfo match = null;
		foreach (var m in type.GetMethods(flags))
		{
			if (m.Name != "Init" || m.ReturnType != typeof(void))
				continue;
			var p = m.GetParameters();
			if (p.Length != 2 || p[0].ParameterType != typeof(DataBuildingData))
				continue;
			if (match != null)
				return null;
			match = m;
		}
		return match;
	}

	/// <summary>The unique Hex class that declares a field of the given data type and has a logic Init(BuildingData, city).</summary>
	internal static Type FindLogicTypeHoldingData(Type dataType)
	{
		Type match = null;
		foreach (var t in HexTypes())
		{
			try
			{
				if (!t.IsClass || FindDeclaredField(t, dataType) == null)
					continue;
				if (FindInit(t, BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly) == null)
					continue;
				if (match != null)
					return null;
				match = t;
			}
			catch
			{
				// Types that fail to reflect are not building logic.
			}
		}
		return match;
	}

	/// <summary>The unique declared member (managed field or Il2CppInterop field-property) of the given type.</summary>
	internal static MemberInfo FindDeclaredField(Type type, Type fieldType)
	{
		MemberInfo match = null;
		foreach (var f in type.GetFields(Declared))
		{
			if (f.FieldType != fieldType)
				continue;
			if (match != null)
				return null;
			match = f;
		}
		foreach (var p in type.GetProperties(Declared))
		{
			if (p.PropertyType != fieldType || p.GetIndexParameters().Length != 0 || p.GetMethod == null)
				continue;
			if (match != null)
				return null;
			match = p;
		}
		return match;
	}

	internal static object ReadMember(MemberInfo member, object instance)
	{
		return member switch
		{
			FieldInfo f => f.GetValue(instance),
			PropertyInfo p => p.GetValue(instance),
			_ => null,
		};
	}

	private static PropertyInfo UniqueProperty(Type type, Type propertyType)
	{
		PropertyInfo match = null;
		foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (p.PropertyType != propertyType || p.GetIndexParameters().Length != 0 || p.GetMethod == null)
				continue;
			// A get/set pair over the same native field shows up once; two distinct properties are ambiguous unless one
			// is the protected field accessor (prop_* wins over field_*).
			if (match != null)
			{
				var mField = match.Name.StartsWith("field_", StringComparison.Ordinal);
				var pField = p.Name.StartsWith("field_", StringComparison.Ordinal);
				if (mField && !pField)
					match = p;
				else if (mField == pField)
					return null;
				continue;
			}
			match = p;
		}
		return match;
	}

	internal static MethodInfo FindDeclaredInit(Type type) => FindInit(type, Declared);

	/// <summary>OnConstruct override: the unique declared protected virtual void().</summary>
	internal static MethodInfo FindDeclaredOnConstruct(Type type)
	{
		return FindUniqueDeclared(type, typeof(void), Type.EmptyTypes, m => m.IsFamily && m.IsVirtual);
	}

	internal static MethodInfo FindUniqueDeclared(Type type, Type returnType, Type[] parameters, Func<MethodInfo, bool> filter)
	{
		MethodInfo match = null;
		foreach (var m in type.GetMethods(Declared))
		{
			if (m.ReturnType != returnType || m.IsGenericMethodDefinition || !SameParameters(m, parameters) || !filter(m))
				continue;
			if (match != null)
				return null;
			match = m;
		}
		return match;
	}

	/// <summary>Like <see cref="FindUniqueDeclared"/>, but only methods with Il2CppInterop CallerCount above 0 count.</summary>
	internal static MethodInfo FindUniqueCalled(Type type, Type returnType, Type[] parameters, Func<MethodInfo, bool> filter)
	{
		MethodInfo match = null;
		foreach (var m in type.GetMethods(Declared))
		{
			if (m.ReturnType != returnType || m.IsGenericMethodDefinition || !SameParameters(m, parameters) || !filter(m))
				continue;
			if (CallerCount(m) <= 0)
				continue;
			if (match != null)
				return null;
			match = m;
		}
		return match;
	}

	private static bool SameParameters(MethodInfo m, Type[] parameters)
	{
		var p = m.GetParameters();
		if (p.Length != parameters.Length)
			return false;
		for (var i = 0; i < p.Length; i++)
			if (parameters[i] != null && p[i].ParameterType != parameters[i])
				return false;
		return true;
	}

	/// <summary>Il2CppInterop's [CallerCount(n)]; -1 when the attribute is absent or unreadable.</summary>
	internal static int CallerCount(MethodInfo method)
	{
		try
		{
			foreach (var attribute in method.GetCustomAttributes(false))
			{
				var type = attribute.GetType();
				if (type.Name != "CallerCountAttribute")
					continue;
				var field = type.GetField("Count", BindingFlags.Instance | BindingFlags.Public);
				if (field != null)
					return Convert.ToInt32(field.GetValue(attribute));
				var prop = type.GetProperty("Count", BindingFlags.Instance | BindingFlags.Public);
				if (prop != null)
					return Convert.ToInt32(prop.GetValue(attribute));
			}
		}
		catch
		{
			// Unreadable attribute: treat as unknown.
		}
		return -1;
	}

	internal static object CityOf(object logicBuilding)
	{
		if (logicBuilding == null || _cityProperty == null || !_baseType.IsInstanceOfType(logicBuilding))
			return null;
		return _cityProperty.GetValue(logicBuilding);
	}

	internal static bool TryReadIdentity(object logicBuilding, out string sid, out int level, out bool constructed)
	{
		sid = null;
		level = 0;
		constructed = false;
		if (logicBuilding == null || _dataProperty == null || !_baseType.IsInstanceOfType(logicBuilding))
			return false;
		var data = _dataProperty.GetValue(logicBuilding);
		if (data == null || !Homm3ConstructionNativeAdapter.TryReadBuildingIdentity(data, out var info, out _))
			return false;
		sid = info.Sid;
		level = info.Level;
		constructed = info.IsConstructed;
		return !string.IsNullOrEmpty(sid);
	}

	internal static int ReadCount(object collection)
	{
		if (collection == null)
			return -1;
		try
		{
			var count = collection.GetType().GetProperty("Count", BindingFlags.Instance | BindingFlags.Public)?.GetValue(collection);
			return count == null ? -1 : Convert.ToInt32(count);
		}
		catch
		{
			return -1;
		}
	}
}
