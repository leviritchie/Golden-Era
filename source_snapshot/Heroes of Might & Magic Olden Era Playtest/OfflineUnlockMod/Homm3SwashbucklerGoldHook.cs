using System;
using System.Collections;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Data;
using Il2CppInterop.Runtime;
using LogicHero = Hex.Session.Logic.Hero;

namespace OfflineUnlockMod;

internal static class Homm3SwashbucklerGoldHook
{
	private const string SwashbucklerSid = "h3_crew_mate_upg_alt";
	private const int GoldPerUnit = 15;

	private static bool _registered;
	private static ManualLogSource _log;
	private static readonly System.Collections.Generic.Dictionary<(IntPtr session, int side), int> _lastGrantDayBySide = new();
	private static PropertyInfo _sideDataProperty;
	private static MemberInfo _sideResourceMember;
	private static PropertyInfo _sideHeroListProperty;
	private static MemberInfo _sessionManagerMember;
	private static PropertyInfo _sessionDataProperty;
	private static MemberInfo _sessionDayMember;
	private static MemberInfo _logicHeroDataMember;
	private static Type _heroListElementType;
	private static bool _heroListIsDirectHero;
	private static PropertyInfo _heroPartyProperty;
	private static PropertyInfo _heroStatusProperty;
	private static PropertyInfo _partyUnitsProperty;
	private static PropertyInfo _unitSidProperty;
	private static PropertyInfo _unitConfigProperty;
	private static PropertyInfo _unitConfigSidProperty;
	private static PropertyInfo _unitStacksProperty;
	private static ConstructorInfo _resourceWrapperCtor;
	private static MethodInfo _addResourceMethod;
	private static int _loggedGrants;
	private static int _loggedSkips;
	private static readonly System.Collections.Generic.List<(string Owner, Func<object, int> Gold)> _dayStartHeroConsumers = new();

	/// <summary>
	/// Adds per-hero gold to the side's once-per-day grant (Tower Artificing gold grafts). The consumer gets each
	/// active hero-list entry (the logic hero unless the list holds data heroes) and returns the gold to add; it may
	/// refresh hero state too. A consumer that throws adds nothing that day.
	/// </summary>
	internal static bool TryRegisterDayStartHeroConsumer(string owner, Func<object, int> consumer, out string failure)
	{
		failure = !_registered ? "day-start hook not registered" : consumer == null ? "consumer is null" : null;
		if (failure != null)
			return false;
		lock (_dayStartHeroConsumers)
		{
			foreach (var existing in _dayStartHeroConsumers)
			{
				if (string.Equals(existing.Owner, owner, StringComparison.Ordinal))
				{
					failure = "owner " + owner + " already registered";
					return false;
				}
			}
			_dayStartHeroConsumers.Add((owner, consumer));
		}
		return true;
	}

	/// <summary>(sid, stacks) of a data hero's living army stacks; null when the cached army accessors do not fit it.</summary>
	internal static System.Collections.Generic.List<(string Sid, int Stacks)> ReadArmy(object dataHero)
	{
		if (!_registered || dataHero == null || _heroPartyProperty == null || !_heroPartyProperty.DeclaringType.IsInstanceOfType(dataHero))
			return null;
		var party = _heroPartyProperty.GetValue(dataHero);
		var units = party == null ? null : _partyUnitsProperty.GetValue(party);
		if (!TryEnumerateList(units, out var enumerable))
			return null;
		var army = new System.Collections.Generic.List<(string Sid, int Stacks)>();
		foreach (var unit in enumerable)
		{
			var stacks = unit == null ? 0 : ReadIntMember(unit, _unitStacksProperty);
			var sid = stacks > 0 ? ReadUnitSid(unit)?.Trim() : null;
			if (!string.IsNullOrEmpty(sid))
				army.Add((sid, stacks));
		}
		return army;
	}

	private static int SumConsumerGold(object sideLogic, out string detail)
	{
		detail = "";
		System.Collections.Generic.List<(string Owner, Func<object, int> Gold)> consumers;
		lock (_dayStartHeroConsumers)
		{
			if (_dayStartHeroConsumers.Count == 0)
				return 0;
			consumers = new System.Collections.Generic.List<(string Owner, Func<object, int> Gold)>(_dayStartHeroConsumers);
		}
		var heroes = sideLogic == null ? null : _sideHeroListProperty.GetValue(sideLogic);
		if (!TryEnumerateList(heroes, out var enumerable))
			return 0;
		var total = 0;
		foreach (var entry in enumerable)
		{
			if (!IsActiveHero(ResolveHeroFromListEntry(entry)))
				continue;
			foreach (var consumer in consumers)
			{
				try
				{
					var gold = consumer.Gold(entry);
					if (gold > 0)
					{
						total = checked(total + gold);
						detail += " " + consumer.Owner + "+" + gold;
					}
				}
				catch (Exception ex)
				{
					LogSkip(consumer.Owner + " day-start consumer failed: " + ex.GetBaseException().Message);
				}
			}
		}
		return total;
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		if (harmony == null)
			throw new InvalidOperationException("Harmony was not initialized before Swashbuckler gold registration.");

		_log = log;
		var type = GameMember.FindType(
			GameSymbols.SwashbucklerGold.SideLogicTypeId,
			GameSymbols.SwashbucklerGold.SideLogicTypeHint,
			ResolveSideLogicTypeByShape);
		if (type == null)
			throw new MissingMemberException("dtj side logic type not found.");

		var startDay = AccessTools.Method(type, GameSymbols.SwashbucklerGold.SideStartDayName, Type.EmptyTypes);
		if (startDay == null)
			throw new MissingMethodException(type.FullName, "OnStartDay()");

		_sideDataProperty = FindProperty(type, typeof(Side), GameSymbols.SwashbucklerGold.SideDataProperties)
		                    ?? FindUniquePropertyByReturnType(type, typeof(Side));
		_sideHeroListProperty = FindHeroListProperty(type)
		                        ?? FindProperty(type, null, GameSymbols.SwashbucklerGold.SideHeroListProperties);
		if (_sideDataProperty == null || _sideHeroListProperty == null)
			throw new MissingMemberException(type.FullName, "Swashbuckler gold side/session properties");
		_sideResourceMember = FindSideResourceMember(typeof(Side));
		if (_sideResourceMember == null)
			throw new MissingMemberException(typeof(Side).FullName, "Swashbuckler gold side resource member");

		var heroListElementType = TryGetListElementType(_sideHeroListProperty.PropertyType);
		if (heroListElementType == null)
			throw new MissingMemberException(type.FullName, "Swashbuckler gold hero list element type");

		_heroListElementType = heroListElementType;
		_heroListIsDirectHero = IsDirectDataHeroListElement(heroListElementType);
		if (!_heroListIsDirectHero)
		{
			_logicHeroDataMember = FindHeroDataBridgeMember(heroListElementType);
			if (_logicHeroDataMember == null)
				throw new MissingMemberException(heroListElementType.FullName, "Swashbuckler gold logic hero data property");
		}

		CacheHeroArmyAccessors(_heroListIsDirectHero ? heroListElementType : GetBridgePayloadType(_logicHeroDataMember));

		var sessionMgrType = GameMember.FindType(
			GameSymbols.SwashbucklerGold.SessionManagerTypeId,
			GameSymbols.SwashbucklerGold.SessionManagerTypeHint,
			ResolveSessionManagerTypeByShape);
		if (sessionMgrType == null)
			throw new MissingMemberException("dsu session manager type not found.");

		_sessionManagerMember = FindSessionManagerMember(type, sessionMgrType);
		if (_sessionManagerMember == null)
			throw new MissingMemberException(type.FullName, "Swashbuckler gold session manager member");

		_sessionDataProperty = FindSessionDataProperty(sessionMgrType);
		if (_sessionDataProperty == null)
			throw new MissingMemberException(sessionMgrType.FullName, "Swashbuckler gold session data property");
		_sessionDayMember = FindIntMember(typeof(Data), GameSymbols.SwashbucklerGold.SessionDayMembers);
		if (_sessionDayMember == null)
			throw new MissingMemberException(typeof(Data).FullName, "Swashbuckler gold session day member");

		var resourceWrapperType = GameMember.FindType(
			GameSymbols.SwashbucklerGold.ResourceWrapperTypeId,
			GameSymbols.SwashbucklerGold.ResourceWrapperTypeHint);
		if (resourceWrapperType == null)
			throw new MissingMemberException("dti resource wrapper type not found.");
		_resourceWrapperCtor = resourceWrapperType.GetConstructor(BindingFlags.Public | BindingFlags.Instance, null, new[] { typeof(ResHeap) }, null);
		if (_resourceWrapperCtor == null)
			throw new MissingMethodException(resourceWrapperType.FullName, ".ctor(ResHeap)");
		// Exact name only (audit B1): a same-shape sibling is a SET (on 25672315 _0 sets and _1 adds),
		// so a signature fallback could overwrite the side's gold instead of adding to it.
		_addResourceMethod = GameMember.FindFirstMethodByNames(
			resourceWrapperType,
			new[] { typeof(string), typeof(int) },
			GameSymbols.SwashbucklerGold.AddResource);
		if (_addResourceMethod == null || _addResourceMethod.ReturnType != typeof(void))
			throw new MissingMethodException(resourceWrapperType.FullName,
				"exact resource add " + string.Join("/", GameSymbols.SwashbucklerGold.AddResource.NameHints) + "(string,int)");

		harmony.Patch(startDay, postfix: new HarmonyMethod(typeof(Homm3SwashbucklerGoldHook), nameof(PostfixSideStartDay)));
		_registered = true;
		_log?.LogInfo(
			"HoMM3 Swashbuckler gold: registered side day-start hook on "
			+ type.FullName + "." + startDay.Name
			+ " side=" + _sideDataProperty.Name
			+ " res=" + _sideResourceMember.Name
			+ " heroes=" + _sideHeroListProperty.Name
			+ " session=" + _sessionManagerMember.Name
			+ " data=" + _sessionDataProperty.Name
			+ " directHeroList=" + _heroListIsDirectHero
			+ " resource=" + resourceWrapperType.FullName + "." + _addResourceMethod.Name + ".");
	}

	private static Type ResolveSideLogicTypeByShape()
	{
		var sideLogic = typeof(Side).Assembly.GetType("Hex.Session.Logic.SideLogic", throwOnError: false);
		if (sideLogic != null && AccessTools.Method(sideLogic, GameSymbols.SwashbucklerGold.SideStartDayName, Type.EmptyTypes) != null)
			return sideLogic;

		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null || !string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				continue;
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }

			foreach (var candidate in types)
			{
				if (candidate == null)
					continue;
				if (AccessTools.Method(candidate, GameSymbols.SwashbucklerGold.SideStartDayName, Type.EmptyTypes) == null)
					continue;
				if (FindProperty(candidate, typeof(Side), null) == null && FindUniquePropertyByReturnType(candidate, typeof(Side)) == null)
					continue;
				if (FindHeroListProperty(candidate) == null)
					continue;
				return candidate;
			}
		}

		return null;
	}

	private static Type ResolveSessionManagerTypeByShape()
	{
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			if (asm == null || !string.Equals(asm.GetName().Name, "Hex", StringComparison.OrdinalIgnoreCase))
				continue;
			Type[] types;
			try { types = asm.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types ?? Array.Empty<Type>(); }
			catch { continue; }

			foreach (var candidate in types)
			{
				if (candidate == null || candidate.IsAbstract || candidate.IsInterface)
					continue;
				if (FindUniquePropertyByReturnType(candidate, typeof(Data)) == null)
					continue;
				if (!HasUniqueReadableProperty(candidate, "Events"))
					continue;
				return candidate;
			}
		}

		return null;
	}

	private static MemberInfo FindSessionManagerMember(Type sideLogicType, Type sessionMgrType)
	{
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in GameSymbols.SwashbucklerGold.SessionManagerMembers)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var property = sideLogicType.GetProperty(name, flags);
			if (property != null && property.GetMethod != null && sessionMgrType.IsAssignableFrom(property.PropertyType))
				return property;
			var field = sideLogicType.GetField(name, flags);
			if (field != null && sessionMgrType.IsAssignableFrom(field.FieldType))
				return field;
		}

		var fields = GameMember.FindFields(
			sideLogicType,
			sessionMgrType,
			GameSymbols.SwashbucklerGold.SessionManagerTypeId,
			GameSymbols.SwashbucklerGold.SessionManagerMembers);
		if (fields.Length == 1)
			return fields[0];

		MemberInfo propertyMatch = null;
		foreach (var property in sideLogicType.GetProperties(flags))
		{
			if (property?.GetMethod == null || !sessionMgrType.IsAssignableFrom(property.PropertyType))
				continue;
			if (propertyMatch != null)
				return null;
			propertyMatch = property;
		}

		return propertyMatch ?? (fields.Length > 0 ? fields[0] : null);
	}

	private static PropertyInfo FindHeroListProperty(Type type)
	{
		if (type == null)
			return null;

		PropertyInfo match = null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var property in type.GetProperties(flags))
		{
			if (property?.GetMethod == null)
				continue;
			var elementType = TryGetListElementType(property.PropertyType);
			if (!IsHeroElementType(elementType))
				continue;
			if (match != null)
				return null;
			match = property;
		}

		return match;
	}

	private static bool IsDirectDataHeroListElement(Type elementType)
	{
		return HasHeroArmyShape(elementType);
	}

	private static bool IsDataHeroType(Type type)
	{
		return HasHeroArmyShape(type);
	}

	private static bool HasHeroArmyShape(Type type)
	{
		return type != null
		       && FindReadableProperty(type, "party") != null
		       && FindReadableProperty(type, "status") != null;
	}

	private static MemberInfo FindHeroDataBridgeMember(Type wrapperType)
	{
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in GameSymbols.SwashbucklerGold.LogicHeroDataProperties)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var property = wrapperType.GetProperty(name, flags);
			if (property != null && property.GetMethod != null && IsDataHeroPayloadType(property.PropertyType))
				return property;
			var field = wrapperType.GetField(name, flags);
			if (field != null && IsDataHeroPayloadType(field.FieldType))
				return field;
			var method = wrapperType.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && IsDataHeroPayloadType(method.ReturnType))
				return method;
		}

		var matches = new System.Collections.Generic.List<MemberInfo>();
		foreach (var property in wrapperType.GetProperties(flags))
		{
			if (property?.GetMethod != null && IsDataHeroPayloadType(property.PropertyType))
				matches.Add(property);
		}
		foreach (var field in wrapperType.GetFields(flags))
		{
			if (IsDataHeroPayloadType(field.FieldType))
				matches.Add(field);
		}
		foreach (var method in wrapperType.GetMethods(flags))
		{
			if (method == null || method.IsStatic || method.GetParameters().Length != 0 || method.ReturnType == typeof(void))
				continue;
			if (IsDataHeroPayloadType(method.ReturnType))
				matches.Add(method);
		}

		return ChoosePreferredBridgeMember(matches);
	}

	private static bool IsDataHeroPayloadType(Type type)
	{
		if (type == null)
			return false;
		var fullName = type.FullName ?? string.Empty;
		if (fullName.EndsWith(".Session.Data.Hero", StringComparison.Ordinal))
			return true;
		return HasHeroArmyShape(type);
	}

	private static MemberInfo ChoosePreferredBridgeMember(System.Collections.Generic.List<MemberInfo> matches)
	{
		if (matches == null || matches.Count == 0)
			return null;
		if (matches.Count == 1)
			return matches[0];

		foreach (var name in GameSymbols.SwashbucklerGold.LogicHeroDataProperties)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			for (var i = 0; i < matches.Count; i++)
			{
				if (string.Equals(matches[i].Name, name, StringComparison.Ordinal))
					return matches[i];
			}
		}

		for (var i = 0; i < matches.Count; i++)
		{
			if (matches[i] is PropertyInfo)
				return matches[i];
		}

		return matches[0];
	}

	private static Type GetBridgePayloadType(MemberInfo member)
	{
		return member switch
		{
			PropertyInfo property => property.PropertyType,
			FieldInfo field => field.FieldType,
			MethodInfo method => method.ReturnType,
			_ => null,
		};
	}

	private static Type GetMemberType(MemberInfo member)
	{
		return GetBridgePayloadType(member);
	}

	private static bool IsLogicHeroWrapperElement(Type elementType)
	{
		if (elementType == null)
			return false;
		var logicHeroType = typeof(LogicHero);
		if (logicHeroType.IsAssignableFrom(elementType) || elementType.IsAssignableFrom(logicHeroType))
			return true;
		return string.Equals(elementType.FullName, logicHeroType.FullName, StringComparison.Ordinal)
		       || string.Equals(elementType.Name, logicHeroType.Name, StringComparison.Ordinal);
	}

	private static bool IsHeroElementType(Type elementType)
	{
		if (elementType == null)
			return false;
		if (HasHeroArmyShape(elementType))
			return true;
		if (IsLogicHeroWrapperElement(elementType))
			return true;
		return FindHeroDataBridgeMember(elementType) != null;
	}

	private static Type ResolveSessionHeroType()
	{
		return typeof(Hero);
	}

	private static Type ResolveHeroType()
	{
		return ResolveSessionHeroType();
	}

	private static void CacheHeroArmyAccessors(Type heroType)
	{
		_heroPartyProperty = RequireReadableProperty(heroType, "party");
		_heroStatusProperty = RequireReadableProperty(heroType, "status");
		var partyType = _heroPartyProperty.PropertyType;
		_partyUnitsProperty = RequireReadableProperty(partyType, "units");
		var unitType = TryGetEnumerableElementType(_partyUnitsProperty.PropertyType) ?? _partyUnitsProperty.PropertyType;
		_unitStacksProperty = RequireReadableProperty(unitType, "stacks");
		if (!TryCacheUnitSidAccessors(unitType))
			throw new MissingMemberException(unitType.FullName, "Swashbuckler gold unit sid accessor");
	}

	private static bool TryCacheUnitSidAccessors(Type unitType)
	{
		_unitSidProperty = null;
		_unitConfigProperty = null;
		_unitConfigSidProperty = null;
		if (unitType == null)
			return false;

		foreach (var name in new[] { "sid", "configSid", "field_Public_String_0" })
		{
			var property = FindReadableProperty(unitType, name);
			if (property != null && property.PropertyType == typeof(string))
			{
				_unitSidProperty = property;
				return true;
			}
		}

		_unitConfigProperty = FindReadableProperty(unitType, "prop_UnitLogicConfig_0")
		                      ?? FindReadableProperty(unitType, "field_Private_UnitLogicConfig_0");
		if (_unitConfigProperty == null)
			return false;

		var configType = _unitConfigProperty.PropertyType;
		_unitConfigSidProperty = FindReadableProperty(configType, "field_Public_String_0")
		                         ?? FindReadableProperty(configType, "prop_String_0")
		                         ?? FindReadableProperty(configType, "id")
		                         ?? FindReadableProperty(configType, "baseSid");
		return _unitConfigSidProperty != null && _unitConfigSidProperty.PropertyType == typeof(string);
	}

	private static string ReadUnitSid(object unit)
	{
		if (unit == null)
			return null;
		if (_unitSidProperty != null)
		{
			var sid = _unitSidProperty.GetValue(unit) as string;
			if (!string.IsNullOrEmpty(sid))
				return sid;
		}
		var config = _unitConfigProperty?.GetValue(unit);
		return config == null ? null : _unitConfigSidProperty?.GetValue(config) as string;
	}

	private static PropertyInfo RequireReadableProperty(Type type, string logicalName)
	{
		var property = FindReadableProperty(type, logicalName);
		if (property == null)
			throw new MissingMemberException(type.FullName, "Swashbuckler gold accessor '" + logicalName + "'");
		return property;
	}

	private static PropertyInfo FindReadableProperty(Type type, string logicalName)
	{
		if (type == null || string.IsNullOrEmpty(logicalName))
			return null;

		PropertyInfo exactMatch = null;
		PropertyInfo fuzzyMatch = null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var property in type.GetProperties(flags))
		{
			if (property?.GetMethod == null)
				continue;
			if (string.Equals(property.Name, logicalName, StringComparison.OrdinalIgnoreCase))
			{
				if (exactMatch != null)
					return null;
				exactMatch = property;
				continue;
			}
			if (property.Name.IndexOf(logicalName, StringComparison.OrdinalIgnoreCase) >= 0)
			{
				if (fuzzyMatch != null)
					return null;
				fuzzyMatch = property;
			}
		}

		return exactMatch ?? fuzzyMatch;
	}

	private static Type TryGetEnumerableElementType(Type type)
	{
		return TryGetListElementType(type);
	}

	private static bool HasUniqueReadableProperty(Type type, string propertyName)
	{
		if (type == null || string.IsNullOrEmpty(propertyName))
			return false;

		PropertyInfo match = null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var property in type.GetProperties(flags))
		{
			if (property?.GetMethod == null || !string.Equals(property.Name, propertyName, StringComparison.Ordinal))
				continue;
			if (match != null)
				return false;
			match = property;
		}

		return match != null;
	}

	private static PropertyInfo FindSessionDataProperty(Type sessionMgrType)
	{
		var fromHints = FindProperty(sessionMgrType, typeof(Data), GameSymbols.SwashbucklerGold.SessionDataProperties);
		if (fromHints != null)
			return fromHints;

		var matches = new System.Collections.Generic.List<PropertyInfo>();
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var property in sessionMgrType.GetProperties(flags))
		{
			if (property?.GetMethod == null || !IsSessionDataType(property.PropertyType))
				continue;
			matches.Add(property);
		}

		if (matches.Count == 0)
			return null;
		if (matches.Count == 1)
			return matches[0];

		foreach (var name in GameSymbols.SwashbucklerGold.SessionDataProperties)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			for (var i = 0; i < matches.Count; i++)
			{
				if (string.Equals(matches[i].Name, name, StringComparison.Ordinal))
					return matches[i];
			}
		}

		return matches[0];
	}

	private static bool IsSessionDataType(Type type)
	{
		if (type == null)
			return false;
		if (typeof(Data).IsAssignableFrom(type) || type.IsAssignableFrom(typeof(Data)))
			return true;
		return string.Equals(type.FullName, typeof(Data).FullName, StringComparison.Ordinal)
		       || (type.FullName ?? string.Empty).EndsWith(".Session.Data.Data", StringComparison.Ordinal);
	}

	private static PropertyInfo FindUniquePropertyByReturnType(Type type, Type valueType)
	{
		if (type == null || valueType == null)
			return null;

		PropertyInfo match = null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var property in type.GetProperties(flags))
		{
			if (property?.GetMethod == null || !valueType.IsAssignableFrom(property.PropertyType))
				continue;
			if (match != null)
				return null;
			match = property;
		}

		return match;
	}

	private static void PostfixSideStartDay(object __instance)
	{
		try
		{
			if (__instance == null || !_sideDataProperty.DeclaringType.IsInstanceOfType(__instance))
			{
				LogSkip("missing side logic");
				return;
			}

			var side = _sideDataProperty.GetValue(__instance) as Side;
			if (side == null || side.status != Side.EStatus.Life)
				return;

			if (!TryReadCurrentDay(__instance, out var currentDay, out var sessionKey))
			{
				LogSkip("session day unavailable; refusing to grant without idempotence key");
				return;
			}
			var grantKey = (sessionKey, side.index);
			if (_lastGrantDayBySide.TryGetValue(grantKey, out var previousDay) && previousDay == currentDay)
			{
				LogSkip("duplicate day-start call side=" + side.index + " day=" + currentDay);
				return;
			}

			var stacks = CountSwashbucklers(__instance, out var heroes, out var slots);
			var extra = SumConsumerGold(__instance, out var extraDetail);
			if (stacks <= 0 && extra <= 0)
				return;

			var resourceHeap = ReadSideResources(side);
			var resources = resourceHeap == null ? null : _resourceWrapperCtor.Invoke(new object[] { resourceHeap });
			if (resources == null)
			{
				LogSkip("side " + side.index + " has no side resource manager");
				return;
			}

			var amount = checked(stacks * GoldPerUnit + extra);
			_addResourceMethod.Invoke(resources, new object[] { "gold", amount });
			_lastGrantDayBySide[grantKey] = currentDay;
			if (_loggedGrants++ < 16)
				_log?.LogInfo("HoMM3 Swashbuckler gold: side=" + side.index + " day=" + currentDay + " heroes=" + heroes + " slots=" + slots + " stacks=" + stacks
					+ " extra=" + extra + (extraDetail.Length == 0 ? "" : " (" + extraDetail.Trim() + ")") + " grant=" + amount + ".");
		}
		catch (Exception ex)
		{
			LogSkip("grant failed: " + ex.Message);
		}
	}

	private static int CountSwashbucklers(object sideLogic, out int heroesWithSwashbucklers, out int occupiedSlots)
	{
		heroesWithSwashbucklers = 0;
		occupiedSlots = 0;
		var total = 0;
		var heroes = sideLogic == null ? null : _sideHeroListProperty.GetValue(sideLogic);
		if (!TryEnumerateList(heroes, out var enumerable))
			return 0;

		foreach (var logicHero in enumerable)
		{
			var hero = ResolveHeroFromListEntry(logicHero);
			if (!IsActiveHero(hero))
				continue;
			var party = hero == null ? null : _heroPartyProperty.GetValue(hero);
			var units = party == null ? null : _partyUnitsProperty.GetValue(party);
			if (!TryEnumerateList(units, out var unitEnumerable))
				continue;

			var heroHasSwashbucklers = false;
			foreach (var unit in unitEnumerable)
			{
				if (unit == null)
					continue;
				var stacks = ReadIntMember(unit, _unitStacksProperty);
				if (stacks <= 0)
					continue;
				var sid = ReadUnitSid(unit);
				if (!string.Equals(sid, SwashbucklerSid, StringComparison.Ordinal))
					continue;
				total = checked(total + stacks);
				occupiedSlots++;
				heroHasSwashbucklers = true;
			}
			if (heroHasSwashbucklers)
				heroesWithSwashbucklers++;
		}

		return total;
	}

	private static ResHeap ReadSideResources(Side side)
	{
		return side == null || _sideResourceMember == null
			? null
			: GetMemberValue(side, _sideResourceMember) as ResHeap;
	}

	private static MemberInfo FindSideResourceMember(Type sideType)
	{
		if (sideType == null)
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in GameSymbols.SwashbucklerGold.SideResourceMembers)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var field = sideType.GetField(name, flags);
			if (field != null && typeof(ResHeap).IsAssignableFrom(field.FieldType))
				return field;
		}
		foreach (var name in GameSymbols.SwashbucklerGold.SideResourceMembers)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var property = sideType.GetProperty(name, flags);
			if (property?.GetMethod != null && typeof(ResHeap).IsAssignableFrom(property.PropertyType))
				return property;
		}

		FieldInfo fieldMatch = null;
		foreach (var field in sideType.GetFields(flags))
		{
			if (field == null || !typeof(ResHeap).IsAssignableFrom(field.FieldType))
				continue;
			if (fieldMatch != null)
				return null;
			fieldMatch = field;
		}
		return fieldMatch;
	}

	private static object ResolveHeroFromListEntry(object entry)
	{
		if (entry == null)
			return null;
		if (_heroListIsDirectHero)
		{
			if (_heroListElementType != null && !_heroListElementType.IsInstanceOfType(entry))
				return null;
			return entry;
		}
		return _logicHeroDataMember == null ? null : GetMemberValue(entry, _logicHeroDataMember);
	}

	private static int ReadIntMember(object instance, PropertyInfo property)
	{
		if (instance == null || property == null)
			return 0;
		var value = property.GetValue(instance);
		if (value == null)
			return 0;
		try { return Convert.ToInt32(value); }
		catch { return 0; }
	}

	private static int ReadIntMember(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return 0;
		var value = GetMemberValue(instance, member);
		if (value == null)
			return 0;
		try { return Convert.ToInt32(value); }
		catch { return 0; }
	}

	private static bool TryReadCurrentDay(object sideLogic, out int day, out IntPtr sessionKey)
	{
		day = -1;
		sessionKey = IntPtr.Zero;
		var sessionLogic = sideLogic == null ? null : GetMemberValue(sideLogic, _sessionManagerMember);
		var data = sessionLogic == null ? null : _sessionDataProperty.GetValue(sessionLogic) as Data;
		if (data == null)
			return false;
		sessionKey = IL2CPP.Il2CppObjectBaseToPtr(data);
		if (sessionKey == IntPtr.Zero)
			return false;
		day = ReadIntMember(data, _sessionDayMember);
		return day > 0;
	}

	private static object GetMemberValue(object instance, MemberInfo member)
	{
		if (instance == null || member == null)
			return null;
		return member switch
		{
			PropertyInfo property => property.GetValue(instance),
			FieldInfo field => field.GetValue(instance),
			MethodInfo method => method.Invoke(instance, null),
			_ => null,
		};
	}

	private static PropertyInfo FindProperty(Type type, Type valueType, string[] names)
	{
		if (type == null)
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		if (names != null)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrEmpty(name))
					continue;
				var property = type.GetProperty(name, flags);
				if (property != null && property.GetMethod != null && (valueType == null || valueType.IsAssignableFrom(property.PropertyType)))
					return property;
			}
		}
		return null;
	}

	private static MemberInfo FindIntMember(Type type, string[] names)
	{
		if (type == null || names == null)
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property?.GetMethod != null && property.PropertyType == typeof(int))
				return property;
			var field = type.GetField(name, flags);
			if (field != null && field.FieldType == typeof(int))
				return field;
			var method = type.GetMethod(name, flags, null, Type.EmptyTypes, null);
			if (method != null && !method.IsSpecialName && method.ReturnType == typeof(int))
				return method;
		}
		return null;
	}

	private static Type TryGetListElementType(Type type)
	{
		if (type == null)
			return null;
		if (type.IsGenericType)
		{
			var args = type.GetGenericArguments();
			if (args.Length == 1)
				return args[0];
		}
		foreach (var iface in type.GetInterfaces())
		{
			if (!iface.IsGenericType)
				continue;
			var definition = iface.GetGenericTypeDefinition();
			if (definition.FullName != "Il2CppSystem.Collections.Generic.IEnumerable`1")
				continue;
			var args = iface.GetGenericArguments();
			if (args.Length == 1)
				return args[0];
		}
		return null;
	}

	private static bool TryEnumerateList(object list, out IEnumerable enumerable)
	{
		enumerable = list as IEnumerable;
		return enumerable != null;
	}

	private static bool IsActiveHero(object hero)
	{
		if (hero == null || _heroStatusProperty == null)
			return false;
		var status = _heroStatusProperty.GetValue(hero);
		if (status == null)
			return false;
		var statusName = status.ToString();
		return string.Equals(statusName, nameof(EHeroStatus.OnMap), StringComparison.Ordinal)
		       || string.Equals(statusName, nameof(EHeroStatus.InCityGarrison), StringComparison.Ordinal)
		       || string.Equals(statusName, nameof(EHeroStatus.Life), StringComparison.Ordinal)
		       || string.Equals(statusName, "OnMap", StringComparison.Ordinal)
		       || string.Equals(statusName, "InCityGarrison", StringComparison.Ordinal)
		       || string.Equals(statusName, "Life", StringComparison.Ordinal);
	}

	private static void LogSkip(string reason)
	{
		if (_loggedSkips++ < 8)
			_log?.LogWarning("HoMM3 Swashbuckler gold: " + reason + ".");
	}
}
