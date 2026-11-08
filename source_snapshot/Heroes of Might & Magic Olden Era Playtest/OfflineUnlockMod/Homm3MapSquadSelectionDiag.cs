using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3MapSquadSelectionDiag
{
	private const string FlagFileName = "homm3_map_squad_selection_diag.flag";
	private const string VisualRootName = "homm3_map_visual";
	private const int MaxPayloadHits = 24;
	private const int MaxPayloadFieldsPerObject = 48;

	private static bool _registered;
	private static int _diagRemaining = 260;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null || !Homm3DiagnosticFlags.IsEnabled(FlagFileName))
			return;

		try
		{
			var patched = 0;
			var controllerTypes = 0;
			foreach (var t in FindControllerTypes())
			{
				controllerTypes++;
				foreach (var m in FindInitLikeMethods(t))
				{
					harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3MapSquadSelectionDiag), nameof(PostfixInitLike)));
					patched++;
				}

				foreach (var m in FindVisibilityBoolMethods(t))
				{
					harmony.Patch(m, postfix: new HarmonyMethod(typeof(Homm3MapSquadSelectionDiag), nameof(PostfixVisibilityBool)));
					patched++;
				}
			}

			_registered = patched > 0;
			log?.LogInfo("HOMM3_MAP_SQUAD_DIAG registered patched=" + patched + " controllerTypes=" + controllerTypes + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HOMM3_MAP_SQUAD_DIAG registration failed: " + ex.Message);
		}
	}

	private static IEnumerable<Type> FindControllerTypes()
	{
		var seen = new HashSet<Type>();
		foreach (var hint in GameSymbols.MapSquadVisual.ControllerTypeHints)
		{
			var t = GameMember.FindType("mapSquadVisual.diag.controller." + hint, hint, () => ModActions.GetHexType(hint));
			if (t != null && seen.Add(t))
				yield return t;
		}
	}

	private static IEnumerable<MethodInfo> FindInitLikeMethods(Type t)
	{
		foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length != 2)
				continue;
			if (IsNamedTypeHint(ps[0].ParameterType, GameSymbols.MapSquadVisual.WorldSquadTypeHints)
			    && IsNamedTypeHint(ps[1].ParameterType, GameSymbols.MapSquadVisual.InitContextTypeHints))
				yield return m;
		}
	}

	private static IEnumerable<MethodInfo> FindVisibilityBoolMethods(Type t)
	{
		foreach (var m in t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
		{
			if (m.ReturnType != typeof(void))
				continue;
			var ps = m.GetParameters();
			if (ps.Length == 1 && ps[0].ParameterType == typeof(bool))
				yield return m;
		}
	}

	private static void PostfixInitLike(object __instance, object __0, object __1, MethodBase __originalMethod)
	{
		LogController(
			__instance,
			"init:" + (__originalMethod?.Name ?? "?"),
			null,
			DescribePayload(__0, "worldSquad") + " " + DescribePayload(__1, "session"));
	}

	private static void PostfixVisibilityBool(object __instance, bool a, MethodBase __originalMethod)
	{
		LogController(__instance, "visibility:" + (__originalMethod?.Name ?? "?"), a, "");
	}

	private static void LogController(object controller, string source, bool? requested, string payload)
	{
		if (controller == null || _diagRemaining <= 0)
			return;

		try
		{
			var root = TryGetRoot(controller);
			var vc = TryGetViewConfig(controller);
			var importRoute = DescribeImportRoute(vc, out var importUnits);
			var hasHomm3Visual = HasDescendant(root, VisualRootName);
			var shouldLog = requested == null
			                || hasHomm3Visual
			                || !string.Equals(importRoute, "none", StringComparison.Ordinal);
			if (!shouldLog)
				return;

			_diagRemaining--;
			Plugin.LogSource?.LogInfo(
				"HOMM3_MAP_SQUAD_DIAG source="
				+ source
				+ " controller="
				+ (controller.GetType().FullName ?? controller.GetType().Name)
				+ " requested="
				+ (requested.HasValue ? requested.Value.ToString() : "(none)")
				+ " view="
				+ DescribeViewConfig(vc)
				+ " importRoute="
				+ importRoute
				+ " importUnits='"
				+ (importUnits ?? "")
				+ "' root="
				+ DescribeRoot(root)
				+ " payload="
				+ (string.IsNullOrWhiteSpace(payload) ? "(none)" : payload)
				+ ".");
		}
		catch (Exception ex)
		{
			if (_diagRemaining > 0)
			{
				_diagRemaining--;
				Plugin.LogSource?.LogWarning("HOMM3_MAP_SQUAD_DIAG failed source=" + source + ": " + ex.Message);
			}
		}
	}

	private static string DescribePayload(object payload, string label)
	{
		if (payload == null)
			return label + "=(null)";

		var worldSquad = DescribeWorldSquad(payload);
		if (!string.IsNullOrEmpty(worldSquad))
			return label + "=" + BriefTypeName(payload) + "{" + worldSquad + "}";

		var hits = new List<string>();
		CollectPayloadFacts(payload, label, 0, hits);
		if (hits.Count == 0)
			return label + "=" + BriefTypeName(payload);
		return label + "=" + BriefTypeName(payload) + "{" + string.Join("; ", hits) + "}";
	}

	private static string DescribeWorldSquad(object candidate)
	{
		if (candidate == null)
			return "";

		var typeName = candidate.GetType().Name;
		if (!string.Equals(typeName, "fcy", StringComparison.Ordinal)
		    && candidate.GetType().FullName?.EndsWith(".fcy", StringComparison.Ordinal) != true)
			return "";

		var dataSquad = GetFieldValue(candidate, "<cjkk>k__BackingField")
		                ?? GetFieldValue(candidate, "cjkk")
		                ?? TryInvokeObjectGetter(candidate, "bjeq");
		if (dataSquad == null)
			return "dataSquad=(null)";

		var parts = new List<string>();
		AddStringPart(parts, "data.configSid", GetMemberValue(dataSquad, "configSid") as string);
		AddScalarPart(parts, "data.id", GetMemberValue(dataSquad, "id"));
		AddStringPart(parts, "data.customTopUnit", GetMemberValue(dataSquad, "customTopUnit") as string);

		var units = GetMemberValue(dataSquad, "units");
		var unitFacts = DescribeDataSquadUnits(units);
		if (!string.IsNullOrEmpty(unitFacts))
			parts.Add("data.units=[" + unitFacts + "]");

		return parts.Count == 0
			? "dataSquad=" + BriefTypeName(dataSquad) + " members=" + DescribeReadableMembers(dataSquad)
			: string.Join("; ", parts);
	}

	private static string DescribeDataSquadUnits(object units)
	{
		if (units == null)
			return "";

		var count = TryGetListCount(units);
		if (count < 0)
			return "unreadable:" + BriefTypeName(units);

		var facts = new List<string>();
		for (var i = 0; i < count && i < 8; i++)
		{
			var unit = TryGetListItem(units, i);
			if (unit == null)
				continue;
			var sid = GetMemberValue(unit, "sid") as string;
			var amount = GetMemberValue(unit, "amount");
			facts.Add("#" + i + ":sid='" + CleanLogValue(sid ?? "") + "' amount=" + FormatScalar(amount));
		}
		if (count > 8)
			facts.Add("+" + (count - 8) + " more");
		return string.Join(", ", facts);
	}

	private static object GetMemberValue(object obj, string name)
	{
		return GetFieldValue(obj, name)
		       ?? GetPropertyValue(obj, name)
		       ?? TryInvokeObjectGetter(obj, name);
	}

	private static object GetPropertyValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var p = t.GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (p == null || p.GetIndexParameters().Length != 0)
				continue;
			try
			{
				return p.GetValue(obj);
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static string DescribeReadableMembers(object obj)
	{
		if (obj == null)
			return "(null)";

		try
		{
			var names = new List<string>();
			var type = obj.GetType();
			foreach (var f in type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (names.Count >= 32)
					break;
				names.Add("f:" + f.Name + ":" + ShortTypeName(f.FieldType));
			}
			foreach (var p in type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (names.Count >= 32)
					break;
				names.Add("p:" + p.Name + ":" + ShortTypeName(p.PropertyType));
			}
			foreach (var m in type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (names.Count >= 32)
					break;
				if (m.GetParameters().Length == 0 && m.ReturnType != typeof(void))
					names.Add("m:" + m.Name + ":" + ShortTypeName(m.ReturnType));
			}
			return names.Count == 0 ? "(none)" : string.Join(",", names);
		}
		catch (Exception ex)
		{
			return "(failed:" + ex.GetType().Name + ")";
		}
	}

	private static string ShortTypeName(Type type)
	{
		if (type == null)
			return "?";
		return type.Name ?? type.FullName ?? "?";
	}

	private static void AddStringPart(List<string> parts, string name, string value)
	{
		if (!string.IsNullOrWhiteSpace(value))
			parts.Add(name + "='" + CleanLogValue(value) + "'");
	}

	private static void AddScalarPart(List<string> parts, string name, object value)
	{
		var text = FormatScalar(value);
		if (!string.IsNullOrEmpty(text))
			parts.Add(name + "=" + text);
	}

	private static string FormatScalar(object value)
	{
		if (value == null)
			return "";
		if (value is string text)
			return "'" + CleanLogValue(text) + "'";
		var type = value.GetType();
		if (type.IsPrimitive || type.IsEnum || type == typeof(decimal))
			return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
		return "";
	}

	private static int TryGetListCount(object list)
	{
		if (list == null)
			return -1;
		try
		{
			var prop = list.GetType().GetProperty("Count", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (prop != null)
				return Convert.ToInt32(prop.GetValue(list), System.Globalization.CultureInfo.InvariantCulture);
		}
		catch
		{
			return -1;
		}
		return -1;
	}

	private static object TryGetListItem(object list, int index)
	{
		if (list == null)
			return null;
		try
		{
			var method = list.GetType().GetMethod("get_Item", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(int) }, null);
			return method?.Invoke(list, new object[] { index });
		}
		catch
		{
			return null;
		}
	}

	private static void CollectPayloadFacts(object value, string path, int depth, List<string> hits)
	{
		if (value == null || hits.Count >= MaxPayloadHits)
			return;

		if (value is UnitViewConfig vc)
		{
			hits.Add(path + "." + DescribeViewConfig(vc));
			return;
		}

		if (value is string text)
		{
			if (IsInterestingString(path, text))
				hits.Add(path + "='" + CleanLogValue(text) + "'");
			return;
		}

		var type = value.GetType();
		if (depth >= 2 || !ShouldScanPayloadType(type))
			return;

		var inspected = 0;
		for (var t = type; t != null && t != typeof(object); t = t.BaseType)
		{
			foreach (var field in t.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (inspected++ >= MaxPayloadFieldsPerObject || hits.Count >= MaxPayloadHits)
					return;

				var fieldValue = GetFieldValue(value, field.Name);
				if (fieldValue == null)
					continue;

				var fieldPath = path + "." + field.Name;
				if (fieldValue is string fieldText)
				{
					if (IsInterestingString(field.Name, fieldText))
						hits.Add(fieldPath + "='" + CleanLogValue(fieldText) + "'");
				}
				else if (fieldValue is UnitViewConfig fieldViewConfig)
				{
					hits.Add(fieldPath + "." + DescribeViewConfig(fieldViewConfig));
				}
				else if (ShouldScanPayloadType(fieldValue.GetType()))
				{
					CollectPayloadFacts(fieldValue, fieldPath, depth + 1, hits);
				}
			}
		}
	}

	private static bool ShouldScanPayloadType(Type type)
	{
		if (type == null || type.IsPrimitive || type.IsEnum)
			return false;
		if (type == typeof(decimal) || type == typeof(string))
			return false;

		var ns = type.Namespace ?? "";
		if (ns.StartsWith("System", StringComparison.Ordinal)
		    || ns.StartsWith("UnityEngine", StringComparison.Ordinal)
		    || ns.StartsWith("HarmonyLib", StringComparison.Ordinal)
		    || ns.StartsWith("BepInEx", StringComparison.Ordinal))
			return false;

		return true;
	}

	private static bool IsInterestingString(string name, string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return false;

		var n = name ?? "";
		if (n.IndexOf("sid", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("id", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("config", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("unit", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("mesh", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("fraction", StringComparison.OrdinalIgnoreCase) >= 0
		    || n.IndexOf("type", StringComparison.OrdinalIgnoreCase) >= 0)
			return true;

		return value.IndexOf("h3_", StringComparison.OrdinalIgnoreCase) >= 0
		       || value.IndexOf("homm3_", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static string BriefTypeName(object value)
	{
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string CleanLogValue(string value)
	{
		if (value == null)
			return "";
		value = value.Replace("'", "\\'").Replace("\r", " ").Replace("\n", " ").Trim();
		return value.Length <= 180 ? value : value.Substring(0, 180) + "...";
	}

	private static UnitViewConfig TryGetViewConfig(object controller)
	{
		foreach (var field in GameSymbols.MapSquadVisual.ViewConfigFields)
		{
			var vc = GetFieldValue(controller, field) as UnitViewConfig;
			if (vc != null)
				return vc;
		}
		return null;
	}

	private static GameObject TryGetRoot(object controller)
	{
		foreach (var field in GameSymbols.MapSquadVisual.RootFields)
		{
			var root = GetFieldValue(controller, field) as GameObject;
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

	private static string DescribeViewConfig(UnitViewConfig vc)
	{
		if (vc == null)
			return "(null)";
		var id = DeobfInteropCompat.GetConfigElementId(vc) ?? "";
		return "id='"
		       + id
		       + "' mapMesh='"
		       + (vc.mapMesh ?? "")
		       + "' mesh='"
		       + (vc.mesh ?? "")
		       + "' scale="
		       + vc.scale.ToString("0.###");
	}

	private static string DescribeImportRoute(UnitViewConfig vc, out string importUnits)
	{
		importUnits = null;
		if (vc == null)
			return "none";

		var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(vc.mapMesh ?? "");
		if (Homm3ImportVisuals.TryResolveHomm3MapEntry(unitsPath, out var mapEntry) && mapEntry != null)
		{
			importUnits = FormatGameUnitSids(mapEntry);
			return "map-path";
		}

		var id = DeobfInteropCompat.GetConfigElementId(vc);
		if (!string.IsNullOrWhiteSpace(id)
		    && Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(id, Plugin.LogSource, out var sidEntry)
		    && sidEntry != null)
		{
			importUnits = FormatGameUnitSids(sidEntry);
			return "unit-sid";
		}

		return "none";
	}

	private static string FormatGameUnitSids(Homm3ImportVisuals.Entry entry)
	{
		if (entry?.GameUnitSids == null || entry.GameUnitSids.Count == 0)
			return "";
		return string.Join(",", entry.GameUnitSids);
	}

	private static string DescribeRoot(GameObject root)
	{
		if (!root)
			return "(null)";

		var renderers = new List<Renderer>();
		CollectRenderers(root.transform, renderers);
		var enabled = 0;
		var forceOff = 0;
		for (var i = 0; i < renderers.Count; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			if (r.enabled)
				enabled++;
			if (r.forceRenderingOff)
				forceOff++;
		}

		var text = "name='"
		           + (root.name ?? "")
		           + "' activeSelf="
		           + root.activeSelf
		           + " activeInHierarchy="
		           + root.activeInHierarchy
		           + " hasHomm3="
		           + HasDescendant(root, VisualRootName)
		           + " renderers="
		           + renderers.Count
		           + " enabled="
		           + enabled
		           + " forceOff="
		           + forceOff;
		var visual = DescribeHomm3Visual(root);
		if (!string.IsNullOrEmpty(visual))
			text += " visual=" + visual;
		for (var i = 0; i < renderers.Count && i < 3; i++)
		{
			var r = renderers[i];
			if (!r)
				continue;
			var m = r.sharedMaterial;
			var tex = m ? (m.HasProperty("_MainTex") ? m.GetTexture("_MainTex") : m.mainTexture) : null;
			text += " | r"
			        + i
			        + " path="
			        + BuildPath(r.transform, root.transform)
			        + " type="
			        + r.GetType().Name
			        + " enabled="
			        + r.enabled
			        + " forceOff="
			        + r.forceRenderingOff
			        + " mat='"
			        + (m ? m.name : "(null)")
			        + "' tex='"
			        + (tex ? tex.name : "(null)")
			        + "'";
		}
		return text;
	}

	private static string DescribeHomm3Visual(GameObject root)
	{
		var visualRoot = FindDescendantTransform(root ? root.transform : null, VisualRootName);
		if (!visualRoot)
			return "";
		var quad = FindDescendantTransform(visualRoot, "quad") ?? visualRoot;
		var renderer = quad.GetComponent(Il2CppType.Of<Renderer>())?.TryCast<Renderer>();
		if (!renderer)
			return "rootPath=" + BuildPath(visualRoot, root.transform) + " quadRenderer=(null)";

		var material = renderer.sharedMaterial;
		var texture = GetMainTexture(material);
		var color = GetMaterialColor(material);
		return "rootPath="
		       + BuildPath(visualRoot, root.transform)
		       + " quadPath="
		       + BuildPath(renderer.transform, root.transform)
		       + " activeSelf="
		       + quad.gameObject.activeSelf
		       + " activeInHierarchy="
		       + quad.gameObject.activeInHierarchy
		       + " rendererEnabled="
		       + renderer.enabled
		       + " forceOff="
		       + renderer.forceRenderingOff
		       + " bounds="
		       + FormatBounds(renderer.bounds)
		       + " localScale="
		       + FormatVector(quad.localScale)
		       + " lossyScale="
		       + FormatVector(quad.lossyScale)
		       + " mat='"
		       + (material ? material.name : "(null)")
		       + "' shader='"
		       + (material && material.shader ? material.shader.name : "(null)")
		       + "' queue="
		       + (material ? material.renderQueue.ToString() : "(null)")
		       + " mainTexProp="
		       + DescribeMainTextureProperty(material)
		       + " tex="
		       + DescribeTexture(texture)
		       + " color="
		       + color;
	}

	private static Texture GetMainTexture(Material material)
	{
		if (!material)
			return null;
		if (material.HasProperty("_MainTex"))
			return material.GetTexture("_MainTex");
		return material.mainTexture;
	}

	private static string DescribeMainTextureProperty(Material material)
	{
		if (!material)
			return "(null)";
		try
		{
			if (material.HasProperty("_MainTex"))
				return "_MainTex";
			if (material.HasProperty("_BaseMap"))
				return "_BaseMap";
			if (material.HasProperty("_MainTexture"))
				return "_MainTexture";
			return "(none)";
		}
		catch
		{
			return "(failed)";
		}
	}

	private static string DescribeTexture(Texture texture)
	{
		if (!texture)
			return "(null)";
		var size = texture is Texture2D tex2d
			? tex2d.width + "x" + tex2d.height
			: texture.width + "x" + texture.height;
		return "'"
		       + texture.name
		       + "' type="
		       + texture.GetType().Name
		       + " dim="
		       + texture.dimension
		       + " size="
		       + size
		       + " aniso="
		       + texture.anisoLevel
		       + " filter="
		       + texture.filterMode
		       + " wrap="
		       + texture.wrapMode;
	}

	private static string GetMaterialColor(Material material)
	{
		if (!material)
			return "(null)";
		try
		{
			if (material.HasProperty("_Color"))
				return FormatColor(material.GetColor("_Color"));
			if (material.HasProperty("_BaseColor"))
				return FormatColor(material.GetColor("_BaseColor"));
		}
		catch
		{
			return "(failed)";
		}
		return "(none)";
	}

	private static string FormatColor(Color color)
	{
		return "("
		       + color.r.ToString("0.###")
		       + ","
		       + color.g.ToString("0.###")
		       + ","
		       + color.b.ToString("0.###")
		       + ","
		       + color.a.ToString("0.###")
		       + ")";
	}

	private static string FormatBounds(Bounds bounds)
	{
		return "center="
		       + FormatVector(bounds.center)
		       + " size="
		       + FormatVector(bounds.size);
	}

	private static string FormatVector(Vector3 vector)
	{
		return "("
		       + vector.x.ToString("0.###")
		       + ","
		       + vector.y.ToString("0.###")
		       + ","
		       + vector.z.ToString("0.###")
		       + ")";
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

	private static bool HasDescendant(GameObject root, string name)
	{
		return root && FindDescendant(root.transform, name);
	}

	private static bool FindDescendant(Transform root, string name)
	{
		return FindDescendantTransform(root, name);
	}

	private static Transform FindDescendantTransform(Transform root, string name)
	{
		if (!root)
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		for (var i = 0; i < root.childCount; i++)
		{
			var found = FindDescendantTransform(root.GetChild(i), name);
			if (found)
				return found;
		}
		return null;
	}

	private static string BuildPath(Transform t, Transform root)
	{
		if (!t)
			return "(null)";
		var parts = new List<string>();
		for (var cur = t; cur != null && cur != root; cur = cur.parent)
			parts.Add(cur.name ?? "?");
		parts.Reverse();
		return parts.Count == 0 ? "." : string.Join("/", parts);
	}

	private static GameObject TryInvokeGameObjectGetter(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		var m = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (m == null || m.ReturnType != typeof(GameObject) || m.GetParameters().Length != 0)
			return null;
		try
		{
			return m.Invoke(obj, null) as GameObject;
		}
		catch
		{
			return null;
		}
	}

	private static object TryInvokeObjectGetter(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		var m = obj.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
		if (m == null || m.GetParameters().Length != 0)
			return null;
		try
		{
			return m.Invoke(obj, null);
		}
		catch
		{
			return null;
		}
	}

	private static object GetFieldValue(object obj, string name)
	{
		if (obj == null || string.IsNullOrEmpty(name))
			return null;
		for (var t = obj.GetType(); t != null; t = t.BaseType)
		{
			var f = t.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (f == null)
				continue;
			try
			{
				return f.GetValue(obj);
			}
			catch
			{
				return null;
			}
		}
		return null;
	}

	private static bool IsNamedTypeHint(Type type, string[] hints)
	{
		if (type == null || hints == null)
			return false;
		for (var i = 0; i < hints.Length; i++)
		{
			var h = hints[i];
			if (string.IsNullOrWhiteSpace(h))
				continue;
			if (string.Equals(type.FullName, h, StringComparison.Ordinal)
			    || string.Equals(type.Name, h, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}
