using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.InteropTypes;

namespace OfflineUnlockMod;

/// <summary>
/// Tower Artificing observation, attribution scope (docs/homm3_tower_artificing.md, "Observation replaces
/// Transcribe"). Diagnostic only: it records nothing in any schematic book and spends no rolls, so it runs
/// while policy.enabled is false, gated by policy.observation.diagnostics (ObservationDiagnostics).
///
/// Scope: a prefix / postfix pair on the native passive action runner's trigger handler (ejh.befp). The
/// handler checks conditions, gathers targets and casts with the runner as castSource, so effects raised
/// while the scope is open belong to that runner's BuffActionConfig. Config identity: the runner's config
/// pointer against the owner unit's UnitLogicConfig.passives[i].actions[j]; (unit sid, i, j) then looks up
/// ObservedPassiveActionsByUnitSid for the schematic it would observe.
///
/// Effects counted inside the scope: unit buff adds (sid, stuck or refused) and ObjectTookDamage events
/// (damage, and whether castSource is the runner). Outside any scope, damage whose castSource is a runner
/// that fired this session is logged as deferred, and buff adds whose sid is an observe tag (buff_applied,
/// aura, side_modifier tables) are logged so the native aura buff sids can be read off the log.
///
/// One line per scope that fired a catalog-linked action or produced an effect, capped at
/// ObservationDiagnosticLogLines per launch. Every read fails closed to "unresolved" in the line.
/// Proof tier: source + build; the identity and in-scope effect assumptions are what the log checks.
/// </summary>
internal static class Homm3TowerArtificingObservation
{
	private const string LogPrefix = "HoMM3 Tower Artificing observe: ";
	private const int MaxScopeDepth = 16;
	private const int MaxRecentRunners = 256;

	private sealed class Scope
	{
		internal long Runner;
		internal string UnitSid;
		internal int Passive = -1;
		internal int Action = -1;
		internal string Identity;
		internal string Trigger;
		internal int Schematic = -1;
		internal readonly List<string> Effects = new();
	}

	[ThreadStatic] private static List<Scope> _scopes;
	[ThreadStatic] private static bool _inDamage;
	private static readonly object Gate = new();
	/// <summary>Runner pointer -> "unit p/a" for deferred-effect lines; cleared when it grows past MaxRecentRunners.</summary>
	private static readonly Dictionary<long, string> RecentRunners = new();
	/// <summary>Config pointer -> (passive, action) found on the owner's UnitLogicConfig; (-1, -1) = not found.</summary>
	private static readonly Dictionary<long, (int Passive, int Action)> IdentityByConfig = new();
	private static bool _registrationAttempted;
	private static MethodInfo _unitLogicConfigGetter;
	private static ManualLogSource _log;
	private static int _lines;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registrationAttempted || harmony == null)
			return;
		_registrationAttempted = true;
		_log = log;
		if (!Homm3TowerArtificingCatalog.ObservationDiagnostics)
		{
			_log?.LogInfo(LogPrefix + "policy.observation.diagnostics=false; attribution scope not registered.");
			return;
		}
		var hexAssembly = typeof(TransferBattle).Assembly;
		var owner = typeof(Homm3TowerArtificingObservation);
		MethodInfo trigger = null;
		try
		{
			var runnerType = Homm3TowerArtificingRuntime.ResolveTypeByHints(hexAssembly, GameSymbols.TowerArtificing.PassiveActionRunnerTypeHints, "homm3.tower.artificing.passiveAction.runner");
			_unitLogicConfigGetter = Homm3TowerArtificingRuntime.ResolveExactMethod(typeof(Unit), typeof(UnitLogicConfig), Type.EmptyTypes, GameSymbols.SelectedUnitHud.UnitLogicConfigGetter);
			trigger = Homm3TowerArtificingRuntime.ResolveHubDispatcher(runnerType, GameSymbols.TowerArtificing.PassiveActionRunnerTrigger);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, owner, trigger, nameof(PrefixTrigger), nameof(PostfixTrigger));
		}
		catch (Exception ex)
		{
			Homm3TowerArtificingRuntime.UnpatchOwned(harmony, owner, trigger, nameof(PrefixTrigger));
			Homm3TowerArtificingRuntime.UnpatchOwned(harmony, owner, trigger, nameof(PostfixTrigger));
			_log?.LogError(LogPrefix + "[scope] NOT registered (no attribution log): " + ex.GetBaseException().Message);
			return;
		}

		var buffAdd = false;
		try
		{
			var managerType = GameMember.FindType(GameSymbols.BuffDebuffLaws.BuffManagerTypeId, GameSymbols.BuffDebuffLaws.BuffManagerTypeHint)
			                  ?? throw new TypeLoadException("unit buff manager type not found");
			Homm3TowerArtificingRuntime.PatchOwned(harmony, owner, Homm3TowerArtificingRuntime.FindBuffAdd(managerType), null, nameof(PostfixUnitBuffAdd));
			buffAdd = true;
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + "[buff] NOT registered (scopes log no buff effects): " + ex.GetBaseException().Message);
		}

		var damage = false;
		MethodInfo dispatcher = null;
		try
		{
			var hubType = Homm3TowerArtificingRuntime.ResolveLogicEventHubType() ?? throw new TypeLoadException("battle event hub type not found from BattleLogicEventsTypeHints");
			dispatcher = Homm3TowerArtificingRuntime.ResolveHubDispatcher(hubType, GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher);
			Homm3TowerArtificingRuntime.PatchOwned(harmony, owner, dispatcher, null, nameof(PostfixObjectTookDamage), Priority.Last);
			damage = true;
		}
		catch (Exception ex)
		{
			Homm3TowerArtificingRuntime.UnpatchOwned(harmony, owner, dispatcher, nameof(PostfixObjectTookDamage));
			_log?.LogError(LogPrefix + "[damage] NOT registered (scopes log no damage effects): " + ex.GetBaseException().Message);
		}
		_log?.LogInfo(LogPrefix + "registered: scope=ok buff=" + (buffAdd ? "ok" : "FAILED") + " damage=" + (damage ? "ok" : "FAILED")
			+ " linkedUnits=" + Homm3TowerArtificingCatalog.ObservedPassiveActionsByUnitSid.Count + " lineBudget=" + Homm3TowerArtificingCatalog.ObservationDiagnosticLogLines
			+ ". Diagnostic only (no rolls, no book writes).");
	}

	private static void PrefixTrigger(object __instance, out int __state)
	{
		__state = -1;
		if (_lines >= Homm3TowerArtificingCatalog.ObservationDiagnosticLogLines)
			return; // budget spent: no more scopes this launch
		var scopes = _scopes ??= new List<Scope>();
		if (scopes.Count >= MaxScopeDepth)
			scopes.Clear(); // a native throw skipped postfixes; drop the stale scopes
		__state = scopes.Count;
		var scope = new Scope();
		scopes.Add(scope);
		try
		{
			if (__instance is Il2CppObjectBase runner)
				scope.Runner = runner.Pointer.ToInt64();
			ResolveScope(__instance, scope);
		}
		catch (Exception ex)
		{
			scope.Identity = "error:" + ex.GetBaseException().GetType().Name;
		}
	}

	private static void PostfixTrigger(int __state)
	{
		var scopes = _scopes;
		if (__state < 0 || scopes == null || scopes.Count <= __state)
			return;
		var scope = scopes[__state];
		scopes.RemoveRange(__state, scopes.Count - __state);
		if (scope.Schematic < 0 && scope.Effects.Count == 0)
			return;
		if (scope.Runner != 0)
		{
			lock (Gate)
			{
				if (RecentRunners.Count >= MaxRecentRunners)
					RecentRunners.Clear();
				RecentRunners[scope.Runner] = (scope.UnitSid ?? "?") + " p" + scope.Passive + "/a" + scope.Action;
			}
		}
		var schematic = scope.Schematic < 0
			? "none"
			: scope.Schematic + ":" + (Homm3TowerArtificingCatalog.SchematicKeyByIndex.TryGetValue(scope.Schematic, out var key) ? key : "?");
		Line("befp unit=" + (scope.UnitSid ?? "unresolved") + " passive=" + scope.Passive + " action=" + scope.Action
			+ " trigger=" + (scope.Trigger ?? "?") + " identity=" + scope.Identity + " schematic=" + schematic
			+ " depth=" + __state + " effects=[" + string.Join(", ", scope.Effects) + "]");
	}

	private static void ResolveScope(object runner, Scope scope)
	{
		var config = Homm3TowerArtificingRuntime.ReadMember(runner, GameSymbols.TowerArtificing.PassiveActionRunnerConfigMembers) as Il2CppObjectBase;
		var owner = Homm3TowerArtificingRuntime.ReadMember(runner, GameSymbols.TowerArtificing.PassiveActionRunnerOwnerMembers);
		if (config == null || config.Pointer == IntPtr.Zero)
		{
			scope.Identity = "config:unresolved";
			return;
		}
		// Registered units only: the registry keys native Unit pointers, so a hit proves the owner is a Unit.
		if (owner == null || !Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(owner, out var unitSid)
		    || !Homm3BattleUnitLawOwnerRegistry.TryGetUnitNativePointer(owner, out var ownerPointer))
		{
			scope.Identity = "owner:not-a-registered-unit";
			return;
		}
		scope.UnitSid = unitSid.Trim();
		var configKey = config.Pointer.ToInt64();
		(int Passive, int Action) found;
		bool cached;
		lock (Gate)
			cached = IdentityByConfig.TryGetValue(configKey, out found);
		if (!cached)
		{
			found = FindAction(new Unit(new IntPtr(ownerPointer)), configKey);
			lock (Gate)
				IdentityByConfig[configKey] = found;
		}
		scope.Passive = found.Passive;
		scope.Action = found.Action;
		scope.Identity = found.Passive < 0 ? "miss" : cached ? "match(cached)" : "match";
		if (Homm3TowerArtificingCatalog.ObservedPassiveActionsByUnitSid.TryGetValue(scope.UnitSid, out var linked))
		{
			foreach (var entry in linked)
			{
				if (entry.Passive == found.Passive && entry.Action == found.Action)
				{
					scope.Schematic = entry.Schematic;
					scope.Trigger = entry.Trigger;
				}
			}
		}
		scope.Trigger ??= (config as BuffActionConfig)?.trigger;
	}

	private static (int, int) FindAction(Unit unit, long configKey)
	{
		if (_unitLogicConfigGetter.Invoke(unit, null) is not UnitLogicConfig logic || logic.passives == null)
			return (-1, -1);
		for (var i = 0; i < logic.passives.Length; i++)
		{
			var actions = logic.passives[i]?.actions;
			if (actions == null)
				continue;
			for (var j = 0; j < actions.Length; j++)
			{
				if (actions[j] != null && actions[j].Pointer.ToInt64() == configKey)
					return (i, j);
			}
		}
		return (-1, -1);
	}

	private static void PostfixUnitBuffAdd(object __instance, object __result, [HarmonyArgument(0)] string sid)
	{
		try
		{
			var scopes = _scopes;
			var top = scopes != null && scopes.Count > 0 ? scopes[scopes.Count - 1] : null;
			if (top != null)
			{
				top.Effects.Add("buff:" + sid + (__result != null ? "" : ":refused"));
				return;
			}
			if (sid == null
			    || !(Homm3TowerArtificingCatalog.ObservedBuffSchematics.ContainsKey(sid)
			         || Homm3TowerArtificingCatalog.ObservedAuraTagSchematics.ContainsKey(sid)
			         || Homm3TowerArtificingCatalog.ObservedSideModifierSchematics.ContainsKey(sid)))
				return;
			var receiver = Homm3TowerArtificingRuntime.ReadMember(__instance, GameSymbols.BuffDebuffLaws.BuffManagerReceiverMembers);
			var receiverSid = receiver != null && Homm3BattleUnitLawOwnerRegistry.TryGetRegisteredConfigSid(receiver, out var s) ? s : "unresolved";
			Line("tagged buff outside scope: " + sid + (__result != null ? "" : ":refused") + " on " + receiverSid);
		}
		catch (Exception ex)
		{
			Line("buff add read failed closed: " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixObjectTookDamage(object[] __args)
	{
		if (_inDamage || __args == null || __args.Length < 2)
			return;
		_inDamage = true;
		try
		{
			if (!Homm3BattleEventNativeAdapter.TryReadDamageEvent(__args[1], out var hit, out _))
				return;
			var source = hit.CastSource is Il2CppObjectBase cast ? cast.Pointer.ToInt64() : 0;
			var scopes = _scopes;
			var top = scopes != null && scopes.Count > 0 ? scopes[scopes.Count - 1] : null;
			if (top != null)
			{
				top.Effects.Add("dmg:" + hit.Damage + (hit.ImmuneToDamage ? ":immune" : "") + (hit.StacksDestroyed > 0 ? ":killed" + hit.StacksDestroyed : "")
					+ (source == 0 ? ":src?" : source == top.Runner ? ":src=runner" : ":src=other"));
				return;
			}
			string runner;
			lock (Gate)
			{
				if (source == 0 || !RecentRunners.TryGetValue(source, out runner))
					return;
			}
			Line("deferred damage from runner " + runner + ": dmg=" + hit.Damage + (hit.ImmuneToDamage ? " immune" : ""));
		}
		catch (Exception ex)
		{
			Line("damage read failed closed: " + ex.GetBaseException().Message);
		}
		finally
		{
			_inDamage = false;
		}
	}

	private static void Line(string message)
	{
		var budget = Homm3TowerArtificingCatalog.ObservationDiagnosticLogLines;
		var n = System.Threading.Interlocked.Increment(ref _lines);
		if (n < budget)
			_log?.LogInfo(LogPrefix + message);
		else if (n == budget)
			_log?.LogInfo(LogPrefix + "line budget " + budget + " reached; further observation lines dropped this launch.");
	}
}
