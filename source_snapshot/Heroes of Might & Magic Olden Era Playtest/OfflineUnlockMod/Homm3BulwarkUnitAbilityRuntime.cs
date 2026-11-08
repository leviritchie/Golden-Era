using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;

namespace OfflineUnlockMod;

/// <summary>
/// Bulwark unit-ability additive runtimes that sit beside Focus actives:
/// Jotunn Frostbound Skies enemy flyer Speed slow at battle start.
/// War Mammoth Defend Defense, Yeti recovery, and Argali adjacent spell-amp remain
/// scaffolded fail-closed until their event/geometry surfaces are live-proven.
///
/// Ownership mirrors Factory Split Assembly / Death March (live-negative 2026-07-24):
/// BattleLogic.Init postfix must NOT clear flyer-Slow plans. Unit.Init is not proven
/// nested inside Init; clearing in postfix made Unit.Init apply silent (planCount==0)
/// while plans had been built. Register the shared Unit.Init owner so the registry
/// tracks units, apply from SnapshotUnits at Init postfix, and use its named consumer
/// for late/nested construction while plans remain until the next battle prefix.
///
/// Plans are keyed by the native Il2Cpp pointer of TransferSide (enemy side to
/// slow), not RuntimeHelpers.GetHashCode. Unit.Init arg[2] is the battle-side
/// wrapper and must be bridged via BattleSideTransferSideMembers; bridged
/// TransferSide proxies often carry a different managed identity than
/// TransferBattle.sides even when the native object matches.
/// Flyer classification reads Core unit-logic stats.moveType == "fly" only
/// (GameSymbols.BattleEventLaws.UnitConfigFlyMoveTypeValue). Apply dedupe keys
/// battle units by native pointer. Buffs are faction-owned speed-only rows.
/// Proof tier: registration + source/static. Combat live-positive unproven.
/// </summary>
internal static class Homm3BulwarkUnitAbilityRuntime
{
	private const string FlyerSlowBuffSidBase = "homm3_bulwark_frostbound_skies_speed_1";
	private const string FlyerSlowBuffSidWarlord = "homm3_bulwark_frostbound_skies_speed_2";
	private const int FlyerSlowDuration = 99;
	private const int FlyerSlowLevel = 0;
	private const int FlyerSlowValueBase = 1;
	private const int FlyerSlowValueWarlord = 2;

	private static readonly HashSet<string> JotunnBaseSids = new(StringComparer.Ordinal)
	{
		"h3_jotunn",
	};
	private static readonly HashSet<string> JotunnWarlordSids = new(StringComparer.Ordinal)
	{
		"h3_jotunn_warlord",
		"h3_jotunn_upg_alt",
	};

	private static readonly object Gate = new();
	private static readonly Dictionary<long, int> FlyerSlowMagnitudeByEnemySideKey = new();
	private static readonly HashSet<long> SlowAppliedUnitKeys = new();

	private static bool _registered;
	private static ManualLogSource _log;
	private static int _loggedApplications;
	private static int _loggedSkips;
	private static int _loggedUnitInitProbes;

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
				"homm3.bulwark.unitAbility.battleLogic");
			var transferBattleType = ResolveRequiredTypeByName(
				hexAssembly,
				GameSymbols.DraconicDominion.TransferBattleTypeName,
				"homm3.bulwark.unitAbility.transferBattle");
			battleLogicInitMethod = ResolveRequiredExactNamedMethod(
				battleLogicType,
				typeof(void),
				new[] { typeof(int), transferBattleType, typeof(bool), typeof(bool) },
				GameSymbols.DraconicDominion.BattleLogicInit.NameHints[0],
				"homm3.bulwark.unitAbility.battleLogic.init",
				method => !method.IsStatic);

			// SnapshotUnits apply at BattleLogic.Init postfix requires the shared
			// law-owner Unit.Init registry. Without it, registry stays empty and
			// army-wide flyer Slow cannot enumerate live units.
			if (!Homm3RuntimeMechanicHooks.TryRegisterSharedUnitInit(harmony, _log))
			{
				throw new InvalidOperationException(
					"homm3.bulwark.unitAbility.sharedUnitInit registry failed closed; SnapshotUnits apply ownership unavailable");
			}

			PatchPrefix(harmony, battleLogicInitMethod, nameof(PrefixBattleLogicInit));
			PatchPostfix(harmony, battleLogicInitMethod, nameof(PostfixBattleLogicInit));
			registrationSummary = "HoMM3 Bulwark unit-ability runtime registered on "
				+ FormatMethod(battleLogicInitMethod)
				+ " with shared Unit.Init consumer. Jotunn flyer Slow is source-wired; Defend Defense / Yeti recovery / Argali aura remain fail-closed scaffolds. Combat unproven.";
			if (!Homm3BattleUnitLawOwnerRegistry.TryRegisterUnitInitConsumer(
					"homm3.bulwark.unitAbility",
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
			_log?.LogWarning("HoMM3 Bulwark unit-ability runtime not registered; exact startup surface missing: " + ex.Message);
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
			BuildFlyerSlowPlans(__1 as TransferBattle);
		}
		catch (Exception ex)
		{
			ClearPlans("battle-logic-init-prefix-failure");
			LogLimited("bulwark flyer Slow plan build failed closed: " + ex.Message);
		}
	}

	private static void PostfixBattleLogicInit(object __1)
	{
		if (!_registered)
			return;
		try
		{
			// Death March / Split Assembly ownership: do not clear plans here — late
			// Unit.Init must still resolve the same TransferSide keys until the next
			// battle prefix.
			ApplyPlannedFlyerSlowToRegisteredUnits("battle-logic-init-postfix");
		}
		catch (Exception ex)
		{
			LogLimited("bulwark flyer Slow postfix apply failed closed: " + ex.Message);
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
				planCount = FlyerSlowMagnitudeByEnemySideKey.Count;

			var unitSid = TryResolveBattleUnitSid(__instance, __args) ?? "?";
			var flyer = IsFlyerUnit(__instance);

			if (planCount == 0)
			{
				if (flyer && _loggedUnitInitProbes++ < 24)
				{
					LogLimited(
						"unit init while plans empty: unitSid="
						+ unitSid
						+ " battleSideType="
						+ (battleSideArg.GetType().FullName ?? "?")
						+ " (flyer Slow apply window already closed or never opened)");
				}
				return;
			}

			if (_loggedUnitInitProbes++ < 24)
			{
				_log?.LogInfo(
					"HoMM3 Bulwark flyer Slow unit init probe: unitSid="
					+ unitSid
					+ " flyer="
					+ flyer
					+ " activePlans="
					+ planCount
					+ " battleSideType="
					+ (battleSideArg.GetType().FullName ?? "?")
					+ ".");
			}

			// Unit.Init arg[2] is the live battle-side wrapper, not TransferSide.
			// Plans are keyed by native TransferSide pointer from TransferBattle.sides.
			if (!TryResolveTransferSideFromUnitInitArg(battleSideArg, out var transferSide, out var resolveReason))
			{
				if (flyer)
				{
					LogLimited(
						"unit init TransferSide resolve failed while plans active: unitSid="
						+ unitSid
						+ " battleSideType="
						+ (battleSideArg.GetType().FullName ?? "?")
						+ " reason="
						+ resolveReason);
				}
				return;
			}

			if (!TryResolveTransferSidePlanKey(transferSide, out var planKey, out var planKeyReason))
			{
				if (flyer)
				{
					LogLimited(
						"unit init TransferSide plan-key resolve failed: unitSid="
						+ unitSid
						+ " reason="
						+ planKeyReason
						+ " managedHash="
						+ RuntimeHelpers.GetHashCode(transferSide)
						+ " activePlans="
						+ planCount
						+ " planKeys=["
						+ FormatPlanKeys()
						+ "]");
				}
				return;
			}

			int magnitude;
			lock (Gate)
			{
				if (!FlyerSlowMagnitudeByEnemySideKey.TryGetValue(planKey, out magnitude) || magnitude < 1)
				{
					if (flyer)
					{
						LogLimited(
							"unit init plan miss: unitSid="
							+ unitSid
							+ " transferSideNativeKey="
							+ planKey
							+ " managedHash="
							+ RuntimeHelpers.GetHashCode(transferSide)
							+ " activePlans="
							+ FlyerSlowMagnitudeByEnemySideKey.Count
							+ " planKeys=["
							+ FormatPlanKeys()
							+ "]");
					}
					return;
				}
			}

			if (!flyer)
				return;

			TryApplyFlyerSlow(__instance, magnitude, unitSid);
		}
		catch (Exception ex)
		{
			LogLimited("bulwark unit init flyer Slow failed closed: " + ex.Message);
		}
	}

	private static void OnSharedUnitInit(object unit, object[] args)
	{
		if (_registered)
			PostfixUnitInit(unit, args);
	}

	private static void ApplyPlannedFlyerSlowToRegisteredUnits(string stage)
	{
		int planCount;
		lock (Gate)
			planCount = FlyerSlowMagnitudeByEnemySideKey.Count;
		if (planCount == 0)
			return;

		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		if (units.Count == 0)
		{
			LogLimited(
				"plans active at "
				+ stage
				+ " but battle-unit registry empty (unitCount=0); keeping plans for Unit.Init apply window");
			return;
		}

		var matched = 0;
		var applied = 0;
		var sampledMissKeys = new List<string>(8);
		foreach (var snapshot in units)
		{
			if (snapshot.Unit == null)
				continue;
			// Snapshot TransferSide may be the battle-side wrapper stored at Unit.Init.
			if (!TryResolveTransferSideFromUnitInitArg(snapshot.TransferSide, out var transferSide, out _))
				continue;
			if (!TryResolveTransferSidePlanKey(transferSide, out var planKey, out _))
			{
				if (sampledMissKeys.Count < 8)
					sampledMissKeys.Add("keyResolveFail:managedHash=" + RuntimeHelpers.GetHashCode(transferSide));
				continue;
			}
			int magnitude;
			lock (Gate)
			{
				if (!FlyerSlowMagnitudeByEnemySideKey.TryGetValue(planKey, out magnitude) || magnitude < 1)
				{
					if (sampledMissKeys.Count < 8)
					{
						sampledMissKeys.Add(
							"nativeKey="
							+ planKey
							+ ":managedHash="
							+ RuntimeHelpers.GetHashCode(transferSide));
					}
					continue;
				}
			}
			matched++;
			if (!IsFlyerUnit(snapshot.Unit))
				continue;
			var unitSid = TryResolveBattleUnitSid(snapshot.Unit) ?? "?";
			if (TryApplyFlyerSlow(snapshot.Unit, magnitude, unitSid))
				applied++;
		}

		if (matched == 0)
		{
			LogLimited(
				"plans active at "
				+ stage
				+ " but zero registered units matched TransferSide plan keys; registryUnits="
				+ units.Count
				+ " activePlans="
				+ planCount
				+ " planKeys=["
				+ FormatPlanKeys()
				+ "] sampleUnitKeys=["
				+ string.Join(",", sampledMissKeys)
				+ "]");
			return;
		}

		if (_loggedApplications++ < 32)
		{
			_log?.LogInfo(
				"HoMM3 Bulwark flyer Slow postfix registry apply: stage="
				+ stage
				+ " matched="
				+ matched
				+ " newlyApplied="
				+ applied
				+ " registryUnits="
				+ units.Count
				+ " activePlans="
				+ planCount
				+ ".");
		}
	}

	private static bool TryApplyFlyerSlow(object unit, int magnitude, string unitSid)
	{
		if (unit == null || magnitude < 1)
			return false;

		if (!Homm3DirectStateIdentity.TryResolveKey(unit, out var unitKey, out var keyReason))
		{
			LogLimited(
				"bulwark flyer Slow skipped: unit native-key resolve failed: unitSid="
				+ (unitSid ?? "?")
				+ " reason="
				+ keyReason);
			return false;
		}

		lock (Gate)
		{
			if (!SlowAppliedUnitKeys.Add(unitKey))
				return false;
		}

		var buffSid = magnitude >= FlyerSlowValueWarlord ? FlyerSlowBuffSidWarlord : FlyerSlowBuffSidBase;
		try
		{
			if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(
				    unit,
				    buffSid,
				    unit,
				    FlyerSlowLevel,
				    FlyerSlowDuration,
				    0,
				    true,
				    out _,
				    out var failReason))
			{
				lock (Gate)
					SlowAppliedUnitKeys.Remove(unitKey);
				LogLimited(
					"bulwark flyer Slow buff failed closed: unitSid="
					+ (unitSid ?? "?")
					+ " magnitude="
					+ magnitude
					+ " buffSid="
					+ buffSid
					+ " reason="
					+ failReason);
				return false;
			}
		}
		catch
		{
			lock (Gate)
				SlowAppliedUnitKeys.Remove(unitKey);
			throw;
		}

		if (_loggedApplications++ < 48)
		{
			_log?.LogInfo(
				"HoMM3 Bulwark applied Frostbound Skies flyer Slow: unitSid="
				+ (unitSid ?? "?")
				+ " magnitude="
				+ magnitude
				+ " buffSid="
				+ buffSid
				+ " nativeKey="
				+ unitKey
				+ ".");
		}
		return true;
	}

	/// <summary>
	/// Live-proven bridge (2026-06-20 law-owner registry): battle-side wrapper
	/// <c>eir</c> exposes TransferSide via <see cref="GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers"/>.
	/// </summary>
	private static bool TryResolveTransferSideFromUnitInitArg(
		object battleSideArg,
		out object transferSide,
		out string failReason)
	{
		transferSide = null;
		failReason = null;
		if (battleSideArg == null)
		{
			failReason = "battle side arg null";
			return false;
		}
		if (battleSideArg is TransferSide typed)
		{
			transferSide = typed;
			return true;
		}

		if (!TryReadNamedObject(
			    battleSideArg,
			    GameSymbols.CustomFactionLawRuntime.BattleSideTransferSideMembers,
			    out transferSide)
		    || transferSide == null)
		{
			failReason =
				"battle side "
				+ (battleSideArg.GetType().FullName ?? "?")
				+ " exposed no TransferSide via BattleSideTransferSideMembers";
			return false;
		}

		if (transferSide is TransferSide)
			return true;
		if (string.Equals(transferSide.GetType().FullName, typeof(TransferSide).FullName, StringComparison.Ordinal))
			return true;

		failReason =
			"battle side "
			+ (battleSideArg.GetType().FullName ?? "?")
			+ " TransferSide member resolved to unexpected type "
			+ (transferSide.GetType().FullName ?? "?");
		transferSide = null;
		return false;
	}

	private static bool TryResolveTransferSidePlanKey(object transferSide, out long planKey, out string failReason)
	{
		return Homm3DirectStateIdentity.TryResolveKey(transferSide, out planKey, out failReason);
	}

	private static string FormatPlanKeys()
	{
		lock (Gate)
			return string.Join(",", FlyerSlowMagnitudeByEnemySideKey.Keys);
	}

	private static bool TryReadNamedObject(object target, string[] names, out object value)
	{
		value = null;
		if (target == null || names == null)
			return false;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.CanRead && property.GetIndexParameters().Length == 0)
					{
						value = property.GetValue(target, null);
						if (value != null)
							return true;
					}
				}
				catch
				{
				}

				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method == null || method.ReturnType == typeof(void) || method.ContainsGenericParameters)
						continue;
					value = method.Invoke(target, Array.Empty<object>());
					if (value != null)
						return true;
				}
				catch
				{
				}

				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						value = field.GetValue(target);
						if (value != null)
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

	private static void BuildFlyerSlowPlans(TransferBattle transferBattle)
	{
		if (transferBattle?.sides == null)
			return;
		var sides = transferBattle.sides;
		for (var i = 0; i < sides.Length; i++)
		{
			var side = sides[i];
			if (side == null)
				continue;
			var magnitude = ResolveJotunnFlyerSlowMagnitude(side);
			if (magnitude < 1)
				continue;
			for (var j = 0; j < sides.Length; j++)
			{
				if (i == j)
					continue;
				var enemy = sides[j];
				if (enemy == null)
					continue;
				if (!TryResolveTransferSidePlanKey(enemy, out var key, out var keyReason))
				{
					LogLimited("flyer Slow enemy side skipped: TransferSide plan-key resolve failed: " + keyReason);
					continue;
				}
				lock (Gate)
				{
					if (!FlyerSlowMagnitudeByEnemySideKey.TryGetValue(key, out var existing) || magnitude > existing)
						FlyerSlowMagnitudeByEnemySideKey[key] = magnitude;
				}
			}

			if (_loggedApplications++ < 24)
			{
				var enemyKeys = new List<string>();
				for (var index = 0; index < sides.Length; index++)
				{
					if (index == i || sides[index] == null)
						continue;
					if (TryResolveTransferSidePlanKey(sides[index], out var enemyKey, out _))
						enemyKeys.Add(enemyKey.ToString());
				}
				_log?.LogInfo(
					"HoMM3 Bulwark flyer Slow planned: jotunnSideMagnitude="
					+ magnitude
					+ " enemySideNativeKeys=["
					+ string.Join(",", enemyKeys)
					+ "].");
			}
		}
	}

	private static int ResolveJotunnFlyerSlowMagnitude(TransferSide side)
	{
		var best = 0;
		if (side?.units == null)
			return best;
		foreach (var unit in side.units)
		{
			var sid = NormalizeSid(unit?.configSid);
			if (string.IsNullOrEmpty(sid))
				continue;
			if (JotunnWarlordSids.Contains(sid))
				best = Math.Max(best, FlyerSlowValueWarlord);
			else if (JotunnBaseSids.Contains(sid))
				best = Math.Max(best, FlyerSlowValueBase);
		}
		return best;
	}

	private static string NormalizeSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		return sid.Trim();
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

	private static bool IsFlyerUnit(object unit)
	{
		if (unit == null)
			return false;

		var logicConfig = ReadMember(unit, GameSymbols.BattleEventLaws.UnitLogicConfigMembers);
		if (logicConfig == null)
			return false;

		var stats = ReadMember(logicConfig, GameSymbols.BattleEventLaws.UnitConfigStatsMembers);
		if (stats == null)
			return false;

		var moveType = TryReadString(stats, GameSymbols.BattleEventLaws.UnitConfigStatsMoveTypeMembers);
		return string.Equals(
			moveType,
			GameSymbols.BattleEventLaws.UnitConfigFlyMoveTypeValue,
			StringComparison.Ordinal);
	}

	private static void ClearPlans(string reason)
	{
		lock (Gate)
		{
			FlyerSlowMagnitudeByEnemySideKey.Clear();
			SlowAppliedUnitKeys.Clear();
		}
	}

	private static void PatchPrefix(Harmony harmony, MethodInfo target, string prefixName)
	{
		var prefix = GameMember.FindOwnedPatchMethod(typeof(Homm3BulwarkUnitAbilityRuntime), prefixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, prefix, out var reason))
			throw new MissingMethodException("prefix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, prefix: new HarmonyMethod(prefix));
	}

	private static void PatchPostfix(Harmony harmony, MethodInfo target, string postfixName)
	{
		var postfix = GameMember.FindOwnedPatchMethod(typeof(Homm3BulwarkUnitAbilityRuntime), postfixName);
		if (!GameMember.IsHarmonyPatchCompatible(target, postfix, out var reason))
			throw new MissingMethodException("postfix incompatible for " + FormatMethod(target) + ": " + reason);
		harmony.Patch(target, postfix: new HarmonyMethod(postfix));
	}

	private static void UnpatchOwned(Harmony harmony, MethodInfo target, string patchName)
	{
		if (harmony == null || target == null)
			return;
		var patch = GameMember.FindOwnedPatchMethod(typeof(Homm3BulwarkUnitAbilityRuntime), patchName);
		if (patch == null)
			return;
		try
		{
			harmony.Unpatch(target, patch);
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Bulwark unit-ability rollback failed for " + patchName + ": " + ex.Message);
		}
	}

	private static Type ResolveRequiredTypeByHint(Assembly assembly, string[] hints, string label)
	{
		foreach (var hint in hints ?? Array.Empty<string>())
		{
			var type = assembly.GetType(hint, false);
			if (type != null)
				return type;
		}
		throw new TypeLoadException(label + " type not found from hints");
	}

	private static Type ResolveRequiredTypeByName(Assembly assembly, string name, string label)
	{
		var type = assembly.GetType(name, false)
			?? throw new TypeLoadException(label + " type '" + name + "' not found");
		return type;
	}

	private static MethodInfo ResolveRequiredExactNamedMethod(
		Type type,
		Type returnType,
		Type[] parameters,
		string nameHint,
		string label,
		Func<MethodInfo, bool> predicate)
	{
		foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (!string.Equals(method.Name, nameHint, StringComparison.Ordinal))
				continue;
			if (method.ReturnType != returnType)
				continue;
			var methodParams = method.GetParameters();
			if (methodParams.Length != parameters.Length)
				continue;
			var match = true;
			for (var i = 0; i < parameters.Length; i++)
			{
				if (methodParams[i].ParameterType != parameters[i])
				{
					match = false;
					break;
				}
			}
			if (!match || (predicate != null && !predicate(method)))
				continue;
			return method;
		}
		throw new MissingMethodException(label + " method '" + nameHint + "' not found");
	}

	private static string FormatMethod(MethodInfo method)
	{
		if (method == null)
			return "<null>";
		var parameters = method.GetParameters().Select(parameter => parameter.ParameterType.Name);
		return method.DeclaringType?.FullName + "." + method.Name + "(" + string.Join(",", parameters) + ")";
	}

	private static void LogLimited(string message)
	{
		if (_loggedSkips++ < 48)
			_log?.LogWarning("HoMM3 Bulwark unit-ability: " + message);
	}
}
