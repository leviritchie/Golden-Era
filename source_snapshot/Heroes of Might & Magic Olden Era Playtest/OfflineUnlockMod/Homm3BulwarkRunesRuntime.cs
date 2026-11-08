using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using DataHero = Hex.Session.Data.Hero;

namespace OfflineUnlockMod;

/// <summary>
/// Bulwark Runes combat owner. Patches only the native logic event hub
/// (<c>eda</c> / <see cref="GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints"/>)
/// plus the token-pinned ability-commit executor on
/// <c>ObjectPublicObceInBoInceAbObELInUnique</c>
/// (<see cref="GameSymbols.BulwarkRunesLaws.AbilityCommitExecute"/>).
/// Does not patch the <c>edb</c> view hub and does not depend on the contested
/// battle-unit init surface. Does not patch <c>eda</c> CastAbility Method_34
/// (LIVE-NEGATIVE map-load stack overflow).
///
/// HotA-style gains (Rune Brand and Possesses Runes excluded):
/// successful DefaultAttack / AlternativeAttack / Ability cast / CounterAttack
/// +1 (awarded directly in the commit-execute postfix after void success);
/// first positive damage received during an enclosing action +2;
/// Defend (logic Skip) +3; Wait / movement-only / cancelled casts / zero damage
/// / immunity award nothing. Caps 3/6/9. Nine incremental threshold buffs apply
/// once each via <see cref="Homm3BuffDebuffNativeAdapter"/> add-and-dispatch
/// when gains fire.
///
/// Place <c>homm3_bulwark_runes_correlation_pilot.flag</c> next to the plugin DLL
/// for a temporary read-only correlation probe (logs native signals; no mutations).
/// Documentation remains runtime-pending until installed gameplay proof.
/// </summary>
internal static class Homm3BulwarkRunesRuntime
{
	internal const string CorrelationPilotFlagName = "homm3_bulwark_runes_correlation_pilot.flag";
	internal const string RuneBuffSidPrefix = "homm3_bulwark_rune_level_";
	internal const string BulwarkSkillSid = "skill_faction_homm3_bulwark";
	internal const int CapBasic = 3;
	internal const int CapAdvanced = 6;
	internal const int CapExpert = 9;
	private const int RuneBuffDuration = 99;
	private const int RuneBuffValue = 1;
	private const int LogCap = 400;

	private static readonly object Gate = new();
	private static readonly Dictionary<long, StackRuneState> StackStateByNativeKey = new();
	private static readonly Dictionary<long, ActionCorrelation> ActionByUnitKey = new();
	/// <summary>
	/// Wait arm outside ActionCorrelation: ActionStarted intervenes between
	/// Method_15 (Wait) and Method_47 on dual-raise Wait, and would wipe a flag
	/// stored on the action bag.
	/// </summary>
	private static readonly Dictionary<long, bool> WaitArmedByUnitKey = new();
	private static readonly HashSet<string> AwardedObservationKeys = new();

	private static bool _registered;
	private static ManualLogSource _log;
	private static bool _probeOnly;
	private static int _patched;
	private static int _logged;
	private static MethodInfo _logicHeroDataHeroGetter;

	[ThreadStatic]
	private static bool _observing;

	private enum GainKind
	{
		AttackOrCast = 1,
		DamageTaken = 2,
		Defend = 3,
	}

	private sealed class StackRuneState
	{
		internal int Level;
		internal readonly HashSet<int> AppliedThresholds = new();
		internal string UnitSid;
		internal int SkillRank;
	}

	private sealed class ActionCorrelation
	{
		internal long UnitKey;
		internal int Sequence;
		internal bool DamageAwarded;
		internal bool AttackOrCastAwarded;
		internal bool DefendAwarded;
		internal bool WaitObserved;
		internal bool CancelledCast;
	}

	/// <summary>
	/// Fail-closed registration of logic-hub patches. Probe flag forces read-only
	/// correlation logging; otherwise mutations apply through the same owner.
	/// </summary>
	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		_log = log;
		if (_registered)
			return;
		_registered = true;
		if (harmony == null)
		{
			_log?.LogWarning("HoMM3 Bulwark Runes failed closed: harmony null.");
			return;
		}

		_probeOnly = File.Exists(Path.Combine(Paths.PluginPathSafe(), CorrelationPilotFlagName));
		if (_probeOnly)
		{
			_log?.LogWarning(
				"HoMM3 Bulwark Runes correlation pilot flag present. "
				+ "Log-only probe armed; Rune Level mutations withheld.");
		}

		try
		{
			_logicHeroDataHeroGetter = ResolveLogicHeroDataHeroGetter();
			_patched = PatchLogicHub(harmony);
			if (_patched <= 0)
			{
				_log?.LogWarning(
					"HoMM3 Bulwark Runes failed closed: no exact eda logic-hub dispatchers patched.");
				return;
			}

			_log?.LogInfo(
				"HoMM3 Bulwark Runes logic-hub owner registered patches="
				+ _patched.ToString(CultureInfo.InvariantCulture)
				+ " probeOnly="
				+ _probeOnly
				+ " (Rune Brand / Possesses Runes excluded).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Bulwark Runes failed closed during registration: " + ex.Message);
		}
	}

	internal static int ResolveCap(int skillRank)
	{
		if (skillRank >= 3)
			return CapExpert;
		if (skillRank >= 2)
			return CapAdvanced;
		if (skillRank >= 1)
			return CapBasic;
		return 0;
	}

	/// <summary>Incremental Offence granted when crossing threshold level.</summary>
	internal static int IncrementalOffenceForThreshold(int threshold)
	{
		return threshold == 1 || threshold == 4 || threshold == 7 ? 2 : 0;
	}

	/// <summary>Incremental Defence granted when crossing threshold level.</summary>
	internal static int IncrementalDefenceForThreshold(int threshold)
	{
		return threshold == 2 || threshold == 5 || threshold == 8 ? 2 : 0;
	}

	/// <summary>Incremental Speed granted when crossing threshold level.</summary>
	internal static int IncrementalSpeedForThreshold(int threshold)
	{
		return threshold == 3 || threshold == 6 || threshold == 9 ? 1 : 0;
	}

	internal static int AttackBonusForLevel(int level)
	{
		var total = 0;
		for (var t = 1; t <= level && t <= CapExpert; t++)
			total += IncrementalOffenceForThreshold(t);
		return total;
	}

	internal static int DefenseBonusForLevel(int level)
	{
		var total = 0;
		for (var t = 1; t <= level && t <= CapExpert; t++)
			total += IncrementalDefenceForThreshold(t);
		return total;
	}

	internal static int SpeedBonusForLevel(int level)
	{
		var total = 0;
		for (var t = 1; t <= level && t <= CapExpert; t++)
			total += IncrementalSpeedForThreshold(t);
		return total;
	}

	internal static string BuffSidForLevel(int level)
	{
		if (level < 1 || level > CapExpert)
			return null;
		return RuneBuffSidPrefix + level;
	}

	internal static int GainForDefend() => 3;

	internal static int GainForDamageTakenOncePerAction() => 2;

	internal static int GainForAttackOrCast() => 1;

	internal static bool IsWarMachineExcluded(string unitSid)
	{
		if (string.IsNullOrWhiteSpace(unitSid))
			return true;
		var sid = unitSid.Trim();
		return sid.IndexOf("ballista", StringComparison.OrdinalIgnoreCase) >= 0
			|| sid.IndexOf("catapult", StringComparison.OrdinalIgnoreCase) >= 0
			|| sid.IndexOf("first_aid", StringComparison.OrdinalIgnoreCase) >= 0
			|| sid.IndexOf("ammo_cart", StringComparison.OrdinalIgnoreCase) >= 0
			|| sid.IndexOf("cannon", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	internal static void ClearBattleState(string reason)
	{
		lock (Gate)
		{
			WaitArmedByUnitKey.Clear();
			StackStateByNativeKey.Clear();
			ActionByUnitKey.Clear();
			AwardedObservationKeys.Clear();
		}
		_log?.LogInfo("HoMM3 Bulwark Runes battle state cleared: reason=" + reason);
	}

	/// <summary>
	/// Pure correlation helper used by the expensive fixture and by live hooks.
	/// Returns the gain to apply (0 when excluded / already awarded / Wait).
	/// </summary>
	private static int CorrelateGain(
		ActionCorrelation action,
		GainKind kind,
		string observationKey,
		bool positiveDamage,
		bool immuneOrFailed,
		bool cancelledCast,
		out string failReason)
	{
		failReason = null;
		if (action == null)
		{
			failReason = "no enclosing action";
			return 0;
		}
		if (cancelledCast || action.CancelledCast)
		{
			action.CancelledCast = true;
			failReason = "cancelled cast";
			return 0;
		}

		lock (Gate)
		{
			if (!string.IsNullOrEmpty(observationKey) && !AwardedObservationKeys.Add(observationKey))
			{
				failReason = "duplicate observation";
				return 0;
			}
		}

		switch (kind)
		{
			case GainKind.AttackOrCast:
				if (action.AttackOrCastAwarded)
				{
					failReason = "attack/cast already awarded this action";
					return 0;
				}
				action.AttackOrCastAwarded = true;
				return GainForAttackOrCast();
			case GainKind.DamageTaken:
				if (immuneOrFailed || !positiveDamage)
				{
					failReason = immuneOrFailed ? "immunity/failed damage" : "zero damage";
					return 0;
				}
				if (action.DamageAwarded)
				{
					failReason = "damage already awarded this action";
					return 0;
				}
				action.DamageAwarded = true;
				return GainForDamageTakenOncePerAction();
			case GainKind.Defend:
				if (action.DefendAwarded)
				{
					failReason = "Defend already awarded this action";
					return 0;
				}
				action.DefendAwarded = true;
				return GainForDefend();
			default:
				failReason = "unknown gain kind";
				return 0;
		}
	}

	private static int PatchLogicHub(Harmony harmony)
	{
		var hubType = ResolveLogicEventHubType();
		if (hubType == null)
		{
			_log?.LogWarning("HoMM3 Bulwark Runes failed closed: eda logic event hub type not found.");
			return 0;
		}

		// LIVE-NEGATIVE: do not Harmony-patch eda CastAbility Method_34 /
		// ChangeAbility Method_23 (map-load stack overflow). Attack/cast/counter
		// +1 is owned by the token-pinned AbilityCommitExecute postfix.
		// Xref retained (do not Patch): GameSymbols.BattleEventLaws.CastAbilityDispatcher
		// and GameSymbols.BattleEventLaws.ChangeAbilityDispatcher.
		_ = GameSymbols.BattleEventLaws.CastAbilityDispatcher;
		_ = GameSymbols.BattleEventLaws.ChangeAbilityDispatcher;
		var patched = 0;
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.ActionStartedDispatcher, nameof(PostfixActionStarted));
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.ActionEndedDispatcher, nameof(PostfixActionEnded));
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher, nameof(PostfixObjectTookDamage));
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.DamageFailedDispatcher, nameof(PostfixDamageFailed));
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.SkipDispatcher, nameof(PostfixSkipDefend));
		patched += PatchDispatcher(harmony, hubType, GameSymbols.BattleEventLaws.WaitDispatcher, nameof(PostfixWait));
		patched += PatchAbilityCommitExecute(harmony);
		return patched;
	}

	private static int PatchAbilityCommitExecute(Harmony harmony)
	{
		var type = ResolveAbilityRuntimeType();
		if (type == null)
		{
			_log?.LogWarning(
				"HoMM3 Bulwark Runes failed closed: ability runtime type not found; "
				+ "attack/cast/counter +1 disabled.");
			return 0;
		}

		var method = ResolveAbilityCommitExecuteMethod(type);
		if (method == null)
		{
			_log?.LogWarning(
				"HoMM3 Bulwark Runes failed closed: token-pinned AbilityCommitExecute MethodInfo not found "
				+ "(expected "
				+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecute.NameHints[0]
				+ " token="
				+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecuteMetadataToken.ToString(CultureInfo.InvariantCulture)
				+ " RVA="
				+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecuteRvaHex
				+ ").");
			return 0;
		}

		var postfix = AccessTools.Method(typeof(Homm3BulwarkRunesRuntime), nameof(PostfixAbilityCommitExecute));
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			_log?.LogWarning("HoMM3 Bulwark Runes refused AbilityCommitExecute patch: " + reason);
			return 0;
		}

		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		LogAbilityCommitPin(type, method);
		return 1;
	}

	private static void LogAbilityCommitPin(Type type, MethodInfo method)
	{
		var parameters = method.GetParameters();
		var paramText = parameters.Length == 0
			? "()"
			: "(" + string.Join(", ", Array.ConvertAll(parameters, p => p.ParameterType.FullName ?? p.ParameterType.Name)) + ")";
		var nativeText = TryReadNativeMethodPointers(type, method, out var methodInfoPtr, out var methodPointer)
			? " methodInfoPtr=0x" + methodInfoPtr.ToString("X")
			  + " methodPointer=0x" + methodPointer.ToString("X")
			: " methodInfoPtr=? methodPointer=?";
		_log?.LogInfo(
			"HoMM3 Bulwark Runes AbilityCommitExecute pin"
			+ " type="
			+ type.FullName
			+ " method="
			+ method.Name
			+ " return="
			+ (method.ReturnType.FullName ?? method.ReturnType.Name)
			+ " params="
			+ paramText
			+ " token="
			+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecuteMetadataToken.ToString(CultureInfo.InvariantCulture)
			+ " RVA="
			+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecuteRvaHex
			+ " VA="
			+ GameSymbols.BulwarkRunesLaws.AbilityCommitExecuteVaHex
			+ nativeText
			+ " (award +1 in postfix; not ActionEnded).");
	}

	private static bool TryReadNativeMethodPointers(Type owner, MethodInfo method, out IntPtr methodInfoPtr, out IntPtr methodPointer)
	{
		methodInfoPtr = IntPtr.Zero;
		methodPointer = IntPtr.Zero;
		if (owner == null || method == null)
			return false;
		FieldInfo field = null;
		var exact = "NativeMethodInfoPtr_" + method.Name;
		try
		{
			field = owner.GetField(exact, BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.DeclaredOnly);
		}
		catch
		{
			field = null;
		}
		if (field == null || field.FieldType != typeof(IntPtr))
			return false;
		object raw;
		try
		{
			raw = field.GetValue(null);
		}
		catch
		{
			return false;
		}
		if (!(raw is IntPtr info) || info == IntPtr.Zero)
			return false;
		methodInfoPtr = info;
		try
		{
			methodPointer = System.Runtime.InteropServices.Marshal.ReadIntPtr(info);
			return methodPointer != IntPtr.Zero;
		}
		catch
		{
			return false;
		}
	}

	private static Type ResolveAbilityRuntimeType()
	{
		for (var i = 0; i < GameSymbols.BulwarkRunesLaws.AbilityRuntimeTypeHints.Length; i++)
		{
			var hint = GameSymbols.BulwarkRunesLaws.AbilityRuntimeTypeHints[i];
			var type = GameMember.FindType(GameSymbols.BulwarkRunesLaws.AbilityRuntimeTypeId + "." + hint, hint)
			           ?? AccessTools.TypeByName(hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static MethodInfo ResolveAbilityCommitExecuteMethod(Type type)
	{
		if (type == null || GameSymbols.BulwarkRunesLaws.AbilityCommitExecute.NameHints == null)
			return null;
		MethodInfo selected = null;
		for (var i = 0; i < GameSymbols.BulwarkRunesLaws.AbilityCommitExecute.NameHints.Length; i++)
		{
			var name = GameSymbols.BulwarkRunesLaws.AbilityCommitExecute.NameHints[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 2)
					continue;
				// Il2CppStructArray<int> + HashSet<FieldObject> (generated wrapper shape).
				if (!parameters[0].ParameterType.Name.Contains("Il2CppStructArray", StringComparison.Ordinal)
				    || !parameters[1].ParameterType.Name.Contains("HashSet", StringComparison.Ordinal))
					continue;
				if (selected != null && !ReferenceEquals(selected, method))
					return null;
				selected = method;
			}
		}
		return selected;
	}

	private static Type ResolveLogicEventHubType()
	{
		for (var i = 0; i < GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints.Length; i++)
		{
			var hint = GameSymbols.BattleEventLaws.BattleLogicEventsTypeHints[i];
			if (string.Equals(hint, "edb", StringComparison.OrdinalIgnoreCase))
				continue;
			var type = GameMember.FindType("directState.battleEventHub." + hint, hint)
			           ?? AccessTools.TypeByName(hint);
			if (type != null)
				return type;
		}
		return null;
	}

	private static int PatchDispatcher(Harmony harmony, Type hubType, GameSymbols.MethodSymbol symbol, string postfixName)
	{
		var method = ResolveHubDispatcher(hubType, symbol);
		if (method == null)
		{
			LogLimited("dispatcher unresolved: " + symbol.Id);
			return 0;
		}
		var postfix = AccessTools.Method(typeof(Homm3BulwarkRunesRuntime), postfixName);
		if (postfix == null)
			return 0;
		if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
		{
			LogLimited("refused incompatible patch for " + method.Name + ": " + reason);
			return 0;
		}
		harmony.Patch(method, postfix: new HarmonyMethod(postfix) { priority = Priority.Last });
		return 1;
	}

	private static MethodInfo ResolveHubDispatcher(Type hubType, GameSymbols.MethodSymbol symbol)
	{
		if (hubType == null || symbol.NameHints == null)
			return null;
		MethodInfo selected = null;
		var methods = hubType.GetMethods(
			BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
		for (var nameIndex = 0; nameIndex < symbol.NameHints.Length; nameIndex++)
		{
			var name = symbol.NameHints[nameIndex];
			if (string.IsNullOrWhiteSpace(name))
				continue;
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

	private static bool EnterObserve()
	{
		if (_observing)
			return false;
		_observing = true;
		return true;
	}

	private static void ExitObserve()
	{
		_observing = false;
	}

	private static void PostfixActionStarted(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			if (!TryReadActionTarget(__args, started: true, out var target, out _))
				return;
			if (!TryResolveUnitKey(target, out var unitKey, out _))
				return;
			lock (Gate)
			{
				ActionByUnitKey.TryGetValue(unitKey, out var prior);
				var sequence = prior == null ? 1 : prior.Sequence + 1;
				ActionByUnitKey[unitKey] = new ActionCorrelation
				{
					UnitKey = unitKey,
					Sequence = sequence,
				};
			}
			LogLimited("corr actionStart unitKey=" + unitKey + " method=" + (__originalMethod?.Name ?? "?"));
		}
		catch (Exception ex)
		{
			LogLimited("actionStart failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static void PostfixActionEnded(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			if (!TryReadActionTarget(__args, started: false, out var target, out _))
				return;
			if (!TryResolveUnitKey(target, out var unitKey, out _))
				return;
			lock (Gate)
			{
				ActionByUnitKey.Remove(unitKey);
				// Method_15-only Wait arms without a following Method_47; clear so a
				// later Defend on this stack is not withheld.
				WaitArmedByUnitKey.Remove(unitKey);
			}
			LogLimited("corr actionEnd unitKey=" + unitKey + " method=" + (__originalMethod?.Name ?? "?"));
		}
		catch (Exception ex)
		{
			LogLimited("actionEnd failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static void PostfixAbilityCommitExecute(object __instance, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			if (!TryReadCommittedAbility(__instance, out var caster, out var abilityType, out var abilityIndex, out var readFail))
			{
				LogLimited("abilityCommit read failed: " + readFail + " method=" + (__originalMethod?.Name ?? "?"));
				return;
			}

			if (!IsAwardableCommittedAbility(abilityType, __instance, out var classifyFail))
			{
				LogLimited(
					"corr abilityCommit excluded type="
					+ abilityType
					+ " index="
					+ abilityIndex
					+ " reason="
					+ classifyFail
					+ " method="
					+ (__originalMethod?.Name ?? "?"));
				return;
			}

			if (!TryResolveUnitKey(caster, out var unitKey, out var keyFail))
			{
				LogLimited("abilityCommit unit key failed: " + keyFail);
				return;
			}

			var action = RequireOrBeginAction(unitKey);
			if (action.WaitObserved)
			{
				LogLimited("corr attack/cast withheld: Wait observed unitKey=" + unitKey);
				return;
			}
			if (action.DefendAwarded)
			{
				LogLimited("corr attack/cast withheld: Defend already awarded unitKey=" + unitKey);
				return;
			}

			var obsKey = "attackOrCast:"
				+ unitKey
				+ ":"
				+ action.Sequence
				+ ":"
				+ abilityType
				+ ":"
				+ abilityIndex;
			var gain = CorrelateGain(action, GainKind.AttackOrCast, obsKey, false, false, false, out var correlateFail);
			LogLimited(
				"corr abilityCommit award unitKey="
				+ unitKey
				+ " type="
				+ abilityType
				+ " index="
				+ abilityIndex
				+ " gain="
				+ gain
				+ " reason="
				+ (correlateFail ?? "ok")
				+ " method="
				+ (__originalMethod?.Name ?? "?"));
			if (gain > 0)
				TryApplyGain(caster, unitKey, gain, "attackOrCast:" + abilityType);
		}
		catch (Exception ex)
		{
			LogLimited("abilityCommit hook failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static bool TryReadCommittedAbility(
		object abilityRuntime,
		out object caster,
		out EAbilityType abilityType,
		out int abilityIndex,
		out string failReason)
	{
		caster = null;
		abilityType = EAbilityType.Unknown;
		abilityIndex = -1;
		failReason = null;
		if (abilityRuntime == null)
		{
			failReason = "ability runtime null";
			return false;
		}

		if (!TryReadMember(abilityRuntime, GameSymbols.BulwarkRunesLaws.AbilityRuntimeCasterMembers, out caster)
		    || caster == null)
		{
			failReason = "dxy.ceis caster missing";
			return false;
		}

		if (!TryReadMember(abilityRuntime, GameSymbols.BulwarkRunesLaws.AbilityRuntimeLogicConfigMembers, out var logic)
		    || logic == null)
		{
			failReason = "dxy.cejb AbilityLogicConfig missing";
			return false;
		}

		if (!TryReadMember(logic, GameSymbols.BattleEventLaws.CastAbilityIdMembers, out var abilityId)
		    || abilityId == null)
		{
			failReason = "AbilityLogicConfig AbilityID missing (interop prop_AbilityID_0 / _bxmh_k__BackingField)";
			return false;
		}

		// AbilityID is a value-type; boxed default is non-null but may be Unknown/0.
		if (abilityId is AbilityID typedId)
		{
			abilityType = typedId.abilityType;
			abilityIndex = typedId.indexInArray;
			if (!IsReadableAbilityType(abilityType))
			{
				failReason = "AbilityID.abilityType unreadable: " + abilityType;
				return false;
			}
			return true;
		}

		if (!TryReadAbilityType(abilityId, out abilityType))
		{
			failReason = "AbilityID.abilityType unreadable";
			return false;
		}

		if (!TryReadInt(abilityId, GameSymbols.BattleEventLaws.AbilityIdIndexMembers, out abilityIndex))
			abilityIndex = -1;
		return true;
	}

	private static bool IsReadableAbilityType(EAbilityType abilityType)
	{
		return abilityType != EAbilityType.Unknown && Enum.IsDefined(typeof(EAbilityType), abilityType);
	}

	private static bool TryReadAbilityType(object abilityId, out EAbilityType abilityType)
	{
		abilityType = EAbilityType.Unknown;
		if (abilityId is AbilityID typed)
		{
			abilityType = typed.abilityType;
			return IsReadableAbilityType(abilityType);
		}
		if (!TryReadMember(abilityId, GameSymbols.BattleEventLaws.AbilityIdTypeMembers, out var raw) || raw == null)
			return false;
		if (raw is EAbilityType enumTyped)
		{
			abilityType = enumTyped;
			return IsReadableAbilityType(abilityType);
		}
		try
		{
			abilityType = (EAbilityType)Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			return IsReadableAbilityType(abilityType);
		}
		catch
		{
			return false;
		}
	}

	private static bool IsAwardableAbilityType(EAbilityType abilityType)
	{
		return abilityType == EAbilityType.DefaultAttack
		       || abilityType == EAbilityType.AlternativeAttack
		       || abilityType == EAbilityType.Ability
		       || abilityType == EAbilityType.CounterAttack;
	}

	private static bool IsAwardableCommittedAbility(EAbilityType abilityType, object abilityRuntime, out string failReason)
	{
		failReason = null;
		if (!IsAwardableAbilityType(abilityType))
		{
			failReason = "ability type not attack/cast/counter";
			return false;
		}

		// Movement-only creature Ability rows: non-empty moveType with no attack/cast marker.
		if (abilityType == EAbilityType.Ability
		    && TryReadMember(abilityRuntime, GameSymbols.BulwarkRunesLaws.AbilityRuntimeLogicConfigMembers, out var logic)
		    && logic != null)
		{
			var moveType = TryReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicMoveTypeMembers);
			var attackType = TryReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicAttackTypeMembers);
			var castType = TryReadString(logic, GameSymbols.BulwarkRunesLaws.AbilityLogicCastTypeMembers);
			if (!string.IsNullOrWhiteSpace(moveType)
			    && string.IsNullOrWhiteSpace(attackType)
			    && string.IsNullOrWhiteSpace(castType))
			{
				failReason = "movement-only Ability (moveType=" + moveType + ")";
				return false;
			}
		}

		return true;
	}

	private static void PostfixObjectTookDamage(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			var eventArgs = __args != null && __args.Length > 1 ? __args[1] : null;
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(eventArgs, out var damage, out var readFail))
			{
				LogLimited("damage read failed: " + readFail);
				return;
			}
			if (damage.Receiver == null)
				return;
			if (!TryResolveUnitKey(damage.Receiver, out var unitKey, out _))
				return;
			var action = RequireAction(unitKey);
			var obsKey = "dmg:" + unitKey + ":" + (action?.Sequence ?? 0) + ":" + Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs);
			var gain = CorrelateGain(
				action,
				GainKind.DamageTaken,
				obsKey,
				positiveDamage: damage.Damage > 0,
				immuneOrFailed: damage.ImmuneToDamage,
				cancelledCast: false,
				out var correlateFail);
			LogLimited(
				"corr damage unitKey="
				+ unitKey
				+ " damage="
				+ damage.Damage
				+ " immune="
				+ damage.ImmuneToDamage
				+ " gain="
				+ gain
				+ " reason="
				+ (correlateFail ?? "ok"));
			if (gain > 0)
				TryApplyGain(damage.Receiver, unitKey, gain, "damage");
		}
		catch (Exception ex)
		{
			LogLimited("damage hook failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static void PostfixDamageFailed(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			var eventArgs = __args != null && __args.Length > 1 ? __args[1] : null;
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(eventArgs, out var damage, out _))
				return;
			if (damage.Receiver == null || !TryResolveUnitKey(damage.Receiver, out var unitKey, out _))
				return;
			var action = RequireAction(unitKey);
			CorrelateGain(
				action,
				GainKind.DamageTaken,
				"fail:" + unitKey + ":" + (action?.Sequence ?? 0) + ":" + Homm3DirectStateIdentity.ResolveKeyOrZero(eventArgs),
				positiveDamage: false,
				immuneOrFailed: true,
				cancelledCast: false,
				out _);
			LogLimited("corr damageFailed unitKey=" + unitKey + " (no Rune gain)");
		}
		catch (Exception ex)
		{
			LogLimited("damageFailed hook failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static void PostfixSkipDefend(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			if (!TryReadActionTarget(__args, started: false, out var target, out _))
				return;
			if (!TryResolveUnitKey(target, out var unitKey, out _))
				return;

			// LIVE-POSITIVE: Method_47 is Defend/Skip. Wait may dual-raise Method_15
			// then Method_47; Method_15 arms WaitArmedByUnitKey so this raise is withheld.
			var waitArmed = false;
			lock (Gate)
			{
				waitArmed = WaitArmedByUnitKey.Remove(unitKey);
			}
			if (waitArmed)
			{
				var waitAction = RequireOrBeginAction(unitKey);
				waitAction.WaitObserved = true;
				LogLimited(
					"corr Defend/Skip withheld: Wait armed unitKey="
					+ unitKey
					+ " method="
					+ (__originalMethod?.Name ?? "?")
					+ " (no Rune gain)");
				return;
			}

			var action = RequireOrBeginAction(unitKey);
			if (action.WaitObserved)
			{
				LogLimited(
					"corr Defend/Skip ignored: Wait already observed unitKey="
					+ unitKey
					+ " method="
					+ (__originalMethod?.Name ?? "?"));
				return;
			}

			var obsKey = "defend:" + unitKey + ":" + action.Sequence + ":" + Homm3DirectStateIdentity.ResolveKeyOrZero(target);
			var gain = CorrelateGain(action, GainKind.Defend, obsKey, false, false, false, out var correlateFail);
			LogLimited(
				"corr Defend/Skip unitKey="
				+ unitKey
				+ " gain="
				+ gain
				+ " reason="
				+ (correlateFail ?? "ok")
				+ " method="
				+ (__originalMethod?.Name ?? "?"));
			if (gain > 0)
				TryApplyGain(target, unitKey, gain, "defend");
		}
		catch (Exception ex)
		{
			LogLimited("Skip/Defend hook failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static void PostfixWait(object __instance, object[] __args, MethodBase __originalMethod)
	{
		if (!EnterObserve())
			return;
		try
		{
			if (!TryReadActionTarget(__args, started: false, out var target, out _))
				return;
			if (!TryResolveUnitKey(target, out var unitKey, out _))
				return;
			// LIVE-POSITIVE: Method_15 is Wait (not Defend). Arm so a following
			// Method_47 dual-raise does not award Defend +3. ActionStarted must not
			// clear this arm (it intervenes between Method_15 and Method_47).
			var action = RequireOrBeginAction(unitKey);
			action.WaitObserved = true;
			lock (Gate)
			{
				WaitArmedByUnitKey[unitKey] = true;
			}
			LogLimited(
				"corr Wait unitKey="
				+ unitKey
				+ " method="
				+ (__originalMethod?.Name ?? "?")
				+ " (no Rune gain; armed for dual-raise Method_47)");
		}
		catch (Exception ex)
		{
			LogLimited("Wait hook failed closed: " + ex.Message);
		}
		finally
		{
			ExitObserve();
		}
	}

	private static ActionCorrelation RequireAction(long unitKey)
	{
		lock (Gate)
		{
			ActionByUnitKey.TryGetValue(unitKey, out var action);
			return action;
		}
	}

	private static ActionCorrelation RequireOrBeginAction(long unitKey)
	{
		lock (Gate)
		{
			if (ActionByUnitKey.TryGetValue(unitKey, out var action) && action != null)
				return action;
			action = new ActionCorrelation { UnitKey = unitKey, Sequence = 1 };
			ActionByUnitKey[unitKey] = action;
			return action;
		}
	}

	private static void TryApplyGain(object unit, long unitKey, int gain, string reason)
	{
		if (_probeOnly || gain <= 0 || unit == null)
			return;
		if (!TryResolveEligibleStack(unit, unitKey, out var unitSid, out var skillRank, out var failReason))
		{
			// Registry GetHashCode caches can stick a TransferSide whose logicHero is
			// null under re-wrap. After this native stack already proved Bulwark
			// eligibility, keep awarding against the cached skill rank instead of
			// freezing the stack at the first successful threshold.
			if (!TryReuseCachedEligibleRank(unitKey, failReason, out unitSid, out skillRank, out var cacheFail))
			{
				LogLimited(
					"Rune gain withheld ("
					+ reason
					+ "): "
					+ failReason
					+ (cacheFail == null ? string.Empty : "; cache=" + cacheFail));
				return;
			}
			LogLimited(
				"Rune gain using cached skillRank="
				+ skillRank.ToString(CultureInfo.InvariantCulture)
				+ " after live miss ("
				+ failReason
				+ ") unitKey="
				+ unitKey);
		}

		var crossed = new List<int>();
		int newLevel;
		lock (Gate)
		{
			if (!StackStateByNativeKey.TryGetValue(unitKey, out var state) || state == null)
			{
				state = new StackRuneState
				{
					UnitSid = unitSid,
					SkillRank = skillRank,
				};
				StackStateByNativeKey[unitKey] = state;
			}
			state.SkillRank = skillRank;
			if (!string.IsNullOrWhiteSpace(unitSid))
				state.UnitSid = unitSid;
			var cap = ResolveCap(skillRank);
			if (cap < 1)
			{
				LogLimited("Rune gain withheld: skill rank grants no cap");
				return;
			}
			var before = state.Level;
			state.Level = Math.Min(cap, Math.Max(0, state.Level + gain));
			newLevel = state.Level;
			for (var threshold = before + 1; threshold <= newLevel; threshold++)
			{
				if (state.AppliedThresholds.Add(threshold))
					crossed.Add(threshold);
			}
		}

		for (var i = 0; i < crossed.Count; i++)
		{
			if (!TryDispatchThresholdBuff(unit, crossed[i], out var buffFail))
			{
				LogLimited(
					"Rune threshold buff failed closed: level="
					+ crossed[i]
					+ " reason="
					+ buffFail);
				return;
			}
		}

		LogLimited(
			"Rune gain applied reason="
			+ reason
			+ " unitKey="
			+ unitKey
			+ " sid="
			+ unitSid
			+ " gain=+"
			+ gain
			+ " level="
			+ newLevel
			+ " thresholds=["
			+ string.Join(",", crossed)
			+ "]");
	}

	private static bool TryReuseCachedEligibleRank(
		long unitKey,
		string liveFailReason,
		out string unitSid,
		out int skillRank,
		out string failReason)
	{
		unitSid = null;
		skillRank = 0;
		failReason = null;
		if (string.IsNullOrWhiteSpace(liveFailReason)
		    || liveFailReason.IndexOf("logicHero", StringComparison.OrdinalIgnoreCase) < 0)
		{
			failReason = "live miss is not a logicHero continuity case";
			return false;
		}
		lock (Gate)
		{
			if (!StackStateByNativeKey.TryGetValue(unitKey, out var state)
			    || state == null
			    || state.SkillRank < 1
			    || ResolveCap(state.SkillRank) < 1)
			{
				failReason = "no prior Bulwark skillRank for unitKey=" + unitKey;
				return false;
			}
			skillRank = state.SkillRank;
			unitSid = state.UnitSid;
			return true;
		}
	}

	private static bool TryDispatchThresholdBuff(object unit, int threshold, out string failReason)
	{
		var buffSid = BuffSidForLevel(threshold);
		if (string.IsNullOrWhiteSpace(buffSid))
		{
			failReason = "no buff SID for threshold " + threshold;
			return false;
		}
		if (IncrementalOffenceForThreshold(threshold) == 0
		    && IncrementalDefenceForThreshold(threshold) == 0
		    && IncrementalSpeedForThreshold(threshold) == 0)
		{
			failReason = "threshold " + threshold + " has no incremental stats";
			return false;
		}

		// Pass the crossed threshold as buff level so UI rank matches Runes I–IX
		// SIDs (exact-id custom rows still require level >= 1).
		if (!Homm3BuffDebuffNativeAdapter.TryAddBuffSidFromReceiver(
			    unit,
			    buffSid,
			    unit,
			    threshold,
			    RuneBuffDuration,
			    RuneBuffValue,
			    refresh: false,
			    out _,
			    out failReason))
			return false;
		failReason = null;
		return true;
	}

	private static bool TryResolveEligibleStack(
		object unit,
		long unitKey,
		out string unitSid,
		out int skillRank,
		out string failReason)
	{
		unitSid = null;
		skillRank = 0;
		failReason = null;
		unitSid = TryResolveBattleUnitSid(unit);
		if (IsWarMachineExcluded(unitSid))
		{
			failReason = "war-machine excluded sid=" + (unitSid ?? "null");
			return false;
		}
		if (!TryResolveTransferSideForRunes(unit, out var transferSide, out failReason)
		    || transferSide == null)
		{
			failReason = failReason ?? ("TransferSide unresolved for unitKey=" + unitKey);
			return false;
		}
		if (!TryResolveBulwarkSkillRank(transferSide, out skillRank, out failReason))
			return false;
		if (ResolveCap(skillRank) < 1)
		{
			failReason = "Runes skill rank grants no cap";
			return false;
		}
		return true;
	}

	/// <summary>
	/// Prefer live TransferSide reads from the battle object. The law-owner
	/// registry keys by managed GetHashCode and can cache a TransferSide whose
	/// <c>logicHero</c> is null across re-wraps, which freezes Rune gains at 1.
	/// </summary>
	private static bool TryResolveTransferSideForRunes(object unit, out object transferSide, out string failReason)
	{
		transferSide = null;
		failReason = null;
		if (unit == null)
		{
			failReason = "unit null";
			return false;
		}

		if (TryReadMember(unit, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out transferSide)
		    && transferSide != null
		    && HasLogicHero(transferSide))
			return true;

		if (TryReadMember(unit, GameSymbols.BattleEventLaws.BattleObjectBattleContextMembers, out var context)
		    && context != null
		    && !ReferenceEquals(context, unit)
		    && TryReadMember(context, GameSymbols.BattleEventLaws.BattleContextTransferSideMembers, out transferSide)
		    && transferSide != null
		    && HasLogicHero(transferSide))
			return true;

		if (Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(unit, out transferSide)
		    && transferSide != null
		    && HasLogicHero(transferSide))
			return true;

		// Last resort: accept a TransferSide even without logicHero so the caller
		// can emit the precise logicHero-missing fail reason.
		if (TryReadMember(unit, GameSymbols.BattleEventLaws.BattleObjectSideMembers, out transferSide)
		    && transferSide != null)
			return true;
		if (TryReadMember(unit, GameSymbols.BattleEventLaws.BattleObjectBattleContextMembers, out context)
		    && context != null
		    && TryReadMember(context, GameSymbols.BattleEventLaws.BattleContextTransferSideMembers, out transferSide)
		    && transferSide != null)
			return true;
		if (Homm3BattleUnitLawOwnerRegistry.TryResolveTransferSide(unit, out transferSide) && transferSide != null)
			return true;

		failReason = "TransferSide unresolved";
		return false;
	}

	private static bool HasLogicHero(object transferSide)
	{
		if (transferSide is TransferSide typedSide)
			return typedSide.logicHero != null;
		return TryReadMember(
			       transferSide,
			       GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers,
			       out var logicHero)
		       && logicHero != null;
	}

	private static bool TryResolveBulwarkSkillRank(object transferSide, out int rank, out string failReason)
	{
		rank = 0;
		failReason = null;
		object logicHero = null;
		if (transferSide is TransferSide typedSide)
			logicHero = typedSide.logicHero;
		else
			TryReadMember(transferSide, GameSymbols.SkeletalNecromancy.TransferSideLogicHeroMembers, out logicHero);
		if (logicHero == null)
		{
			failReason = "logicHero missing on TransferSide";
			return false;
		}

		object dataHeroObj = null;
		if (_logicHeroDataHeroGetter != null
		    && _logicHeroDataHeroGetter.DeclaringType != null
		    && _logicHeroDataHeroGetter.DeclaringType.IsInstanceOfType(logicHero))
		{
			try
			{
				dataHeroObj = _logicHeroDataHeroGetter.Invoke(logicHero, Array.Empty<object>());
			}
			catch (Exception ex)
			{
				failReason = "LogicHero data-Hero resolution failed: " + ex.GetBaseException().Message;
				return false;
			}
		}
		if (dataHeroObj == null)
		{
			failReason = "LogicHero data-Hero missing";
			return false;
		}

		var skills = ReadMember(dataHeroObj, GameSymbols.DraconicDominion.DataHeroSkillsMembers);
		var skillList = ReadMember(skills, GameSymbols.DraconicDominion.HeroSkillsListMembers);
		if (skillList == null)
		{
			failReason = "HeroSkills list missing";
			return false;
		}

		foreach (var heroSkill in EnumerateObjects(skillList))
		{
			var sid = NormalizeSid(TryReadString(heroSkill, GameSymbols.DraconicDominion.HeroSkillSidMembers));
			if (!string.Equals(sid, BulwarkSkillSid, StringComparison.Ordinal))
				continue;
			if (!TryReadInt(heroSkill, GameSymbols.DraconicDominion.HeroSkillLevelMembers, out rank))
			{
				failReason = "Bulwark skill level member missing";
				return false;
			}
			if (rank < 1 || rank > 3)
			{
				failReason = "Bulwark skill level outside Basic/Advanced/Expert: " + rank;
				rank = 0;
				return false;
			}
			return true;
		}

		failReason = "non-Bulwark army (skill_faction_homm3_bulwark absent)";
		return false;
	}

	private static bool TryReadActionTarget(object[] args, bool started, out object target, out string failReason)
	{
		target = null;
		failReason = null;
		var eventArgs = args != null && args.Length > 1 ? args[1] : null;
		if (!Homm3BattleEventNativeAdapter.TryReadActionEvent(eventArgs, out var info, out failReason))
		{
			// Skip/Wait may still carry a plain BattleEventArgs target member.
			if (!TryReadMember(eventArgs, GameSymbols.BattleEventLaws.BattleEventTargetMembers, out target) || target == null)
			{
				failReason = failReason ?? "action target missing";
				return false;
			}
			return true;
		}
		if (info.Started != started && started)
		{
			// ActionStarted adapter may classify by dispatcher; accept either when target present.
		}
		target = info.Target;
		if (target == null)
		{
			failReason = "action target null";
			return false;
		}
		return true;
	}

	private static bool TryResolveUnitKey(object unit, out long unitKey, out string failReason)
	{
		return Homm3DirectStateIdentity.TryResolveKey(unit, out unitKey, out failReason);
	}

	private static string TryResolveBattleUnitSid(object unit)
	{
		if (unit == null)
			return null;
		var transfer = ReadMember(unit, GameSymbols.BattleEventLaws.UnitTransferUnitMembers);
		if (transfer != null)
		{
			var transferSid = NormalizeSid(TryReadString(transfer, GameSymbols.BattleEventLaws.TransferUnitConfigSidMembers));
			if (!string.IsNullOrWhiteSpace(transferSid))
				return transferSid;
		}
		var logic = ReadMember(unit, GameSymbols.BattleEventLaws.UnitLogicConfigMembers);
		return NormalizeSid(TryReadString(logic, GameSymbols.BattleEventLaws.UnitConfigSidMembers));
	}

	private static MethodInfo ResolveLogicHeroDataHeroGetter()
	{
		try
		{
			var type = AccessTools.TypeByName(GameSymbols.CastleEliteStrategem.LogicHeroTypeName)
			           ?? GameMember.FindType(
				           "homm3.runes.logicHero",
				           GameSymbols.CastleEliteStrategem.LogicHeroTypeName);
			if (type == null)
				return null;
			foreach (var name in GameSymbols.CastleEliteStrategem.LogicHeroDataHeroGetter.NameHints)
			{
				var method = AccessTools.DeclaredMethod(type, name);
				if (method != null
				    && method.GetParameters().Length == 0
				    && typeof(DataHero).IsAssignableFrom(method.ReturnType))
					return method;
			}
			foreach (var name in GameSymbols.DraconicDominion.LogicHeroDataHeroGetter.NameHints)
			{
				var method = AccessTools.DeclaredMethod(type, name);
				if (method != null && method.GetParameters().Length == 0)
					return method;
			}
		}
		catch
		{
		}
		return null;
	}

	private static object ReadMember(object target, string[] names)
	{
		TryReadMember(target, names, out var value);
		return value;
	}

	private static bool TryReadMember(object target, string[] names, out object value)
	{
		var found = GameMemberValueReader.TryRead(target, names, out value, out var failure);
		if (!string.IsNullOrEmpty(failure))
			LogLimited("member read failed: " + failure);
		return found;
	}

	private static string TryReadString(object target, string[] names)
	{
		if (!TryReadMember(target, names, out var raw) || raw == null)
			return null;
		return raw as string ?? raw.ToString();
	}

	private static bool TryReadInt(object target, string[] names, out int value)
	{
		value = 0;
		if (!TryReadMember(target, names, out var raw) || raw == null)
			return false;
		try
		{
			value = Convert.ToInt32(raw, CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static IEnumerable<object> EnumerateObjects(object list)
	{
		if (list == null)
			yield break;
		if (list is IEnumerable enumerable)
		{
			foreach (var item in enumerable)
			{
				if (item != null)
					yield return item;
			}
			yield break;
		}
		var type = list.GetType();
		var countProp = AccessTools.Property(type, "Count") ?? AccessTools.Property(type, "count");
		var count = 0;
		try
		{
			if (countProp != null)
				count = Convert.ToInt32(countProp.GetValue(list, null), CultureInfo.InvariantCulture);
		}
		catch
		{
			yield break;
		}
		var indexer = AccessTools.Property(type, "Item");
		if (indexer == null)
			yield break;
		for (var i = 0; i < count; i++)
		{
			object item = null;
			try
			{
				item = indexer.GetValue(list, new object[] { i });
			}
			catch
			{
			}
			if (item != null)
				yield return item;
		}
	}

	private static string NormalizeSid(string sid)
	{
		return string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();
	}

	private static void LogLimited(string message)
	{
		if (_logged++ >= LogCap)
			return;
		_log?.LogInfo("HoMM3 Bulwark Runes: " + message);
	}

	private static class Paths
	{
		internal static string PluginPathSafe()
		{
			try
			{
				var dir = Path.GetDirectoryName(typeof(Homm3BulwarkRunesRuntime).Assembly.Location);
				return string.IsNullOrWhiteSpace(dir) ? "." : dir;
			}
			catch
			{
				return ".";
			}
		}
	}
}
