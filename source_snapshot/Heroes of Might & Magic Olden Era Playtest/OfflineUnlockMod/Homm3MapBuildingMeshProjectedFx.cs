using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Constrained FX for Meshy map-building meshes.
/// Base Hex/Lit emission writes were attached+ticked but not user-visible; a full-mesh
/// particles overlay darkened stone. Visible path: additive glow-only child mesh using
/// the transparent Meshy overlay atlas, with per-kind color curves (and a spinning disc for maelstrom).
/// Base albedo materials are never modified. Proof: source/static until in-map verified.
/// </summary>
internal static class Homm3MapBuildingMeshProjectedFx
{
	internal const string OverlayObjectName = "HOMM3_map_building_fx_overlay";
	internal const string MaelstromDiscObjectName = "HOMM3_maelstrom_spin_disc";

	internal enum Kind
	{
		None = 0,
		WaterRipple = 1,
		FireFlicker = 2,
		AirSwirl = 3,
		MagicPulse = 4,
		GoldShimmer = 5,
		MaelstromSpin = 6
	}

	private readonly struct Plan
	{
		internal readonly string Needle;
		internal readonly Kind Kind;

		internal Plan(string needle, Kind kind)
		{
			Needle = needle;
			Kind = kind;
		}
	}

	private static readonly Plan[] Plans =
	{
		new("avgwatr0", Kind.WaterRipple),
		new("avgfire0", Kind.FireFlicker),
		new("avgair0", Kind.AirSwirl),
		new("avgfbrd", Kind.MagicPulse),
		new("avgelp", Kind.MagicPulse),
		new("hasphtpl", Kind.MaelstromSpin),
		new("avgpega0", Kind.WaterRipple),
		new("avggogs0", Kind.FireFlicker),
		new("avgpit0", Kind.FireFlicker),
		new("avgrdrg0", Kind.GoldShimmer),
	};

	private const string FxRelativeDir = "homm3_map_building_meshes/fx";
	private const string MaelstromDiscRelativePath = FxRelativeDir + "/maelstrom_swirl_disc.png";
	private static bool _typeRegistered;
	private static int _attachLogRemaining = 16;
    private static readonly Dictionary<string, Texture2D> OverlayByPrefabKey =
		new(StringComparer.OrdinalIgnoreCase);
	private static Texture2D _maelstromDiscTexture;
	private static Mesh _horizontalDiscMesh;

	internal static bool IsFxChildObject(Transform transform)
	{
		if (!transform)
			return false;
		if (Homm3MeshFx.IsFxDescendant(transform))
			return true;
		var name = transform.name ?? string.Empty;
		return string.Equals(name, OverlayObjectName, StringComparison.Ordinal)
		       || string.Equals(name, MaelstromDiscObjectName, StringComparison.Ordinal);
	}

	internal static Kind ResolveKind(Homm3MapBuildingMeshBundle.CatalogEntry entry)
	{
		if (entry == null)
			return Kind.None;
		var key = entry.PrefabKey ?? string.Empty;
		var rel = entry.RelativePng ?? string.Empty;
		for (var i = 0; i < Plans.Length; i++)
		{
			var plan = Plans[i];
			if (key.IndexOf(plan.Needle, StringComparison.OrdinalIgnoreCase) >= 0
			    || rel.IndexOf(plan.Needle, StringComparison.OrdinalIgnoreCase) >= 0)
				return plan.Kind;
		}
		return Kind.None;
	}

	internal static void TryAttachForCatalogEntry(
		GameObject meshRoot,
		Homm3MapBuildingMeshBundle.CatalogEntry entry,
		ManualLogSource log)
	{
		if (!meshRoot || entry == null)
			return;
		var kind = ResolveKind(entry);
		if (kind == Kind.None)
			return;
		Attach(meshRoot, kind, entry.PrefabKey, log);
	}

	internal static void Attach(GameObject meshRoot, Kind kind, string prefabKey, ManualLogSource log)
	{
		if (!meshRoot || kind == Kind.None)
			return;
		EnsureTypeRegistered(log);
        if (!TryLoadOverlayTexture(prefabKey, out var overlayTexture, log) || !overlayTexture)
			return;

		var meshFilter = FindPrimaryMeshFilter(meshRoot);
		var donorRenderer = meshFilter ? meshFilter.GetComponent<MeshRenderer>() : null;
		if (!meshFilter || !meshFilter.sharedMesh || !donorRenderer || !donorRenderer.sharedMaterial)
		{
			log?.LogError(
				"Homm3MapBuildingMeshProjectedFx: missing mesh/donor for prefab='"
				+ prefabKey
				+ "'.");
			return;
		}

		var overlayRoot = TryAttachAdditiveGlowOverlay(
			meshRoot,
			meshFilter,
			donorRenderer,
            overlayTexture,
			kind,
			log);
		if (!overlayRoot)
			return;

		if (kind == Kind.MaelstromSpin)
			TryAttachMaelstromSpinDisc(meshRoot, donorRenderer, log);

		var host = overlayRoot.GetComponent<Homm3MapBuildingMeshProjectedFxHost>();
		if (!host)
			host = overlayRoot.AddComponent<Homm3MapBuildingMeshProjectedFxHost>();
		if (!host)
		{
			log?.LogError("Homm3MapBuildingMeshProjectedFx: overlay host AddComponent failed.");
			return;
		}

		Homm3MapBuildingMeshProjectedFxRegistry.Register(
			host,
			kind,
			phaseOffset: (meshRoot.GetInstanceID() & 255) / 255f);

		if (_attachLogRemaining > 0)
		{
			_attachLogRemaining--;
			log?.LogInfo(
				"Homm3MapBuildingMeshProjectedFx: attached kind="
				+ kind
				+ " prefab='"
				+ prefabKey
				+ "' path=additiveGlowOverlay");
		}
	}

	internal static Color ComputeGlowColor(Kind kind, float t, float phaseOffset)
	{
		switch (kind)
		{
			case Kind.WaterRipple:
			case Kind.MaelstromSpin:
			{
				var pulse = 0.55f + 0.35f * Mathf.Sin(t * 2.1f + phaseOffset);
				var flow = 0.08f * Mathf.Sin(t * 1.35f + phaseOffset * 2f);
				return new Color(
					0.10f * pulse,
					(0.42f + flow) * pulse,
					(1.05f + flow * 0.5f) * pulse,
					1f);
			}
			case Kind.FireFlicker:
			{
				var flicker = 0.65f + 0.45f * Mathf.PerlinNoise(t * 1.3f, phaseOffset * 3f);
				return new Color(1.2f * flicker, 0.35f * flicker, 0.04f * flicker, 1f);
			}
			case Kind.AirSwirl:
			{
				var swirl = 0.55f + 0.40f * Mathf.Sin(t * 1.8f + phaseOffset);
				var lift = 0.12f * Mathf.Sin(t * 3.1f + phaseOffset * 1.7f);
				return new Color(
					(0.75f + lift) * swirl,
					(0.85f + lift * 0.5f) * swirl,
					1.15f * swirl,
					1f);
			}
			case Kind.MagicPulse:
			{
				var pulse = 0.50f + 0.45f * Mathf.Sin(t * 2.4f + phaseOffset);
				var spark = 0.15f * Mathf.PerlinNoise(t * 2.0f, phaseOffset * 4f);
				return new Color(
					(0.85f + spark) * pulse,
					(0.35f + spark * 0.5f) * pulse,
					(1.15f + spark) * pulse,
					1f);
			}
			case Kind.GoldShimmer:
			{
				var twinkle = 0.55f + 0.40f * Mathf.PerlinNoise(t * 2.2f, phaseOffset * 5f);
				var beat = 0.12f * Mathf.Sin(t * 4.0f + phaseOffset);
				return new Color(
					(1.15f + beat) * twinkle,
					(0.85f + beat * 0.5f) * twinkle,
					0.22f * twinkle,
					1f);
			}
			default:
				return Color.black;
		}
	}

	private static MeshFilter FindPrimaryMeshFilter(GameObject meshRoot)
	{
		var filters = meshRoot.GetComponentsInChildren<MeshFilter>(true);
		if (filters == null)
			return null;
		for (var i = 0; i < filters.Length; i++)
		{
			var filter = filters[i];
			if (!filter || !filter.sharedMesh || IsFxChildObject(filter.transform))
				continue;
			return filter;
		}
		return null;
	}

	private static void DestroyNamedDescendants(Transform root, string objectName)
	{
		if (!root || string.IsNullOrEmpty(objectName))
			return;
		var children = root.GetComponentsInChildren<Transform>(true);
		if (children == null)
			return;
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (!child || child == root)
				continue;
			if (!string.Equals(child.name, objectName, StringComparison.Ordinal))
				continue;
			UnityEngine.Object.Destroy(child.gameObject);
		}
	}

	private static Material CreateAdditiveGlowMaterial(
        Texture2D overlayTexture,
		Color initialTint,
		string materialName,
		ManualLogSource log)
	{
		var shader = Shader.Find("Hex/Particles")
			?? Shader.Find("Sprites/Default")
			?? Shader.Find("Unlit/Transparent");
		if (!shader)
		{
			log?.LogError("Homm3MapBuildingMeshProjectedFx: no additive glow shader available.");
			return null;
		}

		var material = new Material(shader) { name = materialName };
        if (material.HasProperty("_MainTex"))
            material.SetTexture("_MainTex", overlayTexture);
        else
            material.mainTexture = overlayTexture;
		if (material.HasProperty("_Color"))
			material.SetColor("_Color", initialTint);
		else if (material.HasProperty("_TintColor"))
			material.SetColor("_TintColor", initialTint);

		// Additive: black mask pixels contribute nothing; never darken base albedo.
		if (material.HasProperty("_SrcBlend"))
			material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
		if (material.HasProperty("_DstBlend"))
			material.SetFloat("_DstBlend", (float)BlendMode.One);
		if (material.HasProperty("_ZWrite"))
			material.SetFloat("_ZWrite", 0f);
		if (material.HasProperty("_ZTest"))
			material.SetFloat("_ZTest", (float)CompareFunction.LessEqual);
		if (material.HasProperty("_Cull"))
			material.SetFloat("_Cull", (float)CullMode.Off);
		material.renderQueue = 3001;

		log?.LogInfo(
			"Homm3MapBuildingMeshProjectedFx: additive glow shader='"
			+ (shader.name ?? "?")
			+ "' mat='"
			+ materialName
			+ "'");
		return material;
	}

	private static GameObject TryAttachAdditiveGlowOverlay(
		GameObject meshRoot,
		MeshFilter sourceFilter,
		MeshRenderer donorRenderer,
        Texture2D overlayTexture,
		Kind kind,
		ManualLogSource log)
	{
		DestroyNamedDescendants(meshRoot.transform, OverlayObjectName);

		var initialTint = ComputeGlowColor(kind, Time.time, (meshRoot.GetInstanceID() & 255) / 255f);
		var material = CreateAdditiveGlowMaterial(
            overlayTexture,
			initialTint,
			"HOMM3_map_building_fx_glow_" + kind,
			log);
		if (!material)
			return null;

		var overlay = new GameObject(OverlayObjectName);
		overlay.layer = donorRenderer.gameObject.layer;
		overlay.transform.SetParent(sourceFilter.transform, false);
		overlay.transform.localPosition = Vector3.up * 0.004f;
		overlay.transform.localRotation = Quaternion.identity;
		overlay.transform.localScale = Vector3.one;

		var filter = overlay.AddComponent<MeshFilter>();
		filter.sharedMesh = sourceFilter.sharedMesh;
		var renderer = overlay.AddComponent<MeshRenderer>();
		renderer.sharedMaterial = material;
		renderer.shadowCastingMode = ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		renderer.allowOcclusionWhenDynamic = false;
		renderer.renderingLayerMask = donorRenderer.renderingLayerMask;
		return overlay;
	}

	private static void TryAttachMaelstromSpinDisc(
		GameObject meshRoot,
		MeshRenderer donorRenderer,
		ManualLogSource log)
	{
		DestroyNamedDescendants(meshRoot.transform, MaelstromDiscObjectName);
		if (!TryLoadMaelstromDiscTexture(log, out var discTex) || !discTex)
			return;

		var material = CreateAdditiveGlowMaterial(
			discTex,
			new Color(0.35f, 0.75f, 1.25f, 0.85f),
			"HOMM3_maelstrom_spin_disc_mat",
			log);
		if (!material)
			return;

		var meshFilter = FindPrimaryMeshFilter(meshRoot);
		var localBounds = meshFilter && meshFilter.sharedMesh
			? meshFilter.sharedMesh.bounds
			: new Bounds(Vector3.zero, Vector3.one);
		var diameter = Mathf.Min(localBounds.size.x, localBounds.size.z) * 0.88f;
		if (diameter < 0.05f)
			return;
		var localY = localBounds.min.y + localBounds.size.y * 0.18f;
		var localCenter = new Vector3(localBounds.center.x, localY, localBounds.center.z);

		var disc = new GameObject(MaelstromDiscObjectName);
		disc.layer = donorRenderer.gameObject.layer;
		disc.transform.SetParent(meshRoot.transform, false);
		disc.transform.localPosition = localCenter;
		disc.transform.localRotation = Quaternion.identity;
		disc.transform.localScale = new Vector3(diameter, 1f, diameter);

		var filter = disc.AddComponent<MeshFilter>();
		filter.sharedMesh = GetOrCreateHorizontalDiscMesh();
		var renderer = disc.AddComponent<MeshRenderer>();
		renderer.sharedMaterial = material;
		renderer.shadowCastingMode = ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		renderer.allowOcclusionWhenDynamic = false;
		renderer.renderingLayerMask = donorRenderer.renderingLayerMask;
		if (!disc.AddComponent<Homm3MapBuildingMaelstromSpinDisc>())
		{
			UnityEngine.Object.Destroy(disc);
			log?.LogError("Homm3MapBuildingMeshProjectedFx: maelstrom spin disc AddComponent failed.");
			return;
		}
		log?.LogInfo(
			"Homm3MapBuildingMeshProjectedFx: maelstrom spin disc attached diameter="
			+ diameter.ToString("0.###"));
	}

    private static bool TryLoadOverlayTexture(string prefabKey, out Texture2D texture, ManualLogSource log)
	{
		texture = null;
		if (string.IsNullOrWhiteSpace(prefabKey))
			return false;
        if (OverlayByPrefabKey.TryGetValue(prefabKey, out var cached) && cached)
		{
			texture = cached;
			return true;
		}

        var rel = FxRelativeDir + "/" + prefabKey.Trim() + "_overlay.png";
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(rel);
		if (path == null || !File.Exists(path))
		{
			log?.LogError(
                "Homm3MapBuildingMeshProjectedFx: missing transparent overlay atlas '"
				+ rel
				+ "'.");
			return false;
		}

		try
		{
			var bytes = File.ReadAllBytes(path);
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			var tex = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true, linear: false)
			{
                name = prefabKey + "_overlay",
				wrapMode = TextureWrapMode.Clamp,
				filterMode = FilterMode.Bilinear
			};
			if (!ImageConversion.LoadImage(tex, il2cppBytes, markNonReadable: true))
			{
				UnityEngine.Object.Destroy(tex);
				log?.LogError("Homm3MapBuildingMeshProjectedFx: LoadImage failed for " + path);
				return false;
			}
            OverlayByPrefabKey[prefabKey] = tex;
			texture = tex;
			return true;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MapBuildingMeshProjectedFx: failed loading " + path + ": " + ex.Message);
			return false;
		}
	}

	private static bool TryLoadMaelstromDiscTexture(ManualLogSource log, out Texture2D texture)
	{
		texture = null;
		if (_maelstromDiscTexture)
		{
			texture = _maelstromDiscTexture;
			return true;
		}
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(MaelstromDiscRelativePath);
		if (path == null || !File.Exists(path))
		{
			log?.LogError(
				"Homm3MapBuildingMeshProjectedFx: missing maelstrom swirl disc '"
				+ MaelstromDiscRelativePath
				+ "'.");
			return false;
		}
		try
		{
			var bytes = File.ReadAllBytes(path);
			var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
			for (var i = 0; i < bytes.Length; i++)
				il2cppBytes[i] = bytes[i];
			var tex = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true, linear: false)
			{
				name = "maelstrom_swirl_disc",
				wrapMode = TextureWrapMode.Clamp,
				filterMode = FilterMode.Bilinear
			};
			if (!ImageConversion.LoadImage(tex, il2cppBytes, markNonReadable: true))
			{
				UnityEngine.Object.Destroy(tex);
				log?.LogError("Homm3MapBuildingMeshProjectedFx: LoadImage failed for maelstrom disc.");
				return false;
			}
			_maelstromDiscTexture = tex;
			texture = tex;
			return true;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MapBuildingMeshProjectedFx: maelstrom disc load failed: " + ex.Message);
			return false;
		}
	}

	private static Mesh GetOrCreateHorizontalDiscMesh()
	{
		if (_horizontalDiscMesh)
			return _horizontalDiscMesh;
		const int segments = 48;
		var verts = new Vector3[segments + 1];
		var uvs = new Vector2[segments + 1];
		var tris = new int[segments * 3];
		verts[0] = Vector3.zero;
		uvs[0] = new Vector2(0.5f, 0.5f);
		for (var i = 0; i < segments; i++)
		{
			var a = (i / (float)segments) * Mathf.PI * 2f;
			var x = Mathf.Cos(a) * 0.5f;
			var z = Mathf.Sin(a) * 0.5f;
			verts[i + 1] = new Vector3(x, 0f, z);
			uvs[i + 1] = new Vector2(x + 0.5f, z + 0.5f);
			tris[i * 3] = 0;
			tris[i * 3 + 1] = i + 1;
			tris[i * 3 + 2] = i + 2 <= segments ? i + 2 : 1;
		}
		_horizontalDiscMesh = new Mesh { name = "HOMM3_maelstrom_spin_disc_mesh" };
		_horizontalDiscMesh.vertices = verts;
		_horizontalDiscMesh.uv = uvs;
		_horizontalDiscMesh.triangles = tris;
		_horizontalDiscMesh.RecalculateNormals();
		_horizontalDiscMesh.RecalculateBounds();
		return _horizontalDiscMesh;
	}

	private static void EnsureTypeRegistered(ManualLogSource log)
	{
		if (_typeRegistered)
			return;
		ClassInjector.RegisterTypeInIl2Cpp<Homm3MapBuildingMeshProjectedFxHost>();
		ClassInjector.RegisterTypeInIl2Cpp<Homm3MapBuildingMaelstromSpinDisc>();
		_typeRegistered = true;
		log?.LogInfo("Homm3MapBuildingMeshProjectedFx: registered Il2Cpp host types.");
	}
}

/// <summary>
/// Managed-only FX state. Injected hosts stay parameterless for Il2Cpp.
/// </summary>
internal static class Homm3MapBuildingMeshProjectedFxRegistry
{
	private sealed class Entry
	{
		internal Homm3MapBuildingMeshProjectedFx.Kind Kind;
		internal float PhaseOffset;
	}

	private static readonly Dictionary<int, Entry> ByHostId = new();
	private static int _tickLogRemaining = 6;

	internal static void Register(
		Homm3MapBuildingMeshProjectedFxHost host,
		Homm3MapBuildingMeshProjectedFx.Kind kind,
		float phaseOffset)
	{
		if (!host)
			return;
		ByHostId[host.GetInstanceID()] = new Entry
		{
			Kind = kind,
			PhaseOffset = phaseOffset
		};
	}

	internal static void Unregister(Homm3MapBuildingMeshProjectedFxHost host)
	{
		if (!host)
			return;
		ByHostId.Remove(host.GetInstanceID());
	}

	internal static void Tick(Homm3MapBuildingMeshProjectedFxHost host)
	{
		if (!host || !ByHostId.TryGetValue(host.GetInstanceID(), out var entry) || entry == null)
			return;
		var renderer = host.GetComponent<MeshRenderer>();
		if (!renderer || !renderer.enabled)
			return;
		var mat = renderer.material;
		if (!mat)
			return;

		var t = Time.time + entry.PhaseOffset * 10f;
		var glow = Homm3MapBuildingMeshProjectedFx.ComputeGlowColor(entry.Kind, t, entry.PhaseOffset);
		if (mat.HasProperty("_Color"))
			mat.SetColor("_Color", glow);
		else if (mat.HasProperty("_TintColor"))
			mat.SetColor("_TintColor", glow);

		if (_tickLogRemaining > 0)
		{
			_tickLogRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3MapBuildingMeshProjectedFx: glow tick kind="
				+ entry.Kind
				+ " color="
				+ glow);
		}
	}
}

public sealed class Homm3MapBuildingMeshProjectedFxHost : MonoBehaviour
{
	public Homm3MapBuildingMeshProjectedFxHost(IntPtr ptr)
		: base(ptr)
	{
	}

	private void LateUpdate()
	{
		Homm3MapBuildingMeshProjectedFxRegistry.Tick(this);
	}

	private void OnDestroy()
	{
		Homm3MapBuildingMeshProjectedFxRegistry.Unregister(this);
	}
}

public sealed class Homm3MapBuildingMaelstromSpinDisc : MonoBehaviour
{
	private const float DegreesPerSecond = 48f;

	public Homm3MapBuildingMaelstromSpinDisc(IntPtr ptr)
		: base(ptr)
	{
	}

	private void LateUpdate()
	{
		if (!isActiveAndEnabled)
			return;
		transform.Rotate(0f, DegreesPerSecond * Time.deltaTime, 0f, Space.Self);
	}
}
