using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3ProjectileConfigHook
{
	const string DefaultDonorProjectilePath = "effects/projectiles/crossbowman_upg_hit_bolt_projectile";
	const string CoveCannonProjectilePath = "effects/projectiles/homm3_cove_cannon_projectile";
	const string CoveCannonDonorProjectilePath = "effects/projectiles/siege_projectile";
	const string CoveCannonNativeProjectilePath = "effects/projectiles/Graverobber_projectile";
	const int PendingTtlFrames = 3600;
	// Keep the startup symbol contract, but do not patch this getter until a safe hero projectile attach path is traced.
	const bool PatchHeroAbilityProjectileGetter = false;
	static readonly Queue<PendingProjectile> Pending = new();
	static readonly Queue<PendingProjectile> PendingCoveCannon = new();
	static bool _registered;
	static int _loggedConfig;
	static int _loggedAttachMiss;
	static int _loggedControllerInit;
	static int _loggedControllerUpdate;
	static int _loggedLaunchHelper;
	static int _loggedLaunchHelperScan;

	struct PendingProjectile
	{
		internal string Homm3Path;
		internal int ExpiresAtFrame;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony harmony, ManualLogSource log)
	{
		Register(harmony, log, required: true);
	}

	static void Register(Harmony harmony, ManualLogSource log, bool required)
	{
		if (_registered || harmony == null)
		{
			if (required && harmony == null)
				throw new InvalidOperationException("Harmony was not initialized before required projectile config registration.");
			return;
		}
		try
		{
			if (required)
				Homm3ImportVisuals.RequireLoadedEntriesForReleaseSafeFeature(log, "homm3ReleaseProjectile");

			var projectileGetter = FindAbilityViewProjectileGetter();
			if (projectileGetter == null)
			{
				if (required)
					throw new MissingMethodException("AbilityViewConfig", GameSymbols.Projectile.AbilityViewProjectileGetter.Id);
				log?.LogWarning("Homm3 projectile config hook: AbilityViewConfig projectile getter not found.");
				return;
			}
			var init = FindProjectileControllerMethod(
				GameSymbols.Projectile.ControllerInit,
				typeof(BhProjectileController),
				typeof(Vector3),
				typeof(Vector3),
				typeof(Vector3),
				typeof(string),
				typeof(float),
				typeof(float),
				typeof(ETrajectoryType),
				typeof(float),
				typeof(float));
			if (init == null)
			{
				if (required)
					throw new MissingMethodException("BhProjectileController", GameSymbols.Projectile.ControllerInit.Id);
				log?.LogWarning("Homm3 projectile config hook: BhProjectileController.Init not found.");
				return;
			}
			var heroAbilityProjectileGetter = FindHeroAbilityLevelProjectileGetter();
			if (heroAbilityProjectileGetter == null && required)
				throw new MissingMethodException("HeroAbilityLevelConfig", GameSymbols.Projectile.HeroAbilityLevelProjectileGetter.Id);
			var setPositions = FindProjectileControllerMethod(GameSymbols.Projectile.ControllerSetPositions, typeof(BhProjectileController), typeof(Vector3), typeof(Vector3), typeof(Vector3));
			if (setPositions == null && required)
				throw new MissingMethodException("BhProjectileController", GameSymbols.Projectile.ControllerSetPositions.Id);
			var updateProjectile = FindProjectileControllerMethod(GameSymbols.Projectile.ControllerUpdate, typeof(BhProjectileController), typeof(float));
			if (updateProjectile == null && required)
				throw new MissingMethodException("BhProjectileController", GameSymbols.Projectile.ControllerUpdate.Id);
			var launchHelpers = FindProjectileLaunchHelpers(log);

			harmony.Patch(projectileGetter, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixAbilityViewConfigProjectileGetter)));
			if (PatchHeroAbilityProjectileGetter && heroAbilityProjectileGetter != null)
				harmony.Patch(heroAbilityProjectileGetter, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixHeroAbilityLevelProjectileGetter)));
			harmony.Patch(init, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixProjectileInitWithPath)));
			if (setPositions != null)
				harmony.Patch(setPositions, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixProjectileInit)));
			if (updateProjectile != null)
				harmony.Patch(updateProjectile, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixProjectileUpdate)));
			foreach (var launchHelper in launchHelpers)
				harmony.Patch(launchHelper, postfix: new HarmonyMethod(typeof(Homm3ProjectileConfigHook), nameof(PostfixProjectileLaunchHelper)));
			_registered = true;
			log?.LogInfo(
				"Homm3 projectile config hook: patched "
				+ projectileGetter.DeclaringType?.FullName
				+ "."
				+ projectileGetter.Name
				+ (heroAbilityProjectileGetter != null ? ", verified HeroAbilityLevelConfig." + heroAbilityProjectileGetter.Name + " without runtime postfix" : "")
				+ ", BhProjectileController.Init"
				+ (setPositions != null ? ", BhProjectileController." + setPositions.Name : "")
				+ (updateProjectile != null ? ", BhProjectileController." + updateProjectile.Name : "")
				+ ", launchHelpers="
				+ launchHelpers.Count
				+ ".");
		}
		catch (Exception ex)
		{
			if (required)
				throw new InvalidOperationException("required projectile config hook registration failed.", ex);
			log?.LogWarning("Homm3 projectile config hook: registration failed: " + ex);
		}
	}

	static MethodInfo FindAbilityViewProjectileGetter()
	{
		foreach (var name in GameSymbols.Projectile.AbilityViewProjectileGetter.NameHints)
		{
			var method = FindExactMethod(typeof(AbilityViewConfig), name, typeof(ProjectileConfig), Type.EmptyTypes);
			if (method != null && method.ReturnType == typeof(ProjectileConfig))
				return method;
		}

		foreach (var method in typeof(AbilityViewConfig).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(ProjectileConfig))
				continue;
			if (method.GetParameters().Length == 0)
				return method;
		}
		return null;
	}

	static MethodInfo FindHeroAbilityLevelProjectileGetter()
	{
		foreach (var name in GameSymbols.Projectile.HeroAbilityLevelProjectileGetter.NameHints)
		{
			var method = FindExactMethod(typeof(HeroAbilityLevelConfig), name, typeof(ProjectileConfig), Type.EmptyTypes);
			if (method != null && method.ReturnType == typeof(ProjectileConfig))
				return method;
		}

		foreach (var method in typeof(HeroAbilityLevelConfig).GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
		{
			if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(ProjectileConfig))
				continue;
			if (method.GetParameters().Length == 0)
				return method;
		}
		return null;
	}

	static MethodInfo FindProjectileControllerMethod(GameSymbols.MethodSymbol symbol, Type type, params Type[] parameterTypes)
	{
		if (symbol.NameHints == null)
			return null;
		for (var i = 0; i < symbol.NameHints.Length; i++)
		{
			var method = FindExactMethod(type, symbol.NameHints[i], typeof(void), parameterTypes);
			if (method != null)
				return method;
		}
		return null;
	}

	static MethodInfo FindExactMethod(Type type, string name, Type returnType, params Type[] parameterTypes)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var method in type.GetMethods(flags))
		{
			if (method == null || method.ContainsGenericParameters)
				continue;
			if (!string.Equals(method.Name, name, StringComparison.Ordinal))
				continue;
			if (returnType != null && method.ReturnType != returnType)
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != (parameterTypes?.Length ?? 0))
				continue;
			var match = true;
			for (var i = 0; i < parameters.Length; i++)
			{
				if (parameters[i].ParameterType != parameterTypes[i])
				{
					match = false;
					break;
				}
			}
			if (match)
				return method;
		}
		return null;
	}

	static void PostfixAbilityViewConfigProjectileGetter(ref ProjectileConfig __result)
	{
		PostfixProjectileConfigGetter(ref __result, "ability view");
	}

	static void PostfixHeroAbilityLevelProjectileGetter(ref ProjectileConfig __result)
	{
		PostfixProjectileConfigGetter(ref __result, "hero ability");
	}

	static void PostfixProjectileConfigGetter(ref ProjectileConfig __result, string source)
	{
		try
		{
			if (__result == null)
				return;
			var path = __result.path;
			if (!IsHomm3ProjectilePath(path))
				return;

			var donorPath = DonorPathForHomm3Projectile(path);
			__result = CreateProjectileConfigWithPath(__result, donorPath);
			if (IsCoveCannonProjectilePath(path))
			{
				Homm3CoveCannonShotAudio.TryPlayShot();
				PendingCoveCannon.Enqueue(new PendingProjectile
				{
					Homm3Path = path,
					ExpiresAtFrame = SafeFrameCount() + PendingTtlFrames
				});
				if (_loggedConfig < 12)
				{
					_loggedConfig++;
					Plugin.LogSource?.LogInfo("Homm3 projectile config hook: queued Cove Cannon audiovisuals from " + source + " using donor shell '" + donorPath + "'.");
				}
				return;
			}

			Pending.Enqueue(new PendingProjectile
			{
				Homm3Path = path,
				ExpiresAtFrame = SafeFrameCount() + PendingTtlFrames
			});
			if (_loggedConfig < 12)
			{
				_loggedConfig++;
				Plugin.LogSource?.LogInfo("Homm3 projectile config hook: queued visual '" + path + "' from " + source + " using donor shell '" + donorPath + "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: " + source + " projectile getter postfix failed: " + ex.Message);
		}
	}

	static ProjectileConfig CreateProjectileConfigWithPath(ProjectileConfig source, string path)
	{
		if (source == null)
			return null;
		return new ProjectileConfig(
			path,
			source.emitter,
			source.trajectory,
			source.flightSound,
			source.speed,
			source.maxHeight,
			source.angle,
			source.delay,
			source.startDelay);
	}

	static void PostfixProjectileInitWithPath(BhProjectileController __instance, string __3)
	{
		try
		{
			if (__instance != null
			    && string.Equals(__3, CoveCannonNativeProjectilePath, StringComparison.Ordinal)
			    && __instance.gameObject
			    && Homm3CoveCannonVisuals.TryPlayShootAnimationNear(__instance.gameObject.transform.position, Plugin.LogSource))
				Homm3CoveCannonShotAudio.TryPlayShot();
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: Cove Cannon native projectile animation trigger failed: " + ex.Message);
		}
		PostfixProjectileInit(__instance);
	}

	static void PostfixProjectileInit(BhProjectileController __instance)
	{
		try
		{
			if (__instance == null)
				return;
			if (TryAttachPendingCoveCannon(__instance.gameObject, "init"))
				return;
			var pending = PeekValidPending();
			if (_loggedControllerInit < 20)
			{
				_loggedControllerInit++;
				Plugin.LogSource?.LogInfo(
					"Homm3 projectile config hook: projectile controller init observed shell='"
					+ (__instance.gameObject ? __instance.gameObject.name : "?")
					+ "' pending='"
					+ (pending ?? "")
					+ "' remaining="
					+ Pending.Count
					+ " cove="
					+ PendingCoveCannon.Count
					+ ".");
			}
			if (string.IsNullOrEmpty(pending))
				return;
			var shell = __instance.gameObject;
			if (shell && Homm3ImportVisuals.TryAttachProjectileVisualToShell(shell, pending, true))
			{
				DequeueSpecificPending(pending);
				return;
			}
			if (_loggedAttachMiss < 12)
			{
				_loggedAttachMiss++;
				Plugin.LogSource?.LogWarning("Homm3 projectile config hook: failed attaching queued visual '" + pending + "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: Init postfix failed: " + ex.Message);
		}
	}

	static void PostfixProjectileUpdate(BhProjectileController __instance)
	{
		try
		{
			if (__instance == null)
				return;
			if (TryAttachPendingCoveCannon(__instance.gameObject, "update"))
				return;
			var pending = PeekValidPending();
			if (_loggedControllerUpdate < 20)
			{
				_loggedControllerUpdate++;
				Plugin.LogSource?.LogInfo(
					"Homm3 projectile config hook: projectile controller update observed shell='"
					+ (__instance.gameObject ? __instance.gameObject.name : "?")
					+ "' pending='"
					+ (pending ?? "")
					+ "' remaining="
					+ Pending.Count
					+ " cove="
					+ PendingCoveCannon.Count
					+ ".");
			}
			if (string.IsNullOrEmpty(pending))
				return;
			var shell = __instance.gameObject;
			if (shell && Homm3ImportVisuals.TryAttachProjectileVisualToShell(shell, pending, true))
			{
				DequeueSpecificPending(pending);
				return;
			}
			if (_loggedAttachMiss < 12)
			{
				_loggedAttachMiss++;
				Plugin.LogSource?.LogWarning("Homm3 projectile config hook: update failed attaching queued visual '" + pending + "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: update postfix failed: " + ex.Message);
		}
	}

	static List<MethodInfo> FindProjectileLaunchHelpers(ManualLogSource log)
	{
		var result = new List<MethodInfo>();
		var dzrType = typeof(BhProjectileController).BaseType;
		var types = SafeGetHexTypes();
		foreach (var type in types)
		{
			if (type == null)
				continue;
			MethodInfo[] methods;
			try
			{
				methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			}
			catch
			{
				continue;
			}
			foreach (var method in methods)
			{
				if (method == null || method.ContainsGenericParameters || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length != 4 || parameters[0].ParameterType != typeof(ProjectileConfig))
					continue;
				var lastType = parameters[3].ParameterType;
				if (dzrType != null && !dzrType.IsAssignableFrom(lastType))
					continue;
				result.Add(method);
				if (_loggedLaunchHelperScan < 12)
				{
					_loggedLaunchHelperScan++;
					log?.LogInfo("Homm3 projectile config hook: launch helper candidate " + type.FullName + "." + method.Name + "(" + FormatParameterTypes(parameters) + ").");
				}
			}
		}
		return result;
	}

	static Type[] SafeGetHexTypes()
	{
		try
		{
			return typeof(AbilityViewConfig).Assembly.GetTypes();
		}
		catch (ReflectionTypeLoadException ex)
		{
			return ex.Types ?? Array.Empty<Type>();
		}
		catch
		{
			return Array.Empty<Type>();
		}
	}

	static string FormatParameterTypes(ParameterInfo[] parameters)
	{
		if (parameters == null || parameters.Length == 0)
			return "";
		var parts = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
			parts[i] = parameters[i].ParameterType.FullName ?? parameters[i].ParameterType.Name;
		return string.Join(", ", parts);
	}

	static void PostfixProjectileLaunchHelper(object __instance, object[] __args)
	{
		try
		{
			var pending = PeekValidPending();
			if (_loggedLaunchHelper < 30)
			{
				_loggedLaunchHelper++;
				Plugin.LogSource?.LogInfo(
					"Homm3 projectile config hook: launch helper observed type='"
					+ (__instance != null ? __instance.GetType().FullName : "?")
					+ "' args='"
					+ FormatArgTypes(__args)
					+ "' pending='"
					+ (pending ?? "")
					+ "' remaining="
					+ Pending.Count
					+ " cove="
					+ PendingCoveCannon.Count
					+ ".");
			}
			if (string.IsNullOrEmpty(pending))
				return;
			if (TryAttachPendingToLaunchObjects(__instance, __args, pending))
			{
				DequeueSpecificPending(pending);
				return;
			}
			if (_loggedAttachMiss < 12)
			{
				_loggedAttachMiss++;
				Plugin.LogSource?.LogWarning("Homm3 projectile config hook: launch helper found no attachable projectile for '" + pending + "'.");
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: launch helper postfix failed: " + ex.Message);
		}
	}

	static string FormatArgTypes(object[] args)
	{
		if (args == null || args.Length == 0)
			return "";
		var parts = new string[args.Length];
		for (var i = 0; i < args.Length; i++)
			parts[i] = args[i] != null ? args[i].GetType().FullName : "null";
		return string.Join(", ", parts);
	}

	static bool TryAttachPendingToLaunchObjects(object instance, object[] args, string homm3Path)
	{
		if (TryAttachPendingToObject(instance, homm3Path, 0))
			return true;
		if (args != null)
		{
			foreach (var arg in args)
			{
				if (TryAttachPendingToObject(arg, homm3Path, 0))
					return true;
			}
		}
		return false;
	}

	static bool TryAttachPendingCoveCannon(GameObject shell, string source)
	{
		var pending = PeekValidPending(PendingCoveCannon);
		if (string.IsNullOrEmpty(pending))
			return false;
		if (shell && Homm3CoveCannonVisuals.TryPresentShot(shell, Plugin.LogSource))
		{
			DequeueSpecificPending(PendingCoveCannon, pending);
			return true;
		}
		if (_loggedAttachMiss < 12)
		{
			_loggedAttachMiss++;
			Plugin.LogSource?.LogWarning("Homm3 projectile config hook: " + source + " failed attaching Cove Cannon visuals to shell '" + (shell ? shell.name : "?") + "'.");
		}
		return false;
	}

	static bool TryAttachPendingToObject(object item, string homm3Path, int depth)
	{
		if (item == null || string.IsNullOrEmpty(homm3Path) || depth > 2)
			return false;
		if (item is Component component && component && component.gameObject)
			return Homm3ImportVisuals.TryAttachProjectileVisualToShell(component.gameObject, homm3Path, true);
		if (item is System.Collections.IEnumerable enumerable && item is not string)
		{
			foreach (var child in enumerable)
			{
				if (TryAttachPendingToObject(child, homm3Path, depth + 1))
					return true;
			}
			return false;
		}
		var type = item.GetType();
		FieldInfo[] fields;
		try
		{
			fields = type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		}
		catch
		{
			return false;
		}
		foreach (var field in fields)
		{
			object value;
			try
			{
				value = field.GetValue(item);
			}
			catch
			{
				continue;
			}
			if (TryAttachPendingToObject(value, homm3Path, depth + 1))
				return true;
		}
		return false;
	}

	static string PeekValidPending()
	{
		return PeekValidPending(Pending);
	}

	static string PeekValidPending(Queue<PendingProjectile> queue)
	{
		var frame = SafeFrameCount();
		while (queue.Count > 0 && queue.Peek().ExpiresAtFrame < frame)
			queue.Dequeue();
		return queue.Count > 0 ? queue.Peek().Homm3Path : null;
	}

	static void DequeueSpecificPending(string homm3Path)
	{
		DequeueSpecificPending(Pending, homm3Path);
	}

	static void DequeueSpecificPending(Queue<PendingProjectile> queue, string homm3Path)
	{
		if (string.IsNullOrEmpty(homm3Path) || queue.Count == 0)
			return;
		var keep = new Queue<PendingProjectile>();
		var removed = false;
		while (queue.Count > 0)
		{
			var p = queue.Dequeue();
			if (!removed && string.Equals(p.Homm3Path, homm3Path, StringComparison.Ordinal))
			{
				removed = true;
				continue;
			}
			keep.Enqueue(p);
		}
		while (keep.Count > 0)
			queue.Enqueue(keep.Dequeue());
	}

	static bool IsHomm3ProjectilePath(string path) =>
		!string.IsNullOrWhiteSpace(path)
		&& path.StartsWith("effects/projectiles/homm3_", StringComparison.Ordinal);

	static bool IsCoveCannonProjectilePath(string path) =>
		string.Equals(path, CoveCannonProjectilePath, StringComparison.Ordinal);

	static string DonorPathForHomm3Projectile(string path) =>
		IsCoveCannonProjectilePath(path) ? CoveCannonDonorProjectilePath : DefaultDonorProjectilePath;

	static int SafeFrameCount()
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
}
