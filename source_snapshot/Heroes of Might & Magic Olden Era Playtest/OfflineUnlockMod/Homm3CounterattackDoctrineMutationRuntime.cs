using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Runtime Counterstroke Doctrine (law row 13) for Cove, Dungeon, Fortress, Rampart, Tower, Conflux,
/// Necropolis and Stronghold. User decision 2026-11-10 ("Switch to runtime"): the generic native
/// outDmgMods counter_attack +50% rows were placeholders; their law_overrides row 13 is now a
/// zero-strength loader anchor and this runtime delivers the law text. Castle and Inferno stay
/// native-data (their profiles are DataOnly, so the planner refuses them here).
///
/// Surfaces:
/// <list type="bullet">
/// <item>Damage (always): prefix + postfix on the exact committed Unit damage method
/// (<see cref="GameSymbols.BattleEventLaws.BattleUnitApplyDamage"/>, 8 args). The prefix adjusts the
/// committed int damage (arg 3); the postfix applies after-hit effects with the final damage.
/// A hit is a counterattack when its castSource is the caster's CounterAttack ability (dxy, native
/// class checked, then re-wrapped) or, failing that, its CastDealer config carries the
/// "counter_attack" tag.</item>
/// <item>Counter trigger (once per visible counter): preferred etm.bhdy CounterAttackStep.Begin
/// postfix with state == 2 (<see cref="GameSymbols.CounterattackStepLaws"/>); needs a current-build
/// scope off Golden Era. Fallback: the token-pinned dxy AbilityCommitExecute postfix filtered to
/// CounterAttack. Last fallback: damage-only (Bulwark action serial or frame). The live mode is in
/// <see cref="RegistrationAuditStatus"/>.</item>
/// </list>
///
/// Effects (plan from <see cref="Homm3CustomCounterattackLawRuntime"/>, profile numbers in
/// <see cref="Homm3CustomLawEffectProfiles"/>):
/// Dungeon +40% counter damage when the counterattacking stack outnumbers the attacker;
/// Rampart +30% counter damage, +60% when outnumbered; Conflux +35% counter damage;
/// Tower +4%/+6% counter damage per hero Spell Power by rank (cap 60%/100%, none without a hero);
/// Fortress marks the attacker: its next attack deals 25% less;
/// Necropolis heals the counterattacker 25% of the counter damage dealt (UnitHealer.Heal
/// WithRealUntilStart: raises fallen creatures up to the starting stack size);
/// Cove +1 Focus per counter (max 5 per side per battle);
/// Stronghold: after each counter that stack deals +5% damage for the rest of the battle (max 25%).
///
/// Safety: every Harmony body is try/catch and re-entry guarded; battle-local state is keyed by native
/// pointer, scoped by session token + battle-logic pointer, and cleared by
/// <see cref="Homm3BattleUnitLawOwnerRegistry.Clear"/> (<see cref="ClearForBattle"/>). Effects apply in
/// simulated (auto/AI) battles too: all state is battle-local. Runtime proof pending.
/// Registration order: Plugin.Load registers this after Homm3RuntimeMechanicHooks, whose
/// committed-damage conflict audit refuses foreign patches already present on that method.
/// </summary>
internal static class Homm3CounterattackDoctrineMutationRuntime
{
	private const int LogCap = 120;
	private const int SkipLogCap = 24;
	private const int MaxAppliedKeys = 4096;
	private const int EtmStatePlaying = 2;
	private const int CoveFocusCapPerBattle = 5;
	private const int StrongholdBloodFeudCapPercent = 25;
	private const int RampartOutnumberedMultiplier = 2;
	private const int TowerPercentPerSpellPowerRank1 = 4;
	private const int TowerPercentPerSpellPowerRank2 = 6;
	private const int TowerCapPercentRank1 = 60;
	private const int TowerCapPercentRank2 = 100;
	private const string NecropolisHealTypeName = "WithRealUntilStart";
	private const string CounterAttackDealerTag = "counter_attack";
	private static readonly string[] HeroStatSpellPowerMembers = { "spellPower" };

	private const string CoveKey = "cove.focus.on-counterattack";
	private const string DungeonKey = "dungeon.damage-vs-smaller-stack";
	private const string FortressKey = "fortress.attack-debuff-on-counterattack";
	private const string RampartKey = "rampart.avenger-marked-counterattack-damage";
	private const string TowerKey = "tower.spell-power-as-counterattack-attack";
	private const string ConfluxKey = "conflux.extra-magic-damage-counterattack";
	private const string NecropolisKey = "necropolis.counterattack-drain-restore";
	private const string StrongholdKey = "stronghold.stacking-damage-buff-on-counterattack";

	private enum TriggerMode
	{
		DamageOnly = 0,
		CounterattackStep = 1,
		AbilityCommit = 2,
	}

	/// <summary>One counterattack hit, carried from the damage prefix to its postfix through Harmony __state.</summary>
	internal sealed class CounterHit
	{
		internal object Counterattacker;
		internal object Receiver;
		internal object LawOwner;
		internal string EffectKey;
		internal int FocusDelta;
		internal int AttackDebuff;
		internal int DrainPercent;
		internal int StackingDamagePercent;
		internal int FinalDamage;
	}

	private sealed class Weakness
	{
		internal int Percent;
		internal bool Consumed;
		internal long ConsumedActionSerial;
	}

	private static readonly object Sync = new();
	private static readonly HashSet<string> AppliedOnce = new(StringComparer.Ordinal);
	private static readonly Dictionary<long, long> CounterInstanceByUnit = new();
	private static readonly Dictionary<long, int> BloodFeudPercentByUnit = new();
	private static readonly Dictionary<long, Weakness> WeaknessByUnit = new();
	private static readonly Dictionary<long, int> CoveFocusGrantedBySide = new();
	private static readonly Dictionary<Type, IntPtr> NativeClassByType = new();
	private static long _nextCounterInstance;
	private static long _epoch;
	private static long _scopeSession;
	private static long _scopeBattleLogic;
	private static volatile bool _hasPersistentState;

	private static bool _registered;
	private static int _logged;
	private static int _skipLogged;
	private static TriggerMode _mode = TriggerMode.DamageOnly;
	private static string _registrationAuditStatus = "NOT_ATTEMPTED";

	private static Type _abilityRuntimeType;
	private static IntPtr _abilityRuntimeClass;
	private static IntPtr _counterattackStepClass;
	private static MethodInfo _healMethod;
	private static object _healType;

	[ThreadStatic]
	private static bool _inHook;

	internal static string RegistrationAuditStatus => _registrationAuditStatus;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_registered = true;

		MethodInfo damageMethod;
		try
		{
			var unitType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.BattleEventLawsBattleUnit);
			if (unitType == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: exact battle Unit type not found";
				log?.LogWarning("HoMM3 counterattack doctrine runtime failed closed: exact battle Unit type not found.");
				return;
			}
			damageMethod = null;
			foreach (var name in GameSymbols.BattleEventLaws.BattleUnitApplyDamage.NameHints ?? Array.Empty<string>())
			{
				damageMethod = ResolveDeclaredMethod(unitType, name, 8, isStatic: false);
				if (damageMethod != null)
					break;
			}
			if (damageMethod == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: exact 8-argument Unit damage method not found";
				log?.LogWarning("HoMM3 counterattack doctrine runtime failed closed: exact 8-argument Unit damage method not found on " + unitType.FullName + ".");
				return;
			}
			var prefix = GameMember.FindOwnedPatchMethod(typeof(Homm3CounterattackDoctrineMutationRuntime), nameof(PrefixUnitApplyDamage));
			var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3CounterattackDoctrineMutationRuntime), nameof(PostfixUnitApplyDamage));
			if (prefix == null || postfix == null)
			{
				_registrationAuditStatus = "FAILED_CLOSED: damage patch methods missing";
				log?.LogWarning("HoMM3 counterattack doctrine runtime failed closed: damage patch methods missing.");
				return;
			}
			if (!GameMember.IsHarmonyPatchCompatible(damageMethod, prefix, out var reason)
			    || !GameMember.IsHarmonyPatchCompatible(damageMethod, postfix, out reason))
			{
				_registrationAuditStatus = "FAILED_CLOSED: incompatible Unit damage patch: " + reason;
				log?.LogWarning("HoMM3 counterattack doctrine runtime refused Unit damage patch: " + reason);
				return;
			}

			// Resolve the dxy ability runtime before patching: the damage prefix uses it to recognise counter hits.
			_abilityRuntimeType = Homm3BulwarkRunesRuntime.ResolveAbilityRuntimeType();
			_abilityRuntimeClass = _abilityRuntimeType == null ? IntPtr.Zero : Homm3CovePlunderHook.NativeClassOf(_abilityRuntimeType);

			harmony.Patch(
				damageMethod,
				prefix: new HarmonyMethod(prefix) { priority = Priority.Last },
				postfix: new HarmonyMethod(postfix) { priority = Priority.Normal });
		}
		catch (Exception ex)
		{
			_registrationAuditStatus = "FAILED_CLOSED: " + ex.GetBaseException().Message;
			log?.LogWarning("HoMM3 counterattack doctrine runtime failed closed during damage registration: " + ex.GetBaseException().Message);
			return;
		}

		string stepDetail;
		string commitDetail = "not tried";
		try
		{
			if (TryPatchCounterattackStep(harmony, out stepDetail))
				_mode = TriggerMode.CounterattackStep;
			else if (TryPatchAbilityCommit(harmony, out commitDetail))
				_mode = TriggerMode.AbilityCommit;
			else
				_mode = TriggerMode.DamageOnly;
		}
		catch (Exception ex)
		{
			stepDetail = "trigger registration threw: " + ex.GetBaseException().Message;
			_mode = TriggerMode.DamageOnly;
		}

		string healDetail;
		try
		{
			healDetail = TryResolveHeal(out var healFail) ? "ok" : "off (" + healFail + ")";
		}
		catch (Exception ex)
		{
			healDetail = "off (" + ex.GetBaseException().Message + ")";
		}

		// Unit.Init: a (re)initialised stack starts clean, and a new battle logic resets the battle scope even
		// when no battle-result cleanup ran (auto-resolve simulation followed by an interactive replay).
		string unitInitDetail;
		try
		{
			if (!Homm3RuntimeMechanicHooks.TryRegisterSharedUnitInit(harmony, log))
				unitInitDetail = "off (shared Unit.Init owner not registered)";
			else if (!Homm3BattleUnitLawOwnerRegistry.TryRegisterUnitInitConsumer("homm3.counterattack.doctrine", OnSharedUnitInit, out var consumerFail))
				unitInitDetail = "off (" + consumerFail + ")";
			else
				unitInitDetail = "ok";
		}
		catch (Exception ex)
		{
			unitInitDetail = "off (" + ex.GetBaseException().Message + ")";
		}

		var counterSource = _abilityRuntimeClass != IntPtr.Zero ? "castSource dxy CounterAttack + dealer tag" : "dealer tag only (dxy type unresolved)";
		_registrationAuditStatus = "STARTUP_HOOK_REGISTERED_RUNTIME_UNPROVEN: damage=" + FormatMethod(damageMethod)
		                           + " counterHit=" + counterSource
		                           + " trigger=" + _mode
		                           + " (step: " + stepDetail + "; commit: " + commitDetail + ")"
		                           + " necropolisHeal=" + healDetail
		                           + " unitInitReset=" + unitInitDetail;
		log?.LogInfo("HoMM3 counterattack doctrine runtime registered. " + _registrationAuditStatus + ". Runtime proof still required.");
	}

	/// <summary>Battle cleanup (Homm3BattleUnitLawOwnerRegistry.Clear): native pointers are reused across battles.</summary>
	internal static void ClearForBattle()
	{
		lock (Sync)
			ResetLocked();
	}

	private static void OnSharedUnitInit(object unit, object[] args)
	{
		try
		{
			var unitKey = Homm3DirectStateIdentity.ResolveKeyOrZero(unit);
			if (unitKey == 0)
				return;
			EnsureBattleScope(unit);
			lock (Sync)
			{
				Homm3UnitKitRuntime.ForgetUnit(unitKey);
				CounterInstanceByUnit.Remove(unitKey);
				BloodFeudPercentByUnit.Remove(unitKey);
				WeaknessByUnit.Remove(unitKey);
				_hasPersistentState = BloodFeudPercentByUnit.Count > 0 || WeaknessByUnit.Count > 0;
			}
		}
		catch (Exception ex)
		{
			LogLimited("HoMM3 counterattack doctrine Unit.Init reset failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void ResetLocked()
	{
		AppliedOnce.Clear();
		CounterInstanceByUnit.Clear();
		BloodFeudPercentByUnit.Clear();
		WeaknessByUnit.Clear();
		CoveFocusGrantedBySide.Clear();
		Homm3UnitKitRuntime.ClearForBattle();
		_hasPersistentState = false;
		_scopeSession = 0;
		_scopeBattleLogic = 0;
		_epoch++;
	}

	// ------------------------------------------------------------------ trigger registration

	private static bool TryPatchCounterattackStep(Harmony harmony, out string detail)
	{
		string[][] arrays =
		{
			GameSymbols.CounterattackStepLaws.StepTypeHints,
			GameSymbols.CounterattackStepLaws.StepBegin.NameHints,
			GameSymbols.CounterattackStepLaws.StepCounterattackerMembers,
			GameSymbols.CounterattackStepLaws.StepStateMembers,
		};
		if (!GameBuild.IsGolden)
		{
			foreach (var array in arrays)
			{
				if (!GameSymbolScope.IsScoped(array))
				{
					detail = "no current-build scope for CounterattackStepLaws (regenerate GameSymbolsCurrent.g.cs); " + GameBuild.Describe();
					return false;
				}
				var refusal = GameSymbolScope.RefusalReason(array);
				if (refusal != null)
				{
					detail = "current-build scope refused: " + refusal;
					return false;
				}
			}
		}

		var type = GameMember.FindTypeFromHints("law.counterattackStep.type", GameSymbols.CounterattackStepLaws.StepTypeHints);
		if (type == null)
		{
			detail = "CounterAttackStep type not found";
			return false;
		}
		MethodInfo begin = null;
		foreach (var name in GameSymbols.CounterattackStepLaws.StepBegin.NameHints ?? Array.Empty<string>())
		{
			begin = ResolveDeclaredMethod(type, name, 0, isStatic: false);
			if (begin != null)
				break;
		}
		if (begin == null)
		{
			detail = "CounterAttackStep.Begin not found on " + type.FullName;
			return false;
		}
		if (!HasReadableMember(type, GameSymbols.CounterattackStepLaws.StepCounterattackerMembers)
		    || !HasReadableMember(type, GameSymbols.CounterattackStepLaws.StepStateMembers))
		{
			detail = "CounterAttackStep counterattacker/state members not found on " + type.FullName;
			return false;
		}
		var stepClass = Homm3CovePlunderHook.NativeClassOf(type);
		if (stepClass == IntPtr.Zero)
		{
			detail = "CounterAttackStep native class unresolved";
			return false;
		}
		var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3CounterattackDoctrineMutationRuntime), nameof(PostfixCounterattackStepBegin));
		if (!GameMember.IsHarmonyPatchCompatible(begin, postfix, out var reason))
		{
			detail = "incompatible CounterAttackStep.Begin postfix: " + reason;
			return false;
		}
		_counterattackStepClass = stepClass;
		harmony.Patch(begin, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		detail = "patched " + FormatMethod(begin);
		return true;
	}

	private static bool TryPatchAbilityCommit(Harmony harmony, out string detail)
	{
		if (_abilityRuntimeType == null || _abilityRuntimeClass == IntPtr.Zero)
		{
			detail = "dxy ability runtime type not found";
			return false;
		}
		var method = Homm3BulwarkRunesRuntime.ResolveAbilityCommitExecuteMethod(_abilityRuntimeType);
		if (method == null)
		{
			detail = "token-pinned AbilityCommitExecute not found";
			return false;
		}
		var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3CounterattackDoctrineMutationRuntime), nameof(PostfixAbilityCommitExecute));
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			detail = "incompatible AbilityCommitExecute postfix: " + reason;
			return false;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		detail = "patched " + FormatMethod(method);
		return true;
	}

	private static bool TryResolveHeal(out string failReason)
	{
		var type = GameMember.FindTypeFromHints("law.counterattack.unitHealer", GameSymbols.TowerArtificing.UnitHealerTypeHints);
		if (type == null)
		{
			failReason = "UnitHealer type not found";
			return false;
		}
		MethodInfo selected = null;
		foreach (var name in GameSymbols.TowerArtificing.UnitHealerHeal.NameHints ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
				continue;
			foreach (var method in type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal) || method.ReturnType != typeof(void) || method.ContainsGenericParameters)
					continue;
				var p = method.GetParameters();
				if (p.Length != 4
				    || !typeof(Il2CppObjectBase).IsAssignableFrom(p[0].ParameterType)
				    || p[1].ParameterType != typeof(int)
				    || !p[2].ParameterType.IsEnum
				    || p[3].ParameterType != typeof(bool))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
				{
					failReason = "UnitHealer.Heal ambiguous on " + type.FullName;
					return false;
				}
				selected = method;
			}
			if (selected != null)
				break;
		}
		if (selected == null)
		{
			failReason = "UnitHealer.Heal(Unit, int, EHealType, bool) not found on " + type.FullName;
			return false;
		}
		object healType;
		try
		{
			healType = Enum.Parse(selected.GetParameters()[2].ParameterType, NecropolisHealTypeName);
		}
		catch (ArgumentException)
		{
			failReason = "EHealType." + NecropolisHealTypeName + " not found";
			return false;
		}
		_healType = healType;
		_healMethod = selected;
		failReason = null;
		return true;
	}

	// ------------------------------------------------------------------ trigger postfixes

	private static void PostfixCounterattackStepBegin(object __instance)
	{
		if (_inHook)
			return;
		_inHook = true;
		try
		{
			if (!Homm3CovePlunderHook.IsNativeInstanceOf(__instance, _counterattackStepClass))
				return;
			var state = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CounterattackStepLaws.StepStateMembers);
			if (state == null || Convert.ToInt32(state, CultureInfo.InvariantCulture) != EtmStatePlaying)
				return;
			BeginCounter(Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.CounterattackStepLaws.StepCounterattackerMembers));
		}
		catch (Exception ex)
		{
			LogLimited("HoMM3 counterattack doctrine CounterAttackStep.Begin read failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_inHook = false;
		}
	}

	private static void PostfixAbilityCommitExecute(object __instance)
	{
		if (_inHook)
			return;
		_inHook = true;
		try
		{
			if (!Homm3CovePlunderHook.IsNativeInstanceOf(__instance, _abilityRuntimeClass))
				return;
			if (!Homm3BulwarkRunesRuntime.TryReadCommittedAbility(__instance, out var caster, out var abilityType, out _, out _))
				return;
			if (abilityType == EAbilityType.CounterAttack)
				BeginCounter(caster);
		}
		catch (Exception ex)
		{
			LogLimited("HoMM3 counterattack doctrine AbilityCommitExecute read failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_inHook = false;
		}
	}

	/// <summary>Opens a new counter instance for this stack; once-per-counter effects key on it.</summary>
	private static void BeginCounter(object counterattacker)
	{
		var unitKey = Homm3DirectStateIdentity.ResolveKeyOrZero(counterattacker);
		if (unitKey == 0)
			return;
		EnsureBattleScope(counterattacker);
		lock (Sync)
			CounterInstanceByUnit[unitKey] = ++_nextCounterInstance;
	}

	// ------------------------------------------------------------------ committed damage

	private static void PrefixUnitApplyDamage(
		object __instance,
		object __0,
		object __1,
		object __2,
		ref int __3,
		bool __5,
		ref CounterHit __state)
	{
		__state = null;
		if (_inHook)
			return;
		_inHook = true;
		using var timing = Homm3LoadTiming.Scope("battle damage.counterattackDoctrine", Homm3LoadTiming.BattleScopeMinMs);
		try
		{
			if (__3 <= 0 || __5)
				return;
			var percent = 0;
			string detail = null;
			object scopeUnit = null;

			var isCounterHit = TryDetectCounterHit(__0, __1, __2, out var counterattacker, out var abilityIndex);
			object lawOwner = null;
			Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan = default;
			var planned = false;
			if (isCounterHit)
			{
				planned = Homm3CustomCounterattackLawRuntime.TryPlanAllowedCounterattackDoctrineEffectForBattleObject(
					counterattacker,
					EAbilityType.CounterAttack,
					abilityIndex,
					out _,
					out _,
					out lawOwner,
					out _,
					out plan,
					out var planFail);
				if (!planned)
					LogPlanSkip(planFail);
			}
			if (planned)
			{
				scopeUnit = counterattacker;
				EnsureBattleScope(counterattacker);
				var hit = new CounterHit
				{
					Counterattacker = counterattacker,
					Receiver = __instance,
					LawOwner = lawOwner,
					EffectKey = plan.EffectKey,
					FocusDelta = plan.FocusDelta,
					AttackDebuff = plan.AttackDebuff,
					DrainPercent = plan.DrainPercent,
					StackingDamagePercent = plan.StackingDamagePercent,
				};
				var bonus = CounterDamageBonusPercent(plan, counterattacker, __instance, out var bonusDetail);
				if (bonus != 0)
				{
					percent += bonus;
					detail = plan.EffectKey + " " + bonusDetail;
				}
				__state = hit;
			}

			if (_hasPersistentState)
			{
				var casterKey = Homm3DirectStateIdentity.ResolveKeyOrZero(counterattacker ?? __0);
				if (casterKey != 0 && (scopeUnit != null || EnsureBattleScope(TryWrapUnit(__0) ?? __0)))
				{
					percent += PersistentCasterPercent(casterKey, out var persistentDetail);
					if (persistentDetail != null)
						detail = detail == null ? persistentDetail : detail + "; " + persistentDetail;
				}
			}

			// Fortress Predator Instinct: +bonus predator -> its prey, -penalty predator -> anything else while the prey
			// lives (any hit, counters included). Contributed here so the committed damage keeps a single owner.
			var predatorPercent = Homm3FortressPredatorInstinctRuntime.DamagePercent(counterattacker ?? TryWrapUnit(__0), __instance, out var predatorDetail);
			if (predatorPercent != 0)
			{
				percent += predatorPercent;
				detail = detail == null ? predatorDetail : detail + "; " + predatorDetail;
			}

			// Unit design kits (Strangle, Grudge, Shield Wall): per-unit rules keyed by unit SID, any army.
			var kitPercent = Homm3UnitKitRuntime.DamagePercent(counterattacker ?? TryWrapUnit(__0), __instance, out var kitDetail);
			if (kitPercent != 0)
			{
				percent += kitPercent;
				detail = detail == null ? kitDetail : detail + "; " + kitDetail;
			}

			if (percent != 0)
			{
				var before = __3;
				__3 = ScaleDamage(before, percent);
				LogLimited("HoMM3 counterattack doctrine damage " + before + " -> " + __3 + " (" + percent.ToString("+0;-0", CultureInfo.InvariantCulture) + "%): " + detail + ".");
			}
			// Unit design kits: per-hit cap of the receiver (Diamond Scales), after every percent rule.
			var capped = Homm3UnitKitRuntime.CapDamage(__instance, __3, out var capDetail);
			if (capped != __3)
			{
				LogLimited("HoMM3 unit kit damage " + __3 + " -> " + capped + ": " + capDetail + ".");
				__3 = capped;
			}
			Homm3UnitKitRuntime.NoteCommittedDamage(__instance, __3);
			if (__state != null)
				__state.FinalDamage = __3;
		}
		catch (Exception ex)
		{
			__state = null;
			LogLimited("HoMM3 counterattack doctrine damage prefix failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_inHook = false;
		}
	}

	private static void PostfixUnitApplyDamage(CounterHit __state)
	{
		if (__state == null || _inHook)
			return;
		_inHook = true;
		try
		{
			ApplyAfterCounterHit(__state);
		}
		catch (Exception ex)
		{
			LogLimited("HoMM3 counterattack doctrine damage postfix failed closed for " + __state.EffectKey + ": " + ex.GetBaseException().Message);
		}
		finally
		{
			_inHook = false;
		}
	}

	/// <summary>A counter hit with no custom plan (vanilla factions, Castle/Inferno native-data profiles, no law).</summary>
	private static void LogPlanSkip(string planFail)
	{
		var message = "HoMM3 counterattack doctrine mutation skipped: " + (planFail ?? "no plan");
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_skipLogged >= SkipLogCap)
			return;
		_skipLogged++;
		Plugin.LogSource?.LogInfo(message);
	}

	private static int CounterDamageBonusPercent(
		Homm3CustomLawEffectPlans.CounterattackDoctrineEffectPlan plan,
		object counterattacker,
		object receiver,
		out string detail)
	{
		detail = null;
		switch (plan.EffectKey)
		{
			case DungeonKey when plan.DamagePercentBonus > 0:
			{
				if (!TryReadStacks(counterattacker, receiver, out var mine, out var theirs, out var fail))
				{
					detail = "stack read failed: " + fail;
					return 0;
				}
				detail = "stacks " + mine + " vs " + theirs;
				return mine > theirs ? plan.DamagePercentBonus : 0;
			}
			case RampartKey when plan.DamagePercentBonus > 0:
			{
				if (!TryReadStacks(counterattacker, receiver, out var mine, out var theirs, out var fail))
				{
					detail = "stack read failed (" + fail + "); base bonus";
					return plan.DamagePercentBonus;
				}
				detail = "stacks " + mine + " vs " + theirs;
				return mine < theirs ? plan.DamagePercentBonus * RampartOutnumberedMultiplier : plan.DamagePercentBonus;
			}
			case ConfluxKey when plan.DamagePercentBonus > 0:
				detail = "elemental backlash";
				return plan.DamagePercentBonus;
			case TowerKey:
			{
				if (!TryReadHeroSpellPower(counterattacker, out var spellPower, out var fail))
				{
					detail = "no hero spell power (" + fail + ")";
					return 0;
				}
				var perPoint = plan.Rank >= 2 ? TowerPercentPerSpellPowerRank2 : TowerPercentPerSpellPowerRank1;
				var cap = plan.Rank >= 2 ? TowerCapPercentRank2 : TowerCapPercentRank1;
				var bonus = spellPower <= 0 ? 0 : (int)Math.Min(cap, (long)perPoint * spellPower);
				detail = "spellPower=" + spellPower + " rank=" + plan.Rank + " " + perPoint + "%/pt cap " + cap + "%";
				return bonus;
			}
			default:
				return 0;
		}
	}

	/// <summary>Stronghold Blood Feud (+%) and Fortress weakness (-%) carried by the caster of any hit.</summary>
	private static int PersistentCasterPercent(long casterKey, out string detail)
	{
		detail = null;
		var percent = 0;
		lock (Sync)
		{
			if (BloodFeudPercentByUnit.TryGetValue(casterKey, out var feud) && feud > 0)
			{
				percent += feud;
				detail = StrongholdKey + " +" + feud + "%";
			}
			if (WeaknessByUnit.TryGetValue(casterKey, out var weakness))
			{
				var haveSerial = Homm3BulwarkRunesRuntime.TryGetActionCorrelation(out _, out var serial);
				var apply = false;
				if (!weakness.Consumed)
				{
					apply = true;
					if (haveSerial)
					{
						weakness.Consumed = true;
						weakness.ConsumedActionSerial = serial;
					}
					else
					{
						WeaknessByUnit.Remove(casterKey);
					}
				}
				else if (haveSerial && serial == weakness.ConsumedActionSerial)
				{
					apply = true; // later hits of the same attack (multi-hit / area)
				}
				else
				{
					WeaknessByUnit.Remove(casterKey);
				}
				if (apply)
				{
					percent -= weakness.Percent;
					var text = FortressKey + " -" + weakness.Percent + "%";
					detail = detail == null ? text : detail + "; " + text;
				}
			}
			_hasPersistentState = BloodFeudPercentByUnit.Count > 0 || WeaknessByUnit.Count > 0;
		}
		return percent;
	}

	private static void ApplyAfterCounterHit(CounterHit hit)
	{
		switch (hit.EffectKey)
		{
			case FortressKey when hit.AttackDebuff < 0:
			{
				var receiverKey = Homm3DirectStateIdentity.ResolveKeyOrZero(hit.Receiver);
				if (receiverKey == 0)
					return;
				var percent = Math.Min(100, Math.Abs(hit.AttackDebuff));
				lock (Sync)
				{
					WeaknessByUnit[receiverKey] = new Weakness { Percent = percent };
					_hasPersistentState = true;
				}
				LogLimited("HoMM3 counterattack doctrine " + FortressKey + " marked attacker unit=" + receiverKey + ": next attack -" + percent + "%.");
				return;
			}
			case NecropolisKey when hit.DrainPercent > 0:
			{
				var amount = (int)Math.Round(hit.FinalDamage * (hit.DrainPercent / 100.0), MidpointRounding.AwayFromZero);
				if (amount <= 0)
					return;
				if (_healMethod == null || _healType == null)
				{
					LogLimited("HoMM3 counterattack doctrine " + NecropolisKey + " heal skipped: UnitHealer.Heal unresolved.");
					return;
				}
				var unitArg = ToParameter(hit.Counterattacker, _healMethod.GetParameters()[0].ParameterType);
				if (unitArg == null)
				{
					LogLimited("HoMM3 counterattack doctrine " + NecropolisKey + " heal skipped: counterattacker is not a healable Unit.");
					return;
				}
				// revive=false: a stack that died is not brought back; WithRealUntilStart restores fallen creatures up to the start size.
				_healMethod.Invoke(null, new[] { unitArg, amount, _healType, false });
				LogLimited("HoMM3 counterattack doctrine " + NecropolisKey + " healed counterattacker " + amount + " HP (" + hit.DrainPercent + "% of " + hit.FinalDamage + ").");
				return;
			}
			case CoveKey when hit.FocusDelta > 0:
			{
				if (!TryClaimOncePerCounter(hit, out var key))
					return;
				if (!Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(hit.Counterattacker, out var battleSide) || battleSide == null)
				{
					LogLimited("HoMM3 counterattack doctrine " + CoveKey + " skipped: battle side unresolved for counterattacker.");
					return;
				}
				var sideKey = Homm3DirectStateIdentity.ResolveKeyOrZero(battleSide);
				int granted;
				lock (Sync)
				{
					CoveFocusGrantedBySide.TryGetValue(sideKey, out granted);
					if (granted >= CoveFocusCapPerBattle)
						return;
				}
				var delta = Math.Min(hit.FocusDelta, CoveFocusCapPerBattle - granted);
				if (!Homm3FocusNativeAdapter.TryGrantFocusToSide(battleSide, delta, out var focusFail))
				{
					LogLimited("HoMM3 counterattack doctrine " + CoveKey + " Focus grant failed closed: " + focusFail);
					return;
				}
				lock (Sync)
				{
					CoveFocusGrantedBySide.TryGetValue(sideKey, out granted);
					CoveFocusGrantedBySide[sideKey] = granted + delta;
				}
				LogLimited("HoMM3 counterattack doctrine " + CoveKey + " +" + delta + " Focus (battle total " + (granted + delta) + "/" + CoveFocusCapPerBattle + ") key=" + key + ".");
				return;
			}
			case StrongholdKey when hit.StackingDamagePercent > 0:
			{
				if (!TryClaimOncePerCounter(hit, out var key))
					return;
				var unitKey = Homm3DirectStateIdentity.ResolveKeyOrZero(hit.Counterattacker);
				if (unitKey == 0)
					return;
				int oldPercent, newPercent;
				lock (Sync)
				{
					BloodFeudPercentByUnit.TryGetValue(unitKey, out oldPercent);
					newPercent = Math.Min(StrongholdBloodFeudCapPercent, oldPercent + hit.StackingDamagePercent);
					BloodFeudPercentByUnit[unitKey] = newPercent;
					_hasPersistentState = true;
				}
				LogLimited("HoMM3 counterattack doctrine " + StrongholdKey + " " + oldPercent + "% -> " + newPercent + "% unit=" + unitKey + " key=" + key + ".");
				return;
			}
		}
	}

	/// <summary>
	/// One claim per counterattack for effects that must not repeat per hit. Instance: the
	/// CounterAttackStep/AbilityCommit trigger's counter instance, else the Bulwark action serial,
	/// else the frame (damage-only fallback).
	/// </summary>
	private static bool TryClaimOncePerCounter(CounterHit hit, out string key)
	{
		key = null;
		var unitKey = Homm3DirectStateIdentity.ResolveKeyOrZero(hit.Counterattacker);
		if (unitKey == 0)
			return false;
		string instance = null;
		lock (Sync)
		{
			if (_mode != TriggerMode.DamageOnly && CounterInstanceByUnit.TryGetValue(unitKey, out var counterInstance))
				instance = "counter=" + counterInstance.ToString(CultureInfo.InvariantCulture);
		}
		if (instance == null)
		{
			instance = Homm3BulwarkRunesRuntime.TryGetActionCorrelation(out var generation, out var serial)
				? "action=" + generation.ToString(CultureInfo.InvariantCulture) + ":" + serial.ToString(CultureInfo.InvariantCulture)
				: "frame=" + UnityEngine.Time.frameCount.ToString(CultureInfo.InvariantCulture);
		}
		long epoch;
		lock (Sync)
			epoch = _epoch;
		key = "session=" + Homm3BattleUnitLawOwnerRegistry.ResolveSessionToken().ToString(CultureInfo.InvariantCulture)
		      + "|epoch=" + epoch.ToString(CultureInfo.InvariantCulture)
		      + "|unit=" + unitKey.ToString(CultureInfo.InvariantCulture)
		      + "|" + instance
		      + "|effect=" + hit.EffectKey;
		lock (Sync)
		{
			if (AppliedOnce.Count >= MaxAppliedKeys)
				AppliedOnce.Clear();
			return AppliedOnce.Add(key);
		}
	}

	// ------------------------------------------------------------------ reads

	/// <summary>
	/// Counter hit: castSource is a dxy ability whose AbilityID is CounterAttack (its caster is the
	/// counterattacker); otherwise the CastDealer config carries the counter_attack tag.
	/// </summary>
	private static bool TryDetectCounterHit(object caster, object castSource, object dealer, out object counterattacker, out int abilityIndex)
	{
		counterattacker = null;
		abilityIndex = -1;
		if (_abilityRuntimeClass != IntPtr.Zero && Homm3CovePlunderHook.IsNativeInstanceOf(castSource, _abilityRuntimeClass))
		{
			var ability = ToParameter(castSource, _abilityRuntimeType);
			if (ability != null
			    && Homm3BulwarkRunesRuntime.TryReadCommittedAbility(ability, out var abilityCaster, out var abilityType, out var index, out _))
			{
				if (abilityType != EAbilityType.CounterAttack)
					return false;
				counterattacker = TryWrapUnit(abilityCaster) ?? abilityCaster;
				abilityIndex = index;
				return counterattacker != null;
			}
		}
		if (!DealerHasCounterTag(dealer))
			return false;
		counterattacker = TryWrapUnit(caster);
		return counterattacker != null;
	}

	private static bool DealerHasCounterTag(object dealer)
	{
		if (dealer == null)
			return false;
		var config = Homm3TowerArtificingRuntime.ReadMember(dealer, GameSymbols.TowerArtificing.CastDealerConfigMembers);
		var tags = Homm3TowerArtificingRuntime.ReadMember(config, GameSymbols.TowerArtificing.CastDealerConfigTagsMembers);
		if (tags == null)
			return false;
		var type = tags.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
		                    ?? type.GetProperty("Length", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		var indexer = type.GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(int) }, null);
		if (countProperty?.GetValue(tags) is int count && indexer != null)
		{
			for (var i = 0; i < count; i++)
			{
				if (indexer.Invoke(tags, new object[] { i }) is string tag
				    && string.Equals(tag.Trim(), CounterAttackDealerTag, StringComparison.Ordinal))
					return true;
			}
			return false;
		}
		if (tags is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item is string tag && string.Equals(tag.Trim(), CounterAttackDealerTag, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static bool TryReadStacks(object counterattacker, object receiver, out int mine, out int theirs, out string failReason)
	{
		theirs = 0;
		if (!Homm3TrainingDamageLawRuntime.TryReadBattleStackCount(TryWrapUnit(counterattacker) ?? counterattacker, out mine, out failReason))
		{
			failReason = "counterattacker: " + failReason;
			return false;
		}
		if (!Homm3TrainingDamageLawRuntime.TryReadBattleStackCount(TryWrapUnit(receiver) ?? receiver, out theirs, out failReason))
		{
			failReason = "attacker: " + failReason;
			return false;
		}
		return true;
	}

	/// <summary>Hero Spell Power of the counterattacker's side: battle side, then its TransferSide, -> hero -> heroStat.spellPower.</summary>
	private static bool TryReadHeroSpellPower(object counterattacker, out int spellPower, out string failReason)
	{
		spellPower = 0;
		if (!Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(counterattacker, out var battleSide) || battleSide == null)
		{
			failReason = "battle side unresolved";
			return false;
		}
		var candidates = new[]
		{
			battleSide,
			Homm3TowerArtificingRuntime.ReadMember(battleSide, GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers),
		};
		foreach (var side in candidates)
		{
			if (side == null)
				continue;
			var hero = Homm3TowerArtificingRuntime.ReadMember(side, GameSymbols.SkeletalNecromancy.TransferSideHeroMembers);
			if (hero == null)
				continue;
			var heroStat = Homm3TowerArtificingRuntime.ReadMember(hero, GameSymbols.SkeletalNecromancy.TransferHeroStatMembers);
			var value = Homm3TowerArtificingRuntime.ReadMember(heroStat, HeroStatSpellPowerMembers);
			if (value == null)
				continue;
			spellPower = Convert.ToInt32(value, CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		failReason = "no hero on the counterattacker's side";
		return false;
	}

	/// <summary>
	/// Resets battle-local state when the battle (battle-logic pointer) or session changes, so
	/// simulated battles and reloads never inherit marks through reused native pointers. Returns false
	/// only when this call reset state that belonged to another battle (the caller then skips stale
	/// lookups). An unreadable battle logic leaves state as is (battle cleanup still clears it).
	/// </summary>
	private static bool EnsureBattleScope(object battleUnit)
	{
		var logic = Homm3TowerArtificingRuntime.ReadMember(battleUnit, GameSymbols.BattleEventLaws.BattleObjectBattleLogicMembers);
		var logicKey = Homm3DirectStateIdentity.ResolveKeyOrZero(logic);
		if (logicKey == 0)
			return true;
		var session = Homm3BattleUnitLawOwnerRegistry.ResolveSessionToken();
		lock (Sync)
		{
			if (_scopeBattleLogic == logicKey && _scopeSession == session)
				return true;
			var hadScope = _scopeBattleLogic != 0;
			ResetLocked();
			_scopeBattleLogic = logicKey;
			_scopeSession = session;
			return !hadScope;
		}
	}

	private static object TryWrapUnit(object value)
	{
		if (value is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
			return null;
		try
		{
			// Class-checked cast: caster interfaces may be abilities or hero casts, not Units.
			return il2Cpp.TryCast<Unit>();
		}
		catch
		{
			return null;
		}
	}

	/// <summary>The value as an exact interop parameter type: re-wraps an Il2Cpp proxy of another wrapper type by pointer.</summary>
	private static object ToParameter(object value, Type parameterType)
	{
		if (value == null || parameterType == null)
			return null;
		if (parameterType.IsInstanceOfType(value))
			return value;
		if (value is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero && typeof(Il2CppObjectBase).IsAssignableFrom(parameterType))
		{
			IntPtr expectedClass;
			lock (Sync)
			{
				if (!NativeClassByType.TryGetValue(parameterType, out expectedClass))
				{
					expectedClass = Homm3CovePlunderHook.NativeClassOf(parameterType);
					NativeClassByType[parameterType] = expectedClass;
				}
			}
			if (expectedClass == IntPtr.Zero || !Homm3CovePlunderHook.IsNativeInstanceOf(value, expectedClass))
				return null;
			return Activator.CreateInstance(parameterType, il2Cpp.Pointer);
		}
		return null;
	}

	private static int ScaleDamage(int damage, int percent)
	{
		var factor = Math.Max(0, 100 + percent);
		var scaled = (long)damage * factor / 100L;
		if (scaled > int.MaxValue)
			return int.MaxValue;
		return scaled < 0 ? 0 : (int)scaled;
	}

	private static MethodInfo ResolveDeclaredMethod(Type type, string name, int parameterCount, bool isStatic)
	{
		if (type == null || string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
			return null;
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly
		            | (isStatic ? BindingFlags.Static : BindingFlags.Instance);
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, name, StringComparison.Ordinal)
			    || method.IsSpecialName
			    || method.ContainsGenericParameters
			    || method.ReturnType != typeof(void)
			    || method.GetParameters().Length != parameterCount)
				continue;
			return method;
		}
		return null;
	}

	private static bool HasReadableMember(Type type, string[] names)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name) || GameSymbolScope.IsSentinel(name))
				continue;
			if (type.GetProperty(name, flags)?.GetMethod != null || type.GetField(name, flags) != null)
				return true;
		}
		return false;
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "?" : (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static void LogLimited(string message)
	{
		Homm3CandidateSurfaceRuntimeCounters.Record(message);
		if (_logged >= LogCap)
			return;
		_logged++;
		Plugin.LogSource?.LogInfo(message);
	}
}
