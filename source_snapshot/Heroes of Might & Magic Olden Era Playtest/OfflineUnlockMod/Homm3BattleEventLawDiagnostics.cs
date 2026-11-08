using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Diagnostic-only scaffold for no-compromise battle-event law families.
/// This traces exact battle event argument construction and the currently
/// proven battle event dispatch names used by damage/destruction paths. It is
/// intended to support later morale, formation, and training law work after
/// runtime ordering proves which native event is safe to mutate.
/// </summary>
internal static class Homm3BattleEventLawDiagnostics
{
	internal const string DiagnosticFlag = "homm3_battle_event_law_diag.flag";

	private const int LogCap = 160;
	private const int MaxMemberSnapshots = 24;
	private static readonly object FormationProbeLock = new();
	private static readonly Dictionary<long, int> ObservedCasterCastCounts = new();
	private static bool _registered;
	private static int _logged;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	internal static string RegistrationAuditStatus => _registrationAuditStatus;
	private static int _observedCastSequence;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		if (!Homm3DiagnosticFlags.IsEnabled(DiagnosticFlag))
		{
			_registrationAuditStatus = "DIAGNOSTIC_FLAG_NOT_ENABLED";
			return;
		}
		_registered = true;

		var patched = 0;
		try
		{
			patched += PatchEventConstructors(harmony, log);
			patched += PatchEventDispatchers(harmony, log);
			patched += PatchDamageApplyCandidate(harmony, log);
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.Message;
			log?.LogWarning("HoMM3 battle-event law diagnostics failed closed during registration: " + ex.Message);
			return;
		}

		if (patched == 0)
		{
			_registrationAuditStatus = "FAILED_CLOSED: no exact startup hook surfaces patched";
			log?.LogWarning("HoMM3 battle-event law diagnostics found no exact event surfaces; morale, formation, and training runtime laws remain disabled.");
			return;
		}

		_registrationAuditStatus = "DIAGNOSTIC_HOOK_REGISTERED: exact trace patches=" + patched.ToString(System.Globalization.CultureInfo.InvariantCulture);
		log?.LogInfo("HoMM3 battle-event law diagnostics registered " + patched + " exact trace patch(es). Diagnostic observation only.");
		log?.LogInfo("HoMM3 battle-event law diagnostics: event construction/dispatch traces are evidence only; do not implement morale, formation, or training mutation until runtime ordering and active-side/law rank correlation are proven.");
	}

	private static int PatchEventConstructors(Harmony harmony, ManualLogSource log)
	{
		var patched = 0;
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsUnitPosChangedEventArgs, "unit-pos-changed", 2);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsUnitStartedMovementEventArgs, "unit-started-movement", 7);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsObjectTookDamageEventArgs, "object-took-damage", 0);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsObjectDestroyedEventArgs, "object-destroyed", 4);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsEnergyUpdateEventArgs, "energy-update", 2, 3);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsEnergyUpdatedByMechEventArgs, "energy-updated-by-mech", 3);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsSideUsedEnergyEventArgs, "side-used-energy", 2);
		patched += PatchConstructors(harmony, log, GameSymbols.TypeGroups.BattleEventLawsCastAbilityEventArgs, "cast-ability", 0);
		return patched;
	}

	private static int PatchDamageApplyCandidate(Harmony harmony, ManualLogSource log)
	{
		var patched = 0;
		var type = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
		if (type == null)
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: battle Unit type not found for damage-apply candidate.");
			return 0;
		}

		foreach (var methodName in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints)
			patched += PatchExactMethod(harmony, log, type, methodName, 8, nameof(PostfixDamageApplyCandidate), "damage-apply-candidate");
		return patched;
	}

	private static int PatchEventDispatchers(Harmony harmony, ManualLogSource log)
	{
		var patched = 0;
		foreach (var typeHint in GameSymbols.BattleEventLaws.BattleEventDispatcherTypeHints)
		{
			var type = GameMember.FindType(GameSymbols.BattleEventLaws.BattleEventDispatcherTypeId + "." + typeHint, typeHint);
			type ??= AccessTools.TypeByName(typeHint);
			if (type == null)
			{
				log?.LogWarning("HoMM3 battle-event law diagnostics: dispatcher type " + typeHint + " not found.");
				continue;
			}

			foreach (var methodName in GameSymbols.BattleEventLaws.BattleEventDispatch.NameHints)
				patched += PatchExactMethod(harmony, log, type, methodName, 2, nameof(PostfixEventDispatch), "event-dispatch");
		}

		return patched;
	}

	private static int PatchConstructors(Harmony harmony, ManualLogSource log, GameSymbols.TypeHintGroup typeGroup, string stage, params int[] parameterCounts)
	{
		var type = GameMember.ResolveTypeGroup(typeGroup);
		if (type == null)
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: event type not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3BattleEventLawDiagnostics), nameof(PostfixEventConstructor));
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: constructor postfix not found.");
			return 0;
		}

		var patched = 0;
		foreach (var constructor in type.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
		{
			if (!Contains(parameterCounts, constructor.GetParameters().Length))
				continue;

			harmony.Patch(constructor, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("HoMM3 battle-event law diagnostics: no exact constructor with expected parameter count found for " + stage + " on " + type.FullName + ".");
		return patched;
	}

	private static int PatchExactMethod(Harmony harmony, ManualLogSource log, Type type, string methodName, int parameterCount, string postfixName, string stage)
	{
		var method = ResolveExactVoidMethod(type, methodName, parameterCount);
		if (method == null)
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: exact " + type.FullName + "." + methodName + "(" + parameterCount + " args) not found for " + stage + ".");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3BattleEventLawDiagnostics), postfixName);
		if (postfix == null)
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: postfix " + postfixName + " not found.");
			return 0;
		}

		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			log?.LogWarning("HoMM3 battle-event law diagnostics: refusing incompatible postfix for " + FormatMethod(method) + ": " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveExactVoidMethod(Type type, string name, int parameterCount)
	{
		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var method in methods)
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (method.IsSpecialName)
				continue;
			if (method.ReturnType != typeof(void))
				continue;
			if (method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}

		return null;
	}

	private static bool Contains(int[] values, int value)
	{
		if (values == null)
			return false;
		for (var i = 0; i < values.Length; i++)
		{
			if (values[i] == value)
				return true;
		}
		return false;
	}

	private static void PostfixEventConstructor(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("event-constructed", __instance, __originalMethod, __args);
	}

	private static void PostfixEventDispatch(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("event-dispatch", __instance, __originalMethod, __args);
	}

	private static void PostfixDamageApplyCandidate(object __instance, MethodBase __originalMethod, object[] __args)
	{
		LogTrace("damage-apply-candidate", __instance, __originalMethod, __args);
	}

	private static void LogTrace(string stage, object instance, MethodBase method, object[] args)
	{
		try
		{
			if (_logged >= LogCap)
				return;
			_logged++;
			Homm3DiagnosticBreadcrumbs.Enter("battle-event-law", method, stage);

			Plugin.LogSource?.LogInfo(
				"HoMM3 battle-event law diagnostic: "
				+ stage
				+ " method="
				+ FormatMethod(method)
				+ " instance="
				+ DescribeObjectContext(instance, stage)
				+ " args="
				+ DescribeArgs(args)
				+ " battleActionPlans="
				+ DescribeBattleActionPlans(stage, instance, args)
				+ " handlerGate="
				+ Homm3CustomLawHandlerTrace.Describe(
					ResolveBattleActionHandlerOwner(instance, args),
					Homm3CustomLawHandlerTrace.DamageTraining,
					Homm3CustomLawHandlerTrace.MeleeFormation,
					Homm3CustomLawHandlerTrace.RangedFormation)
				+ ". Diagnostic observation only.");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 battle-event law diagnostic log failed: " + ex.Message);
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static string DescribeBattleActionPlans(string stage, object instance, object[] args)
	{
		var owner = ResolveBattleActionHandlerOwner(instance, args);
		var failures = new List<string>(12);
		if (string.Equals(stage, "damage-apply-candidate", StringComparison.Ordinal)
		    && TryDescribeDamageApplyPlan(instance, args, out var applyPlan, failures))
			return applyPlan;
		if (TryDescribeBattleActionPlansForEvent("instance", owner, instance, out var direct, failures))
			return direct;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryDescribeBattleActionPlansForEvent("arg" + i, owner, args[i], out var fromArg, failures))
					return fromArg;
			}
		}
		return failures.Count == 0
			? "unresolved:no event candidates"
			: "unresolved:[" + string.Join(";", failures) + "]";
	}

	private static bool TryDescribeDamageApplyPlan(
		object receiverUnit,
		object[] args,
		out string description,
		List<string> failures)
	{
		description = null;
		if (Homm3CustomBattleEventLawRuntime.TryPlanCandidateTrainingDamageApplyEffect(
			    receiverUnit,
			    args,
			    out var damageInfo,
			    out var damageProfile,
			    out var damageContext,
			    out var damagePlan,
			    out var damageFail))
		{
			description = "damageApply=[damage={context={" + damageContext + "} event={" + damageInfo + "} profile={" + damageProfile + "} plan={" + damagePlan + "}}]";
			return true;
		}
		failures?.Add("damageApply=" + damageFail);
		return false;
	}
	private static bool TryDescribeBattleActionPlansForEvent(
		string label,
		object lawOwner,
		object eventCandidate,
		out string description,
		List<string> failures)
	{
		description = null;
		if (lawOwner == null)
		{
			failures?.Add(label + ".owner=null");
			return false;
		}
		if (eventCandidate == null)
		{
			failures?.Add(label + ".event=null");
			return false;
		}

		var plans = new List<string>(3);
		if (Homm3CustomBattleEventLawRuntime.TryPlanCandidateTrainingDamageEffect(
			    lawOwner,
			    eventCandidate,
			    out var damageInfo,
			    out var damageProfile,
			    out var damageContext,
			    out var damagePlan,
			    out var damageFail))
		{
			plans.Add("damage={context={" + damageContext + "} event={" + damageInfo + "} profile={" + damageProfile + "} plan={" + damagePlan + "}}");
		}
		else
		{
			failures?.Add(label + ".damage=" + damageFail);
		}

		if (Homm3CustomBattleEventLawRuntime.TryPlanCandidateMeleeFormationEffect(
			    lawOwner,
			    eventCandidate,
			    out var meleeInfo,
			    out var meleeProfile,
			    out var meleeContext,
			    out var meleePlan,
			    out var meleeFail))
		{
			plans.Add("meleeFormation={context={" + meleeContext + "} event={" + meleeInfo + "} profile={" + meleeProfile + "} plan={" + meleePlan + "}}");
		}
		else
		{
			failures?.Add(label + ".melee=" + meleeFail);
		}

		if (Homm3CustomBattleEventLawRuntime.TryPlanCandidateRangedFormationEffect(
			    lawOwner,
			    eventCandidate,
			    out var rangedInfo,
			    out var rangedProfile,
			    out var rangedContext,
			    out var rangedPlan,
			    out var rangedFail))
		{
			plans.Add("rangedFormation={context={" + rangedContext + "} event={" + rangedInfo + "} profile={" + rangedProfile + "} plan={" + rangedPlan + "}}");
		}
		else
		{
			failures?.Add(label + ".ranged=" + rangedFail);
		}

		if (plans.Count == 0)
			return false;
		description = label + "=[" + string.Join("|", plans) + "]";
		return true;
	}

	private static object ResolveBattleActionHandlerOwner(object instance, object[] args)
	{
		if (TryResolveBattleObjectHandlerOwner(instance, out var owner))
			return owner;
		if (args != null)
		{
			for (var i = 0; i < args.Length; i++)
			{
				if (TryResolveBattleObjectHandlerOwner(args[i], out owner))
					return owner;
			}
		}
		return null;
	}

	private static bool TryResolveBattleObjectHandlerOwner(object candidate, out object owner)
	{
		owner = null;
		if (candidate == null)
			return false;
		return Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(candidate, Homm3CustomFactionLawRuntime.HeroPrimaryStatTrainingIndex, out owner, out _)
		       || Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(candidate, Homm3CustomFactionLawRuntime.MeleeFormationIndex, out owner, out _)
		       || Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(candidate, Homm3CustomFactionLawRuntime.RangedFormationIndex, out owner, out _);
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

	private static string DescribeObjectContext(object value, string stage = null)
	{
		if (value == null)
			return "null";

		var type = value.GetType();
		var parts = new List<string>(MaxMemberSnapshots + 2)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		AddStructuredBattleContext(value, type, parts, stage);
		AddSimpleMemberSnapshots(value, type, parts);
		return "{" + string.Join("|", parts) + "}";
	}

	private static void AddStructuredBattleContext(object value, Type type, List<string> parts, string stage)
	{
		if (value == null || type == null)
			return;

		AddDirectBattleObjectContext(value, type, parts);
		AddAbilityLogicContext(value, type, parts);
		AddCastDealerContext(value, type, parts, "dealer");

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleEventTargetMembers, out var target) && target != null)
			parts.Add("event.target=" + DescribeBattleObject(target));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleEventRoundMembers, out var round) && round != null)
			parts.Add("event.round=" + FormatShortValue(round));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitPosChangedTargetHexMembers, out var targetHex) && targetHex != null)
			parts.Add("event.targetHex=" + DescribeHex(targetHex));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitStartedMovementPathMembers, out var path) && path != null)
			parts.Add("event.path=" + DescribeHexPath(path));

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.ObjectTookDamageCasterMembers, out var caster) && caster != null)
			parts.Add("damage.caster=" + DescribeBattleObject(caster));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.ObjectTookDamageReceiverMembers, out var receiver) && receiver != null)
			parts.Add("damage.receiver=" + DescribeBattleObject(receiver));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.ObjectTookDamageCastSourceMembers, out var source) && source != null)
			parts.Add("damage.source=" + DescribeObjectShallow(source));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.ObjectTookDamageDealerMembers, out var dealer) && dealer != null)
			parts.Add("damage.dealer=" + DescribeObjectShallow(dealer));
		foreach (var member in GameSymbols.BattleEventLaws.ObjectTookDamageValueMembers)
		{
			if (TryReadExactMember(value, type, new[] { member }, out var raw) && raw != null)
				parts.Add("damage." + member + "=" + FormatShortValue(raw));
		}

		foreach (var member in GameSymbols.BattleEventLaws.ObjectDestroyedMembers)
		{
			if (!TryReadExactMember(value, type, new[] { member }, out var raw) || raw == null)
				continue;
			if (member == "destroyedObject" || member == "caster")
				parts.Add("destroyed." + member + "=" + DescribeBattleObject(raw));
			else
				parts.Add("destroyed." + member + "=" + FormatShortValue(raw));
		}

		AddCastAbilityEventContext(value, type, parts);
		AddFormationProbeContext(value, type, parts, stage);
	}

	private static void AddCastAbilityEventContext(object value, Type type, List<string> parts)
	{
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityIdMembers, out var abilityId) && abilityId != null)
			parts.Add("cast.abilityID=" + DescribeAbilityId(abilityId));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityNameMembers, out var abilityName) && abilityName != null)
			parts.Add("cast.abilityName=" + FormatShortValue(abilityName));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityCasterMembers, out var caster) && caster != null)
			parts.Add("cast.caster=" + DescribeBattleObject(caster));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedObjectsMembers, out var attackedObjects) && attackedObjects != null)
			parts.Add("cast.attackedObjects=" + DescribeCollectionSummary(attackedObjects, DescribeBattleObject));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedHexesMembers, out var attackedHexes) && attackedHexes != null)
			parts.Add("cast.attackedHexes=" + DescribeCollectionSummary(attackedHexes, DescribeHex));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityImmuneObjectsMembers, out var immuneObjects) && immuneObjects != null)
			parts.Add("cast.immuneObjectsOut=" + DescribeCollectionSummary(immuneObjects, DescribeBattleObject));
	}

	private static string DescribeAbilityId(object abilityId)
	{
		if (abilityId == null)
			return "null";
		var type = abilityId.GetType();
		var parts = new List<string>(4)
		{
			"type=" + (type.FullName ?? type.Name)
		};
		if (TryReadExactMember(abilityId, type, GameSymbols.BattleEventLaws.AbilityIdTypeMembers, out var abilityType) && abilityType != null)
			parts.Add("abilityType=" + FormatShortValue(abilityType));
		if (TryReadExactMember(abilityId, type, GameSymbols.BattleEventLaws.AbilityIdIndexMembers, out var index) && index != null)
			parts.Add("indexInArray=" + FormatShortValue(index));
		return "{" + string.Join(";", parts) + "}";
	}

	private static void AddDirectBattleObjectContext(object value, Type type, List<string> parts)
	{
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out var side) && side != null)
			parts.Add("self.side=" + DescribeBattleSide(side));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex) && hex != null)
			parts.Add("self.hex=" + DescribeHex(hex));
		AddUnitConfigContext(value, type, parts);
	}

	private static string DescribeBattleObject(object value)
	{
		if (value == null)
			return "null";

		var type = value.GetType();
		var parts = new List<string>(8)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out var side) && side != null)
			parts.Add("side=" + DescribeBattleSide(side));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex) && hex != null)
			parts.Add("hex=" + DescribeHex(hex));
		AddUnitConfigContext(value, type, parts);
		parts.Add("classifierEvidence=" + Homm3UnitLawClassifier.DescribeEvidence(value));

		return "{" + string.Join(";", parts) + "}";
	}

	private static string DescribeBattleSide(object side)
	{
		if (side == null)
			return "null";

		var type = side.GetType();
		var parts = new List<string>(5)
		{
			"type=" + (type.FullName ?? type.Name)
		};

		var obfuscated = GameMember.ReadObfuscatedName(type);
		if (!string.IsNullOrEmpty(obfuscated))
			parts.Add("obf=" + obfuscated);

		var lawParts = new List<string>(8);
		foreach (var lawIndex in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices)
		{
			if (!Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLaw(side, lawIndex, out var state))
				continue;
			lawParts.Add("index=" + state.Index
				+ ",rank=" + state.Rank
				+ ",faction=" + state.FactionSid
				+ ",family=" + state.Family);
			if (lawParts.Count >= 8)
				break;
		}

		parts.Add("activeKnownCustomLaws=" + (lawParts.Count == 0 ? "none-or-unresolved" : "[" + string.Join(";", lawParts) + "]"));
		return "{" + string.Join(";", parts) + "}";
	}

	private static void AddUnitConfigContext(object value, Type type, List<string> parts)
	{
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitLogicConfigMembers, out var logicConfig) && logicConfig != null)
			parts.Add("logic=" + DescribeUnitConfig(logicConfig));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitViewConfigMembers, out var viewConfig) && viewConfig != null)
			parts.Add("view=" + DescribeUnitConfig(viewConfig));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.UnitDataMembers, out var unitData) && unitData != null)
			parts.Add("data=" + DescribeObjectShallow(unitData));
		parts.Add("classifierEvidence=" + Homm3UnitLawClassifier.DescribeEvidence(value));
	}

	private static string DescribeUnitConfig(object config)
	{
		if (config == null)
			return "null";
		var type = config.GetType();
		var parts = new List<string>(6)
		{
			"type=" + (type.FullName ?? type.Name)
		};
		if (TryReadExactMember(config, type, GameSymbols.BattleEventLaws.UnitConfigSidMembers, out var sid) && sid != null)
			parts.Add("sid=" + FormatShortValue(sid));
		if (TryReadExactMember(config, type, GameSymbols.BattleEventLaws.UnitConfigFactionMembers, out var faction) && faction != null)
			parts.Add("faction=" + FormatShortValue(faction));
		if (TryReadExactMember(config, type, GameSymbols.BattleEventLaws.UnitConfigTierMembers, out var tier) && tier != null)
			parts.Add("tier=" + FormatShortValue(tier));
		return "{" + string.Join(";", parts) + "}";
	}

	private static void AddAbilityLogicContext(object value, Type type, List<string> parts)
	{
		if (!TryReadAnyExactMember(value, type, GameSymbols.BattleEventLaws.AbilityLogicClassificationMembers, out var classification))
			return;

		var logicParts = new List<string>(12);
		foreach (var member in GameSymbols.BattleEventLaws.AbilityLogicClassificationMembers)
		{
			if (TryReadExactMember(value, type, new[] { member }, out var raw) && raw != null)
				logicParts.Add(member + "=" + FormatShortValue(raw));
		}
		if (logicParts.Count > 0)
			parts.Add("abilityLogic={" + string.Join(";", logicParts) + "}");

		foreach (var member in GameSymbols.BattleEventLaws.AbilityLogicDealerMembers)
		{
			if (TryReadExactMember(value, type, new[] { member }, out var dealer) && dealer != null)
				parts.Add("abilityLogic." + member + "=" + DescribeCastDealer(dealer));
		}
	}

	private static bool TryReadAnyExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (names == null)
			return false;
		foreach (var name in names)
		{
			if (TryReadExactMember(value, type, new[] { name }, out raw) && raw != null)
				return true;
		}
		return false;
	}

	private static void AddCastDealerContext(object value, Type type, List<string> parts, string label)
	{
		if (!TryReadAnyExactMember(value, type, GameSymbols.BattleEventLaws.CastDealerClassificationMembers, out _))
			return;
		parts.Add(label + "=" + DescribeCastDealer(value));
	}

	private static string DescribeCastDealer(object dealer)
	{
		if (dealer == null)
			return "null";
		var type = dealer.GetType();
		var parts = new List<string>(20)
		{
			"type=" + (type.FullName ?? type.Name)
		};
		foreach (var member in GameSymbols.BattleEventLaws.CastDealerClassificationMembers)
		{
			if (TryReadExactMember(dealer, type, new[] { member }, out var raw) && raw != null)
				parts.Add(member + "=" + FormatShortValue(raw));
		}
		return "{" + string.Join(";", parts) + "}";
	}

	private static void AddFormationProbeContext(object value, Type type, List<string> parts, string stage)
	{
		if (!TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityCasterMembers, out var caster) || caster == null)
			return;

		var hasCastEvidence =
			TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityIdMembers, out var abilityId) && abilityId != null
			|| TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedObjectsMembers, out var attackedObjects) && attackedObjects != null
			|| TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedHexesMembers, out var attackedHexes) && attackedHexes != null;
		if (!hasCastEvidence)
			return;

		var probe = new List<string>(16)
		{
			"stage=" + (stage ?? "?")
		};

		AddObservedCasterCastProbe(stage, caster, probe);

		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityNameMembers, out var abilityName) && abilityName != null)
			probe.Add("abilityName=" + FormatShortValue(abilityName));
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityIdMembers, out abilityId) && abilityId != null)
			probe.Add("abilityID=" + DescribeAbilityId(abilityId));

		var casterHex = TryGetBattleObjectHex(caster);
		if (casterHex != null)
			probe.Add("casterHex=" + DescribeHex(casterHex));

		var minDistance = int.MaxValue;
		var targetHexCount = 0;
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedHexesMembers, out var attackedHexesRaw) && attackedHexesRaw != null)
			AccumulateTargetHexDistances(casterHex, attackedHexesRaw, ref minDistance, ref targetHexCount);
		if (TryReadExactMember(value, type, GameSymbols.BattleEventLaws.CastAbilityAttackedObjectsMembers, out var attackedObjectsRaw) && attackedObjectsRaw != null)
			AccumulateTargetObjectHexDistances(casterHex, attackedObjectsRaw, ref minDistance, ref targetHexCount);

		if (targetHexCount > 0)
		{
			probe.Add("targetHexCount=" + targetHexCount);
			if (minDistance != int.MaxValue)
			{
				probe.Add("minHexDistanceCandidate=" + minDistance);
				probe.Add("adjacentCandidate=" + (minDistance == 1 ? "true" : "false"));
			}
		}
		else
		{
			probe.Add("targetHexCount=0-or-unreadable");
		}

		parts.Add("formationProbe={" + string.Join(";", probe) + "}");
	}

	private static void AddObservedCasterCastProbe(string stage, object caster, List<string> probe)
	{
		var casterKey = Homm3DirectStateIdentity.ResolveKeyOrZero(caster);
		lock (FormationProbeLock)
		{
			if (string.Equals(stage, "event-constructed", StringComparison.Ordinal))
			{
				_observedCastSequence++;
				ObservedCasterCastCounts.TryGetValue(casterKey, out var current);
				current++;
				ObservedCasterCastCounts[casterKey] = current;
				probe.Add("observedCastSequence=" + _observedCastSequence);
				probe.Add("observedCasterCastNumber=" + current);
				probe.Add("observedFirstForCaster=" + (current == 1 ? "true" : "false"));
				return;
			}

			ObservedCasterCastCounts.TryGetValue(casterKey, out var seen);
			probe.Add("observedCasterCastNumber=" + (seen == 0 ? "unseen-in-constructor" : seen.ToString()));
			probe.Add("observedFirstForCaster=" + (seen == 1 ? "true" : "false-or-unproven"));
		}
	}

	private static object TryGetBattleObjectHex(object battleObject)
	{
		if (battleObject == null)
			return null;
		var type = battleObject.GetType();
		return TryReadExactMember(battleObject, type, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex) ? hex : null;
	}

	private static void AccumulateTargetObjectHexDistances(object casterHex, object attackedObjects, ref int minDistance, ref int targetHexCount)
	{
		if (attackedObjects is not System.Collections.IEnumerable enumerable)
			return;

		foreach (var item in enumerable)
		{
			var hex = TryGetBattleObjectHex(item);
			if (hex == null)
				continue;
			AccumulateTargetHexDistance(casterHex, hex, ref minDistance, ref targetHexCount);
			if (targetHexCount > 128)
				return;
		}
	}

	private static void AccumulateTargetHexDistances(object casterHex, object attackedHexes, ref int minDistance, ref int targetHexCount)
	{
		if (attackedHexes is not System.Collections.IEnumerable enumerable)
			return;

		foreach (var hex in enumerable)
		{
			if (hex == null)
				continue;
			AccumulateTargetHexDistance(casterHex, hex, ref minDistance, ref targetHexCount);
			if (targetHexCount > 128)
				return;
		}
	}

	private static void AccumulateTargetHexDistance(object casterHex, object targetHex, ref int minDistance, ref int targetHexCount)
	{
		targetHexCount++;
		if (casterHex == null || targetHex == null)
			return;
		if (!TryReadHexCoordinates(casterHex, out var casterX, out var casterZ))
			return;
		if (!TryReadHexCoordinates(targetHex, out var targetX, out var targetZ))
			return;
		var dx = targetX - casterX;
		var dz = targetZ - casterZ;
		var distance = (Math.Abs(dx) + Math.Abs(dz) + Math.Abs(dx + dz)) / 2;
		if (distance < minDistance)
			minDistance = distance;
	}

	private static bool TryReadHexCoordinates(object hex, out int x, out int z)
	{
		x = 0;
		z = 0;
		if (hex == null)
			return false;
		var type = hex.GetType();
		if (!TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexXMembers, out var rawX) || rawX == null)
			return false;
		if (!TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexZMembers, out var rawZ) || rawZ == null)
			return false;
		try
		{
			x = Convert.ToInt32(rawX);
			z = Convert.ToInt32(rawZ);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static string DescribeHex(object hex)
	{
		if (hex == null)
			return "null";

		var type = hex.GetType();
		var parts = new List<string>(8)
		{
			"type=" + (type.FullName ?? type.Name)
		};
		if (TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexIndexMembers, out var index) && index != null)
			parts.Add("index=" + FormatShortValue(index));
		if (TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexXMembers, out var x) && x != null)
			parts.Add("x=" + FormatShortValue(x));
		if (TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexZMembers, out var z) && z != null)
			parts.Add("z=" + FormatShortValue(z));
		if (TryReadExactMember(hex, type, GameSymbols.BattleEventLaws.HexOccupantMembers, out var occupant) && occupant != null)
			parts.Add("occupant=" + DescribeObjectShallow(occupant));
		return "{" + string.Join(";", parts) + "}";
	}

	private static string DescribeHexPath(object path)
	{
		if (path == null)
			return "null";
		if (path is not System.Collections.IEnumerable enumerable)
			return DescribeObjectShallow(path);

		var count = 0;
		object first = null;
		object last = null;
		foreach (var item in enumerable)
		{
			if (count == 0)
				first = item;
			last = item;
			count++;
			if (count > 128)
				break;
		}
		return "{len=" + count + ";first=" + DescribeHex(first) + ";last=" + DescribeHex(last) + "}";
	}

	private static string DescribeCollectionSummary(object collection, Func<object, string> describeItem)
	{
		if (collection == null)
			return "null";
		if (collection is not System.Collections.IEnumerable enumerable)
			return DescribeObjectShallow(collection);

		var count = 0;
		object first = null;
		object last = null;
		foreach (var item in enumerable)
		{
			if (count == 0)
				first = item;
			last = item;
			count++;
			if (count > 128)
				break;
		}
		return "{len=" + count + ";first=" + describeItem(first) + ";last=" + describeItem(last) + "}";
	}

	private static string DescribeObjectShallow(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		var obfuscated = GameMember.ReadObfuscatedName(type);
		return "{type=" + (type.FullName ?? type.Name) + (string.IsNullOrEmpty(obfuscated) ? string.Empty : ";obf=" + obfuscated) + "}";
	}

	private static bool TryReadExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (value == null || type == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (field != null)
				{
					raw = field.GetValue(value);
					return true;
				}
			}
			catch { }
			try
			{
				var property = type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
				if (property != null && property.GetIndexParameters().Length == 0)
				{
					raw = property.GetValue(value, null);
					return true;
				}
			}
			catch { }
			try
			{
				var method = type.GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null);
				if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
				{
					raw = method.Invoke(value, null);
					return true;
				}
			}
			catch { }
		}
		return false;
	}

	private static string FormatShortValue(object raw)
	{
		if (raw == null)
			return "null";
		var text = raw.ToString();
		if (string.IsNullOrEmpty(text))
			text = "(empty)";
		if (text.Length > 80)
			text = text.Substring(0, 80) + "...";
		return text;
	}

	private static void AddSimpleMemberSnapshots(object value, Type type, List<string> parts)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		for (var current = type; current != null && parts.Count < MaxMemberSnapshots; current = current.BaseType)
		{
			foreach (var field in current.GetFields(flags))
			{
				if (field.IsStatic)
					continue;
				if (!TryFormatSimpleValue(field.FieldType, () => field.GetValue(value), out var formatted))
					continue;
				parts.Add(field.Name + "=" + formatted);
				if (parts.Count >= MaxMemberSnapshots)
					return;
			}
		}
	}

	private static bool TryFormatSimpleValue(Type valueType, Func<object> read, out string formatted)
	{
		formatted = null;
		try
		{
			var raw = read();
			if (raw == null)
			{
				formatted = "null";
				return true;
			}

			var runtimeType = raw.GetType();
			if (!IsSimpleType(valueType) && !IsSimpleType(runtimeType))
				return false;

			var text = raw.ToString();
			if (string.IsNullOrEmpty(text))
				text = "(empty)";
			if (text.Length > 80)
				text = text.Substring(0, 80) + "...";
			formatted = text;
			return true;
		}
		catch
		{
			return false;
		}
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
}
