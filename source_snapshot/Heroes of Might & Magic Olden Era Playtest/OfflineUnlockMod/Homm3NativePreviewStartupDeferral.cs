using System;
using System.Diagnostics;
using System.Reflection;
using System.Threading;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Source-only pilot for deferring the current-build native shared-preview pool's startup creation.
/// Runtime behavior, native detour coverage, and first-demand resource behavior remain unproven.
/// </summary>
internal static class Homm3NativePreviewStartupDeferral
{
	private const int RegistrationInactive = 0;
	private const int RegistrationInProgress = 1;
	private const int RegistrationActive = 2;
	private static readonly object RegistrationLock = new();
	private static int _registrationState;
	private static bool IsRegistered => Volatile.Read(ref _registrationState) == RegistrationActive;

	private sealed class ScopeState
	{
		internal NativePreviewStartupScope.Frame Frame;
		internal long StartedTimestamp;
	}

	private sealed class PatchRegistration
	{
		internal MethodBase Target;
		internal MethodInfo Prefix;
		internal MethodInfo Finalizer;
	}

	private static int _loggedMissingNativeOwner;

	internal static bool TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (IsRegistered)
			return true;
		lock (RegistrationLock)
		{
			if (IsRegistered)
				return true;
			if (Volatile.Read(ref _registrationState) == RegistrationInProgress)
			{
				log?.LogError("Homm3NativePreviewStartupDeferral registration is already in progress; no duplicate hooks installed.");
				return false;
			}
			return TryRegisterLocked(harmony, log);
		}
	}

	private static bool TryRegisterLocked(Harmony harmony, ManualLogSource log)
	{
		if (harmony == null)
		{
			log?.LogError("Homm3NativePreviewStartupDeferral unavailable: Harmony owner was null; no hooks installed.");
			return false;
		}
		if (GameBuild.Kind != GameBuildKind.Current)
		{
			log?.LogError("Homm3NativePreviewStartupDeferral unavailable: this pilot is pinned only to the current game build (" + GameBuild.Describe() + "); no hooks installed.");
			return false;
		}

		if (!TryResolveTargets(out var warmup, out var create, out var factory, out var error))
		{
			log?.LogError("Homm3NativePreviewStartupDeferral unavailable: " + error + "; no hooks installed.");
			return false;
		}

		var warmupPrefix = GetPatchMethod(nameof(WarmupPrefix));
		var warmupFinalizer = GetPatchMethod(nameof(WarmupFinalizer));
		var createPrefix = GetPatchMethod(nameof(SharedPreviewCreatePrefix));
		var factoryPrefix = GetPatchMethod(nameof(SharedPreviewFactoryPrefix));
		var factoryFinalizer = GetPatchMethod(nameof(SharedPreviewFactoryFinalizer));
		if (warmupPrefix == null || warmupFinalizer == null || createPrefix == null || factoryPrefix == null || factoryFinalizer == null)
		{
			log?.LogError("Homm3NativePreviewStartupDeferral unavailable: one or more patch methods could not be resolved; no hooks installed.");
			return false;
		}

		var registrations = new[]
		{
			new PatchRegistration { Target = warmup, Prefix = warmupPrefix, Finalizer = warmupFinalizer },
			new PatchRegistration { Target = create, Prefix = createPrefix },
			new PatchRegistration { Target = factory, Prefix = factoryPrefix, Finalizer = factoryFinalizer },
		};
		Volatile.Write(ref _registrationState, RegistrationInProgress);
		try
		{
			foreach (var registration in registrations)
			{
				harmony.Patch(
					registration.Target,
					prefix: new HarmonyMethod(registration.Prefix),
					finalizer: registration.Finalizer == null ? null : new HarmonyMethod(registration.Finalizer));
			}
		}
		catch (Exception ex)
		{
			var rollbackFailures = 0;
			for (var i = registrations.Length - 1; i >= 0; i--)
			{
				var registration = registrations[i];
				rollbackFailures += TryUnpatchExact(harmony, registration.Target, registration.Finalizer, log);
				rollbackFailures += TryUnpatchExact(harmony, registration.Target, registration.Prefix, log);
			}
			Volatile.Write(ref _registrationState, RegistrationInactive);
			var failureMessage =
				"Homm3NativePreviewStartupDeferral hook registration failed and exact-method rollback "
				+ (rollbackFailures == 0 ? "completed" : "was incomplete (" + rollbackFailures + " rollback failure(s))")
				+ ": " + ex.GetType().Name + ": " + ex.Message + ". No alternate hook path was attempted.";
			log?.LogError(failureMessage);
			if (rollbackFailures != 0)
				throw new InvalidOperationException(failureMessage, ex);
			return false;
		}

		Volatile.Write(ref _registrationState, RegistrationActive);
		log?.LogInfo("Homm3NativePreviewStartupDeferral current-build pilot registered on SharedPreviewWarmup, SharedPreviewCreate, and SharedPreviewFactory. Source registration is not runtime proof.");
		return true;
	}

	private static bool TryResolveTargets(out MethodInfo warmup, out MethodInfo create, out MethodInfo factory, out string error)
	{
		warmup = null;
		create = null;
		factory = null;
		error = null;
		var ownerType = typeof(UnitViewConfig).Assembly.GetType("Hex.BhUnitPreviews", throwOnError: false);
		if (ownerType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(ownerType))
		{
			error = "exact Hex.BhUnitPreviews native owner type was unavailable";
			return false;
		}

		var warmups = GameMember.FindMethods(ownerType, typeof(void), Type.EmptyTypes, GameSymbols.UnitPreview.SharedPreviewWarmup);
		if (warmups.Length != 1)
		{
			error = "SharedPreviewWarmup pin resolved " + warmups.Length + " compatible methods instead of exactly one";
			return false;
		}
		warmup = warmups[0];

		var createCandidates = GameMember.FindMethods(
			ownerType,
			null,
			new[] { typeof(UnitViewConfig) },
			GameSymbols.UnitPreview.SharedPreviewCreate);
		foreach (var candidate in createCandidates)
		{
			if (!typeof(MonoBehaviour).IsAssignableFrom(candidate.ReturnType))
				continue;
			if (create != null)
			{
				error = "SharedPreviewCreate pin resolved multiple native-object return methods";
				return false;
			}
			create = candidate;
		}
		if (create == null)
		{
			error = "SharedPreviewCreate pin did not resolve one native-object-returning UnitViewConfig method";
			return false;
		}

		var factoryCandidates = GameMember.FindMethods(
			ownerType,
			typeof(bool),
			new[] { typeof(string), typeof(float), (Type)null },
			GameSymbols.UnitPreview.SharedPreviewFactory);
		foreach (var candidate in factoryCandidates)
		{
			var parameters = candidate.GetParameters();
			if (parameters.Length != 3
			    || !parameters[2].ParameterType.IsByRef
			    || parameters[2].ParameterType.GetElementType() != create.ReturnType)
				continue;
			if (factory != null)
			{
				error = "SharedPreviewFactory pin resolved multiple bool(string,float,ref SharedPreviewCreate-result) methods";
				return false;
			}
			factory = candidate;
		}
		if (factory == null)
		{
			error = "SharedPreviewFactory pin did not resolve the exact bool(string,float,ref SharedPreviewCreate-result) method";
			return false;
		}
		return true;
	}

	private static MethodInfo GetPatchMethod(string name)
	{
		return typeof(Homm3NativePreviewStartupDeferral).GetMethod(
			name,
			BindingFlags.NonPublic | BindingFlags.Static);
	}

	private static int TryUnpatchExact(Harmony harmony, MethodBase target, MethodInfo patch, ManualLogSource log)
	{
		if (patch == null)
			return 0;
		try
		{
			harmony.Unpatch(target, patch);
			return 0;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3NativePreviewStartupDeferral exact rollback failed for " + patch.Name + " on "
				+ target.Name + ": " + ex.GetType().Name + ": " + ex.Message);
			return 1;
		}
	}

	private static void WarmupPrefix(Il2CppObjectBase __instance, out ScopeState __state)
	{
		__state = null;
		if (!IsRegistered)
			return;
		if (!TryGetOwnerKey(__instance, out var ownerKey))
		{
			LogMissingOwnerOnce("SharedPreviewWarmup");
			return;
		}
		__state = new ScopeState
		{
			Frame = NativePreviewStartupScope.EnterWarmup(ownerKey),
			StartedTimestamp = Stopwatch.GetTimestamp(),
		};
	}

	private static Exception WarmupFinalizer(Exception __exception, ScopeState __state)
	{
		return ExitScope(__exception, __state, logWarmup: true);
	}

	private static bool SharedPreviewCreatePrefix(Il2CppObjectBase __instance, ref object __result)
	{
		if (!IsRegistered || !NativePreviewStartupScope.IsActive)
			return true;
		if (!TryGetOwnerKey(__instance, out var ownerKey))
		{
			LogMissingOwnerOnce("SharedPreviewCreate");
			return true;
		}
		if (!NativePreviewStartupScope.TryDefer(ownerKey))
			return true;

		__result = null;
		return false;
	}

	private static void SharedPreviewFactoryPrefix(Il2CppObjectBase __instance, out ScopeState __state)
	{
		__state = null;
		if (!IsRegistered || !NativePreviewStartupScope.IsActive)
			return;
		if (!TryGetOwnerKey(__instance, out var ownerKey))
		{
			LogMissingOwnerOnce("SharedPreviewFactory");
			return;
		}
		var frame = NativePreviewStartupScope.EnterDemand(ownerKey);
		if (frame != null)
			__state = new ScopeState { Frame = frame };
	}

	private static Exception SharedPreviewFactoryFinalizer(Exception __exception, ScopeState __state)
	{
		return ExitScope(__exception, __state, logWarmup: false);
	}

	private static Exception ExitScope(Exception originalException, ScopeState state, bool logWarmup)
	{
		if (state?.Frame == null)
			return originalException;

		try
		{
			NativePreviewStartupScope.Exit(state.Frame);
		}
		catch (Exception cleanupException)
		{
			Plugin.LogSource?.LogError("Homm3NativePreviewStartupDeferral scope cleanup failed: "
				+ cleanupException.GetType().Name + ": " + cleanupException.Message
				+ (originalException == null ? "." : "; retaining the original native exception."));
			return originalException ?? cleanupException;
		}

		if (logWarmup)
		{
			var elapsedMilliseconds = (Stopwatch.GetTimestamp() - state.StartedTimestamp) * 1000d / Stopwatch.Frequency;
			var count = state.Frame.DeferredCount;
			if (count == 0)
			{
				Plugin.LogSource?.LogWarning("Homm3NativePreviewStartupDeferral warmup completed in "
					+ elapsedMilliseconds.ToString("F1", System.Globalization.CultureInfo.InvariantCulture)
					+ " ms with 0 deferred SharedPreviewCreate calls; this invocation does not prove the pilot changed startup work.");
			}
			else
			{
				Plugin.LogSource?.LogInfo("Homm3NativePreviewStartupDeferral warmup deferred " + count
					+ " SharedPreviewCreate call(s) in "
					+ elapsedMilliseconds.ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + " ms.");
			}
		}
		return originalException;
	}

	private static bool TryGetOwnerKey(Il2CppObjectBase owner, out long ownerKey)
	{
		ownerKey = 0;
		if (owner == null || owner.Pointer == IntPtr.Zero)
			return false;
		ownerKey = owner.Pointer.ToInt64();
		return ownerKey != 0;
	}

	private static void LogMissingOwnerOnce(string target)
	{
		if (System.Threading.Interlocked.Exchange(ref _loggedMissingNativeOwner, 1) == 0)
			Plugin.LogSource?.LogError("Homm3NativePreviewStartupDeferral could not obtain a nonzero native owner pointer at "
				+ target + "; the original native method is left enabled and this call is not deferred.");
	}
}
