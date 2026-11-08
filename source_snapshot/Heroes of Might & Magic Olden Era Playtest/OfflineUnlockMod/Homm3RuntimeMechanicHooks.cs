using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Sole native-hook owner for executable runtime mechanics. All required
/// surfaces are preflighted before patching; cleanup is registered before
/// committed damage and the registry is published only after both succeed.
/// </summary>
internal static class Homm3RuntimeMechanicHooks
{
	private static bool _registered;
	private static MethodInfo _damageTarget;
	private static MethodInfo _unitInitTarget;
	private static MethodInfo _unitInitPostfix;
	private static MethodInfo _resultTarget;
	private static MethodInfo _damagePrefix;
	private static MethodInfo _damagePostfix;
	private static MethodInfo _cleanupPrefix;
	private static readonly List<TypedHookRegistration> TypedHooks = new();
	private static readonly Dictionary<MethodBase, Homm3DirectStateHookSurface> TypedDispatchSurfaces = new();
	[ThreadStatic] private static bool _redirectingDamage;
	[ThreadStatic] private static Homm3DirectStateIngressOutcome _damageIngress;
	[ThreadStatic] private static bool _damageIngressReady;
	private static string _activationStatus = "NOT_ATTEMPTED";

	private sealed class TypedHookRegistration
	{
		internal MethodBase Target;
		internal MethodInfo Patch;
	}

	internal static string ActivationStatus => _activationStatus;

	internal static bool TryRegisterSharedBattleResult(Harmony harmony, ManualLogSource log)
	{
		if (_resultTarget != null && _cleanupPrefix != null)
			return true;
		if (harmony == null)
			return false;
		var target = Homm3BattleResultSurface.ResolveApplyBattleResultMethod();
		var prefix = AccessTools.Method(
			typeof(Homm3RuntimeMechanicHooks),
			nameof(PrefixBattleResultCleanup));
		string conflict = null;
		string reason = null;
		if (target == null
		    || prefix == null
		    || !Homm3BattleResultSurface.HasBattleResultAlreadyAppliedSurface(target)
		    || !Homm3DirectStateConflictAudit.TryAuditTarget(target, "battleResult", out conflict)
		    || !GameMember.IsHarmonyPatchCompatible(target, prefix, out reason))
		{
			log?.LogWarning(
				"HoMM3 shared battle-result hook failed closed: "
				+ (conflict ?? reason ?? "exact target, duplicate guard, or prefix missing"));
			return false;
		}
		harmony.Patch(
			target,
			prefix: new HarmonyMethod(prefix) { priority = Priority.Last });
		_resultTarget = target;
		_cleanupPrefix = prefix;
		log?.LogInfo("HoMM3 shared battle-result hook registered by the runtime-mechanics hook owner.");
		return true;
	}

	internal static bool TryRegisterSharedUnitInit(Harmony harmony, ManualLogSource log)
	{
		if (Homm3BattleUnitLawOwnerRegistry.IsRegistered)
			return true;
		if (harmony == null)
			return false;
		var target = Homm3BattleUnitInitSurface.FindUnitInitMethod(ResolveUnitType());
		var postfix = Homm3BattleUnitLawOwnerRegistry.ResolveUnitInitPostfix();
		string conflict = null;
		string reason = null;
		if (target == null
		    || postfix == null
		    || !Homm3DirectStateConflictAudit.TryAuditTarget(target, "unitInit", out conflict)
		    || !GameMember.IsHarmonyPatchCompatible(target, postfix, out reason))
		{
			log?.LogWarning(
				"HoMM3 shared Unit.Init registry failed closed: "
				+ (conflict ?? reason ?? "exact target or postfix missing"));
			return false;
		}
		harmony.Patch(
			target,
			postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		_unitInitTarget = target;
		_unitInitPostfix = postfix;
		Homm3BattleUnitLawOwnerRegistry.MarkRegistered();
		log?.LogInfo("HoMM3 shared Unit.Init registry registered by the runtime-mechanics hook owner.");
		return true;
	}

	internal static bool TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return true;
		if (harmony == null || !Homm3RuntimeMechanicRegistry.HasPreparedMechanics)
		{
			_activationStatus = "INACTIVE_NO_SELECTED_MECHANICS";
			return false;
		}

		MethodInfo damageTarget = null;
		MethodInfo unitInitTarget = null;
		MethodInfo unitInitPostfix = null;
		MethodInfo resultTarget = null;
		MethodInfo damagePrefix = null;
		MethodInfo damagePostfix = null;
		MethodInfo cleanupPrefix = null;
		var unitInitRegisteredHere = false;
		var resultRegisteredHere = false;
		try
		{
			if (!Homm3RuntimeMechanicFixtureHarness.TryValidateSourceFixtures(out var fixtureFailure))
				throw new InvalidOperationException("shared fixture harness rejected source contract: " + fixtureFailure);
			var requiredSurfaces = Homm3RuntimeMechanicRegistry.GetPreparedHookSurfaces();
			if (requiredSurfaces == Homm3DirectStateHookSurface.None)
				throw new InvalidOperationException("selected mechanics declare no hook surfaces");
			for (var adapterValue = 1; adapterValue <= Homm3DirectStateAdapterManifest.Count; adapterValue++)
			{
				var adapterId = (Homm3DirectStateAdapterId)adapterValue;
				if (Homm3RuntimeMechanicRegistry.IsAdapterPrepared(adapterId)
				    && !NativeCombatWriteGateway.TryPrepareAdapter(adapterId, out var adapterFailure))
					throw new InvalidOperationException(adapterId + " native-write preflight failed: " + adapterFailure);
			}
			if (Homm3RuntimeMechanicRegistry.IsAdapterPrepared(Homm3DirectStateAdapterId.Movement))
			{
				if (!NativeCombatWriteGateway.PreparedMovementSurface)
					throw new InvalidOperationException("prepared movement direct-hex surface is missing");
				// Immobility is enforced in Homm3DirectStateAdapters.TryMove; the old
				// BattleLogic Unit_Hex commit Harmony prefix is retired because that
				// native method does not publish unit get_Hex (live Golden Era proof).
			}

			var unitType = ResolveUnitType();
			unitInitTarget = (requiredSurfaces & Homm3DirectStateHookSurface.UnitInit) != 0
				? Homm3BattleUnitInitSurface.FindUnitInitMethod(unitType)
				: null;
			unitInitPostfix = unitInitTarget == null
				? null
				: Homm3BattleUnitLawOwnerRegistry.ResolveUnitInitPostfix();
			var needsDamage = (requiredSurfaces
			                   & (Homm3DirectStateHookSurface.DamageApplying
			                      | Homm3DirectStateHookSurface.DamageApplied)) != 0;
			damageTarget = needsDamage ? ResolveDamageMethod(unitType) : null;
			resultTarget = _resultTarget ?? Homm3BattleResultSurface.ResolveApplyBattleResultMethod();
			// DamageApplied postfixes read Harmony __state. Always register the typed prefix
			// whenever a postfix is required so __state is initialized true; otherwise a
			// DamageApplied-only adapter (e.g. movement Bellwether) silently no-ops.
			var needsDamagePostfix = (requiredSurfaces & Homm3DirectStateHookSurface.DamageApplied) != 0;
			var needsDamagePrefix = needsDamagePostfix
			                        || (requiredSurfaces & Homm3DirectStateHookSurface.DamageApplying) != 0;
			damagePrefix = needsDamagePrefix
				? AccessTools.Method(typeof(Homm3RuntimeMechanicHooks), nameof(PrefixDamageApplying))
				: null;
			damagePostfix = needsDamagePostfix
				? AccessTools.Method(typeof(Homm3RuntimeMechanicHooks), nameof(PostfixDamageApplied))
				: null;
			cleanupPrefix = _cleanupPrefix
			                ?? AccessTools.Method(typeof(Homm3RuntimeMechanicHooks), nameof(PrefixBattleResultCleanup));

			if ((requiredSurfaces & Homm3DirectStateHookSurface.UnitInit) != 0 && unitInitTarget == null)
				throw new InvalidOperationException("exact Unit.Init surface not found");
			if (unitInitTarget != null
			    && !Homm3DirectStateConflictAudit.TryAuditTarget(unitInitTarget, "unitInit", out var initConflict))
				throw new InvalidOperationException(initConflict);
			if (unitInitTarget != null
			    && !GameMember.IsHarmonyPatchCompatible(unitInitTarget, unitInitPostfix, out var initReason))
				throw new InvalidOperationException("Unit.Init postfix incompatible: " + initReason);
			if (needsDamage && damageTarget == null)
				throw new InvalidOperationException("exact committed-damage surface not found");
			if (resultTarget == null)
				throw new InvalidOperationException("exact battle-result surface not found");
			if (!Homm3BattleResultSurface.HasBattleResultAlreadyAppliedSurface(resultTarget))
				throw new InvalidOperationException("battle-result duplicate guard surface not found");
			if (!Homm3DirectStateConflictAudit.TryAuditTarget(resultTarget, "battleResult", out var resultConflict))
				throw new InvalidOperationException(resultConflict);
			if (damageTarget != null
			    && !Homm3DirectStateConflictAudit.TryAuditTarget(damageTarget, "committedDamage", out var damageConflict))
				throw new InvalidOperationException(damageConflict);
			if (damagePrefix != null
			    && !ValidateDamagePatchCompatibility(damageTarget, damagePrefix, out var damageReason))
				throw new InvalidOperationException("typed damage prefix incompatible: " + damageReason);
			if (damagePostfix != null
			    && !ValidateDamagePostfixCompatibility(damageTarget, damagePostfix, out var postfixReason))
				throw new InvalidOperationException("typed damage postfix incompatible: " + postfixReason);
			if (!GameMember.IsHarmonyPatchCompatible(resultTarget, cleanupPrefix, out var cleanupReason))
				throw new InvalidOperationException("cleanup prefix incompatible: " + cleanupReason);

			if (unitInitTarget != null)
			{
				unitInitRegisteredHere = !Homm3BattleUnitLawOwnerRegistry.IsRegistered;
				if (!TryRegisterSharedUnitInit(harmony, log))
					throw new InvalidOperationException("shared Unit.Init registry did not register");
			}

			resultRegisteredHere = _resultTarget == null;
			if (!TryRegisterSharedBattleResult(harmony, log))
				throw new InvalidOperationException("shared battle-result hook did not register");
			resultTarget = _resultTarget;
			cleanupPrefix = _cleanupPrefix;

			if (damageTarget != null)
			{
				harmony.Patch(
					damageTarget,
					prefix: damagePrefix == null ? null : new HarmonyMethod(damagePrefix) { priority = Priority.First },
					postfix: damagePostfix == null ? null : new HarmonyMethod(damagePostfix) { priority = Priority.Last });
				_damageTarget = damageTarget;
				_damagePrefix = damagePrefix;
				_damagePostfix = damagePostfix;
				if (!Homm3DirectStateConflictAudit.TryReadbackDamageSurfaceOwnership(
					    damageTarget,
					    damagePrefix,
					    damagePostfix,
					    requirePrefix: damagePrefix != null,
					    requirePostfix: damagePostfix != null,
					    out var damageReadbackFailure))
					throw new InvalidOperationException(damageReadbackFailure);
			}

			var typedHookCount = RegisterTypedEventHooks(harmony, requiredSurfaces, log);

			if (!Homm3RuntimeMechanicRegistry.PublishPreparedSnapshot())
				throw new InvalidOperationException("prepared registry snapshot was not publishable");

			_registered = true;
			Homm3RuntimeMechanicFixtureHarness.RecordDistinctHookCount(
				1
				+ (damageTarget == null ? 0 : 1)
				+ (unitInitTarget == null ? 0 : 1)
				+ typedHookCount);
			if (Homm3DiagnosticFlags.IsEnabled(Homm3RuntimeMechanicFixtureHarness.AggregateStressFlag))
			{
				if (!Homm3RuntimeMechanicFixtureHarness.TryRunAggregateStress(
					    out var aggregateReport,
					    out var aggregateFailure))
					throw new InvalidOperationException("aggregate direct-state stress failed: " + aggregateFailure);
				log?.LogWarning("HoMM3 direct-state aggregate stress PASS " + aggregateReport);
			}
			_activationStatus = "ACTIVE damage=" + FormatMethod(damageTarget)
			                    + " typedEvents=" + typedHookCount
			                    + " result=" + FormatMethod(resultTarget);
			log?.LogWarning(
				"HoMM3 runtime-mechanics diagnostic hooks active: "
				+ _activationStatus
				+ ". Gameplay fixtures are opt-in and runtime proof remains pending.");
			return true;
		}
		catch (Exception ex)
		{
			UnpatchOwned(harmony, damageTarget, damagePrefix);
			UnpatchOwned(harmony, damageTarget, damagePostfix);
			if (unitInitRegisteredHere)
				UnpatchOwned(harmony, unitInitTarget, unitInitPostfix);
			if (resultRegisteredHere)
				UnpatchOwned(harmony, resultTarget, cleanupPrefix);
			UnpatchTypedEventHooks(harmony);
			_damageTarget = null;
			_unitInitTarget = null;
			_unitInitPostfix = null;
			if (unitInitRegisteredHere)
				Homm3BattleUnitLawOwnerRegistry.MarkUnregistered();
			if (resultRegisteredHere)
				_resultTarget = null;
			_damagePrefix = null;
			_damagePostfix = null;
			if (resultRegisteredHere)
				_cleanupPrefix = null;
			_registered = false;
			_activationStatus = "FAILED_CLOSED: " + ex.Message;
			Homm3RuntimeMechanicRegistry.DisablePreparedSnapshot(_activationStatus);
			log?.LogError("HoMM3 runtime-mechanics activation failed closed: " + ex.Message);
			return false;
		}
	}

	private static bool PrefixDamageApplying(
		object __instance,
		object __0,
		object __1,
		object __2,
		ref int __3,
		object __4,
		bool __5,
		float __6,
		bool __7,
		MethodBase __originalMethod,
		out bool __state)
	{
		__state = true;
		_damageIngressReady = false;
		try
		{
			var ingress = Homm3BattleEventNativeAdapter.NormalizeDamageApplyInvocation(
				Homm3DirectStateHookSurface.DamageApplying,
				__instance,
				__0,
				__1,
				__2,
				__3,
				__4,
				__5,
				__7);
			_damageIngress = ingress;
			_damageIngressReady = true;
			if (!ingress.IsAccepted)
			{
				Homm3DirectStateIngressDispatcher.CapLogOutcome(ingress);
				return true;
			}
			var caster = ingress.Damage.Caster ?? __0;
			if (!_redirectingDamage
			    && Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.NestedDamage)
			    && Homm3BattleLocalLawState.TryGetDirectDamageRedirect(__instance, out var redirectTarget))
			{
				_redirectingDamage = true;
				var redirected = NativeCombatWriteGateway.TryInvokeRedirectedDamage(
					__originalMethod as MethodInfo,
					redirectTarget,
					caster,
					__1,
					__2,
					__3,
					__4,
					__5,
					__6,
					__7,
					out var redirectFailure);
				_redirectingDamage = false;
				__state = false;
				_damageIngressReady = false;
				if (!redirected)
					Homm3RuntimeMechanicFixtureHarness.RecordFailure(redirectFailure);
				return false;
			}
			if (!CustomCombatEffectManager.TryPrepareDamageApplying(
				    caster,
				    __instance,
				    __3,
				    out var application,
				    out var mutation))
				return true;
			if (!Homm3BattleLocalLawState.TryCommitRuntimeMechanicDamage(
				    caster,
				    application,
				    mutation,
				    ref __3))
				return true;
			CustomCombatEffectManager.LogAppliedDamage(application, mutation);
		}
		catch (Exception ex)
		{
			_redirectingDamage = false;
			_damageIngressReady = false;
			Plugin.LogSource?.LogWarning("HoMM3 runtime-mechanics damage prefix failed closed: " + ex.Message);
		}
		return true;
	}

	private static void PostfixDamageApplied(
		object __instance,
		object __0,
		object __1,
		object __2,
		int __3,
		object __4,
		bool __5,
		float __6,
		bool __7,
		MethodBase __originalMethod,
		bool __state)
	{
		try
		{
			if (!__state)
				return;
			Homm3DirectStateIngressOutcome ingress;
			if (_damageIngressReady)
			{
				ingress = _damageIngress;
				if (ingress.IsAccepted && ingress.Damage.Damage != __3)
				{
					ingress = Homm3DirectStateIngressOutcome.AcceptDamage(
						Homm3DirectStateHookSurface.DamageApplied,
						new Homm3BattleEventNativeAdapter.DamageEventInfo(
							ingress.Damage.Caster,
							ingress.Damage.Receiver,
							ingress.Damage.CastSource,
							ingress.Damage.Dealer,
							__3,
							ingress.Damage.StacksDestroyed,
							ingress.Damage.ImmuneToDamage,
							ingress.Damage.Cumulative,
							ingress.Damage.FromMech),
						ingress.AbilityName);
				}
				else if (ingress.IsAccepted)
				{
					ingress = Homm3DirectStateIngressOutcome.AcceptDamage(
						Homm3DirectStateHookSurface.DamageApplied,
						ingress.Damage,
						ingress.AbilityName);
				}
			}
			else
			{
				ingress = Homm3BattleEventNativeAdapter.NormalizeDamageApplyInvocation(
					Homm3DirectStateHookSurface.DamageApplied,
					__instance,
					__0,
					__1,
					__2,
					__3,
					__4,
					__5,
					__7);
			}
			Homm3DirectStateIngressDispatcher.DispatchDamageApplied(
				in ingress,
				__originalMethod as MethodInfo);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 direct-state damage postfix failed closed: " + ex.Message);
		}
		finally
		{
			_damageIngressReady = false;
			_damageIngress = default;
		}
	}

	private static int RegisterTypedEventHooks(
		Harmony harmony,
		Homm3DirectStateHookSurface requiredSurfaces,
		ManualLogSource log)
	{
		var typedSurfaces = new[]
		{
			Homm3DirectStateHookSurface.CastCommitted,
			Homm3DirectStateHookSurface.MovementCommitted,
			Homm3DirectStateHookSurface.ObjectSpawned,
			Homm3DirectStateHookSurface.ObjectDestroyed,
			Homm3DirectStateHookSurface.RoundStart,
			Homm3DirectStateHookSurface.RoundEnd,
			Homm3DirectStateHookSurface.ActionStart,
			Homm3DirectStateHookSurface.ActionEnd,
		};
		var count = 0;
		var seenTargets = new HashSet<MethodBase>();
		var postfix = AccessTools.Method(typeof(Homm3RuntimeMechanicHooks), nameof(PostfixTypedEventConstructed));
		var dispatchPostfix = AccessTools.Method(
			typeof(Homm3RuntimeMechanicHooks),
			nameof(PostfixBattleEventDispatched));
		for (var i = 0; i < typedSurfaces.Length; i++)
		{
			var surface = typedSurfaces[i];
			if ((requiredSurfaces & surface) == 0)
				continue;
			if (IsBattleEventDispatcherSurface(surface))
			{
				var dispatcher = ResolveBattleEventDispatcher(surface);
				if (dispatcher == null)
					throw new InvalidOperationException(surface + " exact battle-event dispatcher was not found");
				if (!seenTargets.Add(dispatcher))
					throw new InvalidOperationException(surface + " resolved to a duplicate battle-event dispatcher");
				if (!Homm3DirectStateConflictAudit.TryAuditTarget(dispatcher, surface.ToString(), out var dispatchConflict))
					throw new InvalidOperationException(dispatchConflict);
				if (!GameMember.IsHarmonyPatchCompatible(dispatcher, dispatchPostfix, out var dispatchReason))
					throw new InvalidOperationException(surface + " dispatcher postfix incompatible: " + dispatchReason);
				harmony.Patch(
					dispatcher,
					postfix: new HarmonyMethod(dispatchPostfix) { priority = Priority.Last });
				TypedHooks.Add(new TypedHookRegistration { Target = dispatcher, Patch = dispatchPostfix });
				TypedDispatchSurfaces[dispatcher] = surface;
				count++;
				continue;
			}
			if (!Homm3BattleEventNativeAdapter.TryGetTypedEventType(surface, out var eventType, out var typeFailure))
				throw new InvalidOperationException(surface + " event type preflight failed: " + typeFailure);
			var constructors = eventType.GetConstructors(
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (constructors.Length == 0)
				throw new InvalidOperationException(surface + " exact event type has no constructors");
			for (var constructorIndex = 0; constructorIndex < constructors.Length; constructorIndex++)
			{
				var constructor = constructors[constructorIndex];
				if (!seenTargets.Add(constructor))
					continue;
				if (!Homm3DirectStateConflictAudit.TryAuditTarget(constructor, surface.ToString(), out var conflict))
					throw new InvalidOperationException(conflict);
				if (!ValidateConstructorPatch(postfix, out var reason))
					throw new InvalidOperationException(surface + " constructor postfix incompatible: " + reason);
				harmony.Patch(constructor, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
				TypedHooks.Add(new TypedHookRegistration { Target = constructor, Patch = postfix });
				count++;
			}
		}

		log?.LogInfo("HoMM3 direct-state exact typed event constructor hooks=" + count + ".");
		return count;
	}

	private static void UnpatchTypedEventHooks(Harmony harmony)
	{
		for (var i = TypedHooks.Count - 1; i >= 0; i--)
		{
			var registration = TypedHooks[i];
			UnpatchOwned(harmony, registration.Target, registration.Patch);
		}
		TypedHooks.Clear();
		TypedDispatchSurfaces.Clear();
	}

	private static void PostfixBattleEventDispatched(object __1, MethodBase __originalMethod)
	{
		try
		{
			if (__1 == null
			    || __originalMethod == null
			    || !TypedDispatchSurfaces.TryGetValue(__originalMethod, out var surface))
				return;
			Homm3DirectStateIngressDispatcher.DispatchBattleEventSurface(surface, __1);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 direct-state battle-event dispatcher failed closed: " + ex.Message);
		}
	}

	private static void PostfixTypedEventConstructed(object __instance)
	{
		try
		{
			Homm3DirectStateIngressDispatcher.DispatchTypedEventConstructed(__instance);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 direct-state typed event observer failed closed: " + ex.Message);
		}
	}

	internal static void ObserveCastCommitted(
		object eventArgs,
		Homm3BattleEventNativeAdapter.CastAbilityEventInfo cast)
	{
		if (cast.Caster == null)
			return;
		var classification = Homm3UnitLawClassifier.Classify(cast.Caster);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out _)
		    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(classification.Sid, out var indexes))
			return;
		var scope = ResolveBattleScope(cast.Caster) ?? cast.Caster;
		var correlationToken = Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs).ToString(System.Globalization.CultureInfo.InvariantCulture)
		                       + ":" + cast.RoundNumber.ToString(System.Globalization.CultureInfo.InvariantCulture);

		// Collect matching castCommitted mechanics first so one cast is one compound attempt.
		var matched = new List<Homm3CompiledRuntimeMechanic>(indexes.Length);
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || !string.Equals(mechanic.Trigger, "castCommitted", StringComparison.Ordinal))
				continue;
			if (!Homm3RuntimeMechanicRegistry.MatchesCastAbility(mechanic.AbilityName, cast.AbilityName))
				continue;
			matched.Add(mechanic);
		}
		if (matched.Count == 0)
			return;

		// One cast event = one root correlation. Nested adapter commits stay reversible
		// until this envelope hard-accepts at depth 0.
		var lead = matched[0];
		if (!BattleCombatTransactionManager.TryBegin(
			    scope,
			    lead.AdapterId,
			    lead.Operation,
			    reserveJournal: Math.Max(8, matched.Count * 4),
			    reserveRootWork: Math.Max(2, matched.Count + 1),
			    out var envelope,
			    out var envelopeFailure))
		{
			Homm3RuntimeMechanicFixtureHarness.RecordFailure(envelopeFailure);
			return;
		}
		using (envelope)
		{
			for (var i = 0; i < matched.Count; i++)
			{
				if (TryApplyCastCommittedMechanic(scope, cast, correlationToken, matched[i], out var failure))
					continue;
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(
					failure ?? ("castCommitted mechanic failed: " + matched[i].MechanicId));
				// Envelope mark is 0; rollback restores every nested journal entry on this root
				// and drops pending children so the cast cannot partially apply.
				envelope.Rollback(out _);
				return;
			}
			if (!envelope.Commit(out var commitFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(commitFailure);
		}
	}

	private static bool TryApplyCastCommittedMechanic(
		object scope,
		Homm3BattleEventNativeAdapter.CastAbilityEventInfo cast,
		string correlationToken,
		Homm3CompiledRuntimeMechanic mechanic,
		out string failReason)
	{
		failReason = null;
		if (mechanic.Operation == Homm3DirectStateOperation.CastChain)
		{
			return Homm3DirectStateAdapters.TryRecordCastCommit(
				scope,
				cast.Caster,
				correlationToken,
				out failReason);
		}
		if (mechanic.Operation == Homm3DirectStateOperation.FocusGrant
		    || mechanic.Operation == Homm3DirectStateOperation.FocusSpend
		    || mechanic.Operation == Homm3DirectStateOperation.FocusSet)
		{
			if (!TryReadObject(cast.Caster, GameSymbols.BattleEventLaws.CasterBattleSideMembers, out var side))
			{
				failReason = "castCommitted Focus requires caster battle side";
				return false;
			}
			return Homm3DirectStateAdapters.TryMutateFocus(
				scope,
				side,
				mechanic.Operation,
				mechanic.Value,
				out _,
				out _,
				out failReason);
		}
		if (mechanic.AdapterId == Homm3DirectStateAdapterId.Cooldown)
		{
			if (!NativeCombatWriteGateway.TryResolveUnitAbility(
				    cast.Caster,
				    cast.AbilityType,
				    cast.AbilityIndex,
				    out var ability,
				    out failReason))
				return false;
			return Homm3DirectStateAdapters.TryMutateCooldown(
				scope,
				ability,
				mechanic.Operation,
				mechanic.Value,
				out _,
				out _,
				out failReason);
		}
		if (mechanic.AdapterId == Homm3DirectStateAdapterId.Status)
		{
			var request = new Homm3DirectStatusRequest(
				mechanic.StringValue,
				1,
				Math.Max(1, mechanic.Value),
				mechanic.SecondaryValue,
				mechanic.Operation == Homm3DirectStateOperation.StatusRefresh,
				cast.RoundNumber);
			return mechanic.Operation == Homm3DirectStateOperation.StatusRemove
				? Homm3DirectStateAdapters.TryRemoveStatus(scope, cast.Caster, mechanic.StringValue, out failReason)
				: Homm3DirectStateAdapters.TryApplyStatus(scope, cast.Caster, cast.Caster, request, out failReason);
		}
		if (mechanic.Operation == Homm3DirectStateOperation.TrapSpawn)
		{
			if (!TryFirstEnumerableValue(cast.AttackedHexes, out var targetHex)
			    || !TryReadInt(targetHex, GameSymbols.BattleEventLaws.HexIndexMembers, out var targetHexIndex)
			    || !TryReadObject(cast.Caster, GameSymbols.BattleEventLaws.CasterBattleSideMembers, out var trapOwnerSide))
			{
				failReason = "castCommitted TrapSpawn requires attacked hex index and caster side";
				return false;
			}
			return Homm3DirectStateAdapters.TryCreateTrap(
				scope,
				trapOwnerSide,
				targetHexIndex,
				mechanic.StringValue,
				out _,
				out failReason);
		}
		if (mechanic.Operation == Homm3DirectStateOperation.SummonCreate)
		{
			// Unit.Init plant is incomplete (lifecycle.spawn.init_v1). Refuse silent no-op.
			failReason =
				"SummonCreate refused for mechanic '"
				+ mechanic.MechanicId
				+ "': Unit.Init spawn plant is incomplete; refusing silent no-op";
			return false;
		}
		if (mechanic.Operation == Homm3DirectStateOperation.CorpseConsume)
		{
			failReason =
				"CorpseConsume has no castCommitted handler for mechanic '" + mechanic.MechanicId + "'";
			return false;
		}
		failReason =
			"castCommitted operation "
			+ mechanic.Operation
			+ " is not wired for mechanic '"
			+ mechanic.MechanicId
			+ "'";
		return false;
	}

	internal static void ObserveSpawned(Homm3BattleEventNativeAdapter.SpawnedEventInfo spawned)
	{
		if (spawned.SpawnedObject != null)
			Homm3RuntimeMechanicFixtureHarness.RecordDirtyUnit(spawned.SpawnedObject);
	}

	internal static void ObserveUnitInitialized(object unit, object ownerSide)
	{
		if (unit == null || !Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Aura))
			return;
		var classification = Homm3UnitLawClassifier.Classify(unit);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out _)
		    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(classification.Sid, out var indexes))
			return;
		var scope = ResolveBattleScope(unit) ?? unit;
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || !string.Equals(mechanic.Trigger, "unitInit", StringComparison.Ordinal)
			    || mechanic.Operation != Homm3DirectStateOperation.AuraDefine)
				continue;
			if (!Homm3DirectStateAdapters.TryDefineAura(
				    scope,
				    unit,
				    ownerSide,
				    Math.Max(0, mechanic.Value),
				    mechanic.StringValue,
				    out _,
				    out var auraFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(auraFailure);
		}
		RefreshAuras();
	}

	internal static void RefreshAuras()
	{
		if (!Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Aura))
		{
			Homm3BattleLocalLawState.ClearDirectDirtyIdentities();
			return;
		}
		var auras = Homm3BattleLocalLawState.SnapshotDirectAuras(32);
		if (auras.Count == 0)
		{
			Homm3BattleLocalLawState.ClearDirectDirtyIdentities();
			return;
		}
		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		for (var auraIndex = 0; auraIndex < auras.Count; auraIndex++)
		{
			var aura = auras[auraIndex];
			if (!TryReadObject(aura.Source, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var sourceHex)
			    || !TryReadInt(sourceHex, GameSymbols.BattleEventLaws.HexXMembers, out var sourceX)
			    || !TryReadInt(sourceHex, GameSymbols.BattleEventLaws.HexZMembers, out var sourceZ))
				continue;
			var members = new List<object>(Math.Min(32, units.Count));
			for (var unitIndex = 0; unitIndex < units.Count && members.Count < 32; unitIndex++)
			{
				var unit = units[unitIndex];
				if (unit.Unit == null
				    || (aura.OwnerSide != null
				        && !ReferenceEquals(unit.TransferSide, aura.OwnerSide)
				        && !ReferenceEquals(unit.DataSide, aura.OwnerSide))
				    || (TryReadInt(unit.Unit, GameSymbols.DirectStateLaws.UnitStackCountMembers, out var stacks)
				        && stacks <= 0)
				    || !TryReadObject(unit.Unit, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var unitHex)
				    || !TryReadInt(unitHex, GameSymbols.BattleEventLaws.HexXMembers, out var unitX)
				    || !TryReadInt(unitHex, GameSymbols.BattleEventLaws.HexZMembers, out var unitZ))
					continue;
				var deltaX = unitX - sourceX;
				var deltaZ = unitZ - sourceZ;
				var distance = (Math.Abs(deltaX) + Math.Abs(deltaZ) + Math.Abs(deltaX + deltaZ)) / 2;
				if (distance <= aura.Radius)
					members.Add(unit.Unit);
			}
			if (!Homm3DirectStateAdapters.TryRefreshAura(
				    ResolveBattleScope(aura.Source) ?? aura.Source,
				    aura.AuraId,
				    members,
				    out _,
				    out var auraFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(auraFailure);
		}
		Homm3BattleLocalLawState.ClearDirectDirtyIdentities();
	}

	internal static void TriggerTrapsAtHex(object targetHex, int hexIndex)
	{
		if (!Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Trap))
			return;
		var trapIds = Homm3BattleLocalLawState.SnapshotArmedDirectTrapsAtHex(hexIndex, 16);
		for (var i = 0; i < trapIds.Count; i++)
		{
			if (!Homm3DirectStateAdapters.TryTriggerTrap(
				    targetHex,
				    trapIds[i],
				    out _,
				    out var trapFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(trapFailure);
		}
	}

	internal static void ObserveRound(Homm3BattleEventNativeAdapter.RoundEventInfo round)
	{
		if (!round.Started && Homm3RuntimeMechanicRegistry.IsAdapterActive(Homm3DirectStateAdapterId.Status))
		{
			var statuses = Homm3BattleLocalLawState.SnapshotDirectStatuses(32);
			for (var statusIndex = 0; statusIndex < statuses.Count; statusIndex++)
			{
				var status = statuses[statusIndex];
				if (!Homm3DirectStateAdapters.TryTickOrExpireStatus(
					    ResolveBattleScope(status.Unit) ?? status.Unit,
					    status.Unit,
					    status.Sid,
					    expire: false,
					    out _,
					    out var statusFailure))
					Homm3RuntimeMechanicFixtureHarness.RecordFailure(statusFailure);
			}
		}
		if (!round.Started || round.Target == null)
			return;
		var classification = Homm3UnitLawClassifier.Classify(round.Target);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out _)
		    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(classification.Sid, out var indexes))
			return;
		var scope = ResolveBattleScope(round.Target) ?? round.Target;
		if (!NativeCombatWriteGateway.TryResolveActionQueue(scope, out var queue, out var queueFailure)
		    && !NativeCombatWriteGateway.TryResolveActionQueue(round.Target, out queue, out queueFailure))
		{
			Homm3RuntimeMechanicFixtureHarness.RecordFailure(queueFailure);
			return;
		}
		var fromIndex = FindQueueEntry(queue, round.Target);
		if (fromIndex < 0)
			return;
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || !string.Equals(mechanic.Trigger, "roundStart", StringComparison.Ordinal)
			    || mechanic.Operation != Homm3DirectStateOperation.TurnOrderReorder)
				continue;
			var toIndex = Math.Max(0, Math.Min(queue.Count - 1, fromIndex - Math.Max(1, mechanic.Value)));
			if (!Homm3DirectStateAdapters.TryReorderTurn(
				    scope,
				    queue,
				    fromIndex,
				    toIndex,
				    out var reorderFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(reorderFailure);
		}
	}

	internal static void ObserveAction(Homm3BattleEventNativeAdapter.ActionEventInfo action)
	{
		if (action.Started || action.Target == null)
			return;
		var classification = Homm3UnitLawClassifier.Classify(action.Target);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out _)
		    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(classification.Sid, out var indexes))
			return;
		var scope = ResolveBattleScope(action.Target) ?? action.Target;
		if (!NativeCombatWriteGateway.TryResolveActionQueue(scope, out var queue, out var queueFailure)
		    && !NativeCombatWriteGateway.TryResolveActionQueue(action.Target, out queue, out queueFailure))
		{
			Homm3RuntimeMechanicFixtureHarness.RecordFailure(queueFailure);
			return;
		}
		var currentIndex = FindQueueEntry(queue, action.Target);
		if (currentIndex < 0)
			return;
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || !string.Equals(mechanic.Trigger, "actionEnd", StringComparison.Ordinal)
			    || mechanic.Operation != Homm3DirectStateOperation.ActionQueueInsert)
				continue;
			if (!Homm3DirectStateAdapters.TryInsertAction(
				    scope,
				    queue,
				    Math.Min(queue.Count, currentIndex + 1),
				    queue[currentIndex],
				    out var actionFailure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(actionFailure);
		}
	}

	internal static void ObserveDestroyed(Homm3BattleEventNativeAdapter.DestroyedEventInfo destroyed)
	{
		if (destroyed.DestroyedObject == null)
			return;
		var scope = ResolveBattleScope(destroyed.DestroyedObject) ?? destroyed.DestroyedObject;
		var victimClassification = Homm3UnitLawClassifier.Classify(destroyed.DestroyedObject);
		Homm3BattleEventNativeAdapter.TryResolveDataSideFromBattleObject(
			destroyed.DestroyedObject,
			out var victimSide,
			out _);
		if (Homm3UnitLawClassifier.HasIdentity(victimClassification, out _)
		    && Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(victimClassification.Sid, out var victimIndexes))
		{
			for (var i = 0; i < victimIndexes.Length; i++)
			{
				if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(victimIndexes[i], out var mechanic)
				    || !string.Equals(mechanic.Trigger, "objectDestroyed", StringComparison.Ordinal)
				    || mechanic.Operation != Homm3DirectStateOperation.CorpseCreate
				    || !TryReadObject(destroyed.DestroyedObject, GameSymbols.BattleEventLaws.BattleObjectHexMembers, out var hex)
				    || !TryReadInt(hex, GameSymbols.BattleEventLaws.HexIndexMembers, out var hexIndex))
					continue;
				if (!Homm3DirectStateAdapters.TryCreateCorpse(
					    scope,
					    destroyed.DestroyedObject,
					    hexIndex,
					    victimClassification.Sid,
					    victimSide,
					    out _,
					    out var corpseFailure))
					Homm3RuntimeMechanicFixtureHarness.RecordFailure(corpseFailure);
			}
		}

		var killer = destroyed.Caster;
		var killerClassification = Homm3UnitLawClassifier.Classify(killer);
		if (Homm3UnitLawClassifier.HasIdentity(killerClassification, out _)
		    && Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(killerClassification.Sid, out var killerIndexes))
		{
			for (var i = 0; i < killerIndexes.Length; i++)
			{
				if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(killerIndexes[i], out var mechanic)
				    || !string.Equals(mechanic.Trigger, "objectDestroyed", StringComparison.Ordinal)
				    || mechanic.Operation != Homm3DirectStateOperation.KillConfirm)
					continue;
				if (!Homm3DirectStateAdapters.TryConfirmKill(
					    scope,
					    killer,
					    destroyed.DestroyedObject,
					    null,
					    0,
					    destroyed.IsTimeout,
					    allyDeath: false,
					    out _,
					    out var killFailure))
					Homm3RuntimeMechanicFixtureHarness.RecordFailure(killFailure);
			}
		}

		if (victimSide == null)
			return;
		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		for (var unitIndex = 0; unitIndex < units.Count; unitIndex++)
		{
			var observer = units[unitIndex];
			if (observer.Unit == null
			    || ReferenceEquals(observer.Unit, destroyed.DestroyedObject)
			    || !observer.DataSideKnown
			    || !ReferenceEquals(observer.DataSide, victimSide))
				continue;
			var observerClassification = Homm3UnitLawClassifier.Classify(observer.Unit);
			if (!Homm3UnitLawClassifier.HasIdentity(observerClassification, out _)
			    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(observerClassification.Sid, out var observerIndexes))
				continue;
			for (var i = 0; i < observerIndexes.Length; i++)
			{
				if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(observerIndexes[i], out var mechanic)
				    || !string.Equals(mechanic.Trigger, "objectDestroyed", StringComparison.Ordinal)
				    || mechanic.Operation != Homm3DirectStateOperation.AllyDeathObserve)
					continue;
				if (!Homm3DirectStateAdapters.TryConfirmKill(
					    scope,
					    observer.Unit,
					    destroyed.DestroyedObject,
					    victimSide,
					    0,
					    destroyed.IsTimeout,
					    allyDeath: true,
					    out _,
					    out var allyFailure))
					Homm3RuntimeMechanicFixtureHarness.RecordFailure(allyFailure);
			}
		}
	}

	internal static void TryEnqueueNestedDamageFromIngress(
		in Homm3DirectStateIngressOutcome outcome,
		MethodInfo applyDamageMethod)
	{
		if (!outcome.IsAccepted)
			return;
		var damage = outcome.Damage;
		TryEnqueueNestedDamage(
			damage.Receiver,
			damage.Caster,
			damage.CastSource,
			damage.Dealer,
			damage.FromMech,
			applyDamageMethod);
	}

	private static void TryEnqueueNestedDamage(
		object receiver,
		object caster,
		object castSource,
		object dealer,
		object fromMech,
		MethodInfo applyDamageMethod)
	{
		var source = dealer ?? caster;
		if (source == null || receiver == null || applyDamageMethod == null)
			return;
		var classification = Homm3UnitLawClassifier.Classify(source);
		if (!Homm3UnitLawClassifier.HasIdentity(classification, out _)
		    || !Homm3RuntimeMechanicRegistry.TryGetActiveMechanicsForUnitSid(classification.Sid, out var indexes))
			return;
		var scope = ResolveBattleScope(receiver) ?? receiver;
		for (var i = 0; i < indexes.Length; i++)
		{
			if (!Homm3RuntimeMechanicRegistry.TryGetActiveMechanic(indexes[i], out var mechanic)
			    || mechanic.AdapterId != Homm3DirectStateAdapterId.NestedDamage
			    || !string.Equals(mechanic.Trigger, "damageApplied", StringComparison.Ordinal)
			    || (mechanic.Operation != Homm3DirectStateOperation.NestedReflection
			        && mechanic.Operation != Homm3DirectStateOperation.NestedSplash))
				continue;
			var damage = Math.Max(0, mechanic.Value);
			if (damage == 0)
				continue;
			var request = new Homm3DirectDamageRequest(
				source,
				applyDamageMethod,
				new[] { receiver, castSource, receiver, (object)damage, fromMech, false, 1f, false },
				damage,
				mechanic.Operation);
			if (!Homm3DirectStateAdapters.TryEnqueueNestedDamage(
				    scope,
				    receiver,
				    request,
				    out var failure))
				Homm3RuntimeMechanicFixtureHarness.RecordFailure(failure);
		}
	}

	private static void PrefixBattleResultCleanup(object __0, bool __1, MethodBase __originalMethod)
	{
		try
		{
			// Always drop thread-local deferred work and fixture dirties when the battle-result
			// surface fires. Aborted/unreadable results still must not leave queues alive.
			BattleCombatTransactionManager.AbortRoot("battle-result cleanup surface");
			Homm3RuntimeMechanicFixtureHarness.ClearForBattle();

			if (__0 == null)
			{
				Homm3BattleLocalLawState.ClearBattleSideIndexedState("battle-result cleanup with null result");
				Homm3BulwarkRunesRuntime.ClearBattleState("battle-result cleanup with null result");
				return;
			}
			if (!Homm3BattleResultSurface.TryReadBattleResultAlreadyApplied(__0, out var alreadyApplied))
			{
				Homm3BattleUnitLawOwnerRegistry.Clear("battle-result cleanup unreadable alreadyApplied");
				Homm3BulwarkRunesRuntime.ClearBattleState("battle-result cleanup unreadable alreadyApplied");
				return;
			}
			if (alreadyApplied)
				return;
			Homm3SkeletalNecromancyProbe.ObserveBeforeBattleResult(__0, __1, __originalMethod);
			Homm3FortressHuntingGroundsHook.ObserveBeforeBattleResult(__0, __1);
			GoldenEraGameplayOptions.ObserveBeforeBattleResult(__0);
			Homm3TowerArtificingRuntime.ObserveBeforeBattleResult(__0);
			Homm3BattleUnitLawOwnerRegistry.Clear("runtime-mechanics exact battle-result cleanup");
			Homm3BulwarkRunesRuntime.ClearBattleState("shared battle-result cleanup");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HoMM3 runtime-mechanics cleanup prefix failed closed: " + ex.Message);
		}
	}

	private static Type ResolveUnitType()
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				var type = assembly.GetType(GameSymbols.BattleEventLaws.BattleUnitTypeHints[0], throwOnError: false);
				if (type != null)
					return type;
			}
			catch
			{
			}
		}
		try
		{
			return typeof(Unit);
		}
		catch
		{
			return null;
		}
	}

	private static bool IsBattleEventDispatcherSurface(Homm3DirectStateHookSurface surface)
	{
		return surface == Homm3DirectStateHookSurface.RoundStart
		       || surface == Homm3DirectStateHookSurface.RoundEnd
		       || surface == Homm3DirectStateHookSurface.ActionStart
		       || surface == Homm3DirectStateHookSurface.ActionEnd;
	}

	private static MethodInfo ResolveBattleEventDispatcher(Homm3DirectStateHookSurface surface)
	{
		Type eventHubType = null;
		for (var i = 0; i < GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints.Length; i++)
		{
			var hint = GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints[i];
			eventHubType = GameMember.FindType("directState.battleEventHub." + hint, hint)
			               ?? AccessTools.TypeByName(hint);
			if (eventHubType != null)
				break;
		}
		if (eventHubType == null)
			return null;

		GameSymbols.MethodSymbol symbol;
		switch (surface)
		{
			case Homm3DirectStateHookSurface.ActionStart:
				symbol = GameSymbols.BattleEventLaws.ActionStartedDispatcher;
				break;
			case Homm3DirectStateHookSurface.ActionEnd:
				symbol = GameSymbols.BattleEventLaws.ActionEndedDispatcher;
				break;
			case Homm3DirectStateHookSurface.RoundStart:
				symbol = GameSymbols.BattleEventLaws.RoundStartedDispatcher;
				break;
			case Homm3DirectStateHookSurface.RoundEnd:
				symbol = GameSymbols.BattleEventLaws.RoundEndedDispatcher;
				break;
			default:
				return null;
		}

		MethodInfo selected = null;
		var methods = eventHubType.GetMethods(
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
		for (var nameIndex = 0; nameIndex < symbol.NameHints.Length; nameIndex++)
		{
			var name = symbol.NameHints[nameIndex];
			for (var methodIndex = 0; methodIndex < methods.Length; methodIndex++)
			{
				var method = methods[methodIndex];
				if (!string.Equals(method.Name, name, StringComparison.Ordinal)
				    || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 2
				    || !string.Equals(parameters[1].ParameterType.Name, "BattleEventArgs", StringComparison.Ordinal))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
					return null;
				selected = method;
			}
		}
		return selected;
	}

	private static MethodInfo ResolveDamageMethod(Type unitType)
	{
		if (unitType == null)
			return null;
		MethodInfo selected = null;
		foreach (var methodName in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints)
		{
			if (string.IsNullOrWhiteSpace(methodName))
				continue;
			MethodInfo[] methods;
			try
			{
				methods = unitType.GetMethods(
					BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			}
			catch
			{
				continue;
			}
			for (var i = 0; i < methods.Length; i++)
			{
				var method = methods[i];
				if (!string.Equals(method.Name, methodName, StringComparison.Ordinal)
				    || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 8
				    || parameters[3].ParameterType != typeof(int)
				    || parameters[5].ParameterType != typeof(bool)
				    || parameters[7].ParameterType != typeof(bool))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
					return null;
				selected = method;
			}
		}
		return selected;
	}

	private static bool ValidateDamagePatchCompatibility(
		MethodInfo target,
		MethodInfo patch,
		out string reason)
	{
		reason = null;
		if (target == null || patch == null)
		{
			reason = "target or patch method is null";
			return false;
		}
		if (!GameMember.IsHarmonyPatchCompatible(target, patch, out reason))
			return false;
		var targetParameters = target.GetParameters();
		if (target.IsStatic || target.ReturnType != typeof(void) || targetParameters.Length != 8)
		{
			reason = "target is not the exact instance void eight-argument shape";
			return false;
		}
		if (targetParameters[0].ParameterType.IsValueType)
		{
			reason = "argument 0 caster is unexpectedly a value type";
			return false;
		}
		if (targetParameters[3].ParameterType != typeof(int))
		{
			reason = "argument 3 is not Int32 committed damage";
			return false;
		}
		var patchParameters = patch.GetParameters();
		if (patch.ReturnType != typeof(bool)
		    || patchParameters.Length != 11
		    || patchParameters[0].Name != "__instance"
		    || patchParameters[0].ParameterType != typeof(object)
		    || patchParameters[1].Name != "__0"
		    || patchParameters[1].ParameterType != typeof(object)
		    || patchParameters[2].Name != "__1"
		    || patchParameters[2].ParameterType != typeof(object)
		    || patchParameters[3].Name != "__2"
		    || patchParameters[3].ParameterType != typeof(object)
		    || patchParameters[4].Name != "__3"
		    || !patchParameters[4].ParameterType.IsByRef
		    || patchParameters[4].ParameterType.GetElementType() != typeof(int)
		    || patchParameters[5].Name != "__4"
		    || patchParameters[5].ParameterType != typeof(object)
		    || patchParameters[6].Name != "__5"
		    || patchParameters[6].ParameterType != typeof(bool)
		    || patchParameters[7].Name != "__6"
		    || patchParameters[7].ParameterType != typeof(float)
		    || patchParameters[8].Name != "__7"
		    || patchParameters[8].ParameterType != typeof(bool)
		    || patchParameters[9].Name != "__originalMethod"
		    || patchParameters[9].ParameterType != typeof(MethodBase)
		    || patchParameters[10].Name != "__state"
		    || !patchParameters[10].ParameterType.IsByRef
		    || patchParameters[10].ParameterType.GetElementType() != typeof(bool))
		{
			reason = "patch signature must be exact typed eight-argument damage prefix plus MethodBase and out bool state";
			return false;
		}
		return true;
	}

	private static bool ValidateDamagePostfixCompatibility(
		MethodInfo target,
		MethodInfo patch,
		out string reason)
	{
		reason = null;
		if (target == null || patch == null)
		{
			reason = "target or patch method is null";
			return false;
		}
		if (!GameMember.IsHarmonyPatchCompatible(target, patch, out reason))
			return false;
		var parameters = patch.GetParameters();
		if (parameters.Length != 11
		    || parameters[0].Name != "__instance"
		    || parameters[0].ParameterType != typeof(object)
		    || parameters[1].Name != "__0"
		    || parameters[1].ParameterType != typeof(object)
		    || parameters[2].Name != "__1"
		    || parameters[2].ParameterType != typeof(object)
		    || parameters[3].Name != "__2"
		    || parameters[3].ParameterType != typeof(object)
		    || parameters[4].Name != "__3"
		    || parameters[4].ParameterType != typeof(int)
		    || parameters[5].Name != "__4"
		    || parameters[5].ParameterType != typeof(object)
		    || parameters[6].Name != "__5"
		    || parameters[6].ParameterType != typeof(bool)
		    || parameters[7].Name != "__6"
		    || parameters[7].ParameterType != typeof(float)
		    || parameters[8].Name != "__7"
		    || parameters[8].ParameterType != typeof(bool)
		    || parameters[9].Name != "__originalMethod"
		    || parameters[9].ParameterType != typeof(MethodBase)
		    || parameters[10].Name != "__state"
		    || parameters[10].ParameterType != typeof(bool))
		{
			reason = "postfix signature must be exact typed eight-argument damage postfix plus MethodBase and bool state";
			return false;
		}
		return true;
	}

	private static bool ValidateConstructorPatch(MethodInfo patch, out string reason)
	{
		reason = null;
		if (patch == null)
		{
			reason = "patch method is null";
			return false;
		}
		var parameters = patch.GetParameters();
		if (parameters.Length != 1
		    || parameters[0].Name != "__instance"
		    || parameters[0].ParameterType != typeof(object))
		{
			reason = "constructor postfix signature must be (object __instance)";
			return false;
		}
		return true;
	}

	private static object ResolveBattleScope(object battleObject)
	{
		return TryReadObject(
			battleObject,
			GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers,
			out var scope)
			? scope
			: null;
	}

	private static bool TryReadInt(object value, string[] names, out int result)
	{
		result = 0;
		if (!TryReadObject(value, names, out var raw) || raw == null)
			return false;
		try
		{
			result = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadObject(object value, string[] names, out object result)
	{
		result = null;
		if (value == null || names == null)
			return false;
		for (var current = value.GetType(); current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						result = field.GetValue(value);
						return true;
					}
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						result = property.GetValue(value, null);
						return true;
					}
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void))
					{
						result = method.Invoke(value, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static bool TryFirstEnumerableValue(object values, out object value)
	{
		value = null;
		if (values is not IEnumerable enumerable)
			return false;
		foreach (var item in enumerable)
		{
			if (item == null)
				continue;
			value = item;
			return true;
		}
		return false;
	}

	private static int FindQueueEntry(IList queue, object unit)
	{
		if (queue == null || unit == null)
			return -1;
		for (var i = 0; i < queue.Count; i++)
		{
			var entry = queue[i];
			if (ReferenceEquals(entry, unit)
			    || (TryReadObject(entry, GameSymbols.DirectStateLaws.ActionQueueEntryUnitMembers, out var entryUnit)
			        && ReferenceEquals(entryUnit, unit)))
				return i;
		}
		return -1;
	}

	private static void UnpatchOwned(Harmony harmony, MethodBase target, MethodInfo patch)
	{
		if (harmony == null || target == null || patch == null)
			return;
		try
		{
			harmony.Unpatch(target, patch);
		}
		catch
		{
		}
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null
			? "?"
			: (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
