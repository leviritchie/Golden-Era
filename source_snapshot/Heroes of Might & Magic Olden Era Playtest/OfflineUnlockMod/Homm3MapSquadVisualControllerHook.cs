using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Hooks the adventure-map squad visual controller (Golden Era: type ezn).
/// HoMM3 map sprites returned from UnitViewConfig.rtd() are model roots, not MapObject roots.
/// </summary>
internal static class Homm3MapSquadVisualControllerHook
{
	private const string ShellRootName = "map_native_shell";
	private const string VisualRootName = "homm3_map_visual";

	private static bool _registered;
	private static int _initDiagRemaining = 24;
	private static int _visibilityDiagRemaining = 48;

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
		if (_registered)
			return;
		if (harmony == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required Homm3Import map squad visual controller registration.");
			return;
		}

		try
		{
			var controllerType = ResolveMapSquadVisualControllerType();
			var initMethods = ResolveInitMethods(controllerType);
			var visibilityMethods = ResolveVisibilityMethods(controllerType);

			var patched = 0;
			var initPatched = 0;
			var visibilityPatched = 0;

			foreach (var m in initMethods)
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3MapSquadVisualControllerHook), nameof(PostfixInitLike)));
				patched++;
				initPatched++;
			}

			foreach (var m in visibilityMethods)
			{
				harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3MapSquadVisualControllerHook), nameof(PostfixVisibilityBool)));
				patched++;
				visibilityPatched++;
			}

			if (required)
			{
				var missing = new List<string>();
				if (controllerType == null)
					missing.Add("map squad visual controller type " + string.Join("/", GameSymbols.MapSquadVisual.ControllerTypeHints));
				if (initPatched == 0)
					missing.Add("map squad visual init surface");
				if (visibilityPatched == 0)
					missing.Add("map squad visual bool visibility surface");
				if (missing.Count > 0)
					throw new InvalidOperationException(
						"required Homm3Import map squad visual controller surface(s) missing: "
						+ string.Join(", ", missing)
						+ "; "
						+ DescribeRegistrationFailure(controllerType, initMethods, visibilityMethods));
			}

			_registered = patched > 0;
			log?.LogInfo(
				"Homm3Import map squad visual controller hook: patched "
				+ patched
				+ (required ? " required" : "")
				+ " on "
				+ (controllerType?.FullName ?? "(missing)")
				+ "; init="
				+ initPatched
				+ ", visibility="
				+ visibilityPatched
				+ ".");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3Import map squad visual controller hook: registration failed: " + ex);
		}
	}

	private static Type ResolveMapSquadVisualControllerType()
	{
		return ResolveTypeFromHints("mapSquadVisual.controller", GameSymbols.MapSquadVisual.ControllerTypeHints, IsMapSquadVisualControllerType);
	}

	private static Type ResolveWorldSquadType()
	{
		return ResolveTypeFromHints("mapSquadVisual.worldSquad", GameSymbols.MapSquadVisual.WorldSquadTypeHints, null);
	}

	private static Type ResolveInitContextType()
	{
		return ResolveTypeFromHints("mapSquadVisual.initContext", GameSymbols.MapSquadVisual.InitContextTypeHints, null);
	}

	private static Type ResolveTypeFromHints(string id, string[] hints, Func<Type, bool> accept)
	{
		if (hints == null)
			return null;
		for (var i = 0; i < hints.Length; i++)
		{
			var hint = hints[i];
			if (string.IsNullOrEmpty(hint))
				continue;
			var type = GameMember.FindType(id + "." + hint, hint, () => ModActions.GetHexType(hint));
			if (type != null && (accept == null || accept(type)))
				return type;
		}
		return null;
	}

	private static bool IsMapSquadVisualControllerType(Type type)
	{
		if (type == null)
			return false;
		var worldType = ResolveWorldSquadType();
		var initContextType = ResolveInitContextType();
		if (worldType == null || initContextType == null)
			return false;
		if (ResolveDeclaredMethods(type, GameSymbols.MapSquadVisual.InitBind, new[] { worldType, initContextType }).Length == 0)
			return false;
		if (!HasGameObjectRootSurface(type))
			return false;
		return HasUnitViewConfigField(type);
	}

	private static bool HasGameObjectRootSurface(Type type)
	{
		foreach (var fieldName in GameSymbols.MapSquadVisual.RootFields)
		{
			var field = type.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field != null && typeof(GameObject).IsAssignableFrom(field.FieldType))
				return true;
			var prop = type.GetProperty(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop != null && prop.GetIndexParameters().Length == 0 && typeof(GameObject).IsAssignableFrom(prop.PropertyType))
				return true;
		}
		foreach (var getter in GameSymbols.MapSquadVisual.RootGetter.NameHints)
		{
			var method = AccessTools.DeclaredMethod(type, getter, Type.EmptyTypes);
			if (method != null && typeof(GameObject).IsAssignableFrom(method.ReturnType))
				return true;
		}
		return false;
	}

	private static bool HasUnitViewConfigField(Type type)
	{
		foreach (var fieldName in GameSymbols.MapSquadVisual.ViewConfigFields)
		{
			var field = type.GetField(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (field?.FieldType?.FullName == "Hex.Configs.UnitViewConfig")
				return true;
			var prop = type.GetProperty(fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop?.PropertyType?.FullName == "Hex.Configs.UnitViewConfig" && prop.GetIndexParameters().Length == 0)
				return true;
		}
		return false;
	}

	private static MethodInfo[] ResolveInitMethods(Type controllerType)
	{
		if (controllerType == null)
			return Array.Empty<MethodInfo>();

		var worldType = ResolveWorldSquadType();
		var initContextType = ResolveInitContextType();
		if (worldType == null || initContextType == null)
			return Array.Empty<MethodInfo>();

		var initParameterTypes = new[] { worldType, initContextType };
		return ResolveDeclaredMethods(
			controllerType,
			GameSymbols.MapSquadVisual.InitBind,
			initParameterTypes);
	}

	private static MethodInfo[] ResolveVisibilityMethods(Type controllerType)
	{
		if (controllerType == null)
			return Array.Empty<MethodInfo>();

		return ResolveDeclaredMethods(
			controllerType,
			GameSymbols.MapSquadVisual.VisibilityBind,
			new[] { typeof(bool) });
	}

	private static MethodInfo[] ResolveDeclaredMethods(
		Type controllerType,
		GameSymbols.MethodSymbol symbol,
		Type[] parameterTypes)
	{
		var resolved = new List<MethodInfo>();
		var seen = new HashSet<string>(StringComparer.Ordinal);
		var hints = symbol.NameHints;
		if (hints == null || hints.Length == 0)
			return Array.Empty<MethodInfo>();

		for (var i = 0; i < hints.Length; i++)
		{
			var name = hints[i];
			if (string.IsNullOrEmpty(name))
				continue;

			var method = AccessTools.DeclaredMethod(controllerType, name, parameterTypes);
			if (method == null)
				continue;

			var key = method.Name + "|" + method.MetadataToken;
			if (!seen.Add(key))
				continue;

			resolved.Add(method);
		}

		return resolved.ToArray();
	}

	private static string DescribeRegistrationFailure(
		Type controllerType,
		MethodInfo[] initMethods,
		MethodInfo[] visibilityMethods)
	{
		var worldType = ResolveWorldSquadType();
		var initContextType = ResolveInitContextType();
		return "controllerType="
		       + (controllerType?.FullName ?? "(null)")
		       + " worldSquadType="
		       + (worldType?.FullName ?? "(null)")
		       + " initContextType="
		       + (initContextType?.FullName ?? "(null)")
		       + " resolvedInit=["
		       + string.Join(",", initMethods.Select(m => m.Name))
		       + "] resolvedVisibility=["
		       + string.Join(",", visibilityMethods.Select(m => m.Name))
		       + "]";
	}

	private static void PostfixInitLike(object __instance, MethodBase __originalMethod)
	{
		try
		{
			var root = TryGetRoot(__instance);
			Homm3MapLoadFlightRecorder.MarkGameObject(
				"map-squad.init.postfix.root",
				root,
				"method=" + (__originalMethod?.Name ?? "?") + " controller=" + (__instance?.GetType().FullName ?? "?"),
				census: true);
			if (!IsHomm3Root(root))
				return;

			ApplyControllerVisibility(__instance, root, "init:" + (__originalMethod?.Name ?? "?"), null);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import map squad visual init hook failed: " + ex.Message);
		}
	}

	private static void PostfixVisibilityBool(object __instance, bool a, MethodBase __originalMethod)
	{
		try
		{
			var root = TryGetRoot(__instance);
			Homm3MapLoadFlightRecorder.MarkGameObject(
				"map-squad.visibility.postfix.root",
				root,
				"method=" + (__originalMethod?.Name ?? "?") + " requested=" + a + " controller=" + (__instance?.GetType().FullName ?? "?"));
			if (!IsHomm3Root(root))
				return;

			ApplyControllerVisibility(__instance, root, "visibility:" + (__originalMethod?.Name ?? "?"), a);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3Import map squad visual visibility hook failed: " + ex.Message);
		}
	}

	private static GameObject TryGetRoot(object controller)
	{
		if (controller == null)
			return null;
		foreach (var field in GameSymbols.MapSquadVisual.RootFields)
		{
			var root = TryReadMember(controller, field) as GameObject;
			if (root)
				return root;
		}
		foreach (var getter in GameSymbols.MapSquadVisual.RootGetter.NameHints)
		{
			var root = TryInvokeGameObjectGetter(controller, getter);
			if (root)
				return root;
		}
		return null;
	}

	private static void ApplyControllerVisibility(object controller, GameObject root, string source, bool? requested)
	{
		var visual = FindDescendant(root.transform, VisualRootName);
		if (!visual)
			return;

		// Owned-skinned Init runs while the squad is not yet in the hierarchy. Forcing
		// owned draw true here (and on the template guard) made meshes ignore fog of war.
		// Native donor renderers stay FoW probes; Homm3OwnedSkinnedMapFogProbe copies that.
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(visual.gameObject))
		{
			Homm3ImportVisuals.RestoreOwnedSkinnedMapFogProbe(root);
			if (!requested.HasValue)
			{
				Homm3MapLoadFlightRecorder.MarkGameObject(
					"map-squad.apply-visibility",
					root,
					"source=" + source
					+ " fogProbeOwnsDraw=owned-skinned"
					+ " requested=(none)",
					census: true);
				return;
			}

			var ownedDesired = root.activeInHierarchy && requested.Value;
			var ownedApplied = ApplyVisibilityToDrawTargets(root.transform, visual, ownedDesired, out var ownedDrawTargets, out var ownedDrawState);
			Homm3MapLoadFlightRecorder.MarkGameObject(
				"map-squad.apply-visibility",
				root,
				"source=" + source
				+ " fogProbeOwnsDraw=owned-skinned"
				+ " requested=" + requested.Value
				+ " desired=" + ownedDesired
				+ " applied=" + ownedApplied
				+ " drawTargets=" + ownedDrawTargets
				+ " drawState=" + ownedDrawState,
				census: true);
			if (_visibilityDiagRemaining > 0)
			{
				_visibilityDiagRemaining--;
				Plugin.LogSource?.LogInfo(
					"Homm3Import map squad visual: source="
					+ source
					+ " root='"
					+ (root.name ?? "?")
					+ "' fogProbeOwnsDraw=owned-skinned"
					+ " requested="
					+ requested.Value
					+ " desired="
					+ ownedDesired
					+ " appliedTargets="
					+ ownedApplied
					+ " drawTargets="
					+ ownedDrawTargets
					+ ".");
			}
			return;
		}

		var desired = root.activeInHierarchy;
		if (requested.HasValue)
			desired = desired && requested.Value;

		var applied = ApplyVisibilityToDrawTargets(root.transform, visual, desired, out var drawTargets, out var drawState);
		Homm3MapLoadFlightRecorder.MarkGameObject(
			"map-squad.apply-visibility",
			root,
			"source=" + source
			+ " requested=" + (requested.HasValue ? requested.Value.ToString() : "(none)")
			+ " desired=" + desired
			+ " applied=" + applied
			+ " drawTargets=" + drawTargets
			+ " drawState=" + drawState,
			census: !requested.HasValue);

		if ((requested.HasValue ? _visibilityDiagRemaining : _initDiagRemaining) > 0)
		{
			if (requested.HasValue)
				_visibilityDiagRemaining--;
			else
				_initDiagRemaining--;

			Plugin.LogSource?.LogInfo(
				"Homm3Import map squad visual: source="
				+ source
				+ " root='"
				+ (root.name ?? "?")
				+ "' requested="
				+ (requested.HasValue ? requested.Value.ToString() : "(none)")
				+ " activeSelf="
				+ root.activeSelf
				+ " activeInHierarchy="
				+ root.activeInHierarchy
				+ " controllerDriven=true"
				+ " appliedVisible="
				+ desired
				+ " appliedTargets="
				+ applied
				+ " drawTargets="
				+ drawTargets
				+ " drawState="
				+ drawState
				+ " viewConfig="
				+ DescribeViewConfig(controller)
				+ ".");
		}
	}

	private static int ApplyVisibilityToDrawTargets(
		Transform root,
		Transform visual,
		bool visible,
		out string drawTargets,
		out string drawState)
	{
		var targetDescriptions = new List<string>();
		var stateDescriptions = new List<string>();
		var applied = 0;

		var arrayBridges = CollectComponents<Homm3MapArraySliceHexLitBridge>(root);
		for (var i = 0; i < arrayBridges.Count; i++)
		{
			var bridge = arrayBridges[i];
			if (!bridge)
				continue;
			bridge.ApplyControllerVisibility(visible);
			targetDescriptions.Add("arrayBridge");
			stateDescriptions.Add("arrayBridge:" + DescribePrimaryDrawRenderer(root));
			applied++;
		}

		var transplants = CollectComponents<Homm3NativeShellRendererTransplantSync>(root);
		for (var i = 0; i < transplants.Count; i++)
		{
			var transplant = transplants[i];
			if (!transplant)
				continue;
			transplant.ApplyControllerVisibility(visible);
			targetDescriptions.Add("nativeTransplant");
			stateDescriptions.Add("nativeTransplant:" + DescribePrimaryDrawRenderer(root));
			applied++;
		}

		if (applied == 0)
		{
			var visualRenderers = CollectRenderers(visual);
			for (var i = 0; visualRenderers != null && i < visualRenderers.Length; i++)
			{
				var r = visualRenderers[i];
				if (!r)
					continue;
				r.enabled = visible;
				r.forceRenderingOff = !visible;
				var path = BuildPath(r.transform, root);
				targetDescriptions.Add("visual:" + path);
				stateDescriptions.Add("visual:" + path + ":" + DescribeRenderer(r));
				applied++;
			}
		}

		drawTargets = targetDescriptions.Count == 0 ? "(none)" : string.Join(",", targetDescriptions);
		drawState = stateDescriptions.Count == 0 ? "(none)" : string.Join(";", stateDescriptions);
		return applied;
	}

	static string DescribePrimaryDrawRenderer(Transform root)
	{
		if (!root)
			return "(null)";
		if (CollectComponents<Homm3NativeShellRendererTransplantSync>(root).Count > 0)
			return "transplantSync";
		if (CollectComponents<Homm3MapArraySliceHexLitBridge>(root).Count > 0)
			return "arraySliceBridge";
		return "(unknown)";
	}

	static string DescribeRenderer(Renderer r)
	{
		if (!r)
			return "enabled=? forceOff=?";
		var shader = r.sharedMaterial && r.sharedMaterial.shader ? r.sharedMaterial.shader.name : "?";
		return "enabled=" + r.enabled + " forceOff=" + r.forceRenderingOff + " shader=" + shader;
	}

	private static List<T> CollectComponents<T>(Transform root) where T : Component
	{
		var result = new List<T>();
		CollectComponents(root, result);
		return result;
	}

	private static void CollectComponents<T>(Transform root, List<T> result) where T : Component
	{
		if (!root)
			return;
		var component = root.GetComponent(Il2CppType.Of<T>())?.TryCast<T>();
		if (component)
			result.Add(component);
		for (var i = 0; i < root.childCount; i++)
			CollectComponents(root.GetChild(i), result);
	}

	internal static void EnsureRuntimeAttachTypeRegistered(ManualLogSource log)
	{
		// Runtime attach/LateUpdate mirrors are intentionally retired for HoMM3 map fog.
	}

	internal static void EnsureRuntimeAttachTypeRegistered(ManualLogSource log, bool required)
	{
		EnsureRuntimeAttachTypeRegistered(log);
	}

	internal static bool IsRuntimeAttachTypeRegistered => false;

	private static bool IsHomm3Root(GameObject root)
	{
		if (!root)
			return false;
		return FindDescendant(root.transform, VisualRootName) != null;
	}

	private static Transform FindDescendant(Transform root, string name)
	{
		if (!root)
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		for (var i = 0; i < root.childCount; i++)
		{
			var child = FindDescendant(root.GetChild(i), name);
			if (child)
				return child;
		}
		return null;
	}

	private static string BuildPath(Transform t, Transform stopAt)
	{
		if (!t)
			return "?";
		var parts = new List<string>();
		var current = t;
		while (current && current != stopAt)
		{
			parts.Add(current.name ?? "?");
			current = current.parent;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static Renderer[] CollectRenderers(Transform root)
	{
		var result = new List<Renderer>();
		CollectRenderers(root, result);
		return result.ToArray();
	}

	private static void CollectRenderers(Transform root, List<Renderer> result)
	{
		if (!root)
			return;
		var renderer = root.GetComponent(Il2CppType.Of<Renderer>())?.TryCast<Renderer>();
		if (renderer)
			result.Add(renderer);
		for (var i = 0; i < root.childCount; i++)
			CollectRenderers(root.GetChild(i), result);
	}

	private static string DescribeViewConfig(object controller)
	{
		if (controller == null)
			return "(null)";
		foreach (var field in GameSymbols.MapSquadVisual.ViewConfigFields)
		{
			var vc = TryReadMember(controller, field);
			if (vc == null)
				continue;
			var id = DeobfInteropCompat.GetConfigElementId(vc) ?? TryReadMember(vc, "id") as string;
			var mapMesh = TryReadMember(vc, "mapMesh") as string;
			return "id=" + (id ?? "?") + " mapMesh=" + (mapMesh ?? "?");
		}
		return "(missing)";
	}

	private static object TryReadMember(object target, string memberName)
	{
		if (target == null || string.IsNullOrEmpty(memberName))
			return null;
		var type = target.GetType();
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var field = type.GetField(memberName, flags);
		if (field != null)
		{
			try { return field.GetValue(target); }
			catch { }
		}
		var prop = type.GetProperty(memberName, flags);
		if (prop != null && prop.CanRead && prop.GetIndexParameters().Length == 0)
		{
			try { return prop.GetValue(target); }
			catch { }
		}
		return null;
	}

	private static object GetFieldValue(object target, string fieldName)
	{
		if (target == null || string.IsNullOrEmpty(fieldName))
			return null;
		try
		{
			var field = target.GetType().GetField(
				fieldName,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			return field?.GetValue(target);
		}
		catch
		{
			return null;
		}
	}

	private static GameObject TryInvokeGameObjectGetter(object target, string methodName)
	{
		if (target == null || string.IsNullOrEmpty(methodName))
			return null;
		try
		{
			var method = target.GetType().GetMethod(
				methodName,
				BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
				null,
				Type.EmptyTypes,
				null);
			return method?.Invoke(target, null) as GameObject;
		}
		catch
		{
			return null;
		}
	}

	internal static T GetComponentSafe<T>(GameObject obj) where T : Component
	{
		if (!obj)
			return null;
		return obj.GetComponent(Il2CppType.Of<T>())?.TryCast<T>();
	}

	internal static T AddComponentSafe<T>(GameObject obj) where T : Component
	{
		if (!obj)
			return null;
		return obj.AddComponent(Il2CppType.Of<T>())?.TryCast<T>();
	}
}
