using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using System.Runtime.CompilerServices;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Release battle units no longer use the old dzk.bath pool. They bind through ecd.Init(...).
/// Keep this hook narrow: resolve Stronghold units from TransferUnit.configSid and replace only the
/// current ecd GameObject/Animator/SpriteRenderer slots by type. These names move across release
/// builds; the current Steam release uses eck cfbg/cfbc/cfbl for direct drawer visual slots. Keep
/// cflk/cfll native-owned for placement, and route cflm/cfln to the HoMM3 root for orientation.
/// </summary>
internal static class Homm3ImportReleaseBattleVisualHook
{
	private const float ReleaseBattleBillboardLocalYOffset = -0.45f;
	private const float ReleaseBattleBillboardLocalXOffset = 0.11f;
	private static bool _patched;
	private static int _loggedApply;
	private static int _loggedMiss;
	private static int _loggedDonorHide;
	private static int _loggedDeferred;
	private static int _loggedInitDiag;
	private static int _loggedSpawnReconcile;
	private static int _loggedSpawnObserverDiag;
	private static int _loggedSummonVisualContext;
	private static int _loggedAmbiguousSummonVisualContext;
	private static bool _rawFieldObjectSpawnContextPatched;
	private static readonly List<PendingSpawnedBattleVisual> PendingSpawnedVisuals = new();
	private static readonly List<PendingSummonedBattleVisual> PendingSummonedVisuals = new();

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: true);
	}

	private static void Register(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_patched)
		{
			if (required && !_rawFieldObjectSpawnContextPatched)
				throw new InvalidOperationException("required release battle visual surface missing: raw field-object spawn context hook was not registered.");
			return;
		}
		if (harmony == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required release battle visual registration.");
			return;
		}
		try
		{
			if (required)
				Homm3ImportVisuals.RequireLoadedEntriesForReleaseSafeFeature(log, "release battle visual");

			var battleUnitViewType = ResolveAssemblyType(GameSymbols.BattleVisual.BattleDrawerTypeNames, "battle.visual.drawer");
			if (battleUnitViewType == null)
			{
				HandleMissing(required, "battle drawer type not found.");
				return;
			}

			var methods = FindReleaseInitMethods(battleUnitViewType);
			if (methods.Count == 0)
			{
				HandleMissing(required, "ecd.Init(UnitViewConfig,TransferUnit,Random,Vector3,float,bool,int) not found.");
				return;
			}

			var postfix = new HarmonyMethod(typeof(Homm3ImportReleaseBattleVisualHook), nameof(PostfixInit));
			foreach (var method in methods)
				harmony.Patch(method, postfix: postfix);
			var rawContextCount = RegisterRawFieldObjectSpawnVisualContext(harmony, log, required);

			_patched = true;
			log?.LogInfo("Homm3Import release battle visual: patched " + methods.Count + (required ? " required" : "") + " ecd.Init-shaped method(s); raw spawn context methods=" + rawContextCount + ".");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogError("Homm3Import release battle visual hook failed: " + ex);
		}
	}

	private static void HandleMissing(bool required, string message)
	{
		if (required)
			throw new InvalidOperationException("required release battle visual surface missing: " + message);
		Plugin.LogSource?.LogWarning("Homm3Import release battle visual: " + message);
	}

	private static List<MethodInfo> FindReleaseInitMethods(Type battleUnitViewType)
	{
		var exactInit = new List<MethodInfo>();
		var shapeFallback = new List<MethodInfo>();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var method in battleUnitViewType.GetMethods(flags))
		{
			if (method.ReturnType != typeof(bool))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != 7)
				continue;
			if (ps[0].ParameterType != typeof(UnitViewConfig)
			    || ps[1].ParameterType != typeof(TransferUnit)
			    || !LooksLikeIl2CppRandom(ps[2].ParameterType)
			    || ps[3].ParameterType != typeof(Vector3)
			    || ps[4].ParameterType != typeof(float)
			    || ps[5].ParameterType != typeof(bool)
			    || ps[6].ParameterType != typeof(int))
				continue;
			if (string.Equals(method.Name, "Init", StringComparison.Ordinal))
				exactInit.Add(method);
			else if (IsReleaseDrawerGeneratedInitName(method.Name))
				shapeFallback.Add(method);
		}
		if (exactInit.Count == 0)
			return shapeFallback;
		exactInit.AddRange(shapeFallback);
		return exactInit;
	}

	private static int RegisterRawFieldObjectSpawnVisualContext(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_rawFieldObjectSpawnContextPatched || harmony == null)
			return 0;
		try
		{
			var methods = FindRawFieldObjectSpawnMethods();
			if (methods.Count == 0)
			{
				var message = "raw field-object spawn context hook skipped; no compatible factory methods found.";
				if (required)
					throw new InvalidOperationException("required release battle visual surface missing: " + message);
				log?.LogWarning("Homm3Import release battle visual: " + message);
				return 0;
			}
			var prefix = new HarmonyMethod(typeof(Homm3ImportReleaseBattleVisualHook), nameof(PrefixRawFieldObjectSpawn));
			for (var i = 0; i < methods.Count; i++)
				harmony.Patch(methods[i], prefix: prefix);
			_rawFieldObjectSpawnContextPatched = true;
			log?.LogInfo("Homm3Import release battle visual: patched " + methods.Count + " raw field-object spawn context method(s).");
			return methods.Count;
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3Import release battle visual: raw field-object spawn context registration failed: " + ex.Message);
			return 0;
		}
	}

	private static List<MethodInfo> FindRawFieldObjectSpawnMethods()
	{
		var methods = new List<MethodInfo>();
		var factoryTypes = new List<Type>();
		var helperMethods = Homm3BattleVisualInterop.ResolveNativeSpawnObjectMethods();
		for (var i = 0; i < helperMethods.Count; i++)
		{
			var ps = helperMethods[i]?.GetParameters();
			if (ps == null || ps.Length == 0 || ps[0].ParameterType == null)
				continue;
			AddUniqueType(factoryTypes, ps[0].ParameterType);
		}
		foreach (var typeName in GameSymbols.BattleVisual.SpawnFactoryTypeNames)
		{
			var type = ResolveAssemblyType(new[] { typeName }, "battle.visual.rawSpawnFactory");
			if (type == null)
				continue;
			AddUniqueType(factoryTypes, type);
		}
		foreach (var type in factoryTypes)
		{
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				if (!IsRawFieldObjectSpawnMethod(method))
					continue;
				AddUniqueMethod(methods, method);
			}
		}
		return methods;
	}

	private static bool IsRawFieldObjectSpawnMethod(MethodInfo method)
	{
		if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(FieldObject))
			return false;
		var ps = method.GetParameters();
		if (ps.Length < 5)
			return false;
		return ps[0].ParameterType == typeof(EFieldObjectType)
		       && ps[1].ParameterType == typeof(string)
		       && ps[2].ParameterType == typeof(int)
		       && IsBattleHexType(ps[4].ParameterType)
		       && StringArrayContains(GameSymbols.BattleVisual.RawFieldObjectSpawnMethodNames, method.Name);
	}

	private static bool IsBattleHexType(Type type)
	{
		if (type == null)
			return false;
		return string.Equals(type.Name, "Hex", StringComparison.Ordinal)
		       && (string.Equals(type.FullName, "Hex.Session.Battle.Hex", StringComparison.Ordinal)
		           || type.FullName == null
		           || type.FullName.EndsWith(".Hex", StringComparison.Ordinal));
	}

	private static void PrefixRawFieldObjectSpawn(object[] __args, object __instance, MethodBase __originalMethod)
	{
		try
		{
			var requestedSid = __args != null && __args.Length > 1 ? NormalizeSid(__args[1] as string) : null;
			if (!TryResolveExplicitSpawnedCustomVisualSid(requestedSid, out var unitSid))
				return;
			QueueSummonedVisualContext(unitSid, "raw-field-object:" + FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			if (_loggedSummonVisualContext++ < 6)
				Plugin.LogSource?.LogWarning("Homm3Import release battle visual: raw field-object spawn context failed: " + ex.Message);
		}
	}

	private static bool TryResolveExplicitSpawnedCustomVisualSid(string requestedSid, out string unitSid)
	{
		unitSid = null;
		requestedSid = NormalizeSid(requestedSid);
		if (string.IsNullOrEmpty(requestedSid) || !requestedSid.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		if (!HasSpawnedBattleVisualReplacement(requestedSid))
			return false;
		unitSid = requestedSid;
		return true;
	}

	private static void AddUniqueMethod(List<MethodInfo> methods, MethodInfo method)
	{
		if (methods == null || method == null)
			return;
		for (var i = 0; i < methods.Count; i++)
			if (methods[i] == method)
				return;
		methods.Add(method);
	}

	private static void AddUniqueType(List<Type> types, Type type)
	{
		if (types == null || type == null)
			return;
		for (var i = 0; i < types.Count; i++)
			if (types[i] == type)
				return;
		types.Add(type);
	}

	private static bool StringArrayContains(string[] values, string candidate)
	{
		if (values == null || string.IsNullOrEmpty(candidate))
			return false;
		for (var i = 0; i < values.Length; i++)
			if (string.Equals(values[i], candidate, StringComparison.Ordinal))
				return true;
		return false;
	}

	private static void QueueSummonedVisualContext(string unitSid, string source)
	{
		unitSid = NormalizeSid(unitSid);
		if (string.IsNullOrEmpty(unitSid) || !HasSpawnedBattleVisualReplacement(unitSid))
			return;
		PruneExpiredSummonedVisualContexts();
		var expires = SafeFrameCount() + 300;
		TryGetSummonDonorSid(unitSid, out var donorSid);
		PendingSummonedVisuals.Add(new PendingSummonedBattleVisual
		{
			UnitSid = unitSid,
			DonorSid = donorSid,
			Source = source,
			ExpiresAtFrame = expires,
		});
		if (IsBattleVisualDiagnosticsEnabled() && _loggedSummonVisualContext++ < 32)
		{
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle visual diag: queued summoned visual context unitSid='"
				+ unitSid
				+ "' donorSid='"
				+ (donorSid ?? "?")
				+ "' source='"
				+ (source ?? "?")
				+ "'.");
		}
	}

	private static bool TryConsumeSummonedVisualContext(TransferUnit transfer, UnitViewConfig viewConfig, string resolvedSid, string consumer, out string unitSid)
	{
		unitSid = null;
		PruneExpiredSummonedVisualContexts();
		if (PendingSummonedVisuals.Count == 0)
			return false;
		var currentSid = NormalizeSid(resolvedSid);
		var transferSid = NormalizeSid(ReadTransferUnitConfigSid(transfer));
		var mesh = NormalizeMeshPath(DeobfInteropCompat.GetUnitViewConfigMapMesh(viewConfig));
		var matchedIndex = -1;
		var matchedSid = null as string;
		var matchedCount = 0;
		for (var i = 0; i < PendingSummonedVisuals.Count; i++)
		{
			var pending = PendingSummonedVisuals[i];
			if (!SummonedContextMatches(pending, currentSid, transferSid))
				continue;
			matchedCount++;
			if (matchedIndex < 0)
			{
				matchedIndex = i;
				matchedSid = pending.UnitSid;
				continue;
			}
			if (!string.Equals(matchedSid, pending.UnitSid, StringComparison.Ordinal))
			{
				LogAmbiguousSummonedVisualContext(currentSid, transferSid, mesh, consumer, matchedCount);
				return false;
			}
		}
		if (matchedIndex >= 0)
		{
			var pending = PendingSummonedVisuals[matchedIndex];
			unitSid = pending.UnitSid;
			PendingSummonedVisuals.RemoveAt(matchedIndex);
			if (IsBattleVisualDiagnosticsEnabled() && _loggedSummonVisualContext++ < 32)
			{
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle visual diag: consumed summoned visual context unitSid='"
					+ unitSid
					+ "' donorSid='"
					+ (pending.DonorSid ?? "?")
					+ "' source='"
					+ (pending.Source ?? "?")
					+ "' consumer='"
					+ (consumer ?? "?")
					+ "' mesh='"
					+ (mesh ?? "?")
					+ "'.");
			}
			return true;
		}
		return false;
	}

	private static void LogAmbiguousSummonedVisualContext(string currentSid, string transferSid, string mesh, string consumer, int matchedCount)
	{
		if (_loggedAmbiguousSummonVisualContext++ >= 8)
			return;
		Plugin.LogSource?.LogWarning(
			"Homm3Import release battle visual: ambiguous summoned visual context skipped; matched="
			+ matchedCount
			+ " currentSid='"
			+ (currentSid ?? "?")
			+ "' transferSid='"
			+ (transferSid ?? "?")
			+ "' consumer='"
			+ (consumer ?? "?")
			+ "' mesh='"
			+ (mesh ?? "?")
			+ "'.");
	}

	private static bool SummonedContextMatches(PendingSummonedBattleVisual pending, string currentSid, string transferSid)
	{
		if (!string.IsNullOrEmpty(currentSid)
		    && !string.Equals(currentSid, pending.DonorSid, StringComparison.Ordinal)
		    && !string.Equals(currentSid, pending.UnitSid, StringComparison.Ordinal))
			return false;
		if (!string.IsNullOrEmpty(transferSid)
		    && !string.Equals(transferSid, pending.DonorSid, StringComparison.Ordinal)
		    && !string.Equals(transferSid, pending.UnitSid, StringComparison.Ordinal))
			return false;
		return true;
	}

	private static bool HasSpawnedBattleVisualReplacement(string unitSid)
	{
		unitSid = NormalizeSid(unitSid);
		if (string.IsNullOrEmpty(unitSid) || !unitSid.StartsWith("h3_", StringComparison.Ordinal))
			return false;
		return string.Equals(unitSid, Homm3CoveCannonVisuals.UnitSid, StringComparison.Ordinal)
		       || Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(unitSid, null, out _);
	}

	private static void PruneExpiredSummonedVisualContexts()
	{
		var frame = SafeFrameCount();
		for (var i = PendingSummonedVisuals.Count - 1; i >= 0; i--)
		{
			if (PendingSummonedVisuals[i].ExpiresAtFrame >= frame)
				continue;
			PendingSummonedVisuals.RemoveAt(i);
		}
	}

	private static bool TryGetSummonDonorSid(string unitSid, out string donorSid)
	{
		donorSid = null;
		unitSid = NormalizeSid(unitSid);
		if (string.IsNullOrEmpty(unitSid))
			return false;
		if (string.Equals(unitSid, Homm3CoveCannonVisuals.UnitSid, StringComparison.Ordinal))
		{
			donorSid = "crossbowman";
			return true;
		}
		if (string.Equals(unitSid, "h3_fangarm", StringComparison.Ordinal))
		{
			donorSid = "hydra_upg";
			return true;
		}
		return Homm3CustomFactionRegistry.TryGetDonorSid(unitSid, out donorSid);
	}

	private static string NormalizeMeshPath(string path)
	{
		if (string.IsNullOrWhiteSpace(path))
			return null;
		return path.Replace('\\', '/').Trim();
	}

	private static MethodInfo FindNativeSpawnObjectMethod() =>
		Homm3BattleVisualInterop.ResolveNativeSpawnObjectMethod();

	private static string FormatMethods(List<MethodInfo> methods)
	{
		if (methods == null || methods.Count == 0)
			return "none";
		var parts = new string[methods.Count];
		for (var i = 0; i < methods.Count; i++)
			parts[i] = FormatMethod(methods[i]);
		return string.Join(", ", parts);
	}

	private static bool IsReleaseDrawerGeneratedInitName(string methodName)
	{
		if (string.IsNullOrWhiteSpace(methodName))
			return false;
		var prefixes = GameSymbols.BattleVisual.DrawerInitGeneratedNamePrefixes;
		for (var i = 0; i < prefixes.Length; i++)
			if (!string.IsNullOrWhiteSpace(prefixes[i]) && methodName.StartsWith(prefixes[i], StringComparison.Ordinal))
				return true;
		return false;
	}

	private static bool NameMatches(string candidate, string[] names)
	{
		if (string.IsNullOrWhiteSpace(candidate) || names == null)
			return false;
		for (var i = 0; i < names.Length; i++)
		{
			if (string.Equals(candidate, names[i], StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool _validatedDrawerFieldSurfaces;

	private static void PostfixInit(object __instance, object[] __args, bool __result)
	{
		if (!__result || __instance == null || __args == null || __args.Length < 2)
			return;
		if (!_validatedDrawerFieldSurfaces)
		{
			try
			{
				RequireCurrentOrientationSurfaces(__instance.GetType());
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning(
					"Homm3Import release battle visual: drawer orientation surface validation failed; continuing with native field reads: "
					+ ex.Message);
			}
			_validatedDrawerFieldSurfaces = true;
		}
		var transfer = __args[1] as TransferUnit;
		var viewConfig = __args[0] as UnitViewConfig;
		var leftSide = __args.Length > 5 && __args[5] is bool b && b;
		var unitSid = ResolveInitUnitSid(transfer, viewConfig);
		if (TryConsumeSummonedVisualContext(transfer, viewConfig, unitSid, "ecd.Init", out var summonedSid))
			unitSid = summonedSid;
		if (!string.IsNullOrEmpty(unitSid) && unitSid.StartsWith("h3_", StringComparison.Ordinal))
			Homm3BattleUnitLawOwnerRegistry.UpgradeDonorRegistrationsToCustomSid(unitSid);
		LogInitDiagnostic(__instance, transfer, viewConfig, unitSid, leftSide);
		if (TryReplaceBattleVisualForDrawer(__instance, unitSid, leftSide, "ecd.Init", null, transfer, viewConfig))
			QueueDrawerGuard(__instance, unitSid, "ecd.Init");
	}


	private static void PostfixSpawnObject(
		FieldObject __result,
		object[] __args,
		MethodBase __originalMethod)
	{
		try
		{
			if (__args == null || __args.Length < 5)
			{
				LogSpawnObserverDiagnostic("args-short", null, null, null, null, null, null, __result, __args, __originalMethod);
				return;
			}
			var requestedSid = NormalizeSid(__args[4] as string);
			if (string.IsNullOrEmpty(requestedSid))
			{
				LogSpawnObserverDiagnostic("requested-empty", null, null, null, null, null, null, __result, __args, __originalMethod);
				return;
			}
			var unit = TryCastIl2Cpp<Unit>(__result);
			if (unit == null)
			{
				LogSpawnObserverDiagnostic("result-not-unit", requestedSid, null, null, null, null, null, __result, __args, __originalMethod);
				return;
			}
			var sourceUnit = TryCastIl2Cpp<Unit>(__args[1]);
			var unitSid = TryResolveBattleUnitSid(unit, includeConfigFallback: false);
			var sourceSid = TryResolveBattleUnitSid(sourceUnit, includeConfigFallback: true);
			var visualSid = ResolveSpawnedVisualSid(requestedSid, unitSid, sourceSid);
			if (string.IsNullOrEmpty(visualSid))
			{
				LogSpawnObserverDiagnostic("visual-null", requestedSid, unitSid, sourceSid, null, null, null, __result, __args, __originalMethod);
				return;
			}
			var nativeVisual = ResolveSpawnedNativeVisual(__result);
			LogSpawnObserverDiagnostic("queued", requestedSid, unitSid, sourceSid, visualSid, nativeVisual, unit, __result, __args, __originalMethod);
			QueueSpawnedBattleVisual(unit, nativeVisual, visualSid, FormatMethod(__originalMethod));
		}
		catch (Exception ex)
		{
			if (_loggedMiss < 8)
			{
				_loggedMiss++;
				Plugin.LogSource?.LogWarning("Homm3Import release battle visual: spawned-unit visual bridge failed: " + ex.Message);
			}
		}
	}

	private static string ResolveSpawnedVisualSid(string requestedSid, string unitSid, string sourceSid)
	{
		requestedSid = NormalizeSid(requestedSid);
		unitSid = NormalizeSid(unitSid);
		sourceSid = NormalizeSid(sourceSid);
		if (string.IsNullOrEmpty(requestedSid))
			return null;

		if (requestedSid.StartsWith("h3_", StringComparison.Ordinal)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(requestedSid, null, out _))
		{
			if (!string.Equals(unitSid, requestedSid, StringComparison.Ordinal))
				LogSpawnReconcile(requestedSid, unitSid, requestedSid, "explicit-request");
			return requestedSid;
		}

		if (!string.IsNullOrEmpty(unitSid)
		    && unitSid.StartsWith("h3_", StringComparison.Ordinal)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(unitSid, null, out _))
			return unitSid;

		if (string.IsNullOrEmpty(sourceSid)
		    || !sourceSid.StartsWith("h3_", StringComparison.Ordinal)
		    || !Homm3CustomFactionRegistry.TryGetFactionSidForCustomUnitSid(sourceSid, out var factionSid))
			return null;

		if (TryResolveSpecialSpawnVisualSid(requestedSid, factionSid, sourceSid, out var customSid)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(customSid, null, out _))
		{
			LogSpawnReconcile(requestedSid, unitSid, customSid, "source=" + sourceSid);
			return customSid;
		}

		if (Homm3CustomFactionRegistry.TryGetCustomSidForDonorInFaction(requestedSid, factionSid, out customSid)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(customSid, null, out _))
		{
			LogSpawnReconcile(requestedSid, unitSid, customSid, "source=" + sourceSid);
			return customSid;
		}

		return null;
	}

	private static void LogSpawnObserverDiagnostic(
		string reason,
		string requestedSid,
		string unitSid,
		string sourceSid,
		string visualSid,
		GameObject nativeVisual,
		Unit unit,
		FieldObject result,
		object[] args,
		MethodBase method)
	{
		if (!IsBattleVisualDiagnosticsEnabled())
			return;
		if (_loggedSpawnObserverDiag++ >= 48)
			return;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle visual diag: spawn observer reason='"
			+ (reason ?? "?")
			+ "' method='"
			+ FormatMethod(method)
			+ "' requestedSid='"
			+ (requestedSid ?? "?")
			+ "' unitSid='"
			+ (unitSid ?? "?")
			+ "' sourceSid='"
			+ (sourceSid ?? "?")
			+ "' visualSid='"
			+ (visualSid ?? "?")
			+ "' resultType='"
			+ (result?.GetType().FullName ?? "?")
			+ "' unitPtr='"
			+ FormatPointer(unit)
			+ "' nativeVisual='"
			+ (nativeVisual ? nativeVisual.name : "?")
			+ "' nativeVisualPath='"
			+ (nativeVisual ? GetTransformPath(nativeVisual.transform) : "?")
			+ "' args='"
			+ FormatSpawnArgs(args)
			+ "'.");
	}

	private static bool TryResolveSpecialSpawnVisualSid(string requestedSid, string factionSid, string sourceSid, out string customSid)
	{
		customSid = null;
		requestedSid = NormalizeSid(requestedSid);
		factionSid = NormalizeSid(factionSid);
		if (string.IsNullOrEmpty(requestedSid) || string.IsNullOrEmpty(factionSid))
			return false;

		if (string.Equals(factionSid, "homm3_cove", StringComparison.Ordinal)
		    && string.Equals(requestedSid, "crossbowman", StringComparison.Ordinal)
		    && IsCoveCannonSource(sourceSid))
		{
			customSid = Homm3CoveCannonVisuals.UnitSid;
			return true;
		}

		return false;
	}

	private static GameObject ResolveSpawnedNativeVisual(FieldObject spawned)
	{
		if (spawned == null)
			return null;
		var component = TryCastIl2Cpp<Component>(spawned);
		if (component && component.gameObject)
			return component.gameObject;
		try
		{
			var direct = ReadMember(spawned, "gameObject") as GameObject;
			if (direct)
				return direct;
		}
		catch
		{
		}
		return null;
	}

	private static bool IsCoveCannonSource(string sourceSid)
	{
		sourceSid = NormalizeSid(sourceSid);
		return string.Equals(sourceSid, "h3_pirate", StringComparison.Ordinal)
		       || string.Equals(sourceSid, "h3_corsair", StringComparison.Ordinal)
		       || string.Equals(sourceSid, "h3_sea_dog", StringComparison.Ordinal);
	}

	private static void LogSpawnReconcile(string requestedSid, string unitSid, string visualSid, string reason)
	{
		if (!IsBattleVisualDiagnosticsEnabled())
			return;
		if (_loggedSpawnReconcile++ >= 24)
			return;
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle visual diag: spawned visual reconciled requestedSid='"
			+ (requestedSid ?? "?")
			+ "' unitSid='"
			+ (unitSid ?? "?")
			+ "' visualSid='"
			+ (visualSid ?? "?")
			+ "' reason='"
			+ (reason ?? "?")
			+ "'.");
	}

	private static bool IsBattleVisualDiagnosticsEnabled()
	{
		return Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag");
	}

	private static int SafeFrameCount()
	{
		try
		{
			return Time.frameCount;
		}
		catch
		{
			return 0;
		}
	}

	internal static bool TryReplaceBattleVisualForDrawer(object drawer, string unitSid, bool? leftSide, string source)
	{
		return TryReplaceBattleVisualForDrawer(drawer, unitSid, leftSide, source, null, null);
	}

	private static bool TryReplaceBattleVisualForDrawer(object drawer, string unitSid, bool? leftSide, string source, GameObject nativeVisualOverride, TransferUnit transfer = null, UnitViewConfig viewConfig = null)
	{
		if (drawer == null)
			return false;
		if (!Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(unitSid, Plugin.LogSource, out var entry))
		{
			if (IsBattleVisualDiagnosticsEnabled() && _loggedMiss < 8 && !string.IsNullOrEmpty(unitSid) && unitSid.StartsWith("h3_", StringComparison.Ordinal))
			{
				_loggedMiss++;
				Plugin.LogSource?.LogInfo("Homm3Import release battle visual: no homm3_import entry for unitSid='" + unitSid + "'.");
			}
			return false;
		}

		if (!Homm3ImportVisuals.TryGetBattleTemplate(entry, Plugin.LogSource, out var template) || !template)
		{
			Plugin.LogSource?.LogWarning("Homm3Import release battle visual: no battle template for unitSid='" + unitSid + "'.");
			return false;
		}

		try
		{
			var nativeVisual = nativeVisualOverride
			                   ?? GetPreferredTypedMemberValue<GameObject>(drawer, GameSymbols.BattleVisual.CurrentEcdVisualGameObjectFields)
			                   ?? GetTypedMemberValue<GameObject>(drawer, GameSymbols.BattleVisual.EcdVisualGameObjectFields);
			if (nativeVisual && Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(nativeVisual))
			{
				AttachRuntimeHelpers(nativeVisual, entry);
				BindOwnedViewHelper(drawer, nativeVisual, unitSid);
				if (string.Equals(unitSid, Homm3CoveCannonVisuals.UnitSid, StringComparison.Ordinal))
					Homm3CoveCannonVisuals.RememberBattleTransfer(transfer, nativeVisual);
				return true;
			}

			var host = (drawer as Component)?.gameObject;
			var instance = UnityEngine.Object.Instantiate(template);
			if (!instance)
				return false;
			instance.name = template.name;

			if (nativeVisual)
			{
				instance.transform.SetParent(nativeVisual.transform.parent, false);
				instance.transform.localPosition = nativeVisual.transform.localPosition;
				instance.transform.localRotation = nativeVisual.transform.localRotation;
				if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
				{
					instance.transform.localScale = Vector3.one;
					Homm3ImportVisuals.FitSkinnedBattleMesh(nativeVisual, instance, entry, Plugin.LogSource);
				}
				else
					instance.transform.localScale = nativeVisual.transform.localScale;
				NormalizeBattlePlaneAnchor(instance);
				if (EsquirePikemanVisuals.BattleSyncVanillaPresentation)
				{
					EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(nativeVisual, instance);
					EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(nativeVisual, instance);
				}
			}
			else if (host)
			{
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle visual: native visual missing for unitSid='"
					+ unitSid
					+ "'; queueing deferred drawer replacement.");
				UnityEngine.Object.Destroy(instance);
				QueueDeferredDrawerReplacement(drawer, unitSid, leftSide, source, viewConfig);
				return false;
			}

			ApplyVerticalAdjustment(nativeVisual, instance);
			if (leftSide.HasValue)
				ApplySideFacing(instance, leftSide.Value);
			// Prefer the vanilla battle presentation (a real 3D unit whose materials use the game's
			// Hex/Lit shader) as the skinned-lane material donor; the game's own native visual for
			// this custom unit is the generic unit_cutout billboard, whose flat-sprite shader must
			// never be applied to the skinned mesh. Cache-only: ecd.Init runs while the battle
			// loader is mid-load, and a re-entrant ResManager.Get for the presentation donor froze
			// combat load (log stopped right after the ResManager type probe). A donor is only used
			// when a safe context (preview UI) already loaded it; otherwise the manual Hex/Lit
			// stamp (Shader.Find + white color + bundle texture + opaque state) carries the material.
			var materialDonor = nativeVisual;
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance)
			    && Homm3ImportVisuals.TryGetCachedBattlePresentationTemplate(entry, Plugin.LogSource, out var presentationDonor)
			    && presentationDonor)
			{
				materialDonor = presentationDonor;
			}
			Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility(instance, materialDonor, entry, Plugin.LogSource);
			Homm3ImportVisuals.ApplyRuntimeBattleSpriteScale(instance);
			var visualGameObjectWritten = SetTypedMemberValue(drawer, typeof(GameObject), instance, GameSymbols.BattleVisual.EcdVisualGameObjectFields);
			var movementGameObjectPreserved = GetTypedMemberValue<GameObject>(drawer, GameSymbols.BattleVisual.CurrentEczMovementGameObjectFields) != null;
			var movementTransformPreserved = GetTypedMemberValue<Transform>(drawer, GameSymbols.BattleVisual.CurrentEczMovementTransformFields) != null;
			var orientationGameObjectWrites = SetPreferredTypedMemberValues(drawer, typeof(GameObject), instance, GameSymbols.BattleVisual.CurrentEczOrientationGameObjectFields);
			var orientationTransformWrites = SetPreferredTypedMemberValues(drawer, typeof(Transform), instance.transform, GameSymbols.BattleVisual.CurrentEczOrientationTransformFields);
			if (orientationGameObjectWrites == 0 && orientationTransformWrites == 0)
			{
				Plugin.LogSource?.LogError(
					"Homm3Import release battle visual: aborting replacement for unitSid='"
					+ unitSid
					+ "' because battle drawer orientation slots did not resolve.");
				UnityEngine.Object.Destroy(instance);
				return false;
			}
			var animatorWritten = SetTypedMemberValue(drawer, typeof(Animator), instance.GetComponentInChildren<Animator>(true), GameSymbols.BattleVisual.EcdAnimatorFields);
			var sprite = instance.GetComponentInChildren<SpriteRenderer>(true);
			var spriteWritten = sprite && SetTypedMemberValue(drawer, typeof(SpriteRenderer), sprite, GameSymbols.BattleVisual.EcdSpriteRendererFields);
			if (nativeVisual)
			{
				nativeVisual.SetActive(false);
				DisableNativeDonorVisuals(instance, nativeVisual, unitSid);
				Homm3BattleDonorVisualSuppressor.TryAttach(instance, nativeVisual.transform.parent, unitSid, Plugin.LogSource);
				if (nativeVisual.scene.IsValid())
					UnityEngine.Object.Destroy(nativeVisual);
			}

			AttachRuntimeHelpers(instance, entry);
			BindOwnedViewHelper(drawer, instance, unitSid);
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
				Homm3SkinnedFacingDiag.TryAttach(instance, Plugin.LogSource);
			if (string.Equals(unitSid, Homm3CoveCannonVisuals.UnitSid, StringComparison.Ordinal))
				Homm3CoveCannonVisuals.RememberBattleTransfer(transfer, instance);
			if (IsBattleVisualDiagnosticsEnabled() && _loggedApply < 32)
			{
				_loggedApply++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle visual: replaced unitSid='"
					+ unitSid
					+ "' with HoMM3 battle prefab; renderers="
					+ instance.GetComponentsInChildren<Renderer>(true).Length
					+ " localScale="
					+ FormatVector3(instance.transform.localScale)
					+ " leftSide="
					+ leftSide
					+ " visualWrite="
					+ visualGameObjectWritten
					+ " movementGoPreserved="
					+ movementGameObjectPreserved
					+ " movementTransformPreserved="
					+ movementTransformPreserved
					+ " orientationGoWrites="
					+ orientationGameObjectWrites
					+ " orientationTransformWrites="
					+ orientationTransformWrites
					+ " animatorWrite="
					+ animatorWritten
					+ " spriteWrite="
					+ spriteWritten
					+ " source="
					+ (source ?? "?")
					+ ".");
			}
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import release battle visual postfix failed for unitSid='" + unitSid + "': " + ex);
			return false;
		}
	}

	private static T GetPreferredTypedMemberValue<T>(object owner, params string[] preferredNames)
		where T : UnityEngine.Object
	{
		return GetTypedMemberValue<T>(owner, preferredNames);
	}

	internal static void ProcessDeferredSpawnedBattleVisuals()
	{
		if (PendingSpawnedVisuals.Count == 0)
			return;
		for (var i = PendingSpawnedVisuals.Count - 1; i >= 0; i--)
		{
			var pending = PendingSpawnedVisuals[i];
			if (string.IsNullOrEmpty(pending.UnitSid)
			    || (pending.Drawer == null && (pending.Unit == null || pending.Unit.Pointer == IntPtr.Zero)))
			{
				PendingSpawnedVisuals.RemoveAt(i);
				continue;
			}

			var drawer = pending.Drawer ?? ResolveDrawerForBattleUnit(pending.Unit);
			if (drawer != null)
			{
				var replaced = TryReplaceBattleVisualForDrawer(drawer, pending.UnitSid, pending.LeftSide, pending.Source, pending.NativeVisual, null, pending.ViewConfig);
				if (replaced)
				{
					if (!pending.Applied)
					{
						pending.Applied = true;
						if (_loggedDeferred < 24)
						{
							_loggedDeferred++;
							Plugin.LogSource?.LogInfo(
								"Homm3Import release battle visual: deferred spawned replacement applied unitSid='"
								+ pending.UnitSid
								+ "' source="
								+ pending.Source
								+ ".");
						}
					}

					pending.GuardFrames--;
					if (pending.GuardFrames <= 0)
						PendingSpawnedVisuals.RemoveAt(i);
					else
						PendingSpawnedVisuals[i] = pending;
					continue;
				}
			}

			pending.AttemptsRemaining--;
			if (pending.AttemptsRemaining <= 0)
			{
				if (_loggedDeferred < 24)
				{
					_loggedDeferred++;
					Plugin.LogSource?.LogWarning(
						"Homm3Import release battle visual: deferred spawned replacement failed unitSid='"
						+ pending.UnitSid
						+ "' drawer="
						+ (drawer == null ? "null" : drawer.GetType().FullName)
						+ " source="
						+ pending.Source
						+ ".");
				}
				PendingSpawnedVisuals.RemoveAt(i);
			}
			else
			{
				PendingSpawnedVisuals[i] = pending;
			}
		}
	}

	private static void QueueSpawnedBattleVisual(Unit unit, GameObject nativeVisual, string unitSid, string source)
	{
		if (unit == null || unit.Pointer == IntPtr.Zero || string.IsNullOrEmpty(unitSid))
			return;
		for (var i = 0; i < PendingSpawnedVisuals.Count; i++)
		{
			var existing = PendingSpawnedVisuals[i];
			if (existing.Unit != null && existing.Unit.Pointer == unit.Pointer && string.Equals(existing.UnitSid, unitSid, StringComparison.Ordinal))
			{
				if (!existing.NativeVisual && nativeVisual)
					existing.NativeVisual = nativeVisual;
				existing.AttemptsRemaining = Math.Max(existing.AttemptsRemaining, 45);
				existing.GuardFrames = Math.Max(existing.GuardFrames, 8);
				PendingSpawnedVisuals[i] = existing;
				return;
			}
		}

		PendingSpawnedVisuals.Add(new PendingSpawnedBattleVisual
		{
			Unit = unit,
			NativeVisual = nativeVisual,
			UnitSid = unitSid,
			Source = "spawn-object:" + (source ?? "?"),
			AttemptsRemaining = 45,
			GuardFrames = 8,
		});
		if (_loggedDeferred < 24)
		{
			_loggedDeferred++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import release battle visual: queued spawned unit replacement unitSid='"
				+ unitSid
				+ "' source="
				+ (source ?? "?")
			+ ".");
		}
	}

	private static void QueueDrawerGuard(object drawer, string unitSid, string source)
	{
		if (drawer == null || string.IsNullOrEmpty(unitSid) || !unitSid.StartsWith("h3_", StringComparison.Ordinal))
			return;
		for (var i = 0; i < PendingSpawnedVisuals.Count; i++)
		{
			var existing = PendingSpawnedVisuals[i];
			if (existing.Drawer == drawer && string.Equals(existing.UnitSid, unitSid, StringComparison.Ordinal))
			{
				existing.GuardFrames = Math.Max(existing.GuardFrames, 8);
				PendingSpawnedVisuals[i] = existing;
				return;
			}
		}

		PendingSpawnedVisuals.Add(new PendingSpawnedBattleVisual
		{
			Drawer = drawer,
			UnitSid = unitSid,
			Source = "drawer-guard:" + (source ?? "?"),
			AttemptsRemaining = 0,
			GuardFrames = 8,
			Applied = true,
		});
	}

	internal static void ValidateDrawerFieldSurfacesOrThrow(object drawer)
	{
		if (drawer == null)
			throw new InvalidOperationException("required release battle visual surface missing: battle drawer instance was null.");
		var drawerType = drawer.GetType();
		RequireCurrentOrientationSurfaces(drawerType);
	}

	private static void RequireCurrentOrientationSurfaces(Type battleUnitViewType)
	{
		if (battleUnitViewType == null)
			throw new InvalidOperationException("required release battle visual orientation surface missing: battle drawer type not found.");
		TryInitializeIl2CppType(battleUnitViewType);
		var drawerBaseType = Homm3BattleVisualInterop.ResolveDrawerSupplementalBaseType()
		                   ?? ResolveAssemblyType(GameSymbols.BattleVisual.BattleDrawerTypeNames, "battle.visual.drawerBase");
		if (drawerBaseType != null)
			TryInitializeIl2CppType(drawerBaseType);
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEcdVisualGameObjectFields))
			throw new InvalidOperationException("required release battle visual surface missing: current battle drawer visual GameObject field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEcdAnimatorFields))
			throw new InvalidOperationException("required release battle visual surface missing: current battle drawer Animator field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEcdSpriteRendererFields))
			throw new InvalidOperationException("required release battle visual surface missing: current battle drawer SpriteRenderer field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEczMovementGameObjectFields))
			throw new InvalidOperationException("required release battle visual placement surface missing: current drawer movement GameObject field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEczMovementTransformFields))
			throw new InvalidOperationException("required release battle visual placement surface missing: current drawer movement Transform field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEczOrientationGameObjectFields))
			throw new InvalidOperationException("required release battle visual orientation surface missing: current drawer orientation GameObject field.");
		if (!HasLogicalFieldOnDrawerTypes(battleUnitViewType, drawerBaseType, GameSymbols.BattleVisual.CurrentEczOrientationTransformFields))
			throw new InvalidOperationException("required release battle visual orientation surface missing: current drawer orientation Transform field.");
	}

	private static bool HasLogicalFieldOnDrawerTypes(Type battleUnitViewType, Type drawerBaseType, params string[] logicalNames)
	{
		if (Homm3BattleVisualInterop.HasLogicalField(battleUnitViewType, logicalNames))
			return true;
		return drawerBaseType != null
		       && drawerBaseType != battleUnitViewType
		       && Homm3BattleVisualInterop.HasLogicalField(drawerBaseType, logicalNames);
	}

	private static void DisableNativeDonorVisuals(GameObject instance, GameObject nativeVisual, string unitSid, Transform parentOverride = null)
	{
		try
		{
			if (!instance || !nativeVisual)
				return;
			var parent = parentOverride ? parentOverride : nativeVisual.transform.parent;
			if (!parent)
				return;

			SuppressDonorVisuals(parent, instance.transform, nativeVisual.transform, suppressAllOtherVisuals: true, out var disabledRenderers, out var stoppedParticles, out var disabledLights);

			if (IsBattleVisualDiagnosticsEnabled() && (disabledRenderers > 0 || stoppedParticles > 0 || disabledLights > 0) && _loggedDonorHide < 24)
			{
				_loggedDonorHide++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import release battle visual: disabled donor visuals near unitSid='"
					+ (unitSid ?? "?")
					+ "' renderers="
					+ disabledRenderers
					+ " particles="
					+ stoppedParticles
					+ " lights="
					+ disabledLights
					+ ".");
			}
		}
		catch (Exception ex)
		{
			if (_loggedDonorHide < 8)
			{
				_loggedDonorHide++;
				Plugin.LogSource?.LogWarning("Homm3Import release battle visual: donor visual hide failed: " + ex.Message);
			}
		}
	}

	internal static void SuppressDonorVisuals(
		Transform parent,
		Transform keepRoot,
		Transform nativeRoot,
		bool suppressAllOtherVisuals,
		out int disabledRenderers,
		out int stoppedParticles,
		out int disabledLights)
	{
		disabledRenderers = 0;
		stoppedParticles = 0;
		disabledLights = 0;
		if (!parent)
			return;

		var renderers = parent.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer || !renderer.gameObject)
				continue;
			var rt = renderer.transform;
			if (IsKeptTransform(rt, keepRoot) || !ShouldSuppressDonorTransform(rt, nativeRoot, renderer.gameObject, suppressAllOtherVisuals))
				continue;
			if (renderer.enabled)
				disabledRenderers++;
			renderer.enabled = false;
		}

		var components = parent.GetComponentsInChildren<Component>(true);
		for (var i = 0; i < components.Length; i++)
		{
			var particle = components[i];
			if (!particle || !particle.gameObject)
				continue;
			var type = particle.GetType();
			if (!string.Equals(type.FullName, "UnityEngine.ParticleSystem", StringComparison.Ordinal)
			    && !string.Equals(type.Name, "ParticleSystem", StringComparison.Ordinal))
				continue;
			var pt = particle.transform;
			if (IsKeptTransform(pt, keepRoot) || !ShouldSuppressDonorTransform(pt, nativeRoot, particle.gameObject, suppressAllOtherVisuals))
				continue;

			var changed = false;
			try
			{
				var isPlaying = GetBoolMemberValue(particle, "isPlaying");
				var particleCount = GetIntMemberValue(particle, "particleCount");
				if (isPlaying || particleCount > 0)
					changed = true;
				InvokeUnityMethod(particle, "Stop", true);
				InvokeUnityMethod(particle, "Clear", true);
			}
			catch { }
			try
			{
				if (TryDisableParticleEmission(particle))
					changed = true;
			}
			catch { }
			if (changed)
				stoppedParticles++;
		}

		var lights = parent.GetComponentsInChildren<Light>(true);
		for (var i = 0; i < lights.Length; i++)
		{
			var light = lights[i];
			if (!light || !light.gameObject)
				continue;
			var lt = light.transform;
			if (IsKeptTransform(lt, keepRoot) || !ShouldSuppressDonorTransform(lt, nativeRoot, light.gameObject, suppressAllOtherVisuals))
				continue;
			if (light.enabled)
				disabledLights++;
			light.enabled = false;
		}
	}

	private static bool IsKeptTransform(Transform candidate, Transform keepRoot)
	{
		if (Homm3MeshFx.IsFxDescendant(candidate))
			return true;
		return candidate && keepRoot && (candidate == keepRoot || candidate.IsChildOf(keepRoot));
	}

	private static bool ShouldSuppressDonorTransform(Transform candidate, Transform nativeRoot, GameObject go, bool suppressAllOtherVisuals)
	{
		if (!candidate)
			return false;
		if (suppressAllOtherVisuals)
			return true;
		return (nativeRoot && (candidate == nativeRoot || candidate.IsChildOf(nativeRoot)))
		       || LooksLikeDungeonDonorObject(go);
	}

	internal static bool LooksLikeDungeonDonorObject(GameObject go)
	{
		if (!go)
			return false;
		var text = (go.name ?? "").ToLowerInvariant();
		var parent = go.transform ? go.transform.parent : null;
		if (parent)
			text += " " + (parent.name ?? "").ToLowerInvariant();
		return text.Contains("trogl")
		       || text.Contains("troglodyte")
		       || text.Contains("pet")
		       || text.Contains("assassin")
		       || text.Contains("blade_dancer")
		       || text.Contains("minos")
		       || text.Contains("medusa")
		       || text.Contains("hydra")
		       || text.Contains("black_dragon");
	}

	private static bool TryDisableParticleEmission(Component particle)
	{
		if (!particle)
			return false;
		var type = particle.GetType();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var prop = type.GetProperty("emission", flags);
		if (prop == null || prop.GetIndexParameters().Length != 0)
			return false;
		var emission = prop.GetValue(particle);
		if (emission == null)
			return false;
		var emissionType = emission.GetType();
		var enabledProp = emissionType.GetProperty("enabled", flags);
		if (enabledProp == null || !enabledProp.CanWrite || enabledProp.GetIndexParameters().Length != 0)
			return false;
		var wasEnabled = false;
		try
		{
			wasEnabled = enabledProp.GetValue(emission) is bool b && b;
		}
		catch { }
		enabledProp.SetValue(emission, false);
		return wasEnabled;
	}

	private static void InvokeUnityMethod(object owner, string methodName, params object[] args)
	{
		if (owner == null || string.IsNullOrEmpty(methodName))
			return;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var methods = owner.GetType().GetMethods(flags);
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (method == null || !string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length != args.Length)
				continue;
			var compatible = true;
			for (var p = 0; p < ps.Length; p++)
			{
				if (args[p] != null && !ps[p].ParameterType.IsInstanceOfType(args[p]))
				{
					compatible = false;
					break;
				}
			}
			if (!compatible)
				continue;
			method.Invoke(owner, args);
			return;
		}
	}

	private static bool GetBoolMemberValue(object owner, string name)
	{
		var value = GetMemberValue(owner, name);
		return value is bool b && b;
	}

	private static int GetIntMemberValue(object owner, string name)
	{
		var value = GetMemberValue(owner, name);
		return value is int i ? i : 0;
	}

	private static void ApplyVerticalAdjustment(GameObject nativeVisual, GameObject instance)
	{
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			return;
		var extraY = EsquirePikemanVisuals.BattleBillboardExtraY;
		var dyAlign = 0f;
		if (nativeVisual
		    && EsquirePikemanVisuals.BattleAlignFeetToVanilla
		    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(nativeVisual, out var vanillaBounds)
		    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(instance, out var customBounds))
		{
			dyAlign = vanillaBounds.min.y - customBounds.min.y;
		}

		var dy = dyAlign + extraY;
		if (Mathf.Abs(dy) <= 1e-5f)
			return;
		var p = instance.transform.position;
		p.y += dy;
		instance.transform.position = p;
	}

	private static void NormalizeBattlePlaneAnchor(GameObject instance)
	{
		if (!instance)
			return;
		var root = instance.transform.Find("billboard");
		if (!root)
			return;
		var p = root.localPosition;
		var targetY = p.y + ReleaseBattleBillboardLocalYOffset;
		if (Mathf.Abs(p.x - ReleaseBattleBillboardLocalXOffset) <= 1e-5f && Mathf.Abs(p.z) <= 1e-5f && Mathf.Abs(p.y - targetY) <= 1e-5f)
			return;
		p.x = ReleaseBattleBillboardLocalXOffset;
		p.y = targetY;
		p.z = 0f;
		root.localPosition = p;
	}

	private static void ApplySideFacing(GameObject instance, bool leftSide)
	{
		if (!instance)
			return;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
		{
			Homm3ImportVisuals.TryApplyOwnedSkinnedSideFacing(instance, leftSide, Plugin.LogSource);
			return;
		}
		var quad = instance.transform.Find("billboard/quad");
		if (!quad)
			quad = instance.GetComponentInChildren<MeshRenderer>(true)?.transform;
		if (!quad)
			return;

		var scale = quad.localScale;
		var x = Mathf.Abs(scale.x);
		if (x <= 1e-5f)
			return;
		var targetX = leftSide ? x : -x;
		scale.x = targetX;
		quad.localScale = scale;

		var p = quad.localPosition;
		var px = Mathf.Abs(p.x);
		if (px > 1e-5f)
		{
			p.x = px * (targetX >= 0f ? 1f : -1f);
			quad.localPosition = p;
		}
	}

	internal static void AttachRuntimeHelpers(GameObject instance, Homm3ImportVisuals.Entry entry)
	{
		if (!Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
		{
			Homm3BattleBillboardCameraFacing.TryAttach(instance, Plugin.LogSource);
			Homm3BattleArrayBillboard.TryAttach(instance, entry, Plugin.LogSource);
			Homm3BattleDiskTextureRemap.TryAttach(instance, entry, Plugin.LogSource);
			Homm3BattlePassiveAttackProbe.TryAttach(instance, entry, Plugin.LogSource);
		}
		else
		{
			// Before the drawer's Init reads meshHolder.GetComponent<view helper>() on the pool path.
			Homm3UnitViewHelperRuntime.TryEnsure(instance, entry?.BundleName, Plugin.LogSource);
		}
		EsquireBattleAnimatorTelemetry.TryAttach(instance, Plugin.LogSource);
		Homm3MeshFx.TryAttachForSkinnedBattle(instance, entry, Plugin.LogSource);
		// Opt-in additive metal shine (homm3_mesh_fx/metal_shine/catalog.json); no row = no host.
		Homm3MetalShine.TryAttachForSkinnedBattle(instance, entry, Plugin.LogSource);
		var stemPrefix = Homm3ImportVisuals.ResolveHomm3LabAudioStemPrefix(entry);
		if (string.IsNullOrEmpty(stemPrefix))
			return;
		Homm3LabBattleAudioPlayer.TryAttach(instance, entry.BundleName, stemPrefix, Plugin.LogSource);
		Homm3LabClipAudioDriver.TryAttach(instance, Plugin.LogSource);
	}

	/// <summary>
	/// The drawer captured its view helper in Init from the pooled meshHolder; when the visible owned skinned
	/// instance is ours, point that slot at the instance's helper so projectiles leave its hand.
	/// </summary>
	private static void BindOwnedViewHelper(object drawer, GameObject instance, string unitSid)
	{
		if (!Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			return;
		var helper = Homm3UnitViewHelperRuntime.TryEnsure(instance, unitSid, Plugin.LogSource);
		if (helper != null)
			Homm3UnitViewHelperRuntime.TryBindDrawer(drawer, helper, unitSid, Plugin.LogSource);
	}

	private static object ResolveDrawerForBattleUnit(Unit unit)
	{
		if (unit == null)
			return null;
		var battleControllerType = ResolveAssemblyType(GameSymbols.BattleVisual.BattleControllerTypeNames, "battle.visual.controller");
		if (battleControllerType == null)
			return null;
		var battleController = ReadStaticMember(battleControllerType, GameSymbols.BattleVisual.BattleControllerInstanceMembers);
		var drawerManager = ReadMember(battleController, GameSymbols.BattleVisual.BattleControllerDrawerManagerMembers);
		if (drawerManager == null)
			return null;
		return InvokeMember(drawerManager, GameSymbols.BattleVisual.DrawerManagerDrawerForUnit.NameHints, unit);
	}

	private static string TryResolveBattleUnitSid(Unit unit, bool includeConfigFallback)
	{
		if (unit == null)
			return null;
		var transfer = ReadMember(unit, GameSymbols.BattleVisual.BattleUnitTransferFields) as TransferUnit
		               ?? DeobfInteropCompat.TryReadNativeObjectMember<TransferUnit>(unit, GameSymbols.BattleVisual.BattleUnitTransferFields);
		var sid = NormalizeSid(ReadTransferUnitConfigSid(transfer))
		          ?? NormalizeSid(DeobfInteropCompat.TryReadNativeStringMember(unit, GameSymbols.BattleVisual.BattleUnitConfigSidMembers))
		          ?? NormalizeSid(ReadMember(unit, GameSymbols.BattleVisual.BattleUnitConfigSidMembers) as string);
		return sid ?? (includeConfigFallback ? ResolveCustomSidFromUnitConfigs(unit) : null);
	}

	private static string ResolveCustomSidFromUnitConfigs(Unit unit)
	{
		if (unit == null)
			return null;
		var logic = ReadMember(unit, GameSymbols.BattleVisual.BattleUnitLogicConfigFields) as UnitLogicConfig
		            ?? DeobfInteropCompat.TryReadNativeObjectMember<UnitLogicConfig>(unit, GameSymbols.BattleVisual.BattleUnitLogicConfigFields);
		var view = ReadMember(unit, GameSymbols.BattleVisual.BattleUnitViewConfigFields) as UnitViewConfig
		           ?? DeobfInteropCompat.TryReadNativeObjectMember<UnitViewConfig>(unit, GameSymbols.BattleVisual.BattleUnitViewConfigFields);

		return FirstCustomSid(
			DeobfInteropCompat.GetConfigElementId(logic),
			DeobfInteropCompat.TryReadNativeStringMember(logic, "sid"),
			DeobfInteropCompat.TryReadNativeStringMember(logic, "id"),
			DeobfInteropCompat.TryReadNativeStringMember(logic, "baseSid"),
			DeobfInteropCompat.TryReadNativeStringMember(logic, "upgradeSid"),
			ReadMember(logic, "sid") as string,
			ReadMember(logic, "id") as string,
			ReadMember(logic, "baseSid") as string,
			ReadMember(logic, "upgradeSid") as string,
			DeobfInteropCompat.GetConfigElementId(view),
			DeobfInteropCompat.TryReadNativeStringMember(view, "sid", "id"),
			ReadMember(view, "sid") as string,
			ReadMember(view, "id") as string);
	}

	private static string FirstCustomSid(params string[] candidates)
	{
		if (candidates == null)
			return null;
		for (var i = 0; i < candidates.Length; i++)
		{
			var sid = NormalizeSid(candidates[i]);
			if (!string.IsNullOrEmpty(sid) && sid.StartsWith("h3_", StringComparison.Ordinal))
				return sid;
		}
		return null;
	}

	private static string ResolveInitUnitSid(TransferUnit transfer, UnitViewConfig viewConfig)
	{
		var transferSid = NormalizeSid(ReadTransferUnitConfigSid(transfer));
		if (!string.IsNullOrEmpty(transferSid) && transferSid.StartsWith("h3_", StringComparison.Ordinal))
			return transferSid;
		var viewSid = NormalizeSid(DeobfInteropCompat.GetConfigElementId(viewConfig))
		              ?? NormalizeSid(DeobfInteropCompat.TryReadNativeStringMember(viewConfig, "sid", "id"))
		              ?? NormalizeSid(ReadMember(viewConfig, "sid") as string);
		if (!string.IsNullOrEmpty(viewSid) && viewSid.StartsWith("h3_", StringComparison.Ordinal))
			return viewSid;
		if (TryResolveInitUnitSidFromViewConfigPath(viewConfig, out var pathSid))
			return pathSid;
		return transferSid ?? viewSid;
	}

	private static bool TryResolveInitUnitSidFromViewConfigPath(UnitViewConfig viewConfig, out string unitSid)
	{
		unitSid = null;
		if (viewConfig == null)
			return false;
		var mapMesh = DeobfInteropCompat.GetUnitViewConfigMapMesh(viewConfig);
		if (Homm3ImportVisuals.TryResolveHomm3UnitSidForUnitsPath(mapMesh, out unitSid))
			return true;
		var mesh = null as string;
		try
		{
			mesh = viewConfig.mesh;
		}
		catch
		{
		}
		if (string.IsNullOrWhiteSpace(mesh))
			mesh = DeobfInteropCompat.TryReadNativeStringMember(viewConfig, "mesh");
		return Homm3ImportVisuals.TryResolveHomm3UnitSidForUnitsPath(mesh, out unitSid);
	}

	private static string ReadTransferUnitConfigSid(TransferUnit transfer)
	{
		if (transfer == null)
			return null;
		try
		{
			var direct = transfer.configSid;
			if (!string.IsNullOrWhiteSpace(direct))
				return direct.Trim();
		}
		catch
		{
		}
		return DeobfInteropCompat.TryReadNativeStringMember(transfer, "configSid", "<configSid>k__BackingField", "_configSid_k__BackingField");
	}

	private static void LogInitDiagnostic(object drawer, TransferUnit transfer, UnitViewConfig viewConfig, string resolvedSid, bool leftSide)
	{
		if (LauncherConfigReader.TryLoad()?.Homm3ReleaseBattleUiDiagnostics != true
		    && !Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
			return;
		if (_loggedInitDiag >= 40)
			return;
		var resolved = NormalizeSid(resolvedSid);
		var isCustom = !string.IsNullOrEmpty(resolved) && resolved.StartsWith("h3_", StringComparison.Ordinal);
		var hasEntry = Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(resolved, null, out var entry);
		var shouldLog = _loggedInitDiag < 12 || isCustom || !hasEntry;
		if (!shouldLog)
			return;
		_loggedInitDiag++;
		var nativeVisual = GetPreferredTypedMemberValue<GameObject>(drawer, GameSymbols.BattleVisual.CurrentEcdVisualGameObjectFields)
		                 ?? GetTypedMemberValue<GameObject>(drawer, GameSymbols.BattleVisual.EcdVisualGameObjectFields);
		Plugin.LogSource?.LogInfo(
			"Homm3Import release battle visual diag: ecd.Init sid='"
			+ (resolved ?? "?")
			+ "' transferSid='"
			+ (NormalizeSid(ReadTransferUnitConfigSid(transfer)) ?? "?")
			+ "' viewConfigId='"
			+ (NormalizeSid(DeobfInteropCompat.GetConfigElementId(viewConfig)) ?? "?")
			+ "' viewSid='"
			+ (NormalizeSid(DeobfInteropCompat.TryReadNativeStringMember(viewConfig, "sid", "id") ?? ReadMember(viewConfig, "sid") as string) ?? "?")
			+ "' mapMesh='"
			+ (DeobfInteropCompat.GetUnitViewConfigMapMesh(viewConfig) ?? "?")
			+ "' importEntry="
			+ hasEntry
			+ " battlePath='"
			+ (hasEntry ? entry.BattlePrefabAssetPath ?? "?" : "?")
			+ "' nativeVisual='"
			+ (nativeVisual ? nativeVisual.name : "(none)")
			+ "' nativeType='"
			+ (nativeVisual ? nativeVisual.GetType().FullName : "?")
			+ "' drawer='"
			+ (drawer?.GetType().FullName ?? "?")
			+ "' leftSide="
			+ leftSide
			+ ".");
	}

	private static T TryCastIl2Cpp<T>(object value) where T : Il2CppObjectBase
	{
		if (value is T typed)
			return typed;
		if (value is Il2CppObjectBase obj && obj.Pointer != IntPtr.Zero)
		{
			try
			{
				return obj.TryCast<T>();
			}
			catch
			{
			}
		}
		return null;
	}

	private static string NormalizeSid(string sid) => string.IsNullOrWhiteSpace(sid) ? null : sid.Trim();

	private static string FormatPointer(Il2CppObjectBase obj)
	{
		if (obj == null || obj.Pointer == IntPtr.Zero)
			return "0x0";
		return "0x" + obj.Pointer.ToInt64().ToString("x", CultureInfo.InvariantCulture);
	}

	private static string GetTransformPath(Transform transform)
	{
		if (!transform)
			return "?";
		var parts = new List<string>();
		for (var t = transform; t; t = t.parent)
		{
			parts.Add(t.name ?? "?");
			if (parts.Count >= 16)
				break;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static string FormatSpawnArgs(object[] args)
	{
		if (args == null)
			return "null";
		var parts = new List<string>();
		for (var i = 0; i < args.Length && i < 10; i++)
		{
			var arg = args[i];
			var text = i + ":";
			if (arg == null)
				text += "null";
			else if (arg is string s)
				text += "string=" + s;
			else if (arg is Il2CppObjectBase obj)
				text += arg.GetType().FullName + "@" + FormatPointer(obj);
			else
				text += arg.GetType().FullName + "=" + arg;
			parts.Add(text);
		}
		if (args.Length > 10)
			parts.Add("...len=" + args.Length);
		return string.Join(",", parts);
	}

	private static string FormatMethod(MethodBase method)
	{
		return method == null ? "?" : method.DeclaringType?.FullName + "." + method.Name;
	}

	private static Type ResolveAssemblyType(IEnumerable<string> names, string registryIdPrefix = "battle.visual.type")
	{
		var asm = typeof(ObjCityConfig).Assembly;
		if (names == null)
			return null;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = asm.GetType(name, throwOnError: false);
			if (type != null)
				return type;
			type = GameMember.FindType(registryIdPrefix + "." + name, name);
			if (type != null)
				return type;
		}
		return null;
	}

	private static bool TypeNameMatches(Type type, IEnumerable<string> names)
	{
		if (type == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			if (string.Equals(type.Name, name, StringComparison.Ordinal)
			    || string.Equals(type.FullName, name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool LooksLikeIl2CppRandom(Type type)
	{
		if (type == null || !string.Equals(type.Name, "Random", StringComparison.Ordinal))
			return false;
		return string.Equals(type.FullName, "Il2CppSystem.Random", StringComparison.Ordinal)
		       || string.Equals(type.FullName, "System.Random", StringComparison.Ordinal);
	}

	private static object GetMemberValue(object owner, string name)
	{
		if (owner == null || string.IsNullOrEmpty(name))
			return null;
		var type = owner.GetType();
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var prop = type.GetProperty(name, flags);
		if (prop != null && prop.GetIndexParameters().Length == 0)
			return prop.GetValue(owner);
		var field = type.GetField(name, flags);
		return field?.GetValue(owner);
	}

	private static object ReadMember(object owner, params string[] names)
	{
		if (owner == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var prop = type.GetProperty(name, flags);
					if (prop != null && prop.GetIndexParameters().Length == 0)
						return prop.GetValue(owner, null);
				}
				catch
				{
				}
				try
				{
					var field = type.GetField(name, flags);
					if (field != null)
						return field.GetValue(owner);
				}
				catch
				{
				}
				try
				{
					var method = type.GetMethod(name, flags);
					if (method != null && method.GetParameters().Length == 0)
						return method.Invoke(owner, Array.Empty<object>());
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static object ReadStaticMember(Type type, params string[] names)
	{
		if (type == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0)
					return prop.GetValue(null, null);
			}
			catch
			{
			}
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(null);
			}
			catch
			{
			}
			try
			{
				var method = type.GetMethod(name, flags);
				if (method != null && method.GetParameters().Length == 0)
					return method.Invoke(null, Array.Empty<object>());
			}
			catch
			{
			}
		}
		return null;
	}

	private static object InvokeMember(object owner, string[] names, params object[] args)
	{
		if (owner == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var method = type.GetMethod(name, flags);
					if (method == null)
						continue;
					var ps = method.GetParameters();
					if (ps.Length != (args?.Length ?? 0))
						continue;
					return method.Invoke(owner, args ?? Array.Empty<object>());
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private struct PendingSpawnedBattleVisual
	{
		internal Unit Unit;
		internal GameObject NativeVisual;
		internal object Drawer;
		internal string UnitSid;
		internal string Source;
		internal int AttemptsRemaining;
		internal int GuardFrames;
		internal bool Applied;
		internal bool? LeftSide;
		internal UnitViewConfig ViewConfig;
	}

	private struct PendingSummonedBattleVisual
	{
		internal string UnitSid;
		internal string DonorSid;
		internal string Source;
		internal int ExpiresAtFrame;
	}

	private static void QueueDeferredDrawerReplacement(object drawer, string unitSid, bool? leftSide, string source, UnitViewConfig viewConfig)
	{
		if (drawer == null || string.IsNullOrEmpty(unitSid))
			return;
		for (var i = 0; i < PendingSpawnedVisuals.Count; i++)
		{
			var existing = PendingSpawnedVisuals[i];
			if (existing.Drawer == drawer && string.Equals(existing.UnitSid, unitSid, StringComparison.Ordinal))
			{
				existing.AttemptsRemaining = Math.Max(existing.AttemptsRemaining, 45);
				existing.GuardFrames = Math.Max(existing.GuardFrames, 8);
				if (leftSide.HasValue)
					existing.LeftSide = leftSide;
				if (viewConfig != null)
					existing.ViewConfig = viewConfig;
				PendingSpawnedVisuals[i] = existing;
				return;
			}
		}
		PendingSpawnedVisuals.Add(new PendingSpawnedBattleVisual
		{
			Drawer = drawer,
			UnitSid = unitSid,
			Source = "deferred-drawer:" + (source ?? "?"),
			AttemptsRemaining = 45,
			GuardFrames = 8,
			LeftSide = leftSide,
			ViewConfig = viewConfig,
		});
	}


	private static T GetTypedMemberValue<T>(object owner, params string[] preferredNames)
		where T : UnityEngine.Object
	{
		if (owner == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in preferredNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0 && typeof(T).IsAssignableFrom(prop.PropertyType))
				{
					try { return prop.GetValue(owner) as T; } catch { }
				}
				var field = type.GetField(name, flags);
				if (field != null && typeof(T).IsAssignableFrom(field.FieldType))
				{
					try { return field.GetValue(owner) as T; } catch { }
				}
			}
		}

		var native = Homm3BattleVisualInterop.TryReadUnityField<T>(owner, preferredNames);
		if (native)
			return native;

		return null;
	}

	private static bool SetTypedMemberValue(object owner, Type targetType, object value, params string[] preferredNames)
	{
		if (owner == null || targetType == null || value == null)
			return false;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in preferredNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var prop = type.GetProperty(name, flags);
				if (prop != null
				    && prop.CanWrite
				    && prop.GetIndexParameters().Length == 0
				    && targetType.IsAssignableFrom(prop.PropertyType))
				{
					try
					{
						prop.SetValue(owner, value);
						return true;
					}
					catch { }
				}
				var field = type.GetField(name, flags);
				if (field != null && targetType.IsAssignableFrom(field.FieldType))
				{
					try
					{
						field.SetValue(owner, value);
						return true;
					}
					catch { }
				}
			}
		}

		if (value is UnityEngine.Object unityValue
		    && Homm3BattleVisualInterop.TryWriteUnityField(owner, unityValue, preferredNames))
			return true;

		var writableProps = new List<PropertyInfo>();
		var writableFields = new List<FieldInfo>();
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var prop in type.GetProperties(flags))
			{
				if (prop != null
				    && prop.CanWrite
				    && prop.GetIndexParameters().Length == 0
				    && targetType.IsAssignableFrom(prop.PropertyType))
					writableProps.Add(prop);
			}
			foreach (var field in type.GetFields(flags))
			{
				if (field != null && targetType.IsAssignableFrom(field.FieldType))
					writableFields.Add(field);
			}
		}
		if (writableProps.Count == 1)
		{
			try
			{
				writableProps[0].SetValue(owner, value);
				return true;
			}
			catch { }
		}
		if (writableFields.Count == 1)
		{
			try
			{
				writableFields[0].SetValue(owner, value);
				return true;
			}
			catch { }
		}

		return false;
	}

	private static int SetPreferredTypedMemberValues(object owner, Type targetType, object value, params string[] preferredNames)
	{
		if (owner == null || targetType == null || value == null || preferredNames == null)
			return 0;
		var writes = 0;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in preferredNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var prop = type.GetProperty(name, flags);
				if (prop != null
				    && prop.CanWrite
				    && prop.GetIndexParameters().Length == 0
				    && targetType.IsAssignableFrom(prop.PropertyType))
				{
					try
					{
						prop.SetValue(owner, value);
						writes++;
						continue;
					}
					catch { }
				}
				var field = type.GetField(name, flags);
				if (field != null && targetType.IsAssignableFrom(field.FieldType))
				{
					try
					{
						field.SetValue(owner, value);
						writes++;
					}
					catch { }
				}
			}
		}

		if (value is UnityEngine.Object unityValue
		    && Homm3BattleVisualInterop.TryWriteUnityField(owner, unityValue, preferredNames))
			writes++;

		return writes;
	}

	private static bool HasAssignableMember(Type ownerType, Type targetType, params string[] preferredNames)
	{
		if (ownerType == null || targetType == null || preferredNames == null)
			return false;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = ownerType; type != null; type = type.BaseType)
		{
			foreach (var name in preferredNames)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetIndexParameters().Length == 0 && targetType.IsAssignableFrom(prop.PropertyType))
					return true;
				var field = type.GetField(name, flags);
				if (field != null && targetType.IsAssignableFrom(field.FieldType))
					return true;
			}
		}
		return false;
	}

	private static bool HasAllAssignableMembers(Type ownerType, Type targetType, params string[] preferredNames)
	{
		if (preferredNames == null || preferredNames.Length == 0)
			return false;
		for (var i = 0; i < preferredNames.Length; i++)
		{
			if (!HasAssignableMember(ownerType, targetType, preferredNames[i]))
				return false;
		}
		return true;
	}

	private static void TryInitializeIl2CppType(Type battleUnitViewType)
	{
		if (battleUnitViewType == null)
			return;
		try
		{
			RuntimeHelpers.RunClassConstructor(battleUnitViewType.TypeHandle);
		}
		catch
		{
		}
	}

	private static string FormatVector3(Vector3 v) =>
		"("
		+ v.x.ToString("0.###", CultureInfo.InvariantCulture)
		+ ", "
		+ v.y.ToString("0.###", CultureInfo.InvariantCulture)
		+ ", "
		+ v.z.ToString("0.###", CultureInfo.InvariantCulture)
		+ ")";
}

public sealed class Homm3SpawnedBattleVisualBridgePump : MonoBehaviour
{
	private static bool _typeRegistered;
	private static bool _created;

	public Homm3SpawnedBattleVisualBridgePump(IntPtr ptr) : base(ptr) { }

	internal static bool Ensure(ManualLogSource log)
	{
		if (_created)
			return true;
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3SpawnedBattleVisualBridgePump>();
				_typeRegistered = true;
			}
			var go = new GameObject("Homm3SpawnedBattleVisualBridgePump");
			go.AddComponent<Homm3SpawnedBattleVisualBridgePump>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_created = true;
			log?.LogInfo("Homm3Import release battle visual: spawned-unit deferred bridge pump registered.");
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import release battle visual: spawned-unit deferred bridge pump failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	private void LateUpdate()
	{
		Homm3ImportReleaseBattleVisualHook.ProcessDeferredSpawnedBattleVisuals();
	}
}
