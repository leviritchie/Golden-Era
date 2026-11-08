using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;
using UnityEngine.EventSystems;

namespace OfflineUnlockMod;

/// <summary>
/// Building picking on the full-3D town scenes (Homm3TownScene3d layers): the pointer hits the geometry that is drawn.
/// Native dispatch is unchanged: EventSystem PhysicsRaycaster takes the nearest collider on the pointer ray and
/// ExecuteEvents bubbles up the transform parents to <c>BhBuilding.OnPointerEnter/Exit/Click</c> (mono decomp
/// Hex.Session.City.BhBuilding). Only which building is hit changes.
/// Before 2026-10-01 each building kept one native BoxCollider refit to the world AABB of its body re-boxed in the
/// collider's rotated space: on Rampart that box disagreed with the drawn building on 81% of building pixels over the
/// native pan (tools/homm3_town_scene_meshes/town_full3d_pick.py), because the 3D boxes of the thin relief meshes
/// cover gaps and terrain and a near building's box face wins the ray over a farther building that is drawn in front.
/// Now: the variant's native BoxColliders are disabled (restored on clear), and every drawn body MeshRenderer gets a
/// MeshCollider of its own mesh at its exact world pose:
/// <list type="bullet">
/// <item>interactive (the native variant ships a BoxCollider): a holder under the BhBuilding mirrors the scene root
/// and the renderer's transform chain, so the hit bubbles to that BhBuilding;</item>
/// <item>non-interactive (cityHuman2 Walls / Resource_Depot_2 ship none, so vanilla never makes them clickable) and
/// every environment Mesh_ piece (terrain, water, rocks, props): an occluder MeshCollider on
/// <see cref="OccluderLayer"/>.</item>
/// </list>
/// Occluders must hide what they cover without becoming a pointer target: the city camera's IsOverUI
/// (Hex.Session.City.BhCityCamera / CursorCameraMode, mono decomp) is EventSystem.IsPointerOverGameObject and not
/// CursorRayCast.isOverCityBuilding, so a raycast-visible handler-less collider freezes the cursor camera over it.
/// So occluders live on a layer outside the PhysicsRaycaster's finalEventMask (level67 MainCamera cullingMask
/// 0x9f17; checked at build) and a postfix on PhysicsRaycaster.Raycast drops that raycaster's hits that lie beyond
/// the nearest occluder on the same ray (ComputeRayAndDistance). Without them, building surface sunk into or behind
/// the terrain picked through it: 0.3-5.3% of building pixels per town (Cove Bank IoU 0.07).
/// Physics raycasts skip back faces (queriesHitBackfaces default false), the faces Hex/Lit Cull Back drops.
/// Bundle meshes are Read/Write (m_IsReadable), required for runtime MeshCollider cooking.
/// Gate: tools/validate_town_scene3d_pick_contract.py. Proof tier: source/static + generated-artifact measurement;
/// in-game hover/click is runtime-unproven.
/// </summary>
internal static class Homm3TownScene3dPick
{
	/// <summary>Prefix shared with the mesh lane so RemoveTownSceneMeshChild and IsOwnedArtObject cover the holder.</summary>
	internal const string HolderName = Homm3TownSceneMeshBundle.MeshChildPrefix + "~pick";
	internal const string OccluderName = "OfflineUnlockTownScene3DPickOcclude";
	/// <summary>Outside the city camera's cullingMask (0x9f17), so never a PhysicsRaycaster target.</summary>
	internal const int OccluderLayer = 31;
	private const string MeshPiecePrefix = "Mesh_";
	private const string NodePrefix = "Pick_";
	private const string LogPrefix = "HoMM3 town scene 3D pick: ";
	/// <summary>Child of a holder whose pick meshes are baked into the BhBuilding's own space (see BakeIntoBuildingSpace).</summary>
	private const string BakedMarkerName = "Baked";
	private const string BakedMeshPrefix = "OfflineUnlockTownScene3DPickBaked_";
	private static readonly HashSet<string> LoggedBakedBuildings = new(StringComparer.Ordinal);

	/// <summary>
	/// Build the pick colliders for one building's scene-3D layer. Call after the native BoxColliders are disabled and
	/// the building is anchored. Returns the number of MeshColliders.
	/// </summary>
	internal static int BuildOrThrow(Transform building, Transform sceneRoot, Transform body, bool interactive)
	{
		if (building == null || sceneRoot == null || body == null)
			throw new InvalidOperationException(LogPrefix + "null building, scene root or body.");
		var renderers = DrawnBodyRenderersOrThrow(body);
		var layer = building.gameObject.layer;
		if (!interactive)
		{
			DestroyStaleHolder(building);
			for (var i = 0; i < renderers.Count; i++)
				EnsureOccluder(renderers[i]);
			return renderers.Count;
		}

		DestroyStaleHolder(building);
		var holder = new GameObject(HolderName);
		holder.transform.SetParent(building, false);
		holder.layer = layer;
		if (!MapsRootAsSimilarity(building, sceneRoot))
		{
			BakeIntoBuildingSpace(holder.transform, building, renderers, layer);
			return renderers.Count;
		}
		PoseHolderOrThrow(holder.transform, building, sceneRoot);
		for (var i = 0; i < renderers.Count; i++)
		{
			var chain = ChainBelowOrThrow(renderers[i].Renderer.transform, sceneRoot);
			var parent = holder.transform;
			for (var c = 0; c < chain.Count; c++)
			{
				var node = new GameObject(NodePrefix + chain[c].name);
				node.layer = layer;
				node.transform.SetParent(parent, false);
				node.transform.localPosition = chain[c].localPosition;
				node.transform.localRotation = chain[c].localRotation;
				node.transform.localScale = chain[c].localScale;
				parent = node.transform;
			}
			ConfigureCollider(parent.gameObject, renderers[i], layer);
		}
		return renderers.Count;
	}

	/// <summary>
	/// Camera / anchor moved: re-seat an interactive holder on the scene root (the mirrored chain below it is static);
	/// an occluder-only building needs nothing (its colliders live under the renderers). Neither present is drift.
	/// </summary>
	internal static void ReposeOrThrow(Transform building, Transform sceneRoot, Transform body)
	{
		if (building == null || sceneRoot == null || body == null)
			throw new InvalidOperationException(LogPrefix + "null building, scene root or body during reposition.");
		var holder = building.Find(HolderName);
		if (holder != null)
		{
			// Baked meshes are fixed in the building's space at bake time: rebake rather than re-pose, but only when
			// the bake inputs changed. The sync re-poses every building every frame; rebaking (new meshes + MeshCollider
			// cooking) each time cost ~650 ms per sync on Stronghold and hung the game (2026-10-17).
			if (holder.Find(BakedMarkerName) != null || !MapsRootAsSimilarity(building, sceneRoot))
			{
				var signature = BakeSignature(building, sceneRoot, body);
				if (holder.Find(BakedMarkerName) != null
				    && BakedSignatures.TryGetValue(holder.GetInstanceID(), out var baked) && SameSignature(baked, signature))
					return;
				BuildOrThrow(building, sceneRoot, body, interactive: true);
				var rebuilt = building.Find(HolderName);
				if (rebuilt != null && rebuilt.Find(BakedMarkerName) != null)
					BakedSignatures[rebuilt.GetInstanceID()] = signature;
				return;
			}
			PoseHolderOrThrow(holder, building, sceneRoot);
			return;
		}
		var renderers = body.GetComponentsInChildren<MeshRenderer>(true);
		if (renderers != null && renderers.Length > 0 && renderers[0].transform.Find(OccluderName) != null)
			return;
		throw new InvalidOperationException(LogPrefix + "BhBuilding '" + building.name + "' has neither a pick holder "
			+ "nor occluders during camera reposition; refusing silent pick drift.");
	}

	/// <summary>
	/// Every environment Mesh_ renderer occludes building picks. Idempotent (the environment is kept across
	/// recomposes). The camera must carry the PhysicsRaycaster that dispatches to BhBuilding, and its event mask must
	/// not see <see cref="OccluderLayer"/>, or an occluder would become the pointer target.
	/// </summary>
	internal static int EnsureEnvironmentOccludersOrThrow(Transform environment, Camera camera)
	{
		if (environment == null || camera == null)
			throw new InvalidOperationException(LogPrefix + "null environment or camera for occluders.");
		RequireOccluderLayerHiddenOrThrow(camera);
		var count = 0;
		for (var c = 0; c < environment.childCount; c++)
		{
			var piece = environment.GetChild(c);
			if (piece == null || piece.name == null || !piece.name.StartsWith(MeshPiecePrefix, StringComparison.Ordinal))
				continue;
			var renderers = DrawnBodyRenderersOrThrow(piece);
			for (var i = 0; i < renderers.Count; i++)
				EnsureOccluder(renderers[i]);
			count += renderers.Count;
		}
		if (count == 0)
			throw new InvalidOperationException(LogPrefix + "environment '" + environment.name + "' has no Mesh_ renderer to occlude with.");
		_occludersArmed = true;
		return count;
	}

	internal static int RegisterHarmony(Harmony harmony)
	{
		if (harmony == null)
			throw new InvalidOperationException(LogPrefix + "Harmony missing.");
		// Public UnityEngine.UI API (not obfuscated); the live interop wrapper is
		// Raycast(PointerEventData, Il2CppSystem.Collections.Generic.List<RaycastResult>).
		var method = typeof(PhysicsRaycaster).GetMethod(nameof(PhysicsRaycaster.Raycast),
			BindingFlags.Instance | BindingFlags.Public, null,
			new[] { typeof(PointerEventData), typeof(Il2CppSystem.Collections.Generic.List<RaycastResult>) }, null);
		var postfix = typeof(Homm3TownScene3dPick).GetMethod(nameof(PostfixPhysicsRaycast),
			BindingFlags.Static | BindingFlags.NonPublic);
		if (method == null || postfix == null)
			throw new InvalidOperationException(LogPrefix + "missing PhysicsRaycaster.Raycast patch surface.");
		harmony.Patch(method, postfix: new HarmonyMethod(postfix));
		return 1;
	}

	private static bool _occludersArmed;
	private static string _lastPostfixError;

	/// <summary>
	/// Drop this raycaster's hits that lie beyond the nearest occluder on its own ray: what the drawn scenery covers
	/// is not hovered or clicked. Only removes results (native ordering and dispatch unchanged); idle until a full-3D
	/// environment armed it, and inert where no occluder collider exists.
	/// </summary>
	private static void PostfixPhysicsRaycast(PhysicsRaycaster __instance, PointerEventData eventData,
		Il2CppSystem.Collections.Generic.List<RaycastResult> resultAppendList)
	{
		if (!_occludersArmed || __instance == null || eventData == null || resultAppendList == null
		    || resultAppendList.Count == 0)
			return;
		try
		{
			var ray = default(Ray);
			var display = 0;
			var clip = 0f;
			if (!__instance.ComputeRayAndDistance(eventData, ref ray, ref display, ref clip))
				return;
			if (!Physics.Raycast(ray.origin, ray.direction, out var hit, clip, 1 << OccluderLayer, QueryTriggerInteraction.Ignore))
				return;
			var occluded = hit.distance;
			var self = __instance.Pointer;
			for (var i = resultAppendList.Count - 1; i >= 0; i--)
			{
				var result = resultAppendList[i];
				var module = result != null ? result.module : null;
				if (module == null || module.Pointer != self)
					continue;
				if (result.distance > occluded)
					resultAppendList.RemoveAt(i);
			}
		}
		catch (Exception ex)
		{
			// Never throw into EventSystem.Update (it would stop all input); report each distinct failure once.
			var message = ex.GetType().Name + ": " + ex.Message;
			if (!string.Equals(message, _lastPostfixError, StringComparison.Ordinal))
			{
				_lastPostfixError = message;
				Plugin.LogSource?.LogError(LogPrefix + "occluder filter failed, building picks are unoccluded: " + ex);
			}
		}
	}

	private static void RequireOccluderLayerHiddenOrThrow(Camera camera)
	{
		var raycaster = camera.GetComponent<PhysicsRaycaster>();
		if (raycaster == null)
			throw new InvalidOperationException(LogPrefix + "camera '" + camera.name + "' has no PhysicsRaycaster; "
				+ "BhBuilding pointer dispatch cannot reach the scene-3D pick.");
		var mask = raycaster.finalEventMask;
		if ((mask & (1 << OccluderLayer)) != 0)
			throw new InvalidOperationException(LogPrefix + "PhysicsRaycaster on '" + camera.name + "' sees layer "
				+ OccluderLayer + " (finalEventMask 0x" + mask.ToString("x") + "): occluders would become pointer targets "
				+ "and freeze the cursor camera (BhCityCamera.IsOverUI).");
	}

	private static void EnsureOccluder(DrawnRenderer drawn)
	{
		var rt = drawn.Renderer.transform;
		var existing = rt.Find(OccluderName);
		var go = existing != null ? existing.gameObject : new GameObject(OccluderName);
		if (existing == null)
		{
			go.transform.SetParent(rt, false);
			go.transform.localPosition = Vector3.zero;
			go.transform.localRotation = Quaternion.identity;
			go.transform.localScale = Vector3.one;
		}
		ConfigureCollider(go, drawn, OccluderLayer);
	}

	private readonly struct DrawnRenderer
	{
		internal DrawnRenderer(MeshRenderer renderer, Mesh mesh)
		{
			Renderer = renderer;
			Mesh = mesh;
		}

		internal MeshRenderer Renderer { get; }
		internal Mesh Mesh { get; }
	}

	private static List<DrawnRenderer> DrawnBodyRenderersOrThrow(Transform body)
	{
		var result = new List<DrawnRenderer>();
		var renderers = body.GetComponentsInChildren<MeshRenderer>(true);
		for (var i = 0; renderers != null && i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (r == null)
				continue;
			var filter = r.GetComponent<MeshFilter>();
			var mesh = filter != null ? filter.sharedMesh : null;
			if (mesh == null)
				throw new InvalidOperationException(LogPrefix + "body renderer '" + r.name + "' has no mesh.");
			if (!mesh.isReadable)
				throw new InvalidOperationException(LogPrefix + "body mesh '" + mesh.name
					+ "' is not Read/Write; a runtime MeshCollider cannot cook it (rebuild the scene bundle).");
			result.Add(new DrawnRenderer(r, mesh));
		}
		if (result.Count == 0)
			throw new InvalidOperationException(LogPrefix + "body '" + body.name + "' has no MeshRenderer to pick.");
		return result;
	}

	private static void ConfigureCollider(GameObject go, DrawnRenderer drawn, int layer)
	{
		go.layer = layer;
		var collider = go.GetComponent<MeshCollider>();
		if (collider == null)
			collider = go.AddComponent<MeshCollider>();
		collider.convex = false;
		if (collider.sharedMesh != drawn.Mesh)
			collider.sharedMesh = drawn.Mesh;
		// A collider only where something is drawn: a disabled body renderer picks nothing.
		collider.enabled = drawn.Renderer.enabled && drawn.Renderer.gameObject.activeInHierarchy;
	}

	/// <summary>
	/// The holder reproduces the scene root's world pose exactly under the BhBuilding. Native BhBuildings may be
	/// mirrored: cityHuman2 'H_build_Tier_3_Level_1' (the Castle Griffin Tower) has lossy scale (-445.6, 445.6, 445.6)
	/// (2026-10-01 LogOutput). The scene root expressed in the building's local space is then a similarity with a
	/// reflection, which a child reproduces exactly with a mirrored local X scale and the matching rotation. The local
	/// pose is solved in the building's space (Transform icalls only, no Matrix4x4 interop) and the result is checked
	/// against the scene root; anything that is not a similarity (shear or non-uniform scale) throws.
	/// </summary>
	private static void PoseHolderOrThrow(Transform holder, Transform building, Transform sceneRoot)
	{
		if (sceneRoot.parent != null)
			throw new InvalidOperationException(LogPrefix + "scene root is parented; its lossy scale is not its local scale.");
		if (holder.parent != building)
			throw new InvalidOperationException(LogPrefix + "pick holder is not a direct child of BhBuilding '" + building.name + "'.");
		var origin = building.InverseTransformPoint(sceneRoot.position);
		RootAxesInBuilding(building, sceneRoot, out var c0, out var c1, out var c2);
		var scale = c0.magnitude;
		if (!IsSimilarity(c0, c1, c2))
			throw new InvalidOperationException(LogPrefix + "BhBuilding '" + building.name + "' (lossy scale "
				+ building.lossyScale + ") maps the scene root to a non-similarity (axes " + c0 + ", " + c1 + ", " + c2
				+ "); a child cannot reproduce the scene root's pose without shear.");
		var mirrored = Vector3.Dot(Vector3.Cross(c0, c1), c2) < 0f;
		holder.localPosition = origin;
		holder.localRotation = Quaternion.LookRotation(c2 / scale, c1 / scale);
		holder.localScale = new Vector3(mirrored ? -scale : scale, scale, scale);
		RequireHolderMatchesRootOrThrow(holder, building, sceneRoot);
	}

	private static void RootAxesInBuilding(Transform building, Transform sceneRoot, out Vector3 c0, out Vector3 c1, out Vector3 c2)
	{
		c0 = building.InverseTransformVector(sceneRoot.TransformVector(Vector3.right));
		c1 = building.InverseTransformVector(sceneRoot.TransformVector(Vector3.up));
		c2 = building.InverseTransformVector(sceneRoot.TransformVector(Vector3.forward));
	}

	private static bool IsSimilarity(Vector3 c0, Vector3 c1, Vector3 c2)
	{
		var scale = c0.magnitude;
		var tol = scale * 1e-3f;
		return !(scale < 1e-9f || Mathf.Abs(c1.magnitude - scale) > tol || Mathf.Abs(c2.magnitude - scale) > tol
		         || Mathf.Abs(Vector3.Dot(c0, c1)) > scale * tol || Mathf.Abs(Vector3.Dot(c0, c2)) > scale * tol
		         || Mathf.Abs(Vector3.Dot(c1, c2)) > scale * tol);
	}

	private static bool MapsRootAsSimilarity(Transform building, Transform sceneRoot)
	{
		RootAxesInBuilding(building, sceneRoot, out var c0, out var c1, out var c2);
		return IsSimilarity(c0, c1, c2);
	}

	/// <summary>
	/// Fallback when the BhBuilding's world transform cannot host a similarity holder (shear or non-uniform scale in
	/// its native chain; Castle 'H_build_Main_Level_1', lossy scale (482.69, 482.69, 482.69), 2026-10-07 LogOutput,
	/// which suspended the whole town presentation: black screen). Each drawn mesh is copied with its vertices mapped
	/// into the building's local space (an affine map, exact for any transform; winding flipped when the map
	/// mirrors), so the hit still bubbles to this BhBuilding. Meshes are rebaked on a reposition that changes the bake
	/// inputs (BakeSignature). A degenerate map leaves that mesh unpickable for this pass instead of failing the town.
	/// </summary>
	private static void BakeIntoBuildingSpace(Transform holder, Transform building, List<DrawnRenderer> renderers, int layer)
	{
		holder.localPosition = Vector3.zero;
		holder.localRotation = Quaternion.identity;
		holder.localScale = Vector3.one;
		var marker = new GameObject(BakedMarkerName);
		marker.transform.SetParent(holder, false);
		marker.SetActive(false);
		if (LoggedBakedBuildings.Add(building.name))
			Plugin.LogSource?.LogWarning(LogPrefix + "BhBuilding '" + building.name + "' (lossy scale " + building.lossyScale
				+ ") cannot host a similarity holder; pick meshes are baked into its local space.");
		for (var i = 0; i < renderers.Count; i++)
		{
			var drawn = renderers[i];
			var source = drawn.Renderer.transform;
			var o = building.InverseTransformPoint(source.TransformPoint(Vector3.zero));
			var ex = building.InverseTransformPoint(source.TransformPoint(Vector3.right)) - o;
			var ey = building.InverseTransformPoint(source.TransformPoint(Vector3.up)) - o;
			var ez = building.InverseTransformPoint(source.TransformPoint(Vector3.forward)) - o;
			var det = Vector3.Dot(Vector3.Cross(ex, ey), ez);
			if (float.IsNaN(det) || float.IsInfinity(det) || Mathf.Abs(det) < 1e-12f)
			{
				Plugin.LogSource?.LogWarning(LogPrefix + "BhBuilding '" + building.name + "' maps body mesh '"
					+ drawn.Mesh.name + "' degenerately; it is not pickable this pass.");
				continue;
			}
			var verts = drawn.Mesh.vertices;
			var baked = new Vector3[verts.Length];
			for (var v = 0; v < baked.Length; v++)
			{
				var p = verts[v];
				baked[v] = o + ex * p.x + ey * p.y + ez * p.z;
			}
			var tris = drawn.Mesh.triangles;
			var indices = new int[tris.Length];
			for (var t = 0; t + 2 < indices.Length; t += 3)
			{
				indices[t] = tris[t];
				// A mirroring map reverses winding; swap to keep the drawn faces front-facing for the raycast.
				indices[t + 1] = det < 0f ? tris[t + 2] : tris[t + 1];
				indices[t + 2] = det < 0f ? tris[t + 1] : tris[t + 2];
			}
			var mesh = new Mesh { name = BakedMeshPrefix + drawn.Mesh.name };
			if (baked.Length > 65535)
				mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
			mesh.vertices = baked;
			mesh.triangles = indices;
			mesh.RecalculateBounds();
			var node = new GameObject(NodePrefix + drawn.Renderer.name);
			node.layer = layer;
			node.transform.SetParent(holder, false);
			ConfigureCollider(node, new DrawnRenderer(drawn.Renderer, mesh), layer);
		}
	}

	private static void RequireHolderMatchesRootOrThrow(Transform holder, Transform building, Transform sceneRoot)
	{
		var axes = new[] { Vector3.zero, Vector3.right, Vector3.up, Vector3.forward };
		var reach = Mathf.Max(1f, sceneRoot.TransformVector(Vector3.right).magnitude);
		for (var i = 0; i < axes.Length; i++)
		{
			var want = sceneRoot.TransformPoint(axes[i]);
			var got = holder.TransformPoint(axes[i]);
			var limit = 1e-3f * Mathf.Max(reach, want.magnitude);
			if ((got - want).magnitude > limit)
				throw new InvalidOperationException(LogPrefix + "pick holder under BhBuilding '" + building.name
					+ "' (lossy scale " + building.lossyScale + ") misses the scene root pose at local " + axes[i]
					+ ": " + got + " vs " + want + ".");
		}
	}

	private static List<Transform> ChainBelowOrThrow(Transform leaf, Transform sceneRoot)
	{
		var chain = new List<Transform>();
		var cursor = leaf;
		while (cursor != null && cursor != sceneRoot)
		{
			chain.Add(cursor);
			cursor = cursor.parent;
		}
		if (cursor != sceneRoot)
			throw new InvalidOperationException(LogPrefix + "renderer '" + leaf.name + "' is not under the scene root.");
		chain.Reverse();
		return chain;
	}

	/// <summary>Bake inputs per baked holder (instance id): see <see cref="BakeSignature"/>.</summary>
	private static readonly Dictionary<int, float[]> BakedSignatures = new();

	/// <summary>
	/// What a baked holder depends on: the scene root's origin and axes in the BhBuilding's space (the renderer chain
	/// below the root is static) and each body renderer's drawn state (ConfigureCollider enables only drawn meshes).
	/// Transform icalls only, no Matrix4x4 interop.
	/// </summary>
	private static float[] BakeSignature(Transform building, Transform sceneRoot, Transform body)
	{
		var origin = building.InverseTransformPoint(sceneRoot.position);
		RootAxesInBuilding(building, sceneRoot, out var c0, out var c1, out var c2);
		var renderers = body.GetComponentsInChildren<MeshRenderer>(true);
		var count = renderers != null ? renderers.Length : 0;
		var signature = new float[13 + count];
		var axes = new[] { origin, c0, c1, c2 };
		for (var a = 0; a < axes.Length; a++)
		{
			signature[a * 3] = axes[a].x;
			signature[a * 3 + 1] = axes[a].y;
			signature[a * 3 + 2] = axes[a].z;
		}
		signature[12] = count;
		for (var i = 0; i < count; i++)
		{
			var r = renderers[i];
			signature[13 + i] = r != null && r.enabled && r.gameObject.activeInHierarchy ? 1f : 0f;
		}
		return signature;
	}

	private static bool SameSignature(float[] a, float[] b)
	{
		if (a == null || b == null || a.Length != b.Length)
			return false;
		var reach = 1f;
		for (var i = 0; i < 12; i++)
			reach = Mathf.Max(reach, Mathf.Abs(a[i]));
		var tol = 1e-5f * reach;
		for (var i = 0; i < a.Length; i++)
			if (Mathf.Abs(a[i] - b[i]) > (i < 12 ? tol : 0f))
				return false;
		return true;
	}

	private static void DestroyStaleHolder(Transform building)
	{
		for (var i = building.childCount - 1; i >= 0; i--)
		{
			var child = building.GetChild(i);
			if (child == null || !string.Equals(child.name, HolderName, StringComparison.Ordinal))
				continue;
			BakedSignatures.Remove(child.GetInstanceID());
			// Destroy is deferred to the end of the frame: rename first so a same-frame Find never returns it.
			child.name = HolderName + "~stale";
			var colliders = child.GetComponentsInChildren<MeshCollider>(true);
			for (var c = 0; colliders != null && c < colliders.Length; c++)
			{
				var mesh = colliders[c] != null ? colliders[c].sharedMesh : null;
				if (mesh != null && mesh.name != null && mesh.name.StartsWith(BakedMeshPrefix, StringComparison.Ordinal))
					UnityEngine.Object.Destroy(mesh);
			}
			UnityEngine.Object.Destroy(child.gameObject);
		}
	}
}
