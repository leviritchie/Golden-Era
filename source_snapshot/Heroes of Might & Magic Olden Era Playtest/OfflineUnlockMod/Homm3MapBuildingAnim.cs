using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Adventure-map building animation (catalog <c>homm3_map_building_meshes/anim/catalog.json</c>,
/// produced by <c>tools/homm3_map_building_meshes/map_building_anim.py</c>).
/// <list type="bullet">
/// <item><c>rotor</c> (mesh): the prefab carries its own Animator + looping clip (native windmill
/// pattern); runtime only verifies the pivots and the Animator exist and are enabled.</item>
/// <item><c>pendulum</c> / <c>articulated_rigid</c> (mesh): parts cut from the shipped mesh under
/// <c>HOMM3_anim_part_*_pivot</c> nodes, driven by the prefab's own Animator clip (keyed swing or
/// slew); verified exactly like rotors.</item>
/// <item><c>vanilla_style_effect</c> (mesh; rotor rows may also carry <c>effects</c>): vanilla Olden Era
/// map-object ParticleSystems cloned onto <c>HOMM3_anim_anchor_*</c> empties of the prefab by
/// <see cref="Homm3MeshFx"/> (map_building rows compiled by map_building_fx.py). This class only verifies the
/// anchors exist. HoMM3 sprite flipbooks are retired: lane <c>flipbook</c> and key <c>flipbooks</c> fail the catalog.</item>
/// <item><c>billboard_frames</c> (billboard): whole-frame composites swapped on the billboard's own
/// material by the same registry.</item>
/// </list>
/// Materials are named <see cref="MaterialPrefix"/> so frame swaps touch only the main texture slots.
/// Proof tier: source/build; runtime playback is unproven until tested in game.
/// </summary>
internal static class Homm3MapBuildingAnim
{
	internal const string RelativeCatalogPath = "homm3_map_building_meshes/anim/catalog.json";
	internal const string CatalogSchema = "homm3_map_building_anim.v1";
	internal const string MaterialPrefix = "HOMM3_map_anim_";
	private const string AnchorPrefix = "HOMM3_anim_anchor_";
	private const string AssetFolder = "homm3_map_building_meshes/anim/";

	private sealed class Entry
	{
		internal string RelativePng;
		internal string Delivery;
		internal string Lane;
		internal float FrameMs;
		internal string[] BillboardFrames;
		// Vanilla-style effect anchors (HOMM3_anim_anchor_<id>); the effects themselves are Homm3MeshFx rows.
		internal readonly List<string> EffectAnchors = new();
		// Animator-driven pivots: rotor pivots and keyed part pivots.
		internal readonly List<string> RotorPivots = new();
	}

	private static bool _catalogLoadAttempted;
	private static Dictionary<string, Entry> _byRelativePng;
	private static readonly Dictionary<string, Texture2D> TexturesByPath = new(StringComparer.OrdinalIgnoreCase);
	private static readonly HashSet<string> LoggedErrors = new(StringComparer.Ordinal);
	private static readonly HashSet<string> LoggedApplied = new(StringComparer.Ordinal);
	/// <summary>Startup gate: catalog schema + every referenced frame PNG must exist.</summary>
	internal static void ValidatePayloadOrFail(ManualLogSource log)
	{
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (path == null || !File.Exists(path))
			throw new FileNotFoundException(
				"homm3MapBuildingMeshes is enabled but the map building animation catalog is missing. Run "
				+ "tools/homm3_map_building_meshes/map_building_anim.py build and redeploy.",
				RelativeCatalogPath);
		EnsureCatalog(log);
		if (_byRelativePng == null)
			throw new InvalidOperationException("map building animation catalog failed to parse: " + RelativeCatalogPath);
		var frames = 0;
		foreach (var e in _byRelativePng.Values)
		{
			foreach (var rel in EnumerateFrames(e))
			{
				var p = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(AssetFolder + rel);
				if (p == null || !File.Exists(p))
					throw new FileNotFoundException(
						"map building animation frame missing for '" + e.RelativePng + "'",
						AssetFolder + rel);
				frames++;
			}
			if (e.Delivery == "mesh" && !Homm3MapBuildingMeshBundle.HasMeshForRelativePath(e.RelativePng))
				throw new InvalidOperationException(
					"map building animation row '" + e.RelativePng + "' is a mesh row but the mesh catalog has no entry for it.");
		}
		log?.LogInfo(
			"Homm3MapBuildingAnim: validated "
			+ _byRelativePng.Count
			+ " animated building row(s), "
			+ frames
			+ " frame file(s).");
	}

	private static IEnumerable<string> EnumerateFrames(Entry e)
	{
		if (e.BillboardFrames != null)
			foreach (var f in e.BillboardFrames)
				yield return f;
	}

	internal static bool HasBillboardFrames(string relativePng)
	{
		return TryGetEntry(relativePng, out var e) && e.Lane == "billboard_frames" && e.BillboardFrames != null;
	}

	/// <summary>First composite frame of an animated billboard (used as the material's base texture).</summary>
	internal static Texture2D TryGetBillboardFirstFrame(string relativePng, ManualLogSource log)
	{
		if (!TryGetEntry(relativePng, out var e) || e.Lane != "billboard_frames" || e.BillboardFrames == null)
			return null;
		return LoadTexture(e.BillboardFrames[0], log);
	}

	/// <summary>Register an animated billboard's own material and quad renderer with the map idle ticker.</summary>
	internal static bool TryRegisterBillboard(Material material, Renderer quadRenderer, string relativePng, ManualLogSource log)
	{
		if (!material || !quadRenderer)
			return false;
		if (!TryGetEntry(relativePng, out var e) || e.Lane != "billboard_frames" || e.BillboardFrames == null)
			return false;
		if (!(material.name ?? string.Empty).StartsWith(MaterialPrefix, StringComparison.Ordinal))
		{
			LogErrorOnce(
				"billboard-material|" + relativePng,
				"Homm3MapBuildingAnim: billboard material '" + material.name + "' for '" + relativePng
				+ "' is not " + MaterialPrefix + "*; refuse to animate (frame swap would overwrite every texture slot).",
				log);
			return false;
		}
		var frames = LoadFrames(e.BillboardFrames, log);
		if (frames == null)
			return false;
		return RegisterQuad(material, quadRenderer, frames, e.FrameMs, relativePng, log);
	}

	/// <summary>Mesh building instance: verify the rotor Animator and the vanilla-style effect anchors.</summary>
	internal static void TryAttachForMapBuilding(
		GameObject meshInstance,
		Homm3MapBuildingMeshBundle.CatalogEntry meshEntry,
		Renderer donor,
		ManualLogSource log)
	{
		if (!meshInstance || meshEntry == null)
			return;
		if (!TryGetEntry(meshEntry.RelativePng, out var e) || e.Delivery != "mesh")
			return;
		try
		{
			if (IsAnimatorLane(e.Lane))
				VerifyRotor(meshInstance, e, log);
			if (e.EffectAnchors.Count > 0)
				VerifyEffectAnchors(meshInstance, e, log);
		}
		catch (Exception ex)
		{
			LogErrorOnce("attach|" + e.RelativePng, "Homm3MapBuildingAnim: attach failed for '" + e.RelativePng + "': " + ex, log);
		}
	}

	/// <summary>Lanes whose motion is the prefab's own baked Animator clip on named pivots.</summary>
	private static bool IsAnimatorLane(string lane) =>
		lane == "rotor" || lane == "pendulum" || lane == "articulated_rigid";

	private const string LaneEffect = "vanilla_style_effect";
	private const string LaneBillboardFrames = "billboard_frames";

	private static bool IsKnownLane(string lane) =>
		IsAnimatorLane(lane) || lane == LaneEffect || lane == LaneBillboardFrames;

	private static void VerifyRotor(GameObject meshInstance, Entry e, ManualLogSource log)
	{
		var animator = meshInstance.GetComponent<Animator>();
		if (!animator || !animator.runtimeAnimatorController)
		{
			LogErrorOnce(
				"rotor-animator|" + e.RelativePng,
				"Homm3MapBuildingAnim: " + e.Lane + " row '" + e.RelativePng
				+ "' but the mesh prefab has no Animator/controller — the installed homm3_map_building_meshes bundle predates the animation build.",
				log);
			return;
		}
		foreach (var pivot in e.RotorPivots)
		{
			if (!FindDescendant(meshInstance.transform, pivot))
			{
				LogErrorOnce(
					"rotor-pivot|" + e.RelativePng + "|" + pivot,
					"Homm3MapBuildingAnim: " + e.Lane + " pivot '" + pivot + "' missing under '" + meshInstance.name + "'.",
					log);
				return;
			}
		}
		animator.enabled = true;
		if (LoggedApplied.Add("rotor|" + e.RelativePng))
			log?.LogInfo(
				"Homm3MapBuildingAnim: " + e.Lane + " Animator active on '" + meshInstance.name + "' pivots=" + e.RotorPivots.Count + ".");
	}

	private static void VerifyEffectAnchors(GameObject meshInstance, Entry e, ManualLogSource log)
	{
		foreach (var anchor in e.EffectAnchors)
		{
			if (!FindDescendant(meshInstance.transform, anchor))
			{
				LogErrorOnce(
					"fx-anchor|" + e.RelativePng + "|" + anchor,
					"Homm3MapBuildingAnim: effect anchor '" + anchor + "' missing under '" + meshInstance.name
					+ "' — the installed homm3_map_building_meshes bundle predates the effect build.",
					log);
				return;
			}
		}
		if (LoggedApplied.Add("fx|" + e.RelativePng))
			log?.LogInfo(
				"Homm3MapBuildingAnim: vanilla-style effect anchors verified on '" + meshInstance.name + "' count="
				+ e.EffectAnchors.Count + " (effects attach through Homm3MeshFx).");
	}

	private static bool RegisterQuad(Material material, Renderer renderer, Texture2D[] frames, float frameMs, string key, ManualLogSource log)
	{
		Homm3ImportVisuals.EnsureHomm3MapIdleAnimatorHost(log);
		Homm3MapIdleTextureAnimatorRegistry.Register(material, frames, frameMs);
		Homm3MapIdleTextureAnimatorRegistry.RegisterRenderer(renderer);
		var go = renderer.gameObject;
		if (!go.GetComponent<Homm3MapIdleTextureAnimator>() && !go.AddComponent<Homm3MapIdleTextureAnimator>())
		{
			LogErrorOnce("ticker|" + key, "Homm3MapBuildingAnim: failed to add Homm3MapIdleTextureAnimator for '" + key + "'.", log);
			return false;
		}
		return true;
	}

	internal static string SanitizeName(string relativePng)
	{
		var dir = Path.GetFileName(Path.GetDirectoryName((relativePng ?? string.Empty).Replace('/', Path.DirectorySeparatorChar)) ?? string.Empty);
		if (dir.EndsWith(".dir", StringComparison.OrdinalIgnoreCase))
			dir = dir.Substring(0, dir.Length - 4);
		return dir.ToLowerInvariant();
	}

	private static Transform FindDescendant(Transform root, string name)
	{
		if (!root || string.IsNullOrEmpty(name))
			return null;
		var all = root.GetComponentsInChildren<Transform>(true);
		for (var i = 0; i < all.Length; i++)
			if (all[i] && string.Equals(all[i].name, name, StringComparison.Ordinal))
				return all[i];
		return null;
	}

	private static Texture2D[] LoadFrames(string[] relFrames, ManualLogSource log)
	{
		if (relFrames == null || relFrames.Length < 2)
			return null;
		var frames = new Texture2D[relFrames.Length];
		for (var i = 0; i < relFrames.Length; i++)
		{
			frames[i] = LoadTexture(relFrames[i], log);
			if (!frames[i])
				return null;
		}
		return frames;
	}

	private static Texture2D LoadTexture(string rel, ManualLogSource log)
	{
		if (TexturesByPath.TryGetValue(rel, out var cached) && cached)
			return cached;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(AssetFolder + rel);
		if (path == null || !File.Exists(path))
		{
			LogErrorOnce("frame|" + rel, "Homm3MapBuildingAnim: frame missing " + AssetFolder + rel + ".", log);
			return null;
		}
		var bytes = File.ReadAllBytes(path);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		for (var i = 0; i < bytes.Length; i++)
			il2cppBytes[i] = bytes[i];
		var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
		if (!ImageConversion.LoadImage(tex, il2cppBytes))
		{
			UnityEngine.Object.Destroy(tex);
			LogErrorOnce("decode|" + rel, "Homm3MapBuildingAnim: PNG decode failed " + rel + ".", log);
			return null;
		}
		tex.name = MaterialPrefix + rel.Replace('/', '_');
		tex.filterMode = FilterMode.Bilinear;
		tex.wrapMode = TextureWrapMode.Clamp;
		tex.hideFlags = HideFlags.DontUnloadUnusedAsset;
		TexturesByPath[rel] = tex;
		return tex;
	}

	private static bool TryGetEntry(string relativePng, out Entry entry)
	{
		entry = null;
		if (string.IsNullOrWhiteSpace(relativePng))
			return false;
		EnsureCatalog(null);
		return _byRelativePng != null
		       && _byRelativePng.TryGetValue(Normalize(relativePng), out entry)
		       && entry != null;
	}

	private static string Normalize(string relativePng) =>
		(relativePng ?? string.Empty).Replace('\\', '/').Trim().TrimStart('/');

	private static void EnsureCatalog(ManualLogSource log)
	{
		if (_catalogLoadAttempted)
			return;
		_catalogLoadAttempted = true;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (path == null || !File.Exists(path))
		{
			log?.LogWarning("Homm3MapBuildingAnim: catalog missing at " + RelativeCatalogPath + "; map buildings stay static.");
			return;
		}
		var map = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
		try
		{
			var root = Newtonsoft.Json.Linq.JObject.Parse(File.ReadAllText(path));
			var schema = root["schema"]?.ToString() ?? string.Empty;
			if (!string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
				throw new InvalidOperationException("schema mismatch: expected " + CatalogSchema + " got " + schema);
			var entries = Newtonsoft.Json.Linq.JArray.Parse(root["entries"]?.ToString() ?? "[]");
			for (var i = 0; i < entries.Count; i++)
			{
				var row = Newtonsoft.Json.Linq.JObject.Parse(entries[i].ToString());
				var e = new Entry
				{
					RelativePng = Normalize(row["relativePng"]?.ToString()),
					Delivery = row["delivery"]?.ToString() ?? string.Empty,
					Lane = row["lane"]?.ToString() ?? string.Empty,
					FrameMs = ParseFloat(row["frameMs"]?.ToString(), 180f)
				};
				if (string.IsNullOrEmpty(e.RelativePng))
					throw new InvalidOperationException("row " + i + " has no relativePng");
				if (!IsKnownLane(e.Lane))
					throw new InvalidOperationException("row '" + e.RelativePng + "' has unknown lane '" + e.Lane + "' (flipbook is retired)");
				if (row["flipbooks"] != null)
					throw new InvalidOperationException("row '" + e.RelativePng + "' carries retired flipbooks");
				var bframes = row["frames"]?.ToString();
				if (!string.IsNullOrEmpty(bframes))
					e.BillboardFrames = ParseStringArray(bframes);
				var effects = row["effects"]?.ToString();
				if (!string.IsNullOrEmpty(effects))
				{
					var arr = Newtonsoft.Json.Linq.JArray.Parse(effects);
					for (var k = 0; k < arr.Count; k++)
					{
						var anchor = Newtonsoft.Json.Linq.JObject.Parse(arr[k].ToString())["anchor"]?.ToString();
						if (string.IsNullOrEmpty(anchor) || !anchor.StartsWith(AnchorPrefix, StringComparison.Ordinal))
							throw new InvalidOperationException("row '" + e.RelativePng + "' effect " + k + " anchor is not " + AnchorPrefix + "*");
						e.EffectAnchors.Add(anchor);
					}
				}
				if (e.Lane == LaneEffect && (e.Delivery != "mesh" || e.EffectAnchors.Count == 0))
					throw new InvalidOperationException("row '" + e.RelativePng + "' lane " + LaneEffect + " needs a mesh row with effects");
				var rotors = row["rotors"]?.ToString();
				if (!string.IsNullOrEmpty(rotors))
				{
					var arr = Newtonsoft.Json.Linq.JArray.Parse(rotors);
					for (var k = 0; k < arr.Count; k++)
					{
						var pivot = Newtonsoft.Json.Linq.JObject.Parse(arr[k].ToString())["pivot"]?.ToString();
						if (string.IsNullOrEmpty(pivot))
							throw new InvalidOperationException("row '" + e.RelativePng + "' rotor " + k + " has no pivot");
						e.RotorPivots.Add(pivot);
					}
				}
				var parts = row["parts"]?.ToString();
				if (!string.IsNullOrEmpty(parts))
				{
					var arr = Newtonsoft.Json.Linq.JArray.Parse(parts);
					for (var k = 0; k < arr.Count; k++)
					{
						var pivot = Newtonsoft.Json.Linq.JObject.Parse(arr[k].ToString())["pivot"]?.ToString();
						if (string.IsNullOrEmpty(pivot))
							throw new InvalidOperationException("row '" + e.RelativePng + "' part " + k + " has no pivot");
						e.RotorPivots.Add(pivot);
					}
				}
				if (e.Delivery == "mesh" && IsAnimatorLane(e.Lane) && e.RotorPivots.Count == 0)
					throw new InvalidOperationException("row '" + e.RelativePng + "' lane " + e.Lane + " lists no pivots");
				map[e.RelativePng] = e;
			}
			_byRelativePng = map;
		}
		catch (Exception ex)
		{
			_byRelativePng = null;
			log?.LogError("Homm3MapBuildingAnim: catalog parse failed: " + ex.Message);
		}
	}

	private static string[] ParseStringArray(string json)
	{
		var arr = Newtonsoft.Json.Linq.JArray.Parse(json);
		var outp = new string[arr.Count];
		for (var i = 0; i < arr.Count; i++)
			outp[i] = arr[i].ToString();
		return outp;
	}

	private static float ParseFloat(string s, float fallback)
	{
		return !string.IsNullOrWhiteSpace(s)
		       && Homm3JsonNumber.TryParseFloat(s, out var v)
			? v
			: fallback;
	}

	private static void LogErrorOnce(string key, string message, ManualLogSource log)
	{
		if (LoggedErrors.Add(key))
			(log ?? Plugin.LogSource)?.LogError(message);
	}
}
