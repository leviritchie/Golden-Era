using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Factory Split Assembly: at battle start, distinct Natural / Industrial recruit
/// lines unlock tiered army-wide bonuses scaled by skill rank. Fourth-branch
/// bonuses require Expert. Natural Overclock / Industrial Overclock subskills add
/// +1 effective line count.
///
/// Ownership: Core skill/buff rows are data only — there is no native Split
/// Assembly mechanic. Combat apply is wholly owned by this Harmony runtime.
///
/// Producer/consumer join (live-negative 2026-07-25): do NOT key plans by
/// TransferSide native pointer. TransferBattle.sides TransferSide objects are
/// distinct from the TransferSide exposed by Unit.Init's battle-side wrapper, so
/// pointer joins miss with activePlans>0. Join on battle-local side index:
/// BuildPlans stores PlansBySideIndex by TransferBattle.sides array index;
/// Unit.Init reads field_Public_Int32_0 from the battle-side wrapper via
/// BattleSideWrapperLocalSideIndexMembers and applies immediately to __instance.
/// Live logs prove BattleLogic.Init prefix builds plans before each relevant
/// Unit.Init, so direct Unit.Init apply is sufficient — no SnapshotUnits
/// fallback (that registry accumulates stale units across repeated Inits).
/// Focus / Field Triage unlock state uses the same side-index keys, cleared on
/// each BattleLogic.Init prefix with the plans.
/// Effective combat stats: Homm3BuffDebuffNativeAdapter folds BuffConfig.data.stats
/// additively onto Unit.get_stats after bbgf (live-probe-proven for speed mid-combat).
/// Battle-start UI Speed / Focus / Carapace / Field Triage still need a Golden Era
/// combat after OfflineUnlockMod deploy.
/// </summary>
internal static class Homm3FactorySplitAssemblyRuntime
{
	private const string FactoryFactionSid = Homm3FactorySplitAssemblyEvaluator.FactoryFactionSid;
	private const string FactorySkillSid = Homm3FactorySplitAssemblyEvaluator.FactorySkillSid;
	private const string NaturalOverclockSubSkillSid = Homm3FactorySplitAssemblyEvaluator.NaturalOverclockSubSkillSid;
	private const string IndustrialOverclockSubSkillSid = Homm3FactorySplitAssemblyEvaluator.IndustrialOverclockSubSkillSid;
	private const string FieldTriageAbilitySid = "skill_faction_homm3_factory_ability_field_triage";
	private const string CarapaceBuffSid = "magic_carapace_effect";
	private const int AssemblyBuffDuration = 99;
	// Custom exact-id buff rows (and law markers) apply with level >= 1; level 0 is
	// reserved for vanilla baseSid + leveled config lookup (magic_haste_effect_N).
	private const int AssemblyBuffLevel = 1;
	private const int AssemblyBuffValue = 1;
	private static readonly object Gate = new();
	private static readonly Dictionary<int, SideAssemblyPlan> PlansBySideIndex = new();
	private static readonly HashSet<int> FocusGrantedSideIndexes = new();
	private static readonly HashSet<int> FieldTriageUnlockedSideIndexes = new();
	private static readonly HashSet<long> BuffAppliedUnitKeys = new();

	private static bool _registered;
	private static ManualLogSource _log;
	private static MethodInfo _logicHeroDataHeroGetter;
	private static int _loggedApplications;
	private static int _loggedSkips;
	private static int _loggedUnitApplications;
	private static int _loggedUnitInitProbes;

	private sealed class SideAssemblyPlan
	{
		internal int Rank;
		internal int NaturalEffective;
		internal int IndustrialEffective;
		internal int NaturalTier;
		internal int IndustrialTier;
		internal string NaturalLines;
		internal string IndustrialLines;
		internal bool NaturalOverclock;
		internal bool IndustrialOverclock;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		MethodInfo battleLogicInitMethod = null;
		string registrationSummary = null;
		try
		{
			var hexAssembly = typeof(TransferBattle).Assembly;
			var battleLogicType = ResolveRequiredTypeByHint(
				hexAssembly,
				GameSymbols.DraconicDominion.BattleLogicTypeHints,
				"homm3.factory.splitAssembly.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.factory.splitAssembly.transferBattle");
			battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.factory.splitAssembly.battleLogic.init",
				method => !method.IsStatic);
			var logicHeroType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.CastleEliteStrategem.LogicHeroTypeName,
				"homm3.factory.splitAssembly.logicHero");
			_logicHeroDataHeroGetter = ResolveRequiredExactNamedMethod(
				logicHeroType,
				typeof(DataHero),
				Type.EmptyTypes,
				GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints[0],
				"homm3.factory.splitAssembly.logicHero.dataHeroGetter",
				method => !method.IsStatic);

			if (!Homm3RuntimeMechanicHooks.TryRegisterSharedUnitInit(harmony, _log))
				throw new InvalidOperationException("shared Unit.Init owner did not register");

			PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			PatchPostfix(harmony, battleLogicInitMethod, nameof(PostfixBattleLogicInit));
			registrationSummary = "HoMM3 Factory Split Assembly runtime registered on "
				+ FormatMethod(battleLogicInitMethod)
				+ " with the shared Unit.Init consumer (battle-local side-index plan join; Unit.Init direct apply). Line counts, rank magnitudes, Expert fourth-tier gates, and overclock subskills fail closed; gameplay remains runtime-unvalidated.";
			if (!Homm3BattleUnitLawOwnerRegistry.TryRegisterUnitInitConsumer(
					"homm3.factory.splitAssembly",
					OnSharedUnitInit,
					out var consumerFailure))
				throw new InvalidOperationException("shared Unit.Init consumer registration failed: " + consumerFailure);
			_registered = true;
		}
		catch (Exception ex)
		{
			_registered = false;
			UnpatchOwned(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			UnpatchOwned(harmony, battleLogicInitMethod, nameof(PostfixBattleLogicInit));
			_log?.LogWarning("HoMM3 Factory Split Assembly runtime not registered; exact startup surface missing: " + ex.Message);
		}
		if (_registered)
			_log?.LogInfo(registrationSummary);
	}

	private static void PrefixBattleLogicInit(object __1)
	{
		if (!_registered)
			return;
		ClearPlans("battle-logic-init-prefix");
		try
		{
			BuildPlans(__1 as TransferBattle);
		}
		catch (Exception ex)
		{
			ClearPlans("battle-logic-init-prefix-failure");
			LogLimited("battle init plan build failed closed: " + ex.Message);
		}
	}

	private static void PostfixBattleLogicInit(object __1)
	{
		if (!_registered)
			return;
		try
		{
			GrantPendingFocus(__1 as TransferBattle);
			ApplyFieldTriageChargeLocks(__1 as TransferBattle);
		}
		catch (Exception ex)
		{
			LogLimited("battle init Focus/Field Triage apply failed closed: " + ex.Message);
		}
	}

	private static void PostfixUnitInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null || __args == null || __args.Length < 3)
				return;
			var battleSideArg = __args[2];
			if (battleSideArg == null)
				return;

			int planCount;
			lock (Gate)
				planCount = PlansBySideIndex.Count;

			var unitSid = TryResolveBattleUnitSid(__instance, __args) ?? "?";
			var factoryUnit = IsFactoryBattleUnitSid(unitSid)
			                  || IsFactoryBattleUnit(__instance);

			if (planCount == 0)
			{
				if (factoryUnit && _loggedUnitInitProbes++ < 24)
				{
					LogLimited(
						"unit init while plans empty: unitSid="
						+ unitSid
						+ " battleSideType="
						+ (battleSideArg.GetType().FullName ?? "?")
						+ " (buff apply window already closed or never opened)");
				}
				return;
			}

			if (!TryResolveBattleLocalSideIndex(battleSideArg, out var sideIndex, out var sideIndexReason))
			{
				if (factoryUnit)
				{
					LogLimited(
						"unit init side-index resolve failed while plans active: unitSid="
						+ unitSid
						+ " battleSideType="
						+ (battleSideArg.GetType().FullName ?? "?")
						+ " reason="
						+ sideIndexReason
						+ " planKeys=["
						+ FormatPlanKeys()
						+ "]");
				}
				return;
			}

			if (_loggedUnitInitProbes++ < 24)
			{
				_log?.LogInfo(
					"HoMM3 Factory Split Assembly unit init probe: unitSid="
					+ unitSid
					+ " factoryUnit="
					+ factoryUnit
					+ " sideIndex="
					+ sideIndex
					+ " activePlans="
					+ planCount
					+ " battleSideType="
					+ (battleSideArg.GetType().FullName ?? "?")
					+ ".");
			}

			SideAssemblyPlan plan;
			lock (Gate)
			{
				if (!PlansBySideIndex.TryGetValue(sideIndex, out plan) || plan == null)
				{
					if (factoryUnit)
					{
						LogLimited(
							"unit init plan miss: unitSid="
							+ unitSid
							+ " sideIndex="
							+ sideIndex
							+ " activePlans="
							+ PlansBySideIndex.Count
							+ " planKeys=["
							+ FormatPlanKeys()
							+ "]");
					}
					return;
				}
			}
			ApplyUnitBonuses(__instance, plan, sideIndex);
		}
		catch (Exception ex)
		{
			LogLimited("unit init Split Assembly apply failed closed: " + ex.Message);
		}
	}

	private static void OnSharedUnitInit(object unit, object[] args)
	{
		if (_registered)
			PostfixUnitInit(unit, args);
	}

	/// <summary>
	/// Battle-local side index from Unit.Init arg[2] (battle-side wrapper).
	/// Matches <see cref="BuildPlans"/> TransferBattle.sides array indexes.
	/// Do not read this group from native TransferSide.
	/// </summary>
	private static bool TryResolveBattleLocalSideIndex(
		object battleSideArg,
		out int sideIndex,
		out string failReason)
	{
		sideIndex = -1;
		failReason = null;
		if (battleSideArg == null)
		{
			failReason = "battle side arg null";
			return false;
		}
		if (battleSideArg is TransferSide)
		{
			failReason = "Unit.Init side arg is TransferSide; expected battle-side wrapper for local side index";
			return false;
		}
		if (!TryReadInt(
			    battleSideArg,
			    GameSymbols.BattleEventLaws.BattleSideWrapperLocalSideIndexMembers,
			    out sideIndex))
		{
			failReason =
				"battle side "
				+ (battleSideArg.GetType().FullName ?? "?")
				+ " exposed no battle-local side index via BattleSideWrapperLocalSideIndexMembers";
			return false;
		}
		return true;
	}

	private static string FormatPlanKeys()
	{
		lock (Gate)
			return string.Join(",", PlansBySideIndex.Keys);
	}

	private static bool IsFactoryBattleUnit(object unit)
	{
		return IsFactoryBattleUnitSid(TryResolveBattleUnitSid(unit));
	}

	private static bool IsFactoryBattleUnitSid(string sid)
	{
		if (sid == null)
			return false;
		return Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sid, out var factionSid)
		       && string.Equals(factionSid, FactoryFactionSid, StringComparison.Ordinal);
	}

	private static void BuildPlans(TransferBattle transferBattle)
	{
		if (transferBattle?.sides == null)
			return;
		var sides = transferBattle.sides;
		for (var sideIndex = 0; sideIndex < sides.Length; sideIndex++)
		{
			var side = sides[sideIndex];
			if (side == null)
				continue;
			if (!TryResolveFactorySkillRank(side, out var rank, out var dataHero, out var rankFailReason))
			{
				if (SideContainsFactoryUnit(side))
					LogLimited("sideIndex=" + sideIndex + " with Factory units skipped: " + rankFailReason);
				continue;
			}
			var unitSids = CollectTransferSideUnitSids(side, out var countFailReason);
			if (unitSids == null)
			{
				LogLimited("sideIndex=" + sideIndex + " rank " + rank + " skipped: " + countFailReason);
				continue;
			}

			var naturalOverclock = HasHeroSubSkill(dataHero, NaturalOverclockSubSkillSid);
			var industrialOverclock = HasHeroSubSkill(dataHero, IndustrialOverclockSubSkillSid);
			if (!Homm3FactorySplitAssemblyEvaluator.TryEvaluate(
				    unitSids,
				    rank,
				    naturalOverclock,
				    industrialOverclock,
				    out var snapshot,
				    out var evalFailReason))
			{
				LogLimited("sideIndex=" + sideIndex + " rank " + rank + " skipped: " + evalFailReason);
				continue;
			}
			if (snapshot.NaturalTier == 0 && snapshot.IndustrialTier == 0)
				continue;

			var plan = new SideAssemblyPlan
			{
				Rank = snapshot.Rank,
				NaturalEffective = snapshot.NaturalEffective,
				IndustrialEffective = snapshot.IndustrialEffective,
				NaturalTier = snapshot.NaturalTier,
				IndustrialTier = snapshot.IndustrialTier,
				NaturalLines = snapshot.NaturalLines,
				IndustrialLines = snapshot.IndustrialLines,
				NaturalOverclock = snapshot.NaturalOverclock,
				IndustrialOverclock = snapshot.IndustrialOverclock,
			};

			lock (Gate)
			{
				PlansBySideIndex[sideIndex] = plan;
				if (plan.IndustrialTier >= 4)
					FieldTriageUnlockedSideIndexes.Add(sideIndex);
				else
					FieldTriageUnlockedSideIndexes.Remove(sideIndex);
			}

			if (_loggedApplications++ < 24)
			{
				_log?.LogInfo(
					"HoMM3 Factory Split Assembly planned: rank="
					+ plan.Rank
					+ " sideIndex="
					+ sideIndex
					+ " natural=["
					+ plan.NaturalLines
					+ "] effective="
					+ plan.NaturalEffective
					+ " tiers="
					+ plan.NaturalTier
					+ " industrial=["
					+ plan.IndustrialLines
					+ "] effective="
					+ plan.IndustrialEffective
					+ " tiers="
					+ plan.IndustrialTier
					+ " overclockN="
					+ plan.NaturalOverclock
					+ " overclockI="
					+ plan.IndustrialOverclock
					+ ".");
			}
		}
	}

	private static void ApplyFieldTriageChargeLocks(TransferBattle transferBattle)
	{
		if (transferBattle?.sides == null)
			return;
		var sides = transferBattle.sides;
		for (var sideIndex = 0; sideIndex < sides.Length; sideIndex++)
		{
			var side = sides[sideIndex];
			if (side?.logicHero == null)
				continue;
			bool unlocked;
			lock (Gate)
			{
				unlocked = FieldTriageUnlockedSideIndexes.Contains(sideIndex);
			}
			var lockedCount = 0;
			foreach (var ability in EnumerateHeroAbilities(side.logicHero))
			{
				var sid = NormalizeSid(TryGetMemberValue(ability, "sid") as string
					?? TryGetMemberValue(ability, "<sid>k__BackingField") as string
					?? TryGetMemberValue(ability, "_sid_k__BackingField") as string
					?? TryGetMemberValue(ability, "id") as string);
				if (!string.Equals(sid, FieldTriageAbilitySid, StringComparison.Ordinal))
					continue;
				// Expert Core always grants the ability row. Fourth-tier Industrial unlock
				// is required before charges become usable.
				TrySetIntMember(ability, "charges", unlocked ? -1 : 0);
				TrySetIntMember(ability, "castsPerBattleLeft", unlocked ? -1 : 0);
				lockedCount++;
			}
			if (lockedCount > 0 && _loggedApplications++ < 40)
			{
				_log?.LogInfo(
					"HoMM3 Factory Split Assembly Field Triage "
					+ (unlocked ? "unlocked" : "charge-locked")
					+ " sideIndex="
					+ sideIndex
					+ " on "
					+ lockedCount
					+ " ability instance(s).");
			}
		}
	}

	private static IEnumerable<object> EnumerateHeroAbilities(object logicHero)
	{
		if (logicHero == null)
			yield break;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var member in logicHero.GetType().GetMembers(flags))
		{
			object value = null;
			try
			{
				value = member switch
				{
					FieldInfo field => field.GetValue(logicHero),
					PropertyInfo property when property.CanRead && property.GetIndexParameters().Length == 0 => property.GetValue(logicHero),
					_ => null,
				};
			}
			catch
			{
				continue;
			}
			if (value == null || value is string || value.GetType().IsPrimitive)
				continue;
			if (value is IEnumerable enumerable and not IDictionary)
			{
				foreach (var item in enumerable)
				{
					if (item != null)
						yield return item;
				}
				continue;
			}
			yield return value;
		}
	}

	private static object TryGetMemberValue(object target, string name)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		var property = type.GetProperty(name, flags);
		if (property != null && property.CanRead && property.GetIndexParameters().Length == 0)
			return property.GetValue(target);
		var field = type.GetField(name, flags);
		return field?.GetValue(target);
	}

	private static void TrySetIntMember(object target, string name, int value)
	{
		if (target == null || string.IsNullOrWhiteSpace(name))
			return;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = target.GetType();
		var field = type.GetField(name, flags);
		if (field != null && field.FieldType == typeof(int) && !field.IsInitOnly)
		{
			field.SetValue(target, value);
			return;
		}
		var property = type.GetProperty(name, flags);
		if (property != null && property.PropertyType == typeof(int) && property.CanWrite)
			property.SetValue(target, value);
	}

	private static void GrantPendingFocus(TransferBattle transferBattle)
	{
		if (transferBattle?.sides == null)
			return;
		var sides = transferBattle.sides;
		for (var sideIndex = 0; sideIndex < sides.Length; sideIndex++)
		{
			var side = sides[sideIndex];
			if (side == null)
				continue;
			SideAssemblyPlan plan;
			lock (Gate)
			{
				if (!PlansBySideIndex.TryGetValue(sideIndex, out plan) || plan == null)
					continue;
				if (plan.NaturalTier < 3)
					continue;
				if (!FocusGrantedSideIndexes.Add(sideIndex))
					continue;
			}

			if (side.logicHero == null)
			{
				LogLimited(
					"Natural tier-3 Focus skipped: sideIndex="
					+ sideIndex
					+ " typed TransferSide.logicHero missing.");
				continue;
			}

			// Prefer the law-owner registry bridge (side-index / wrapper routes). The
			// reflection-only TransferSide.logicHero reader can miss the interop getter
			// even when the typed property is populated at plan time.
			if (!Homm3BattleUnitLawOwnerRegistry.TryResolveDataSideFromBattleSide(side, out var dataSide)
			    || dataSide == null)
			{
				LogLimited(
					"Natural tier-3 Focus skipped: sideIndex="
					+ sideIndex
					+ " Data.Side unresolved via law-owner registry (typedLogicHero=present).");
				continue;
			}
			if (!Homm3FocusNativeAdapter.TryGrantFocusToSide(dataSide, 1, out var failReason))
			{
				LogLimited(
					"Natural tier-3 Focus grant failed closed: sideIndex="
					+ sideIndex
					+ " "
					+ failReason);
				continue;
			}
			if (_loggedApplications++ < 32)
			{
				_log?.LogInfo(
					"HoMM3 Factory Split Assembly granted +1 battle-start Focus for Natural tier 3 sideIndex="
					+ sideIndex
					+ ".");
			}
		}
	}

	private static bool ApplyUnitBonuses(object unit, SideAssemblyPlan plan, int sideIndex)
	{
		if (unit == null || plan == null)
			return false;
		var magnitude = plan.Rank;
		if (magnitude < 1 || magnitude > 3)
			return false;

		var unitSid = TryResolveBattleUnitSid(unit) ?? "?";
		if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var unitKey, out var keyReason))
		{
			LogLimited(
				"unit apply skipped: native-key resolve failed: unitSid="
				+ unitSid
				+ " sideIndex="
				+ sideIndex
				+ " reason="
				+ keyReason);
			return false;
		}

		lock (Gate)
		{
			if (!BuffAppliedUnitKeys.Add(unitKey))
				return false;
		}

		try
		{
			if (plan.NaturalTier >= 1)
				RequireBuff(unit, BuffSid("ranged", magnitude), "natural ranged");
			if (plan.NaturalTier >= 2)
				RequireBuff(unit, BuffSid("mitigation", magnitude), "natural mitigation");
			if (plan.NaturalTier >= 4)
				RequireBuff(unit, CarapaceBuffSid, "natural Carapace");

			if (plan.IndustrialTier >= 1)
				RequireBuff(unit, BuffSid("melee", magnitude), "industrial melee");
			if (plan.IndustrialTier >= 2)
				RequireBuff(unit, BuffSid("speed", magnitude), "industrial speed");
			if (plan.IndustrialTier >= 3)
				RequireBuff(unit, BuffSid("initiative", magnitude), "industrial initiative");
		}
		catch
		{
			lock (Gate)
				BuffAppliedUnitKeys.Remove(unitKey);
			throw;
		}

		if (_loggedUnitApplications++ < 48)
		{
			var buffSids = CollectPlannedBuffSids(plan);
			var verified = VerifyBuffSidsPresent(unit, buffSids, out var missingBuffs);
			_log?.LogInfo(
				"HoMM3 Factory Split Assembly applied unit buffs: unitSid="
				+ unitSid
				+ " sideIndex="
				+ sideIndex
				+ " unitNativeKey="
				+ unitKey
				+ " naturalTiers="
				+ plan.NaturalTier
				+ " industrialTiers="
				+ plan.IndustrialTier
				+ " rank="
				+ plan.Rank
				+ " buffSids=["
				+ string.Join(",", buffSids)
				+ "] verified="
				+ (verified ? "true" : "false")
				+ (verified ? "" : " missing=[" + string.Join(",", missingBuffs) + "]")
				+ ".");
		}
		return true;
	}

	private static string TryResolveBattleUnitSid(object unit, object[] initArgs = null)
	{
		if (unit == null && initArgs == null)
			return null;
		if (unit != null
		    && Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(unit, out var registered)
		    && !string.IsNullOrWhiteSpace(registered))
			return NormalizeSid(registered);

		if (initArgs != null && initArgs.Length > 7)
		{
			var argSid = NormalizeSid(initArgs[7] as string);
			if (argSid != null)
				return argSid;
		}

		if (unit == null)
			return null;

		var transfer = TryGetMemberValue(unit, "transfer")
			?? TryGetMemberValue(unit, "TransferUnit")
			?? ReadMember(unit, GameSymbols.BattleEventLaws.UnitTransferUnitMembers)
			?? ReadMember(unit, GameSymbols.BattleVisual.BattleUnitTransferFields);
		if (transfer != null)
		{
			var transferSid = NormalizeSid(TryReadString(transfer, GameSymbols.BattleEventLaws.TransferUnitConfigSidMembers)
				?? TryGetMemberValue(transfer, "configSid") as string);
			if (transferSid != null)
				return transferSid;
		}

		return NormalizeSid(TryReadString(unit, GameSymbols.BattleVisual.BattleUnitConfigSidMembers)
			?? TryGetMemberValue(unit, "configSid") as string);
	}

	private static List<string> CollectPlannedBuffSids(SideAssemblyPlan plan)
	{
		var buffSids = new List<string>();
		if (plan == null)
			return buffSids;
		var magnitude = plan.Rank;
		if (magnitude < 1 || magnitude > 3)
			return buffSids;
		if (plan.NaturalTier >= 1)
			buffSids.Add(BuffSid("ranged", magnitude));
		if (plan.NaturalTier >= 2)
			buffSids.Add(BuffSid("mitigation", magnitude));
		if (plan.NaturalTier >= 4)
			buffSids.Add(CarapaceBuffSid);
		if (plan.IndustrialTier >= 1)
			buffSids.Add(BuffSid("melee", magnitude));
		if (plan.IndustrialTier >= 2)
			buffSids.Add(BuffSid("speed", magnitude));
		if (plan.IndustrialTier >= 3)
			buffSids.Add(BuffSid("initiative", magnitude));
		return buffSids;
	}

	private static bool VerifyBuffSidsPresent(object unit, IReadOnlyList<string> buffSids, out List<string> missing)
	{
		missing = new List<string>();
		if (unit == null || buffSids == null || buffSids.Count == 0)
			return true;
		foreach (var buffSid in buffSids)
		{
			if (string.IsNullOrWhiteSpace(buffSid))
				continue;
			if (!Homm3BuffDebuffNativeAdapter.TryRequireBuffSidFromReceiver(unit, buffSid, out _, out _))
				missing.Add(buffSid);
		}
		return missing.Count == 0;
	}

	private static void RequireBuff(object unit, string buffSid, string label)
	{
		if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(
			    unit,
			    buffSid,
			    unit,
			    AssemblyBuffLevel,
			    AssemblyBuffDuration,
			    AssemblyBuffValue,
			    true,
			    out _,
			    out var failReason))
		{
			throw new InvalidOperationException(label + " buff '" + buffSid + "' failed: " + failReason);
		}
	}

	private static string BuffSid(string kind, int magnitude)
	{
		return "homm3_factory_split_assembly_" + kind + "_" + magnitude;
	}

	private static List<string> CollectTransferSideUnitSids(TransferSide side, out string failReason)
	{
		failReason = null;
		if (side?.units == null)
		{
			failReason = "transfer unit array missing";
			return null;
		}

		var sids = new List<string>(side.units.Length);
		foreach (var unit in side.units)
		{
			if (unit == null)
			{
				failReason = "transfer unit array contains null";
				return null;
			}
			var sid = NormalizeSid(unit.configSid);
			if (sid == null)
			{
				failReason = "transfer unit has empty configSid";
				return null;
			}
			sids.Add(sid);
		}
		return sids;
	}

	private static bool TryResolveFactorySkillRank(
		TransferSide side,
		out int rank,
		out DataHero dataHero,
		out string failReason)
	{
		rank = 0;
		dataHero = null;
		failReason = null;
		if (side?.logicHero == null)
		{
			failReason = "battle LogicHero missing";
			return false;
		}
		if (_logicHeroDataHeroGetter == null || !_logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(side.logicHero))
		{
			failReason = "exact LogicHero data-Hero getter unavailable for side";
			return false;
		}

		try
		{
			dataHero = _logicHeroDataHeroGetter.Invoke(side.logicHero, Array.Empty<object>()) as DataHero;
		}
		catch (Exception ex)
		{
			failReason = "LogicHero data-Hero resolution failed: " + ex.GetBaseException().Message;
			return false;
		}
		if (dataHero == null)
		{
			failReason = "LogicHero data-Hero missing";
			return false;
		}

		var skills = ReadMember(dataHero, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		if (skills == null)
		{
			failReason = "data-Hero skills member missing";
			return false;
		}
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (skillList == null)
		{
			failReason = "HeroSkills list member missing";
			return false;
		}

		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, FactorySkillSid, StringComparison.Ordinal))
				continue;
			if (!TryReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers, out rank))
			{
				failReason = "Factory skill level member missing";
				return false;
			}
			if (rank < 1 || rank > 3)
			{
				failReason = "Factory skill level outside Basic/Advanced/Expert range: " + rank;
				rank = 0;
				return false;
			}
			return true;
		}

		var skillCount = TryReadCount(skillList, skillList.GetType());
		failReason = skillCount == null
			? "Factory faction skill not present"
			: "Factory faction skill not present (HeroSkills.Count=" + skillCount.Value + ")";
		return false;
	}

	private static bool HasHeroSubSkill(DataHero dataHero, string subSkillSid)
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
				if (string.Equals(sid, subSkillSid, StringComparison.Ordinal))
					return true;
			}
		}
		return false;
	}

	private static bool SideContainsFactoryUnit(TransferSide side)
	{
		if (side?.units == null)
			return false;
		foreach (var unit in side.units)
		{
			var sid = NormalizeSid(unit?.configSid);
			if (sid != null
			    && Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sid, out var factionSid)
			    && string.Equals(factionSid, FactoryFactionSid, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void ClearPlans(string reason)
	{
		lock (Gate)
		{
			PlansBySideIndex.Clear();
			FocusGrantedSideIndexes.Clear();
			FieldTriageUnlockedSideIndexes.Clear();
			BuffAppliedUnitKeys.Clear();
		}
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string fullName, string symbolId)
	{
		var type = assembly?.GetType(fullName);
		if (type != null)
			return type;
		throw new MissingMemberException(symbolId + " type not found: " + fullName);
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string symbolId)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly?.GetType(hint);
			if (type != null)
				return type;
		}
		throw new MissingMemberException(symbolId + " type not found from hints [" + string.Join(",", hints ?? Array.Empty<string>()) + "]");
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(
		Type type,
		Type returnType,
		Type[] parameterTypes,
		string methodName,
		string symbolId,
		Func<MethodInfo, bool> predicate)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal) || method.ReturnType != returnType)
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != parameterTypes.Length)
				continue;
			var exact = true;
			for (var index = 0; index < parameterTypes.Length; index++)
			{
				if (parameters[index].ParameterType == parameterTypes[index])
					continue;
				exact = false;
				break;
			}
			if (!exact || (predicate != null && !predicate(method)))
				continue;
			return method;
		}
		throw new MissingMethodException(symbolId + " exact method not found on " + (type?.FullName ?? "null"));
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = GameMember.FindOwnedPatchMethod(typeof(Homm3FactorySplitAssemblyRuntime), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3FactorySplitAssemblyRuntime), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static void UnpatchOwned(Harmony harmony, MethodInfo target, string patchName)
	{
		if (harmony == null || target == null)
			return;
		var patch = GameMember.FindOwnedPatchMethod(typeof(Homm3FactorySplitAssemblyRuntime), patchName);
		if (patch == null)
			return;
		try
		{
			harmony.Unpatch(target, patch);
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Factory Split Assembly rollback failed for " + patchName + ": " + ex.Message);
		}
	}

	private static object ReadMember(object target, IEnumerable<string> names)
	{
		if (target == null)
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			var property = type.GetProperty(name, flags);
			if (property != null && property.CanRead)
				return property.GetValue(target);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(target);
		}
		return null;
	}

	private static string TryReadString(object target, IEnumerable<string> names)
	{
		return ReadMember(target, names) as string;
	}

	private static bool TryReadInt(object target, IEnumerable<string> names, out int value)
	{
		value = 0;
		var raw = ReadMember(target, names);
		if (raw is int i)
		{
			value = i;
			return true;
		}
		return false;
	}

	/// <summary>
	/// Il2Cpp skill/subskill lists often implement <see cref="IEnumerable"/> but yield
	/// nothing under managed foreach. Prefer Count + int indexer (live-positive pattern
	/// from skeletal/necromancy and Dominion hooks). Fall back to IEnumerable only when
	/// indexed enumeration is unavailable.
	/// </summary>
	private static IEnumerable<object> EnumerateObjects(object list)
	{
		if (list == null)
			yield break;

		var type = list.GetType();
		var count = TryReadCount(list, type);
		var indexer = ResolveIntIndexer(type);
		if (count != null && count.Value > 0 && indexer != null)
		{
			for (var i = 0; i < count.Value; i++)
			{
				object item = null;
				try
				{
					item = indexer.Invoke(list, new object[] { i });
				}
				catch
				{
				}

				if (item != null)
					yield return item;
			}

			yield break;
		}

		if (list is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
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
		catch
		{
		}

		try
		{
			var method = type.GetMethod("get_Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (method != null && method.GetParameters().Length == 0 && method.Invoke(value, Array.Empty<object>()) is int methodCount)
				return methodCount;
		}
		catch
		{
		}

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

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "null";
		var parameters = method.GetParameters().Select(parameter => parameter.ParameterType.Name);
		return method.DeclaringType?.FullName + "." + method.Name + "(" + string.Join(",", parameters) + ")";
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ >= 48)
			return;
		_log?.LogWarning("HoMM3 Factory Split Assembly runtime: " + message);
	}
}
