using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

internal static class Homm3ConfluxSpellCopyVisualRuntime
{
	private readonly struct SpellCopyVisualSpec
	{
		internal readonly string UnitSid;
		internal readonly int AbilityIndex;
		internal readonly string SpellSid;
		internal readonly int SpellLevel;

		internal SpellCopyVisualSpec(string unitSid, int abilityIndex, string spellSid, int spellLevel)
		{
			UnitSid = unitSid;
			AbilityIndex = abilityIndex;
			SpellSid = spellSid;
			SpellLevel = spellLevel;
		}
	}

	private static readonly SpellCopyVisualSpec[] SpellCopies =
	{
		new("h3_air_elemental_upg", 0, "primal_1_magic_thunderbolt", 1),
		new("h3_air_elemental_upg_alt", 0, "day_3_magic_haste", 1),
		new("h3_fire_elemental_upg", 0, "space_1_magic_early_start", 1),
		new("h3_fire_elemental_upg_alt", 0, "primal_12_magic_chain_lightning", 1),
		new("h3_earth_elemental_upg", 0, "primal_4_magic_fire_globe", 1),
		new("h3_earth_elemental_upg_alt", 0, "primal_7_magic_wall_of_flame", 1),
	};

	private static readonly object LockObject = new();
	private static readonly HashSet<long> DispatchedSourceEventIds = new();
	private static bool _registered;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";
	private static ManualLogSource _log;
	private static MethodInfo _castMagicFromListsFactory;
	private static Type _magicDataType;
	private static Type _magicRuntimeDataType;
	private static Type _castedMagicType;
	private static int _patched;
	private static int _observed;
	private static int _dispatched;
	private static int _failed;
	private static string _lastDispatched = "none";
	private static string _lastFailure = "none";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;
		_log = log;
		try
		{
			var patched = 0;
			foreach (var typeHint in GameSymbols.BattleEventLaws.BattleEventDispatcherTypeHints)
			{
				var type = GameMember.FindType(GameSymbols.BattleEventLaws.BattleEventDispatcherTypeId + "." + typeHint, typeHint) ?? AccessTools.TypeByName(typeHint);
				if (type == null)
					continue;
				foreach (var methodName in GameSymbols.BattleEventLaws.BattleEventDispatch.NameHints)
					patched += PatchExactVoidMethod(harmony, type, methodName, 2);
			}
			_patched = patched;
			if (patched == 0)
			{
				_registrationAuditStatus = "FAILED_CLOSED: no exact battle-event dispatcher patched";
				log?.LogWarning("HoMM3 Conflux spell-copy visual runtime failed closed: no exact dispatcher hook was patched.");
				return;
			}
			_registrationAuditStatus = "RUNTIME_HOOK_REGISTERED: exact dispatcher patches=" + patched.ToString(CultureInfo.InvariantCulture);
			log?.LogInfo("HoMM3 Conflux spell-copy visual runtime registered " + patched.ToString(CultureInfo.InvariantCulture) + " exact dispatcher patch(es).");
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 Conflux spell-copy visual runtime failed closed during registration: " + ex.Message);
		}
	}

	private static int PatchExactVoidMethod(Harmony harmony, Type type, string methodName, int parameterCount)
	{
		var method = ResolveExactVoidMethod(type, methodName, parameterCount);
		if (method == null)
			return 0;
		var postfix = AccessTools.Method(typeof(Homm3ConfluxSpellCopyVisualRuntime), nameof(PostfixEventDispatch));
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			_log?.LogWarning("HoMM3 Conflux spell-copy visual runtime refused incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactVoidMethod(Type type, string methodName, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static void PostfixEventDispatch(object __instance, MethodBase __originalMethod, object[] __args)
	{
		try
		{
			if (__args == null || __args.Length != 2)
				return;
			TryDispatchSpellVisual(__instance, __originalMethod, __args, __args[1]);
		}
		catch (Exception ex)
		{
			RecordFailure("exception: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool TryDispatchSpellVisual(object dispatcher, MethodBase originalMethod, object[] originalArgs, object eventArgs)
	{
		if (dispatcher == null || originalMethod == null || originalArgs == null || eventArgs == null)
			return false;
		if (!Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent(eventArgs, out var eventInfo, out _))
			return false;
		_observed++;
		var eventId = Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs);
		lock (LockObject)
		{
			if (DispatchedSourceEventIds.Contains(eventId))
				return false;
		}

		if (!TryFindSpellCopySpec(eventInfo, out var spec, out var findFailReason))
		{
			if (findFailReason != null)
				RecordFailure(findFailReason);
			return false;
		}
		if (!TryBuildSyntheticCastMagicEvent(eventInfo, spec, out var syntheticEvent, out var buildFailReason))
		{
			RecordFailure(buildFailReason);
			return false;
		}

		lock (LockObject)
			DispatchedSourceEventIds.Add(eventId);
		var replayArgs = new object[] { originalArgs[0], syntheticEvent };
		originalMethod.Invoke(originalMethod.IsStatic ? null : dispatcher, replayArgs);
		RecordDispatched(spec, eventInfo);
		return true;
	}

	private static bool TryFindSpellCopySpec(Homm3BattleEventNativeAdapter.CastAbilityEventInfo eventInfo, out SpellCopyVisualSpec spec, out string failReason)
	{
		spec = default;
		failReason = null;
		if (eventInfo.Caster == null)
		{
			failReason = "cast ability event has no caster";
			return false;
		}
		if (!TryConvertInt(eventInfo.AbilityIndex, out var abilityIndex))
		{
			failReason = "cast ability event has no exact ability index";
			return false;
		}
		var classification = Homm3UnitLawClassifier.Classify(eventInfo.Caster);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out var identityFailReason))
		{
			failReason = "caster identity failed: " + identityFailReason;
			return false;
		}
		foreach (var candidate in SpellCopies)
		{
			if (string.Equals(candidate.UnitSid, classification.Sid, StringComparison.Ordinal) && candidate.AbilityIndex == abilityIndex)
			{
				spec = candidate;
				return true;
			}
		}
		return false;
	}

	private static bool TryBuildSyntheticCastMagicEvent(Homm3BattleEventNativeAdapter.CastAbilityEventInfo eventInfo, SpellCopyVisualSpec spec, out object syntheticEvent, out string failReason)
	{
		syntheticEvent = null;
		failReason = null;
		if (eventInfo.AttackedHexes == null)
		{
			failReason = spec.UnitSid + " spell-copy visual has no attacked hex list";
			return false;
		}
		if (!TryReadExactMember(eventInfo.Caster, eventInfo.Caster?.GetType(), GameSymbols.BattleEventLaws.CasterBattleSideMembers, out var casterSide) || casterSide == null)
		{
			failReason = spec.UnitSid + " spell-copy visual could not resolve exact caster battle side";
			return false;
		}
		if (!TryCreateMagicData(spec.SpellSid, spec.SpellLevel, out var magicData, out failReason))
			return false;
		if (!TryCreateCastedMagic(casterSide, magicData, spec, out var castedMagic, out failReason))
			return false;

		if (!TryResolveCastMagicFromListsFactory(out var factory, out failReason))
			return false;
		try
		{
			syntheticEvent = factory.Invoke(null, new[] { casterSide, castedMagic, eventInfo.AttackedHexes, eventInfo.AttackedHexes });
		}
		catch (Exception ex)
		{
			failReason = spec.UnitSid + " spell-copy visual CastMagicEventArgs factory failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
		if (syntheticEvent == null)
		{
			failReason = spec.UnitSid + " spell-copy visual CastMagicEventArgs factory returned null";
			return false;
		}
		return true;
	}

	private static bool TryCreateMagicData(string spellSid, int spellLevel, out object magicData, out string failReason)
	{
		magicData = null;
		failReason = null;
		if (!TryResolveMagicDataType(out var type, out failReason))
			return false;
		try
		{
			magicData = Activator.CreateInstance(type);
		}
		catch (Exception ex)
		{
			failReason = "MagicData construction failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
		if (magicData == null)
		{
			failReason = "MagicData construction returned null";
			return false;
		}
		if (!TryWriteExactMember(magicData, type, GameSymbols.SpellbookLaws.MagicDataSidConfigMembers, spellSid))
		{
			failReason = "MagicData sidConfig write failed for " + spellSid;
			return false;
		}
		if (!TryWriteExactMember(magicData, type, GameSymbols.SpellbookLaws.MagicDataLevelMembers, spellLevel))
		{
			failReason = "MagicData level write failed for " + spellSid;
			return false;
		}
		if (!TryWriteExactMember(magicData, type, GameSymbols.SpellbookLaws.MagicDataIsLearnedMembers, true))
		{
			failReason = "MagicData isLearned write failed for " + spellSid;
			return false;
		}
		return true;
	}

	private static bool TryCreateCastedMagic(object casterSide, object magicData, SpellCopyVisualSpec spec, out object castedMagic, out string failReason)
	{
		castedMagic = null;
		failReason = null;
		if (!TryCreateMagicRuntimeData(magicData, out var magicRuntimeData, out failReason))
			return false;
		if (!TryResolveCastedMagicType(out var castedMagicType, out failReason))
			return false;
		var constructor = ResolveExactConstructor(
			castedMagicType,
			new[]
			{
				"ObjectPublicPrcgObPrcgInTrPrcgInUnique",
				"ObjectPublicMaHeccObInccStMacnBoUnique",
				"Int32"
			});
		if (constructor == null)
		{
			failReason = spec.UnitSid + " spell-copy visual castedMagic constructor was not found by exact signature";
			return false;
		}
		try
		{
			castedMagic = constructor.Invoke(new[] { casterSide, magicRuntimeData, spec.SpellLevel });
		}
		catch (Exception ex)
		{
			failReason = spec.UnitSid + " spell-copy visual castedMagic construction failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
		if (castedMagic == null)
		{
			failReason = spec.UnitSid + " spell-copy visual castedMagic construction returned null";
			return false;
		}
		return true;
	}

	private static bool TryCreateMagicRuntimeData(object magicData, out object magicRuntimeData, out string failReason)
	{
		magicRuntimeData = null;
		failReason = null;
		if (!TryResolveMagicRuntimeDataType(out var type, out failReason))
			return false;
		try
		{
			magicRuntimeData = Activator.CreateInstance(type);
		}
		catch (Exception ex)
		{
			failReason = "magic runtime data construction failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
		if (magicRuntimeData == null)
		{
			failReason = "magic runtime data construction returned null";
			return false;
		}
		foreach (var methodName in GameSymbols.SpellbookLaws.MagicRuntimeDataInit.NameHints)
		{
			var init = ResolveExactInstanceMethod(type, methodName, new[] { "MagicData", "Hero" });
			if (init == null)
				continue;
			try
			{
				init.Invoke(magicRuntimeData, new[] { magicData, null });
				return true;
			}
			catch (Exception ex)
			{
				failReason = "magic runtime data init failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}
		failReason = "magic runtime data init method was not found by exact symbols";
		return false;
	}

	private static bool TryResolveMagicRuntimeDataType(out Type type, out string failReason)
	{
		type = _magicRuntimeDataType;
		failReason = null;
		if (type != null)
			return true;
		foreach (var hint in GameSymbols.SpellbookLaws.MagicRuntimeDataTypeHints)
		{
			type = GameMember.FindType(GameSymbols.SpellbookLaws.MagicRuntimeDataTypeId + "." + hint, hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
			{
				_magicRuntimeDataType = type;
				return true;
			}
		}
		failReason = "magic runtime data type was not found by exact hints";
		return false;
	}

	private static bool TryResolveCastedMagicType(out Type type, out string failReason)
	{
		type = _castedMagicType;
		failReason = null;
		if (type != null)
			return true;
		foreach (var hint in GameSymbols.SpellbookLaws.CastedMagicTypeHints)
		{
			type = GameMember.FindType(GameSymbols.SpellbookLaws.CastedMagicTypeId + "." + hint, hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
			{
				_castedMagicType = type;
				return true;
			}
		}
		failReason = "castedMagic type was not found by exact hints";
		return false;
	}

	private static bool TryResolveMagicDataType(out Type type, out string failReason)
	{
		type = _magicDataType;
		failReason = null;
		if (type != null)
			return true;
		foreach (var hint in GameSymbols.SpellbookLaws.MagicDataTypeHints)
		{
			type = GameMember.FindType(GameSymbols.SpellbookLaws.MagicDataTypeId + "." + hint, hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
			{
				_magicDataType = type;
				return true;
			}
		}
		failReason = "MagicData type was not found by exact hints";
		return false;
	}

	private static bool TryResolveCastMagicFromListsFactory(out MethodInfo method, out string failReason)
	{
		method = _castMagicFromListsFactory;
		failReason = null;
		if (method != null)
			return true;
		Type type = null;
		foreach (var hint in GameSymbols.SpellbookLaws.CastMagicEventArgsTypeHints)
		{
			type = GameMember.FindType(GameSymbols.SpellbookLaws.CastMagicEventArgsTypeId + "." + hint, hint) ?? AccessTools.TypeByName(hint);
			if (type != null)
				break;
		}
		if (type == null)
		{
			failReason = "CastMagicEventArgs type was not found by exact hints";
			return false;
		}
		foreach (var methodName in GameSymbols.SpellbookLaws.CastMagicFromListsFactory.NameHints)
		{
			method = ResolveExactStaticMethod(type, methodName, new[] { "ObjectPublicPrcgObPrcgInTrPrcgInUnique", "ObjectPublicObcfInStcfInObcnMacfUnique", "Il2CppSystem.Collections.Generic.List|Hex.Session.Battle.Hex", "Il2CppSystem.Collections.Generic.List|Hex.Session.Battle.Hex" });
			if (method != null)
			{
				_castMagicFromListsFactory = method;
				return true;
			}
		}
		failReason = "CastMagicEventArgs list factory was not found by exact symbols";
		return false;
	}

	private static ConstructorInfo ResolveExactConstructor(Type type, string[] expectedParameterTypeTokens)
	{
		if (type == null)
			return null;
		foreach (var constructor in type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (ExpectedParameterTypesMatch(constructor, expectedParameterTypeTokens))
				return constructor;
		}
		return null;
	}

	private static MethodInfo ResolveExactInstanceMethod(Type type, string methodName, string[] expectedParameterTypeTokens)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (!ExpectedParameterTypesMatch(method, expectedParameterTypeTokens))
				continue;
			return method;
		}
		return null;
	}

	private static MethodInfo ResolveExactStaticMethod(Type type, string methodName, string[] expectedParameterTypeTokens)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			if (!ExpectedParameterTypesMatch(method, expectedParameterTypeTokens))
				continue;
			return method;
		}
		return null;
	}

	private static bool ExpectedParameterTypesMatch(MethodBase method, string[] expectedParameterTypeTokens)
	{
		if (method == null || expectedParameterTypeTokens == null)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != expectedParameterTypeTokens.Length)
			return false;
		for (var i = 0; i < parameters.Length; i++)
		{
			var actual = parameters[i].ParameterType;
			var actualName = (actual.FullName ?? actual.Name) + "|" + actual.Name;
			foreach (var token in expectedParameterTypeTokens[i].Split('|'))
			{
				if (string.IsNullOrWhiteSpace(token))
					continue;
				if (actualName.IndexOf(token, StringComparison.Ordinal) < 0)
					return false;
			}
		}
		return true;
	}
	private static bool TryReadExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (value == null || type == null || names == null)
			return false;
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
				if (field != null)
				{
					raw = field.GetValue(value);
					return true;
				}
				var property = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
				if (property?.GetIndexParameters().Length == 0)
				{
					raw = property.GetValue(value, null);
					return true;
				}
			}
		}
		return false;
	}

	private static bool TryWriteExactMember(object value, Type type, string[] names, object raw)
	{
		if (value == null || type == null || names == null)
			return false;
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				var field = current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (field != null)
				{
					field.SetValue(value, raw);
					return true;
				}
				var property = current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (property?.CanWrite == true && property.GetIndexParameters().Length == 0)
				{
					property.SetValue(value, raw, null);
					return true;
				}
			}
		}
		return false;
	}

	private static bool TryConvertInt(object value, out int result)
	{
		result = 0;
		if (value == null)
			return false;
		try
		{
			result = Convert.ToInt32(value, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static void RecordDispatched(SpellCopyVisualSpec spec, Homm3BattleEventNativeAdapter.CastAbilityEventInfo eventInfo)
	{
		_dispatched++;
		_lastDispatched = spec.UnitSid + " abilityIndex=" + spec.AbilityIndex.ToString(CultureInfo.InvariantCulture) + " spell=" + spec.SpellSid + " nativeName=" + (eventInfo.AbilityName ?? "<null>");
		_log?.LogInfo("HoMM3 Conflux spell-copy visual dispatched synthetic CastMagicEventArgs: " + _lastDispatched);
	}

	private static void RecordFailure(string detail)
	{
		_failed++;
		_lastFailure = detail ?? "unknown";
	}

	internal static string SnapshotJson()
	{
		return "{\"registration\":\"" + EscapeJson(_registrationAuditStatus) + "\",\"patched\":" + _patched.ToString(CultureInfo.InvariantCulture)
		       + ",\"observed\":" + _observed.ToString(CultureInfo.InvariantCulture)
		       + ",\"dispatched\":" + _dispatched.ToString(CultureInfo.InvariantCulture)
		       + ",\"failed\":" + _failed.ToString(CultureInfo.InvariantCulture)
		       + ",\"lastDispatched\":\"" + EscapeJson(_lastDispatched) + "\",\"lastFailure\":\"" + EscapeJson(_lastFailure) + "\"}";
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "<null>" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static string EscapeJson(string value)
	{
		return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
	}
}