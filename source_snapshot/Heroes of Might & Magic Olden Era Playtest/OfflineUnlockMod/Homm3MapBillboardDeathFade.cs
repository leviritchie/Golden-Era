using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3MapBillboardDeathFade : MonoBehaviour
{
	private const float FadeSeconds = 0.45f;

	private Renderer _renderer;
	private MaterialPropertyBlock _block;
	private Vector3 _startScale;
	private float _elapsed;
	private bool _started;

	private void Awake()
	{
		_renderer = ResolveRenderer();
		_startScale = transform.localScale;
	}

	public void StartFade()
	{
		if (_started)
			return;
		if (!_renderer)
			_renderer = ResolveRenderer();
		_started = true;
		_elapsed = 0f;
		if (_block == null)
			_block = new MaterialPropertyBlock();
	}

	private void LateUpdate()
	{
		if (!_started)
			return;
		if (!_renderer)
			_renderer = ResolveRenderer();
		_elapsed += Time.deltaTime;
		var t = Mathf.Clamp01(_elapsed / FadeSeconds);
		var alpha = 1f - t;
		ApplyAlpha(alpha);
		transform.localScale = _startScale * Mathf.Lerp(1f, 0.96f, t);
		if (t >= 1f && _renderer)
			_renderer.forceRenderingOff = true;
	}

	private void ApplyAlpha(float alpha)
	{
		if (!_renderer)
			return;
		if (_block == null)
			_block = new MaterialPropertyBlock();
		_renderer.GetPropertyBlock(_block);
		var material = _renderer.sharedMaterial;
		if (material && material.shader)
		{
			var count = material.shader.GetPropertyCount();
			for (var i = 0; i < count; i++)
			{
				if (material.shader.GetPropertyType(i) != UnityEngine.Rendering.ShaderPropertyType.Color)
					continue;
				var prop = material.shader.GetPropertyName(i);
				if (string.IsNullOrEmpty(prop) || !material.HasProperty(prop))
					continue;
				var color = material.GetColor(prop);
				color.a = alpha;
				_block.SetColor(prop, color);
			}
			SetFloatIfPresent(material, "_Alpha", alpha);
			SetFloatIfPresent(material, "_Opacity", alpha);
		}
		_renderer.SetPropertyBlock(_block);
	}

	private void SetFloatIfPresent(Material material, string prop, float value)
	{
		if (material && material.HasProperty(prop))
			_block.SetFloat(prop, value);
	}

	private Renderer ResolveRenderer()
	{
		return gameObject ? gameObject.GetComponent(Il2CppType.Of<Renderer>())?.TryCast<Renderer>() : null;
	}
}

internal static class Homm3MapBillboardDeathFadeHook
{
	private sealed class TrackedRoot
	{
		internal GameObject Root;
		internal int Id;
		internal string Sid;
	}

	private static readonly Dictionary<int, TrackedRoot> RootsById = new();
	private static readonly Dictionary<int, TrackedRoot> RootsByRootInstanceId = new();
	private static bool _registered;
	private static bool _componentRegistered;
	private static int _triggerDiagRemaining = 24;
	private static int _registerDiagRemaining = 24;
	private static int _patchDiagRemaining = 12;

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
				throw new InvalidOperationException("Harmony was not initialized before required HoMM3 map billboard death fade registration.");
			return;
		}

		try
		{
			EnsureComponentRegistered(log, required);
			var idRemovalType = FindFirstType(
				GameSymbols.MapBillboardDeathFade.IdRemovalTypeId,
				GameSymbols.MapBillboardDeathFade.IdRemovalTypeHints);
			var objectRemovalType = FindFirstType(
				GameSymbols.MapBillboardDeathFade.ObjectRemovalTypeId,
				GameSymbols.MapBillboardDeathFade.ObjectRemovalTypeHints);

			if (required)
			{
				var missing = new List<string>();
				if (!_componentRegistered)
					missing.Add(nameof(Homm3MapBillboardDeathFade) + " injected component");
				if (idRemovalType == null)
					missing.Add("id removal type " + string.Join("/", GameSymbols.MapBillboardDeathFade.IdRemovalTypeHints));
				if (objectRemovalType == null)
					missing.Add("object removal type " + string.Join("/", GameSymbols.MapBillboardDeathFade.ObjectRemovalTypeHints));
				if (missing.Count > 0)
					throw new InvalidOperationException("required HoMM3 map billboard death fade surface(s) missing: " + string.Join(", ", missing));
			}

			var idPatched = PatchMethodsByNames(
				harmony,
				idRemovalType,
				new[] { typeof(int) },
				GameSymbols.MapBillboardDeathFade.IdRemovalMethods,
				nameof(PrefixObjectId));
			var objectNoArgPatched = PatchMethodsByNames(
				harmony,
				objectRemovalType,
				Type.EmptyTypes,
				GameSymbols.MapBillboardDeathFade.ObjectNoArgRemovalMethods,
				nameof(PrefixObjectInstance));
			var objectIntPatched = PatchMethodsByNames(
				harmony,
				objectRemovalType,
				new[] { typeof(int) },
				GameSymbols.MapBillboardDeathFade.ObjectIntRemovalMethods,
				nameof(PrefixObjectInstance));
			var objectPatched = objectNoArgPatched + objectIntPatched;
			var patched = idPatched + objectPatched;

			if (required)
			{
				var missing = new List<string>();
				if (idPatched == 0)
					missing.Add("id removal methods");
				if (objectPatched == 0)
					missing.Add("object removal methods");
				if (missing.Count > 0)
					throw new InvalidOperationException("required HoMM3 map billboard death fade method surface(s) missing: " + string.Join(", ", missing));
			}

			_registered = patched > 0 || !required;
			log?.LogInfo("Homm3 map billboard death fade: patched " + patched + (required ? " required" : "") + " map removal/death candidate(s); id=" + idPatched + ", object=" + objectPatched + ".");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3 map billboard death fade: registration failed: " + ex.Message);
		}
	}

	internal static void EnsureComponentRegistered(ManualLogSource log)
	{
		EnsureComponentRegistered(log, required: false);
	}

	private static void EnsureComponentRegistered(ManualLogSource log, bool required)
	{
		if (_componentRegistered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3MapBillboardDeathFade>();
			_componentRegistered = true;
			log?.LogInfo("Homm3 map billboard death fade: registered Il2Cpp component.");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3 map billboard death fade: component registration failed: " + ex.Message);
		}
	}

	internal static void AttachToQuad(GameObject quadGo, ManualLogSource log)
	{
		if (!quadGo)
			return;
		EnsureComponentRegistered(log);
		if (!_componentRegistered)
			return;
		try
		{
			if (!GetComponentSafe<Homm3MapBillboardDeathFade>(quadGo))
				AddComponentSafe<Homm3MapBillboardDeathFade>(quadGo);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 map billboard death fade: attach failed: " + ex.Message);
		}
	}

	internal static void RegisterRoot(GameObject root, object meta, string sid)
	{
		if (!root || !HasFadeBillboard(root))
			return;
		var id = TryGetInt(meta, GameSymbols.MapBillboardDeathFade.ObjectIdFields);
		if (id <= 0)
			id = TryParseFirstPositiveInt(root.name);
		var tracked = new TrackedRoot { Root = root, Id = id, Sid = sid ?? string.Empty };
		RootsByRootInstanceId[root.GetInstanceID()] = tracked;
		if (id > 0)
			RootsById[id] = tracked;
		if (_registerDiagRemaining > 0)
		{
			_registerDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 map billboard death fade: registered root='"
				+ (root.name ?? "?")
				+ "' id="
				+ id
				+ " sid='"
				+ (tracked.Sid ?? "")
				+ "'.");
		}
	}

	private static int PatchMethodsByNames(Harmony harmony, Type type, Type[] parameters, GameSymbols.MethodSymbol symbol, string prefixName)
	{
		if (harmony == null || type == null)
			return 0;
		var prefix = typeof(Homm3MapBillboardDeathFadeHook).GetMethod(prefixName, BindingFlags.Static | BindingFlags.NonPublic);
		var patched = 0;
		foreach (var method in GameMember.FindMethodsByNames(type, parameters, symbol))
		{
			harmony.Patch(method, prefix: new HarmonyMethod(prefix));
			LogPatch(type, method);
			patched++;
		}
		return patched;
	}

	private static void PrefixObjectId([HarmonyArgument(0)] int id, MethodBase __originalMethod)
	{
		try
		{
			if (id <= 0)
				return;
			if (RootsById.TryGetValue(id, out var tracked))
				Trigger(tracked, __originalMethod?.Name ?? "?");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 map billboard death fade: id trigger failed: " + ex.Message);
		}
	}

	private static void PrefixObjectInstance(object __instance, MethodBase __originalMethod)
	{
		try
		{
			var data = GetFirstFieldValue(__instance, GameSymbols.MapBillboardDeathFade.ObjectDataFields)
			           ?? InvokeFirstNoArg(__instance, null, GameSymbols.MapBillboardDeathFade.ObjectDataGetter);
			var id = TryGetInt(data, GameSymbols.MapBillboardDeathFade.ObjectIdFields);
			if (id > 0 && RootsById.TryGetValue(id, out var tracked))
				Trigger(tracked, __originalMethod?.Name ?? "?");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 map billboard death fade: object trigger failed: " + ex.Message);
		}
	}

	private static void Trigger(TrackedRoot tracked, string path)
	{
		if (tracked == null || !tracked.Root)
			return;
		var quads = CollectDeathFades(tracked.Root.transform);
		if (quads.Length == 0)
			return;
		for (var i = 0; i < quads.Length; i++)
			if (quads[i])
				quads[i].StartFade();
		if (_triggerDiagRemaining > 0)
		{
			_triggerDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 map billboard death fade: triggered path='"
				+ (path ?? "?")
				+ "' root='"
				+ (tracked.Root.name ?? "?")
				+ "' id="
				+ tracked.Id
				+ " sid='"
				+ (tracked.Sid ?? "")
				+ "' quads="
				+ quads.Length
				+ ".");
		}
	}

	private static bool HasFadeBillboard(GameObject root)
	{
		return GetComponentInChildrenSafe<Homm3MapBillboardDeathFade>(root.transform)
		       || FindDescendant(root.transform, "homm3_map_visual") != null;
	}

	private static Transform FindDescendant(Transform root, string name)
	{
		if (!root)
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		for (var i = 0; i < root.childCount; i++)
		{
			var found = FindDescendant(root.GetChild(i), name);
			if (found)
				return found;
		}
		return null;
	}

	private static int TryGetInt(object obj, string[] names)
	{
		if (obj == null)
			return 0;
		foreach (var name in names)
		{
			var v = GetInheritedFieldValue(obj, name);
			if (v == null)
				continue;
			try
			{
				return Convert.ToInt32(v);
			}
			catch
			{
				// ignored
			}
		}
		return 0;
	}

	private static object GetFirstFieldValue(object obj, string[] names)
	{
		if (obj == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var value = GetInheritedFieldValue(obj, names[i]);
			if (value != null)
				return value;
		}
		return null;
	}

	private static object GetInheritedFieldValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, flags);
			if (f != null)
			{
				try { return f.GetValue(obj); } catch { }
			}
		}
		return null;
	}

	private static object InvokeFirstNoArg(object obj, Type returnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null)
			return null;
		var methods = GameMember.FindMethodsByNames(obj.GetType(), Type.EmptyTypes, symbol);
		for (var i = 0; i < methods.Length; i++)
		{
			if (returnType != null && methods[i].ReturnType != returnType)
				continue;
			try { return methods[i].Invoke(obj, null); } catch { }
		}
		return null;
	}

	private static T GetComponentSafe<T>(GameObject obj) where T : Component
	{
		return obj ? obj.GetComponent(Il2CppType.Of<T>())?.TryCast<T>() : null;
	}

	private static T AddComponentSafe<T>(GameObject obj) where T : Component
	{
		return obj ? obj.AddComponent(Il2CppType.Of<T>())?.TryCast<T>() : null;
	}

	private static T GetComponentInChildrenSafe<T>(Transform root) where T : Component
	{
		if (!root)
			return null;
		var component = root.GetComponent(Il2CppType.Of<T>())?.TryCast<T>();
		if (component)
			return component;
		for (var i = 0; i < root.childCount; i++)
		{
			component = GetComponentInChildrenSafe<T>(root.GetChild(i));
			if (component)
				return component;
		}
		return null;
	}

	private static Homm3MapBillboardDeathFade[] CollectDeathFades(Transform root)
	{
		var result = new List<Homm3MapBillboardDeathFade>();
		CollectDeathFades(root, result);
		return result.ToArray();
	}

	private static void CollectDeathFades(Transform root, List<Homm3MapBillboardDeathFade> result)
	{
		if (!root)
			return;
		var component = root.GetComponent(Il2CppType.Of<Homm3MapBillboardDeathFade>())?.TryCast<Homm3MapBillboardDeathFade>();
		if (component)
			result.Add(component);
		for (var i = 0; i < root.childCount; i++)
			CollectDeathFades(root.GetChild(i), result);
	}

	private static int TryParseFirstPositiveInt(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return 0;
		var value = 0;
		var reading = false;
		foreach (var c in text)
		{
			if (c >= '0' && c <= '9')
			{
				reading = true;
				value = value * 10 + (c - '0');
			}
			else if (reading)
				return value;
		}
		return value;
	}

	private static void LogPatch(Type type, MethodBase method)
	{
		if (_patchDiagRemaining <= 0)
			return;
		_patchDiagRemaining--;
		Plugin.LogSource?.LogInfo("Homm3 map billboard death fade: patched " + type.Name + "." + method.Name + ".");
	}

	private static Type FindFirstType(string id, string[] names)
	{
		if (names == null || names.Length == 0)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			var type = GameMember.FindType(id + "." + name, name, () => ModActions.GetHexType(name));
			if (type != null)
				return type;
		}
		return GameMember.FindType(id, names[0], () => ModActions.GetHexType(names[0]));
	}
}
