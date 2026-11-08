using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3MapObjectUnitVisualHook
{
	private static bool _registered;
	private static int _diagRemaining = 80;
	private static int _homm3ObjectDiagRemaining = 40;

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
				throw new InvalidOperationException("Harmony was not initialized before required Homm3Import map-object unit visual registration.");
			return;
		}

		try
		{
			Type metaType = null;
			foreach (var hint in GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints)
			{
				var candidate = GameMember.FindType(
					GameSymbols.CustomTownMapBillboard.ObjectMetaTypeId + "." + hint,
					hint,
					() => FindRuntimeType(hint));
				if (candidate != null)
				{
					metaType = candidate;
					break;
				}
			}
			var objectType = GameMember.FindPlacedObjectType(
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeId,
				GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints,
				FindRuntimeType);
			if (required)
			{
				var missing = new List<string>();
				if (metaType == null)
					missing.Add("placed-object metadata type " + string.Join("/", GameSymbols.CustomTownMapBillboard.ObjectMetaTypeHints));
				if (objectType == null)
					missing.Add("placed-object type " + string.Join("/", GameSymbols.CustomTownMapBillboard.PlacedObjectTypeHints));
				if (missing.Count > 0)
					throw new InvalidOperationException("required Homm3Import map-object unit visual type(s) missing: " + string.Join(", ", missing));
			}

			var patched = 0;
			foreach (var m in GameMember.FindPlacedObjectInitMethods(objectType, metaType))
			{
				harmony.Patch(
					m,
					postfix: new HarmonyMethod(typeof(Homm3MapObjectUnitVisualHook), nameof(PostfixMapObjectInit)));
				patched++;
			}

			if (required && patched == 0)
				throw new InvalidOperationException("required Homm3Import map-object unit visual placed-object init surface missing on " + (objectType?.FullName ?? "(null)") + ".");
			_registered = patched > 0 || !required;
			log?.LogInfo("Homm3Import map-object unit visual hook: patched " + patched + (required ? " required" : "") + " current map-object init candidate(s).");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogWarning("Homm3Import map-object unit visual hook: registration failed: " + ex);
		}
	}

	private static Type FindRuntimeType(string fullName)
	{
		return ModActions.GetHexType(fullName);
	}

	private static void PostfixMapObjectInit(object __instance, object[] __args)
	{
		try
		{
			if (__instance == null)
				return;

			Homm3MapIdleTextureAnimatorRegistry.ResetMapStateIfChanged(__args != null && __args.Length > 0 ? __args[0] : null);
			var meta = (__args != null && __args.Length > 1) ? __args[1] : null;
			meta ??= GetFirstFieldValue(__instance, GameSymbols.CustomTownMapBillboard.MetaFields);
			var root = GetReleaseMapObjectRoot(__instance);

			if (!root)
				return;

			var sid = TryGetPlacedObjectSid(__instance) ?? TryGetMetaSid(meta);
			if (Homm3HomecomingWaterTileOverlayVisual.TryApply(root, sid, Plugin.LogSource))
				return;
			var hasHomm3 = HasDescendant(root, "homm3_map_visual") || HasDescendant(root, "map_native_shell");
			var looksUnit = LooksLikeUnitMapObject(root, sid);
			if (!hasHomm3 && !looksUnit)
				return;
			if (hasHomm3)
				Homm3MapBillboardDeathFadeHook.RegisterRoot(root, meta, sid);

			if (hasHomm3 && _homm3ObjectDiagRemaining > 0)
			{
				_homm3ObjectDiagRemaining--;
				Plugin.LogSource?.LogInfo(
					"Homm3Import map-object unit visual: HoMM3 object root='"
					+ (root.name ?? "?")
					+ "' sid='"
					+ (sid ?? "")
					+ "' "
					+ DescribeRoot(root));
			}
			else if (_diagRemaining > 0)
			{
				_diagRemaining--;
				Plugin.LogSource?.LogInfo(
					"Homm3Import map-object unit visual: candidate root='"
					+ (root.name ?? "?")
					+ "' sid='"
					+ (sid ?? "")
					+ "' "
					+ DescribeRoot(root));
			}
		}
		catch (Exception ex)
		{
			if (Homm3HomecomingWaterTileOverlayVisual.IsRequiredFailure(ex))
				throw;
			Plugin.LogSource?.LogWarning("Homm3Import map-object unit visual postfix failed: " + ex.Message);
		}
	}

	private static bool LooksLikeUnitMapObject(GameObject root, string sid)
	{
		if (!root)
			return false;
		if (!string.IsNullOrEmpty(sid)
		    && (sid.IndexOf("unit", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("h3_", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("goblin", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("orc", StringComparison.OrdinalIgnoreCase) >= 0
		        || sid.IndexOf("cyclops", StringComparison.OrdinalIgnoreCase) >= 0))
			return true;
		var n = root.name ?? string.Empty;
		return n.IndexOf("unit", StringComparison.OrdinalIgnoreCase) >= 0
		       || n.IndexOf("map", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static string TryGetMetaSid(object meta)
	{
		if (meta == null)
			return null;
		var config = GetFirstFieldValue(meta, GameSymbols.CustomTownMapBillboard.MetaConfigFields);
		if (config == null)
			return null;
		return GetFirstFieldValue(config, GameSymbols.CustomTownMapBillboard.ConfigIdFields) as string
		       ?? GetInheritedFieldValue(config, "id") as string;
	}

	private static string TryGetPlacedObjectSid(object instance)
	{
		return GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.PlacedObjectSidFields) as string;
	}

	private static GameObject GetReleaseMapObjectRoot(object instance)
	{
		if (instance == null)
			return null;
		var root = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.RootGameObjectFields) as GameObject;
		if (root)
			return root;
		var transform = GetFirstFieldValue(instance, GameSymbols.CustomTownMapBillboard.RootTransformFields) as Transform;
		if (transform && transform.gameObject)
			return transform.gameObject;
		root = InvokeFirstNoArg(instance, typeof(GameObject), GameSymbols.CustomTownMapBillboard.RootGameObjectGetter) as GameObject;
		if (root)
			return root;
		transform = InvokeFirstNoArg(instance, typeof(Transform), GameSymbols.CustomTownMapBillboard.RootTransformGetter) as Transform;
		if (transform && transform.gameObject)
			return transform.gameObject;
		return instance is Component component ? component.gameObject : null;
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
		if (obj == null)
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			try
			{
				var f = t.GetField(name, flags);
				if (f != null)
					return f.GetValue(obj);
			}
			catch { }
		}
		return null;
	}

	private static object InvokeFirstNoArg(object obj, Type returnType, GameSymbols.MethodSymbol symbol)
	{
		if (obj == null)
			return null;
		var methods = GameMember.FindMethods(obj.GetType(), returnType, Type.EmptyTypes, symbol);
		for (var i = 0; i < methods.Length; i++)
		{
			try { return methods[i].Invoke(obj, null); } catch { }
		}
		return null;
	}

	private static bool HasDescendant(GameObject root, string name)
	{
		if (!root)
			return false;
		return FindDescendant(root.transform, name);
	}

	private static bool FindDescendant(Transform root, string name)
	{
		if (!root)
			return false;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return true;
		for (var i = 0; i < root.childCount; i++)
			if (FindDescendant(root.GetChild(i), name))
				return true;
		return false;
	}

	private static string DescribeRoot(GameObject root)
	{
		var renderers = CollectRenderers(root);
		var mesh = 0;
		var skinned = 0;
		for (var i = 0; i < renderers.Length; i++)
		{
			var typeName = renderers[i]?.GetType().Name ?? "";
			if (typeName.IndexOf("SkinnedMeshRenderer", StringComparison.OrdinalIgnoreCase) >= 0)
				skinned++;
			else if (typeName.IndexOf("MeshRenderer", StringComparison.OrdinalIgnoreCase) >= 0)
				mesh++;
		}
		var msg = "renderers=" + renderers.Length
		          + " mesh=" + mesh
		          + " skinned=" + skinned;
		for (var i = 0; i < renderers.Length && i < 4; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			var m = r.sharedMaterial;
			msg += " | r" + i
			       + " type=" + r.GetType().Name
			       + " path=" + BuildPath(r.transform, root.transform)
			       + " enabled=" + r.enabled
			       + " forceOff=" + r.forceRenderingOff
			       + " shadow=" + r.shadowCastingMode
			       + " mat=" + (m ? m.name : "(null)")
			       + " shader=" + (m && m.shader ? m.shader.name : "(null)");
		}
		return msg;
	}

	private static Renderer[] CollectRenderers(GameObject root)
	{
		var result = new List<Renderer>();
		if (root)
			CollectRenderers(root.transform, result);
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

	private static string BuildPath(Transform t, Transform root)
	{
		if (!t)
			return "(null)";
		var parts = new System.Collections.Generic.List<string>();
		for (var cur = t; cur != null && cur != root; cur = cur.parent)
			parts.Add(cur.name ?? "?");
		parts.Reverse();
		return parts.Count == 0 ? "." : string.Join("/", parts);
	}
}
