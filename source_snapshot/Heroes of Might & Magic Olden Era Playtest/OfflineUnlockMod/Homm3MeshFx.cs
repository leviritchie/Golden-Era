using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Shared world-space VFX attach for Meshy map-building meshes and skinned battle units.
/// Native prefs load through Il2Cpp runtime invoke from LateUpdate only — never
/// MethodInfo.Invoke ResManager.Get (Harmony DMD AccessViolation).
/// Never rewrite Hex/Lit albedo.
/// Two vanilla-style layer types (tools/homm3_vfx/vanilla_style_fx.py, docs/olden_era_vanilla_vfx_style.md 8.3):
///   * vanillaStyle rows clone one bare Shuriken subtree of a native prefab (real magic/VfxUber materials)
///     under a bone, keep only the listed systems, and start/stop them from the animator window;
///   * battle_emission rows switch on the Hex/Lit emission map of the owned skinned body material;
///   * battle_body_displacement rows switch on the Hex/Lit FLAG vertex displacement of that material, masked by the
///     mesh's baked COLOR_0.r (tools/homm3_vfx/displacement_mask_bake.py); refused when the mesh has no colour stream;
///   * battle_body_overlay rows append one vanilla material (a native prefab renderer's) to the owned body
///     SkinnedMeshRenderer, always or inside an animator window (the BhBattleTimelineHelper.AppendMaterial idiom).
/// Particle settings the stripped live interop cannot reach (scalingMode, start colour) arrive precomputed
/// in the catalog (localScaleNodes, recolorNodes).
/// Proof: source/static until in-map / in-combat look is exercised.
/// </summary>
internal static class Homm3MeshFx
{
	internal const string CatalogSchema = "homm3_mesh_fx_catalog.v1";
	internal const string RelativeCatalogPath = "homm3_mesh_fx/catalog.json";
	internal const string ChildNamePrefix = "HOMM3_mesh_fx_";
	internal const string LaneMapBuilding = "map_building";
	internal const string LaneBattleSkinned = "battle_skinned";
	internal const string LaneBattleEmission = "battle_emission";
	internal const string EmissionKeyword = "HEX_EMISSION_MAP_ENABLED";
	internal const string LaneBattleBodyDisplacement = "battle_body_displacement";
	internal const string LaneBattleBodyOverlay = "battle_body_overlay";
	internal const string FlagDisplacementKeyword = "HEX_VERTEX_DISPLACEMENT_FLAG";
	internal const string TreeDisplacementKeyword = "HEX_VERTEX_DISPLACEMENT_TREE";
	// Hex/Lit _VertexDisplacementType 1 = FLAG: posWS += _FlagPower * sin(dot(posWS, _FlagDirection) + t * _FlagSpeed) * COLOR.r.
	internal const float FlagDisplacementType = 1f;
	internal const string OrientBone = "bone";
	internal const string OrientEmitUp = "emitUp";
	internal const string OrientBody = "body";
	internal const string FollowBone = "bone";
	// follow=release: at each window start the clone is placed on its socket, played, then reparented to the host
	// root (world pose kept), so the burst stays where the bone released it instead of riding the arm's
	// follow-through onto the body. The live MainModule interop has no simulationSpace setter; this is the native
	// SpawnAttackEffect spawnAsChild=false contract (parent to the battle root at the spawn point).
	internal const string FollowRelease = "release";

	internal enum TriggerMode
	{
		Always = 0,
		AnimatorState = 1,
		AnimatorWindow = 2
	}

	internal enum SocketKind
	{
		MeshBounds = 0,
		Bones = 1
	}

	internal sealed class CatalogRow
	{
		internal string Id;
		internal string Lane;
		internal string PrefabKeyContains;
		internal string[] UnitSids;
		internal string NativeResPath;
		internal string OwnedPrefabKey;
		internal bool MapObjectParticles;
		internal SocketKind Socket;
		internal string[] BoneNames;
		internal Vector3 NormalizedOffset;
		internal Vector3 LocalScale;
		internal TriggerMode Trigger;
		internal string[] AnimatorStates;
		internal float WindowStart;
		internal float WindowEnd;
		internal bool KeepExistingGlow;
		internal VanillaStyleSpec Vanilla;
		internal EmissionSpec Emission;
		internal DisplacementSpec Displacement;
		internal OverlaySpec Overlay;
	}

	internal sealed class DisplacementSpec
	{
		internal Vector4 Direction;
		internal Vector4 Power;
		internal float Speed;
	}

	internal sealed class OverlaySpec
	{
		internal string RendererPath;
		internal int MaterialIndex;
		// Optional per-unit tint: absolute (HDR) colours written to the private material copy, e.g. the
		// magic/Fresnel rim's _Color/_EdgeColor. Every property must exist on the native material and read back.
		internal string[] ColorProperties = Array.Empty<string>();
		internal Color[] ColorValues = Array.Empty<Color>();
	}

	internal sealed class VanillaStyleSpec
	{
		internal string ChildPath;
		internal string[] KeepNodes;
		internal float WorldScale;
		internal float RateMul;
		internal bool Loop;
		internal bool ZeroChildPositions;
		internal string Orient;
		internal float BodyYawDeg;
		// orient bone / emitUp: the clone root's rotation in the bone frame (vanilla_style_fx alignToReach).
		internal Quaternion BoneLocalRot = Quaternion.identity;
		// The clone root's position in the bone frame (vanilla_style_fx boneAnchor: a rest-pose mesh point, e.g. a
		// muzzle in front of a Head joint buried in the skull). Zero = the joint itself.
		internal Vector3 BoneLocalPos = Vector3.zero;
		internal string AnchorNode;
		internal string[] LocalScaleNodes;
		internal RecolorSpec[] RecolorNodes;
		internal bool FollowRelease;
	}

	internal sealed class RecolorSpec
	{
		internal string Node;
		internal float[][] GradientColor;
		internal float[][] GradientAlpha;
		internal Vector3 MaterialColorMul;
	}

	internal sealed class EmissionSpec
	{
		internal string Texture;
		internal string TextureSha256;
		internal Color Color;
		internal float MinPower;
		internal float BlinkPower;
		internal float BlinkSpeed;
	}

	private sealed class Slot
	{
		internal CatalogRow Row;
		internal GameObject Instance;
		internal int LoadAttempts;
		internal bool LoadFailed;
		internal bool InWindow;
		internal bool HelperPrepared;
		// Animator trigger: the catalog's stock clip slots resolved to the clip names the host's controller plays.
		internal int ClipsForController;
		internal HashSet<string> ClipNames;
		// vanillaStyle runtime state
		internal Transform Socket;
		internal Transform Orientation;
		internal Transform Anchor;
		internal List<ParticleSystem> Kept;
		internal List<Transform> KeptTransforms;
		internal List<ParticleSystem> Others;
		internal Transform[] LocalScaleNodes;
		internal Vector3[] LocalScaleOriginals;
		internal float AppliedSocketScale;
		internal float AppliedRefScale;
		internal bool WasActive;
		// follow=release: the clone is parented to the host root until the next window start.
		internal bool Detached;
		internal List<Material> OwnedMaterials;
		// battle_body_overlay runtime state
		internal Material OverlayMaterial;
		internal bool OverlayOn;
		internal int OverlayVerifyCountdown;
	}

	private static bool _catalogLoadAttempted;
	private static bool _typeRegistered;
	private static int _attachLogRemaining = 12;
	private static int _catalogMissLogRemaining = 4;
	private static readonly HashSet<string> UnresolvedTriggerLogged = new(StringComparer.Ordinal);
	private static List<CatalogRow> _rows;
	private static readonly Dictionary<int, Slot[]> SlotsByHostId = new();
	private static readonly Dictionary<string, GameObject> OwnedPrefabsByKey =
		new(StringComparer.OrdinalIgnoreCase);
	private static readonly BindingFlags InvokeFlags =
		BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
	private static readonly Dictionary<string, Texture2D> EmissionTextures = new(StringComparer.Ordinal);
	private static readonly HashSet<string> EmissionFailures = new(StringComparer.Ordinal);
	private static readonly HashSet<string> EmissionAppliedLog = new(StringComparer.Ordinal);
	private static bool _emitUpCameraMissingLogged;

	internal static bool IsFxDescendant(Transform transform)
	{
		var current = transform;
		while (current)
		{
			var name = current.name ?? string.Empty;
			if (name.StartsWith(ChildNamePrefix, StringComparison.Ordinal))
				return true;
			current = current.parent;
		}
		return false;
	}

	internal static void TryAttachForMapBuilding(
		GameObject meshRoot,
		Homm3MapBuildingMeshBundle.CatalogEntry mapEntry,
		ManualLogSource log)
	{
		if (!meshRoot || mapEntry == null)
			return;
		var prefabKey = mapEntry.PrefabKey ?? string.Empty;
		if (string.IsNullOrWhiteSpace(prefabKey))
			return;
		EnsureCatalog(log);
		if (_rows == null || _rows.Count == 0)
			return;
		var matched = new List<CatalogRow>();
		for (var i = 0; i < _rows.Count; i++)
		{
			var row = _rows[i];
			if (row == null || !string.Equals(row.Lane, LaneMapBuilding, StringComparison.Ordinal))
				continue;
			if (string.IsNullOrEmpty(row.PrefabKeyContains))
				continue;
			if (prefabKey.IndexOf(row.PrefabKeyContains, StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			matched.Add(row);
		}
		if (matched.Count == 0)
			return;
		AttachRows(meshRoot, matched, log, "map prefab='" + prefabKey + "'");
	}

	internal static void TryAttachForSkinnedBattle(
		GameObject battleRoot,
		Homm3ImportVisuals.Entry entry,
		ManualLogSource log)
	{
		if (!battleRoot || !Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(battleRoot))
			return;
		EnsureCatalog(log);
		if (_rows == null || _rows.Count == 0)
			return;
		var sids = CollectSkinnedMatchSids(entry);
		var matched = new List<CatalogRow>();
		for (var i = 0; i < _rows.Count; i++)
		{
			var row = _rows[i];
			if (row == null
			    || (!string.Equals(row.Lane, LaneBattleSkinned, StringComparison.Ordinal)
			        && !string.Equals(row.Lane, LaneBattleBodyOverlay, StringComparison.Ordinal)))
				continue;
			if (row.UnitSids == null || row.UnitSids.Length == 0)
				continue;
			if (!SidListIntersects(row.UnitSids, sids))
				continue;
			matched.Add(row);
		}
		if (matched.Count == 0)
			return;
		AttachRows(battleRoot, matched, log, "skinned sids='" + string.Join(",", sids) + "'");
	}

	/// <summary>
	/// Idle presentation (adventure-map unit, hire/town preview): the battle_skinned vanilla-style layers that
	/// belong to the idle (trigger always, or animator windows on idle states only) also play here; attack /
	/// hit windows stay battle-only. User direction 2026-09-26: an idle with effects keeps them in previews.
	/// </summary>
	internal static void TryAttachForSkinnedPresentation(
		GameObject visual,
		Homm3ImportVisuals.Entry entry,
		string lane,
		ManualLogSource log)
	{
		if (!visual || entry == null)
			return;
		EnsureCatalog(log);
		if (_rows == null || _rows.Count == 0)
			return;
		var sids = CollectSkinnedMatchSids(entry);
		var matched = new List<CatalogRow>();
		for (var i = 0; i < _rows.Count; i++)
		{
			var row = _rows[i];
			if (row?.Vanilla == null || !string.Equals(row.Lane, LaneBattleSkinned, StringComparison.Ordinal))
				continue;
			if (row.UnitSids == null || !SidListIntersects(row.UnitSids, sids) || !IsIdleTrigger(row))
				continue;
			matched.Add(row);
		}
		if (matched.Count == 0)
			return;
		AttachRows(visual, matched, log, lane + " skinned sids='" + string.Join(",", sids) + "'");
	}

	private static bool IsIdleTrigger(CatalogRow row)
	{
		if (row.Trigger == TriggerMode.Always)
			return true;
		if (row.Trigger != TriggerMode.AnimatorWindow || row.AnimatorStates == null || row.AnimatorStates.Length == 0)
			return false;
		for (var i = 0; i < row.AnimatorStates.Length; i++)
		{
			if (row.AnimatorStates[i] == null || row.AnimatorStates[i].IndexOf("Idle", StringComparison.Ordinal) < 0)
				return false;
		}
		return true;
	}

	private static void AttachRows(
		GameObject root,
		List<CatalogRow> rows,
		ManualLogSource log,
		string context)
	{
		EnsureTypeRegistered(log);
		var host = root.GetComponent<Homm3MeshFxHost>();
		if (!host)
			host = root.AddComponent<Homm3MeshFxHost>();
		if (!host)
		{
			log?.LogError("Homm3MeshFx: host AddComponent failed for " + context + ".");
			return;
		}

		var slots = new Slot[rows.Count];
		for (var i = 0; i < rows.Count; i++)
			slots[i] = new Slot { Row = rows[i] };
		SlotsByHostId[host.GetInstanceID()] = slots;
		for (var i = 0; i < slots.Length; i++)
			EnsureInstance(host, slots[i], log, allowIl2CppNativeLoad: false);

		var keepGlow = false;
		var mapLane = false;
		for (var i = 0; i < rows.Count; i++)
		{
			if (rows[i] == null)
				continue;
			if (rows[i].KeepExistingGlow)
				keepGlow = true;
			if (string.Equals(rows[i].Lane, LaneMapBuilding, StringComparison.Ordinal))
				mapLane = true;
		}
		if (mapLane && !keepGlow)
		{
			DestroyNamedDescendant(root.transform, Homm3MapBuildingMeshProjectedFx.OverlayObjectName);
			DestroyNamedDescendant(root.transform, Homm3MapBuildingMeshProjectedFx.MaelstromDiscObjectName);
		}

		if (_attachLogRemaining > 0)
		{
			_attachLogRemaining--;
			log?.LogInfo(
				"Homm3MeshFx: attached rows="
				+ rows.Count
				+ " "
				+ context
				+ " proof=source/static");
		}
	}

	internal static void Unregister(Homm3MeshFxHost host)
	{
		if (!host)
			return;
		var id = host.GetInstanceID();
		if (SlotsByHostId.TryGetValue(id, out var slots) && slots != null)
		{
			for (var i = 0; i < slots.Length; i++)
			{
				var owned = slots[i]?.OwnedMaterials;
				if (owned == null)
					continue;
				for (var j = 0; j < owned.Count; j++)
				{
					if (owned[j])
						UnityEngine.Object.Destroy(owned[j]);
				}
				owned.Clear();
			}
		}
		SlotsByHostId.Remove(id);
	}

	internal static void Tick(Homm3MeshFxHost host)
	{
		if (!host || !SlotsByHostId.TryGetValue(host.GetInstanceID(), out var slots) || slots == null)
			return;
		Animator animator = null;
		var needAnimator = false;
		for (var i = 0; i < slots.Length; i++)
		{
			var slot = slots[i];
			if (slot?.Row != null && slot.Row.Trigger != TriggerMode.Always)
			{
				needAnimator = true;
				break;
			}
		}
		if (needAnimator)
		{
			try
			{
				animator = host.GetComponentInChildren<Animator>(true);
			}
			catch
			{
				animator = null;
			}
		}

		for (var i = 0; i < slots.Length; i++)
			TickSlot(host, slots[i], animator);
	}

	private static void TickSlot(Homm3MeshFxHost host, Slot slot, Animator animator)
	{
		if (slot == null || slot.Row == null || !host)
			return;
		if (slot.Row.Overlay != null)
		{
			TickOverlaySlot(host, slot, animator);
			return;
		}
		if (slot.Row.Vanilla != null)
		{
			TickVanillaSlot(host, slot, animator);
			return;
		}
		var row = slot.Row;
		var wantActive = row.Trigger == TriggerMode.Always;
		var risingEdge = false;
		if (row.Trigger == TriggerMode.AnimatorState)
			wantActive = AnimatorMatches(animator, slot, out _);
		else if (row.Trigger == TriggerMode.AnimatorWindow)
		{
			var inWindow = AnimatorMatches(animator, slot, out var normalized)
			               && normalized >= row.WindowStart
			               && normalized <= row.WindowEnd;
			risingEdge = inWindow && !slot.InWindow;
			slot.InWindow = inWindow;
			wantActive = inWindow;
		}

		if (!wantActive)
		{
			if (!slot.LoadFailed)
				EnsureInstance(host, slot, Plugin.LogSource, allowIl2CppNativeLoad: true);
			if (slot.Instance)
				slot.Instance.SetActive(false);
			return;
		}

		if (!EnsureInstance(host, slot, Plugin.LogSource, allowIl2CppNativeLoad: true))
			return;
		if (!slot.Instance)
			return;
		if (risingEdge)
		{
			slot.Instance.SetActive(false);
			slot.Instance.SetActive(true);
			TryStartNativeHelper(slot.Instance, slot, forceRestart: true);
		}
		else if (!slot.Instance.activeSelf)
		{
			slot.Instance.SetActive(true);
			TryStartNativeHelper(slot.Instance, slot, forceRestart: false);
		}
	}

	private static bool EnsureInstance(
		Homm3MeshFxHost host,
		Slot slot,
		ManualLogSource log,
		bool allowIl2CppNativeLoad)
	{
		if (slot.Instance)
			return true;
		if (slot.LoadFailed)
			return false;
		var row = slot.Row;
		if (row == null)
			return false;
		// Overlay rows own no GameObject: their material loads in TickOverlaySlot (LateUpdate only).
		if (row.Overlay != null)
			return false;
		if (row.MapObjectParticles)
			return TryInstantiateMapObjectParticles(host, slot, log);
		if (row.Vanilla != null)
			return EnsureVanillaInstance(host, slot, log, allowIl2CppNativeLoad);
		if (!TryResolveTemplate(row, log, out var template) || !template)
		{
			if (!allowIl2CppNativeLoad || string.IsNullOrWhiteSpace(row.NativeResPath))
				return false;
			slot.LoadAttempts++;
			if (slot.LoadAttempts > 90)
			{
				slot.LoadFailed = true;
				log?.LogError(
					"Homm3MeshFx: missing source for id='"
					+ (row.Id ?? "?")
					+ "' nativeResPath='"
					+ (row.NativeResPath ?? "")
					+ "' after Il2Cpp LateUpdate loads. MethodInfo.Invoke Get is forbidden.");
				return false;
			}
			if (!Homm3ImportVisuals.TryLoadNativeResManagerGameObjectIl2Cpp(row.NativeResPath.Trim(), log, out template)
			    || !template)
				return false;
		}

		if (!TryResolveSocket(host.transform, row, log, out var socketParent, out var localPosition))
		{
			slot.LoadFailed = true;
			return false;
		}

		DestroyNamedDescendant(host.transform, ChildNamePrefix + row.Id);
		GameObject instance;
		try
		{
			instance = UnityEngine.Object.Instantiate(template);
		}
		catch (Exception ex)
		{
			slot.LoadFailed = true;
			log?.LogError("Homm3MeshFx: Instantiate failed id='" + row.Id + "': " + ex.Message);
			return false;
		}
		if (!instance)
		{
			slot.LoadFailed = true;
			log?.LogError("Homm3MeshFx: Instantiate returned null id='" + row.Id + "'.");
			return false;
		}

		instance.name = ChildNamePrefix + row.Id;
		instance.transform.SetParent(socketParent, false);
		instance.transform.localPosition = localPosition;
		instance.transform.localRotation = Quaternion.identity;
		instance.transform.localScale = row.LocalScale;
		SetLayerRecursive(instance, host.gameObject.layer);
		var startActive = row.Trigger == TriggerMode.Always;
		instance.SetActive(startActive);
		TryPrepareNativeHelper(instance, socketParent);
		if (startActive)
			TryStartNativeHelper(instance, slot, forceRestart: false);
		slot.Instance = instance;
		slot.HelperPrepared = true;
		if (_attachLogRemaining > 0)
		{
			_attachLogRemaining--;
			log?.LogInfo(
				"Homm3MeshFx: instantiated id='"
				+ row.Id
				+ "' source='"
				+ (row.MapObjectParticles
					? "mapObjectParticles"
					: (string.IsNullOrEmpty(row.NativeResPath) ? row.OwnedPrefabKey : row.NativeResPath))
				+ "' parent='"
				+ (socketParent.name ?? "?")
				+ "'.");
		}
		return true;
	}

	private static bool TryInstantiateMapObjectParticles(Homm3MeshFxHost host, Slot slot, ManualLogSource log)
	{
		var row = slot.Row;
		if (!host || row == null)
			return false;
		if (!TryResolveSocket(host.transform, row, log, out var socketParent, out var localPosition))
		{
			slot.LoadFailed = true;
			return false;
		}

		var donors = CollectOutermostDonorParticleRoots(host.transform);
		if (donors.Count == 0)
		{
			slot.LoadFailed = true;
			log?.LogError(
				"Homm3MeshFx: id='"
				+ row.Id
				+ "' mapObjectParticles found no ParticleSystem on the map object (native fire was not present to clone). KeepExistingGlow stays. Plugin ResManager.Get is forbidden.");
			return false;
		}

		DestroyNamedDescendant(host.transform, ChildNamePrefix + row.Id);
		var wrapper = new GameObject(ChildNamePrefix + row.Id);
		wrapper.transform.SetParent(socketParent, false);
		wrapper.transform.localPosition = localPosition;
		wrapper.transform.localRotation = Quaternion.identity;
		wrapper.transform.localScale = row.LocalScale;
		SetLayerRecursive(wrapper, host.gameObject.layer);

		var cloned = 0;
		for (var i = 0; i < donors.Count; i++)
		{
			var donor = donors[i];
			if (!donor)
				continue;
			GameObject clone;
			try
			{
				clone = UnityEngine.Object.Instantiate(donor, wrapper.transform, false);
			}
			catch (Exception ex)
			{
				slot.LoadFailed = true;
				UnityEngine.Object.Destroy(wrapper);
				log?.LogError("Homm3MeshFx: ParticleSystem clone failed id='" + row.Id + "': " + ex.Message);
				return false;
			}
			if (!clone)
				continue;
			clone.name = "particle_" + cloned.ToString(CultureInfo.InvariantCulture);
			clone.transform.localPosition = Vector3.zero;
			clone.transform.localRotation = Quaternion.identity;
			clone.SetActive(true);
			PrepareClonedMapParticles(clone);
			cloned++;
		}

		if (cloned == 0)
		{
			slot.LoadFailed = true;
			UnityEngine.Object.Destroy(wrapper);
			log?.LogError("Homm3MeshFx: id='" + row.Id + "' mapObjectParticles cloned zero ParticleSystem roots.");
			return false;
		}

		var startActive = row.Trigger == TriggerMode.Always;
		wrapper.SetActive(startActive);
		slot.Instance = wrapper;
		slot.HelperPrepared = true;
		if (_attachLogRemaining > 0)
		{
			_attachLogRemaining--;
			log?.LogInfo(
				"Homm3MeshFx: instantiated id='"
				+ row.Id
				+ "' source='mapObjectParticles' clones="
				+ cloned
				+ " parent='"
				+ (socketParent.name ?? "?")
				+ "'.");
		}
		return true;
	}

	private static List<GameObject> CollectOutermostDonorParticleRoots(Transform meshRoot)
	{
		var results = new List<GameObject>();
		if (!meshRoot)
			return results;
		var scanRoot = meshRoot.parent ? meshRoot.parent : meshRoot;
		var components = scanRoot.GetComponentsInChildren<Component>(true);
		if (components == null)
			return results;
		var particleTransforms = new List<Transform>();
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !IsParticleSystemComponent(component))
				continue;
			var t = component.transform;
			if (!t)
				continue;
			if (t == meshRoot || t.IsChildOf(meshRoot))
				continue;
			if (IsFxDescendant(t) || Homm3MapBuildingMeshProjectedFx.IsFxChildObject(t))
				continue;
			particleTransforms.Add(t);
		}

		for (var i = 0; i < particleTransforms.Count; i++)
		{
			var candidate = particleTransforms[i];
			var nested = false;
			for (var j = 0; j < particleTransforms.Count; j++)
			{
				if (i == j)
					continue;
				var other = particleTransforms[j];
				if (other && candidate.IsChildOf(other))
				{
					nested = true;
					break;
				}
			}
			if (nested || !candidate.gameObject)
				continue;
			if (results.Contains(candidate.gameObject))
				continue;
			results.Add(candidate.gameObject);
		}
		return results;
	}

	private static void PrepareClonedMapParticles(GameObject clone)
	{
		if (!clone)
			return;
		var renderers = clone.GetComponentsInChildren<Renderer>(true);
		if (renderers != null)
		{
			for (var i = 0; i < renderers.Length; i++)
			{
				var renderer = renderers[i];
				if (!renderer)
					continue;
				var typeName = renderer.GetType().Name ?? string.Empty;
				renderer.enabled = typeName.IndexOf("ParticleSystemRenderer", StringComparison.Ordinal) >= 0;
			}
		}

		var components = clone.GetComponentsInChildren<Component>(true);
		if (components == null)
			return;
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !IsParticleSystemComponent(component))
				continue;
			try
			{
				var play = component.GetType().GetMethod("Play", Type.EmptyTypes);
				play?.Invoke(component, null);
			}
			catch
			{
			}
		}
	}

	private static bool IsParticleSystemComponent(Component component)
	{
		if (!component)
			return false;
		var type = component.GetType();
		return string.Equals(type.FullName, "UnityEngine.ParticleSystem", StringComparison.Ordinal)
		       || string.Equals(type.Name, "ParticleSystem", StringComparison.Ordinal);
	}

	private static bool TryResolveTemplate(
		CatalogRow row,
		ManualLogSource log,
		out GameObject template)
	{
		template = null;
		if (row == null)
			return false;
		if (row.MapObjectParticles)
			return false;
		var hasNative = !string.IsNullOrWhiteSpace(row.NativeResPath);
		var hasOwned = !string.IsNullOrWhiteSpace(row.OwnedPrefabKey);
		if (hasNative == hasOwned)
			return false;
		if (!hasNative)
			return TryLoadOwnedPrefab(row.OwnedPrefabKey.Trim(), log, out template) && template;
		var path = row.NativeResPath.Trim();
		if (string.Equals(row.Lane, LaneMapBuilding, StringComparison.Ordinal) && !IsMapFxResPath(path))
			return false;
		return Homm3ImportVisuals.TryGetCachedNativeResManagerGameObject(path, out template) && template;
	}

	private static bool IsMapFxResPath(string path)
	{
		if (string.IsNullOrWhiteSpace(path))
			return false;
		if (path.IndexOf("Prefabs_vfx", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		// Resources key of a Core map-object prefab (Core DB names it fx/…, interactive/…, resource/…; the map
		// loader roots it at objects/). Its effect systems are magic/VfxUber map systems; combat spell FX are not.
		return path.StartsWith("objects/", StringComparison.Ordinal);
	}

	private static bool TryLoadOwnedPrefab(string prefabKey, ManualLogSource log, out GameObject prefab)
	{
		prefab = null;
		if (OwnedPrefabsByKey.TryGetValue(prefabKey, out var cached) && cached)
		{
			prefab = cached;
			return true;
		}
		log?.LogError(
			"Homm3MeshFx: ownedPrefabKey='"
			+ prefabKey
			+ "' is catalogued but no owned FX bundle is staged.");
		return false;
	}

	private static bool TryResolveSocket(
		Transform root,
		CatalogRow row,
		ManualLogSource log,
		out Transform parent,
		out Vector3 localPosition)
	{
		parent = root;
		localPosition = Vector3.zero;
		if (!root || row == null)
			return false;
		if (row.Socket == SocketKind.Bones)
		{
			if (row.BoneNames == null || row.BoneNames.Length == 0)
			{
				log?.LogError("Homm3MeshFx: id='" + row.Id + "' bones socket has empty names list.");
				return false;
			}
			for (var i = 0; i < row.BoneNames.Length; i++)
			{
				var bone = FindNamedTransform(root, row.BoneNames[i]);
				if (!bone)
					continue;
				parent = bone;
				localPosition = Vector3.zero;
				return true;
			}
			log?.LogError(
				"Homm3MeshFx: id='"
				+ row.Id
				+ "' none of catalog sockets exist: "
				+ string.Join(",", row.BoneNames)
				+ ".");
			return false;
		}

		var filter = FindPrimaryMeshFilter(root.gameObject);
		if (!filter || !filter.sharedMesh)
		{
			log?.LogError("Homm3MeshFx: id='" + row.Id + "' meshBounds socket has no MeshFilter.");
			return false;
		}
		parent = filter.transform;
		var bounds = filter.sharedMesh.bounds;
		var offset = new Vector3(
			bounds.size.x * row.NormalizedOffset.x,
			bounds.size.y * row.NormalizedOffset.y,
			bounds.size.z * row.NormalizedOffset.z);
		localPosition = bounds.center + offset;
		return true;
	}

	private static MeshFilter FindPrimaryMeshFilter(GameObject root)
	{
		var filters = root.GetComponentsInChildren<MeshFilter>(true);
		if (filters == null)
			return null;
		for (var i = 0; i < filters.Length; i++)
		{
			var filter = filters[i];
			if (!filter || !filter.sharedMesh)
				continue;
			if (Homm3MapBuildingMeshProjectedFx.IsFxChildObject(filter.transform))
				continue;
			if (IsFxDescendant(filter.transform))
				continue;
			return filter;
		}
		return null;
	}

	private static Transform FindNamedTransform(Transform root, string name)
	{
		if (!root || string.IsNullOrEmpty(name))
			return null;
		if (string.Equals(root.name, name, StringComparison.Ordinal))
			return root;
		var children = root.GetComponentsInChildren<Transform>(true);
		if (children == null)
			return null;
		for (var i = 0; i < children.Length; i++)
		{
			var child = children[i];
			if (child && string.Equals(child.name, name, StringComparison.Ordinal))
				return child;
		}
		return null;
	}

	/// <summary>
	/// A trigger's <c>states</c> are stock clip slots ("14.Attack", "22.Idle", ...), not Animator state names:
	/// the stock battle controller's states are "Attack Tree 2", "idle", "moveAttack", so
	/// <see cref="AnimatorStateInfo.IsName"/> on a slot name never matched and every window row stayed dark.
	/// Each slot is resolved through the host's own controller (the override clip when it is an
	/// AnimatorOverrideController, else the stock clip itself) and the row fires while the dominant playing clip
	/// is one of them; the window is the state's normalized time.
	/// </summary>
	private static bool AnimatorMatches(Animator animator, Slot slot, out float normalizedTime)
	{
		normalizedTime = 0f;
		var row = slot.Row;
		if (!animator || row.AnimatorStates == null || row.AnimatorStates.Length == 0)
			return false;
		var clipNames = ResolveTriggerClips(animator, slot);
		if (clipNames == null || clipNames.Count == 0)
			return false;
		AnimatorStateInfo stateInfo;
		Il2CppStructArray<AnimatorClipInfo> infos;
		try
		{
			// During a cross-fade the state being entered is the one whose window matters: the stock
			// controller reaches the attack through a transition, and gating on "not in transition"
			// dropped the first part of every attack window.
			if (animator.IsInTransition(0))
			{
				stateInfo = animator.GetNextAnimatorStateInfo(0);
				infos = animator.GetNextAnimatorClipInfo(0);
			}
			else
			{
				stateInfo = animator.GetCurrentAnimatorStateInfo(0);
				infos = animator.GetCurrentAnimatorClipInfo(0);
			}
		}
		catch
		{
			return false;
		}
		if (infos == null || infos.Length == 0)
			return false;
		AnimationClip dominant = null;
		var bestWeight = 0f;
		for (var i = 0; i < infos.Length; i++)
		{
			var info = infos[i];
			var clip = info.clip;
			if (clip && info.weight > bestWeight)
			{
				bestWeight = info.weight;
				dominant = clip;
			}
		}
		if (!dominant || !clipNames.Contains(dominant.name))
			return false;
		var nt = stateInfo.normalizedTime;
		if (stateInfo.loop)
			nt -= Mathf.Floor(nt);
		normalizedTime = nt;
		return true;
	}

	/// <summary>
	/// Resolves (once per host controller) the clip names a trigger row's stock slots play. Fail-closed: a row
	/// none of whose slots resolves to a clip of the controller logs an error once per row and controller and
	/// never fires, instead of staying silently dark.
	/// </summary>
	private static HashSet<string> ResolveTriggerClips(Animator animator, Slot slot)
	{
		RuntimeAnimatorController rac;
		try
		{
			rac = animator.runtimeAnimatorController;
		}
		catch
		{
			rac = null;
		}
		if (!rac)
			return null;
		var racId = rac.GetInstanceID();
		if (slot.ClipNames != null && slot.ClipsForController == racId)
			return slot.ClipNames;
		var row = slot.Row;
		var controllerClips = new HashSet<string>(StringComparer.Ordinal);
		AnimatorOverrideController aoc = null;
		string failure = null;
		try
		{
			var clips = rac.animationClips;
			if (clips != null)
			{
				for (var i = 0; i < clips.Length; i++)
				{
					if (clips[i])
						controllerClips.Add(clips[i].name);
				}
			}
			aoc = rac.TryCast<AnimatorOverrideController>();
		}
		catch (Exception ex)
		{
			failure = "controller clip read threw " + ex.GetType().Name + ": " + ex.Message;
		}
		var resolved = new HashSet<string>(StringComparer.Ordinal);
		var pairs = new List<string>();
		if (failure == null)
		{
			for (var i = 0; i < row.AnimatorStates.Length; i++)
			{
				var slotName = row.AnimatorStates[i];
				if (string.IsNullOrEmpty(slotName))
					continue;
				string played = null;
				if (aoc)
				{
					try
					{
						// Never aoc[string]: its live-interop wrapper marshals the name through
						// Il2CppSystem.ReadOnlySpan<char>.GetPinnableReference, which the live mscorlib lacks
						// (MissingMethodException in game, 2026-09-26). Find the stock clip on the base
						// controller by name, then use the clip-keyed GetClip, which passes object pointers.
						var stock = FindClipNamed(aoc.runtimeAnimatorController, slotName);
						var clip = stock ? aoc[stock] : null;
						played = clip ? clip.name : null;
					}
					catch (Exception ex)
					{
						failure = "override lookup '" + slotName + "' threw " + ex.GetType().Name + ": " + ex.Message;
						break;
					}
				}
				else if (controllerClips.Contains(slotName))
				{
					played = slotName;
				}
				pairs.Add(slotName + "->" + (played ?? "(none)"));
				if (played != null && controllerClips.Contains(played))
					resolved.Add(played);
			}
		}
		slot.ClipsForController = racId;
		slot.ClipNames = resolved;
		if (failure != null || resolved.Count == 0)
		{
			var key = row.Id + "|" + rac.name;
			if (UnresolvedTriggerLogged.Add(key))
			{
				Plugin.LogSource?.LogError(
					"Homm3MeshFx: id='" + row.Id + "' trigger names no clip of controller '" + rac.name + "'"
					+ (aoc ? " (override)" : string.Empty) + "; the row will never fire. slots=["
					+ string.Join(", ", pairs) + "] " + (failure ?? "controllerClips=" + controllerClips.Count) + ".");
			}
		}
		else if (UnresolvedTriggerLogged.Add(row.Id + "|" + rac.name + "|ok"))
		{
			Plugin.LogSource?.LogInfo(
				"Homm3MeshFx: id='" + row.Id + "' trigger on controller '" + rac.name + "' plays ["
				+ string.Join(", ", resolved) + "].");
		}
		return resolved;
	}

	private static AnimationClip FindClipNamed(RuntimeAnimatorController controller, string name)
	{
		var clips = controller ? controller.animationClips : null;
		for (var i = 0; clips != null && i < clips.Length; i++)
		{
			if (clips[i] && string.Equals(clips[i].name, name, StringComparison.Ordinal))
				return clips[i];
		}
		return null;
	}

	// ------------------------------------------------------------------ vanilla particle-prefab reuse layer

	private static bool EnsureVanillaInstance(
		Homm3MeshFxHost host,
		Slot slot,
		ManualLogSource log,
		bool allowIl2CppNativeLoad)
	{
		var row = slot.Row;
		var vs = row.Vanilla;
		if (!TryResolveTemplate(row, log, out var template) || !template)
		{
			if (!allowIl2CppNativeLoad)
				return false;
			slot.LoadAttempts++;
			if (slot.LoadAttempts > 90)
			{
				slot.LoadFailed = true;
				log?.LogError(
					"Homm3MeshFx: missing vanilla source for id='"
					+ row.Id
					+ "' nativeResPath='"
					+ row.NativeResPath
					+ "' after Il2Cpp LateUpdate loads.");
				return false;
			}
			if (!Homm3ImportVisuals.TryLoadNativeResManagerGameObjectIl2Cpp(row.NativeResPath, log, out template)
			    || !template)
				return false;
		}

		if (!TryResolveSocket(host.transform, row, log, out var socket, out _))
		{
			slot.LoadFailed = true;
			return false;
		}
		// Clone only the bare Shuriken subtree: the source is a whole unit/spell prefab whose root
		// carries the game's own scripts, animator and director (the compiler refuses subtrees with any).
		var child = template.transform.Find(vs.ChildPath);
		if (!child)
			return FailVanilla(slot, log, "childPath '" + vs.ChildPath + "' not found in '" + row.NativeResPath + "'");

		DestroyNamedDescendant(host.transform, ChildNamePrefix + row.Id);
		GameObject instance;
		try
		{
			instance = UnityEngine.Object.Instantiate(child.gameObject);
		}
		catch (Exception ex)
		{
			return FailVanilla(slot, log, "Instantiate failed: " + ex.Message);
		}
		if (!instance)
			return FailVanilla(slot, log, "Instantiate returned null");
		instance.SetActive(false);
		instance.name = ChildNamePrefix + row.Id;
		var root = instance.transform;
		root.SetParent(socket, false);
		root.localPosition = vs.BoneLocalPos;
		root.localRotation = vs.BoneLocalRot;
		root.localScale = Vector3.one;

		var kept = new List<ParticleSystem>(vs.KeepNodes.Length);
		var keptTransforms = new List<Transform>(vs.KeepNodes.Length);
		var keptIds = new HashSet<int>();
		for (var i = 0; i < vs.KeepNodes.Length; i++)
		{
			var node = FindRelative(root, vs.KeepNodes[i]);
			var ps = node ? node.GetComponent<ParticleSystem>() : null;
			if (!ps)
			{
				UnityEngine.Object.Destroy(instance);
				return FailVanilla(slot, log, "keepNode '" + vs.KeepNodes[i] + "' is missing or has no ParticleSystem");
			}
			// Source children can be inactive in the prefab (the phoenix hides its effect roots).
			for (var a = node; a && a != root; a = a.parent)
				a.gameObject.SetActive(true);
			kept.Add(ps);
			keptTransforms.Add(node);
			keptIds.Add(ps.GetInstanceID());
		}
		if (vs.ZeroChildPositions)
		{
			var all = root.GetComponentsInChildren<Transform>(true);
			for (var i = 0; i < all.Length; i++)
			{
				if (all[i] && all[i] != root)
					all[i].localPosition = Vector3.zero;
			}
		}
		Transform anchor = null;
		if (!string.IsNullOrEmpty(vs.AnchorNode))
		{
			anchor = FindRelative(root, vs.AnchorNode);
			if (!anchor)
			{
				UnityEngine.Object.Destroy(instance);
				return FailVanilla(slot, log, "anchorNode '" + vs.AnchorNode + "' not found");
			}
		}
		var localNodes = new Transform[vs.LocalScaleNodes.Length];
		var localOriginals = new Vector3[localNodes.Length];
		for (var i = 0; i < localNodes.Length; i++)
		{
			localNodes[i] = FindRelative(root, vs.LocalScaleNodes[i]);
			if (!localNodes[i])
			{
				UnityEngine.Object.Destroy(instance);
				return FailVanilla(slot, log, "localScaleNode '" + vs.LocalScaleNodes[i] + "' not found");
			}
			localOriginals[i] = localNodes[i].localScale;
		}

		var others = new List<ParticleSystem>();
		var systems = root.GetComponentsInChildren<ParticleSystem>(true);
		for (var i = 0; i < systems.Length; i++)
		{
			var ps = systems[i];
			if (!ps || keptIds.Contains(ps.GetInstanceID()))
				continue;
			others.Add(ps);
			var renderer = ps.GetComponent<ParticleSystemRenderer>();
			if (renderer)
				renderer.enabled = false;
		}

		var ownedMaterials = new List<Material>();
		try
		{
			for (var i = 0; i < kept.Count; i++)
			{
				var main = kept[i].main;
				main.loop = vs.Loop;
				var emission = kept[i].emission;
				emission.rateOverTimeMultiplier = emission.rateOverTimeMultiplier * vs.RateMul;
			}
			for (var i = 0; i < vs.RecolorNodes.Length; i++)
				ApplyRecolor(root, vs.RecolorNodes[i], ownedMaterials);
		}
		catch (Exception ex)
		{
			UnityEngine.Object.Destroy(instance);
			for (var i = 0; i < ownedMaterials.Count; i++)
				UnityEngine.Object.Destroy(ownedMaterials[i]);
			return FailVanilla(slot, log, "particle setup failed: " + ex.Message);
		}

		SetLayerRecursive(instance, host.gameObject.layer);
		slot.Instance = instance;
		slot.Socket = socket;
		slot.Orientation = FindOrientationNode(host.transform);
		slot.Anchor = anchor;
		slot.Kept = kept;
		slot.KeptTransforms = keptTransforms;
		slot.Others = others;
		slot.LocalScaleNodes = localNodes;
		slot.LocalScaleOriginals = localOriginals;
		slot.OwnedMaterials = ownedMaterials;
		slot.HelperPrepared = true;
		slot.WasActive = false;
		slot.InWindow = false;
		ApplyVanillaScale(slot, force: true);
		instance.SetActive(true);
		if (_attachLogRemaining > 0)
		{
			_attachLogRemaining--;
			log?.LogInfo(
				"Homm3MeshFx: vanilla-style id='"
				+ row.Id
				+ "' source='"
				+ row.NativeResPath
				+ "/"
				+ vs.ChildPath
				+ "' kept="
				+ kept.Count
				+ " silenced="
				+ others.Count
				+ " socket='"
				+ (socket.name ?? "?")
				+ "' orientation='"
				+ (slot.Orientation ? slot.Orientation.name : "none")
				+ "' proof=source/static.");
		}
		return true;
	}

	private static bool FailVanilla(Slot slot, ManualLogSource log, string reason)
	{
		slot.LoadFailed = true;
		log?.LogError("Homm3MeshFx: vanilla-style id='" + (slot.Row?.Id ?? "?") + "' " + reason + ".");
		return false;
	}

	private static Transform FindRelative(Transform root, string relativePath)
	{
		if (!root)
			return null;
		return string.IsNullOrEmpty(relativePath) ? root : root.Find(relativePath);
	}

	private static Transform FindOrientationNode(Transform hostRoot)
	{
		var orientation = FindNamedTransform(hostRoot, "Orientation");
		if (orientation)
			return orientation;
		var mocap = FindNamedTransform(hostRoot, "MocapDeliveryRoot");
		return mocap ? mocap : hostRoot;
	}

	private static void ApplyRecolor(Transform root, RecolorSpec spec, List<Material> ownedMaterials)
	{
		var node = FindRelative(root, spec.Node);
		var ps = node ? node.GetComponent<ParticleSystem>() : null;
		if (!ps)
			throw new InvalidOperationException("recolor node '" + spec.Node + "' has no ParticleSystem");
		if (spec.GradientColor != null && spec.GradientAlpha != null)
		{
			var colorKeys = new Il2CppStructArray<GradientColorKey>(spec.GradientColor.Length);
			for (var i = 0; i < spec.GradientColor.Length; i++)
			{
				var k = spec.GradientColor[i];
				colorKeys[i] = new GradientColorKey(new Color(k[1], k[2], k[3], 1f), k[0]);
			}
			var alphaKeys = new Il2CppStructArray<GradientAlphaKey>(spec.GradientAlpha.Length);
			for (var i = 0; i < spec.GradientAlpha.Length; i++)
				alphaKeys[i] = new GradientAlphaKey(spec.GradientAlpha[i][1], spec.GradientAlpha[i][0]);
			var gradient = new Gradient();
			gradient.SetKeys(colorKeys, alphaKeys);
			var colorOverLifetime = ps.colorOverLifetime;
			colorOverLifetime.color = new ParticleSystem.MinMaxGradient(gradient);
		}
		var mul = spec.MaterialColorMul;
		if (Mathf.Approximately(mul.x, 1f) && Mathf.Approximately(mul.y, 1f) && Mathf.Approximately(mul.z, 1f))
			return;
		var renderer = ps.GetComponent<ParticleSystemRenderer>();
		if (!renderer)
			throw new InvalidOperationException("recolor node '" + spec.Node + "' has no ParticleSystemRenderer");
		var material = renderer.material;
		if (material == null || !material.HasProperty("_Color"))
			throw new InvalidOperationException("recolor node '" + spec.Node + "' material has no _Color");
		ownedMaterials.Add(material);
		var c = material.GetColor("_Color");
		material.SetColor("_Color", new Color(c.r * mul.x, c.g * mul.y, c.b * mul.z, c.a));
	}

	private static float AverageAbsScale(Vector3 scale)
	{
		return (Mathf.Abs(scale.x) + Mathf.Abs(scale.y) + Mathf.Abs(scale.z)) / 3f;
	}

	/// <summary>
	/// Lab semantics: an effect's world size is worldScale in unscaled delivered-GLB units, i.e. worldScale x
	/// the Orientation node's scale. Local-scaled systems use only their own localScale, so they get the lossy
	/// scale Hierarchy scaling would have given them (the lab switched them to Hierarchy; the live interop cannot).
	/// </summary>
	private static void ApplyVanillaScale(Slot slot, bool force)
	{
		if (!slot.Instance || !slot.Socket)
			return;
		var socketScale = AverageAbsScale(slot.Socket.lossyScale);
		var refScale = slot.Orientation ? AverageAbsScale(slot.Orientation.lossyScale) : 1f;
		if (socketScale < 1e-6f || refScale < 1e-6f)
			return;
		if (!force
		    && Mathf.Abs(socketScale - slot.AppliedSocketScale) <= 0.01f * slot.AppliedSocketScale
		    && Mathf.Abs(refScale - slot.AppliedRefScale) <= 0.01f * slot.AppliedRefScale)
			return;
		slot.AppliedSocketScale = socketScale;
		slot.AppliedRefScale = refScale;
		var root = slot.Instance.transform;
		root.localScale = Vector3.one * (slot.Row.Vanilla.WorldScale * refScale / socketScale);
		var nodes = slot.LocalScaleNodes;
		if (nodes == null || nodes.Length == 0)
			return;
		for (var i = 0; i < nodes.Length; i++)
		{
			if (nodes[i])
				nodes[i].localScale = slot.LocalScaleOriginals[i];
		}
		var targets = new Vector3[nodes.Length];
		for (var i = 0; i < nodes.Length; i++)
			targets[i] = nodes[i] ? nodes[i].lossyScale : Vector3.one;
		for (var i = 0; i < nodes.Length; i++)
		{
			if (nodes[i])
				nodes[i].localScale = targets[i];
		}
	}

	private static void StopSystems(List<ParticleSystem> systems, ParticleSystemStopBehavior behavior)
	{
		if (systems == null)
			return;
		for (var i = 0; i < systems.Count; i++)
		{
			if (systems[i])
				systems[i].Stop(false, behavior);
		}
	}

	private static void PlayKept(Slot slot, bool restart)
	{
		if (slot.Kept == null)
			return;
		if (restart)
			StopSystems(slot.Kept, ParticleSystemStopBehavior.StopEmittingAndClear);
		for (var i = 0; i < slot.Kept.Count; i++)
		{
			if (slot.Kept[i])
				slot.Kept[i].Play(false);
		}
	}

	private static void TickVanillaSlot(Homm3MeshFxHost host, Slot slot, Animator animator)
	{
		if (!EnsureInstance(host, slot, Plugin.LogSource, allowIl2CppNativeLoad: true) || !slot.Instance)
			return;
		var row = slot.Row;
		if (!slot.Instance.activeInHierarchy)
		{
			slot.WasActive = false;
			return;
		}
		if (!slot.WasActive)
		{
			// First frame alive (or back from a hidden parent): OnEnable replayed every playOnAwake
			// system, so silence the unkept ones and put the kept ones in their trigger state.
			slot.WasActive = true;
			ReattachToSocket(slot);
			StopSystems(slot.Others, ParticleSystemStopBehavior.StopEmittingAndClear);
			StopSystems(slot.Kept, ParticleSystemStopBehavior.StopEmittingAndClear);
			slot.InWindow = false;
			if (row.Trigger == TriggerMode.Always)
				PlayKept(slot, restart: false);
		}
		if (row.Trigger == TriggerMode.AnimatorWindow)
		{
			var inWindow = AnimatorMatches(animator, slot, out var normalized)
			               && normalized >= row.WindowStart
			               && normalized <= row.WindowEnd;
			if (inWindow && !slot.InWindow)
			{
				if (row.Vanilla.FollowRelease)
				{
					ReattachToSocket(slot);
					OrientVanilla(slot);
				}
				PlayKept(slot, restart: true);
				if (row.Vanilla.FollowRelease)
				{
					slot.Instance.transform.SetParent(host.transform, true);
					slot.Detached = true;
				}
			}
			else if (!inWindow && slot.InWindow)
				StopSystems(slot.Kept, ParticleSystemStopBehavior.StopEmitting);
			slot.InWindow = inWindow;
		}
		if (slot.Detached)
			return;
		ApplyVanillaScale(slot, force: false);
		OrientVanilla(slot);
	}

	private static void ReattachToSocket(Slot slot)
	{
		if (!slot.Detached || !slot.Instance || !slot.Socket)
			return;
		var root = slot.Instance.transform;
		root.SetParent(slot.Socket, false);
		root.localPosition = slot.Row.Vanilla.BoneLocalPos;
		root.localRotation = slot.Row.Vanilla.BoneLocalRot;
		slot.Detached = false;
		// SetParent(worldPositionStays) rewrote localScale for the host frame; restore the socket-frame scale.
		ApplyVanillaScale(slot, force: true);
	}

	private static void OrientVanilla(Slot slot)
	{
		var vs = slot.Row.Vanilla;
		var root = slot.Instance.transform;
		if (string.Equals(vs.Orient, OrientBody, StringComparison.Ordinal))
		{
			// Body frame = Orientation turned by the fleet bind facing (the idle-0 mesh faces -60 inside it).
			var basis = slot.Orientation ? Homm3ImportVisuals.OwnedSkinnedBodyRotation(slot.Orientation) : Quaternion.identity;
			root.rotation = basis * Quaternion.Euler(0f, vs.BodyYawDeg, 0f);
		}
		else if (string.Equals(vs.Orient, OrientEmitUp, StringComparison.Ordinal))
		{
			var camera = Camera.main;
			if (camera)
			{
				var facing = Quaternion.LookRotation(Vector3.up, -camera.transform.forward);
				for (var i = 0; i < slot.KeptTransforms.Count; i++)
				{
					if (slot.KeptTransforms[i])
						slot.KeptTransforms[i].rotation = facing;
				}
			}
			else if (!_emitUpCameraMissingLogged)
			{
				_emitUpCameraMissingLogged = true;
				Plugin.LogSource?.LogWarning(
					"Homm3MeshFx: emitUp rows found no Camera.main; flames keep the bone orientation.");
			}
		}
		if (slot.Anchor)
		{
			root.localPosition = vs.BoneLocalPos;
			root.position += slot.Socket.TransformPoint(vs.BoneLocalPos) - slot.Anchor.position;
		}
	}

	// ------------------------------------------------------------------ Hex/Lit FLAG vertex-displacement layer

	private static bool TryFindUniqueBodyDisplacementRow(
		Homm3ImportVisuals.Entry entry,
		out CatalogRow row,
		out CatalogRow duplicateRow,
		out List<string> sids)
	{
		row = null;
		duplicateRow = null;
		if (entry == null || _rows == null || _rows.Count == 0)
		{
			sids = new List<string>();
			return false;
		}
		sids = CollectSkinnedMatchSids(entry);

		for (var i = 0; i < _rows.Count; i++)
		{
			var candidate = _rows[i];
			if (candidate?.Displacement == null
			    || !string.Equals(candidate.Lane, LaneBattleBodyDisplacement, StringComparison.Ordinal)
			    || !SidListIntersects(candidate.UnitSids, sids))
				continue;
			if (row != null)
			{
				duplicateRow = candidate;
				return false;
			}
			row = candidate;
		}
		return row != null;
	}

	private static bool IsExpectedBodyDisplacementMaterialState(Material material, SkinnedMeshRenderer skin, CatalogRow row)
	{
		if (!material || !skin || row?.Displacement == null)
			return false;
		try
		{
			var mesh = skin.sharedMesh;
			if (!mesh || !mesh.HasVertexAttribute(VertexAttribute.Color))
				return false;

			string[] props = { "_VertexDisplacementType", "_FlagDirection", "_FlagPower", "_FlagSpeed" };
			for (var i = 0; i < props.Length; i++)
			{
				if (!material.HasProperty(props[i]))
					return false;
			}

			var d = row.Displacement;
			var readType = material.GetFloat("_VertexDisplacementType");
			var readDirection = material.GetVector("_FlagDirection");
			var readPower = material.GetVector("_FlagPower");
			var readSpeed = material.GetFloat("_FlagSpeed");
			return MaterialHasKeyword(material, FlagDisplacementKeyword)
			       && !MaterialHasKeyword(material, TreeDisplacementKeyword)
			       && Mathf.Abs(readType - FlagDisplacementType) <= 1e-4f
			       && (readDirection - d.Direction).sqrMagnitude <= 1e-10f
			       && (readPower - d.Power).sqrMagnitude <= 1e-10f
			       && Mathf.Abs(readSpeed - d.Speed) <= 1e-4f;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>
	/// Revalidates the current owned-skinned map/battle material against its unique displacement row. This keeps
	/// the visibility self-check idempotent when an already-rebound material is seen again on a later presentation pass.
	/// </summary>
	internal static bool IsExpectedBodyDisplacementApplied(
		Material material,
		SkinnedMeshRenderer skin,
		Homm3ImportVisuals.Entry entry,
		string lane)
	{
		if (!material || !skin || entry == null
		    || (!string.Equals(lane, "battle", StringComparison.Ordinal)
		        && !string.Equals(lane, "adventure-map", StringComparison.Ordinal)))
			return false;
		EnsureCatalog(null);
		if (!TryFindUniqueBodyDisplacementRow(entry, out var row, out _, out _))
			return false;
		return IsExpectedBodyDisplacementMaterialState(material, skin, row);
	}

	/// <summary>
	/// Switch on the Hex/Lit FLAG vertex displacement of an owned skinned body material. The shader moves each
	/// vertex by _FlagPower * sin(dot(posWS, _FlagDirection) + time * _FlagSpeed) scaled by the vertex colour's red
	/// channel, so the mask is the delivered mesh's COLOR_0.r; a mesh without a colour stream would wave the whole
	/// body, so it is refused. Called beside TryApplyBodyEmission after the Hex/Lit rebind.
	/// </summary>
	internal static void TryApplyBodyDisplacement(
		Material material,
		SkinnedMeshRenderer skin,
		Homm3ImportVisuals.Entry entry,
		string lane,
		ManualLogSource log)
	{
		if (material == null || entry == null)
			return;
		EnsureCatalog(log);
		if (_rows == null || _rows.Count == 0)
			return;
		if (!TryFindUniqueBodyDisplacementRow(entry, out var row, out var duplicateRow, out var sids))
		{
			if (duplicateRow != null)
				log?.LogError(
					"Homm3MeshFx: two displacement rows ('" + row.Id + "', '" + duplicateRow.Id + "') match sids='"
					+ string.Join(",", sids) + "'; refusing both.");
			return;
		}
		var mesh = skin ? skin.sharedMesh : null;
		bool hasColors;
		try
		{
			hasColors = mesh && mesh.HasVertexAttribute(VertexAttribute.Color);
		}
		catch (Exception ex)
		{
			if (EmissionFailures.Add(row.Id + "|dispmesh|" + lane))
				log?.LogError("Homm3MeshFx: displacement id='" + row.Id + "' vertex-stream probe failed: " + ex.Message + ".");
			return;
		}
		if (!hasColors)
		{
			if (EmissionFailures.Add(row.Id + "|dispcolor|" + lane))
				log?.LogError(
					"Homm3MeshFx: displacement id='" + row.Id + "' lane=" + lane + " mesh '"
					+ (mesh ? mesh.name : "<none>")
					+ "' has no vertex colour stream (the baked COLOR_0 mask did not ship); refusing, or the whole body would wave.");
			return;
		}
		string[] props = { "_VertexDisplacementType", "_FlagDirection", "_FlagPower", "_FlagSpeed" };
		var missing = new List<string>();
		for (var i = 0; i < props.Length; i++)
		{
			if (!material.HasProperty(props[i]))
				missing.Add(props[i]);
		}
		if (missing.Count > 0)
		{
			if (EmissionFailures.Add(row.Id + "|dispprops|" + lane))
				log?.LogError(
					"Homm3MeshFx: displacement id='" + row.Id + "' lane=" + lane + " material '" + material.name
					+ "' shader '" + (material.shader ? material.shader.name : "?") + "' lacks "
					+ string.Join(",", missing) + "; body displacement not applied.");
			return;
		}
		var d = row.Displacement;
		material.SetFloat("_VertexDisplacementType", FlagDisplacementType);
		material.SetVector("_FlagDirection", d.Direction);
		material.SetVector("_FlagPower", d.Power);
		material.SetFloat("_FlagSpeed", d.Speed);
		material.DisableKeyword(TreeDisplacementKeyword);
		material.EnableKeyword(FlagDisplacementKeyword);
		var readType = material.GetFloat("_VertexDisplacementType");
		var readDirection = material.GetVector("_FlagDirection");
		var readPower = material.GetVector("_FlagPower");
		var readSpeed = material.GetFloat("_FlagSpeed");
		if (!IsExpectedBodyDisplacementMaterialState(material, skin, row))
		{
			// Half a displacement (keyword without power, or power without keyword) is worse than none.
			var keywordStuck = MaterialHasKeyword(material, FlagDisplacementKeyword);
			material.DisableKeyword(FlagDisplacementKeyword);
			material.SetFloat("_VertexDisplacementType", 0f);
			if (EmissionFailures.Add(row.Id + "|dispkeyword|" + lane))
				log?.LogError(
					"Homm3MeshFx: displacement id='" + row.Id + "' lane=" + lane + " readback failed on '" + material.name
					+ "' (keyword=" + keywordStuck + " type=" + readType + " direction=" + readDirection
					+ " power=" + readPower + " speed=" + readSpeed + "); reverted.");
			return;
		}
		if (EmissionAppliedLog.Add(row.Id + "|" + lane))
			log?.LogInfo(
				"Homm3MeshFx: displacement id='" + row.Id + "' lane=" + lane + " material='" + material.name
				+ "' mesh='" + mesh.name + "' proof=source/static.");
	}

	// ------------------------------------------------------------------ vanilla body-overlay material layer

	/// <summary>
	/// Append one vanilla material to the owned body SkinnedMeshRenderer(s) while the row's trigger holds (the
	/// extra material redraws the last submesh, as BhBattleTimelineHelper.AppendMaterial does for vanilla units).
	/// The material is a private copy of a native prefab renderer's sharedMaterials[materialIndex], loaded only
	/// through the Il2Cpp ResManager loader from LateUpdate. Any miss fails the row closed with one error.
	/// </summary>
	private static void TickOverlaySlot(Homm3MeshFxHost host, Slot slot, Animator animator)
	{
		var row = slot.Row;
		if (slot.LoadFailed)
			return;
		bool want;
		if (row.Trigger == TriggerMode.Always)
			want = true;
		else
			want = AnimatorMatches(animator, slot, out var normalized)
			       && normalized >= row.WindowStart
			       && normalized <= row.WindowEnd;
		if (want && !slot.OverlayMaterial && !EnsureOverlayMaterial(slot, Plugin.LogSource))
			return;
		if (want == slot.OverlayOn)
		{
			// Something else (the Hex/Lit rebind, a native material swap) may rewrite sharedMaterials: re-verify.
			if (!want || --slot.OverlayVerifyCountdown > 0)
				return;
		}
		slot.OverlayVerifyCountdown = 60;
		if (!SetOverlay(host, slot, want, Plugin.LogSource))
		{
			SetOverlay(host, slot, false, null);
			slot.OverlayOn = false;
			slot.LoadFailed = true;
			return;
		}
		slot.OverlayOn = want;
	}

	private static bool EnsureOverlayMaterial(Slot slot, ManualLogSource log)
	{
		var row = slot.Row;
		var ov = row.Overlay;
		slot.LoadAttempts++;
		if (slot.LoadAttempts > 90)
		{
			slot.LoadFailed = true;
			log?.LogError(
				"Homm3MeshFx: overlay id='" + row.Id + "' nativeResPath='" + row.NativeResPath
				+ "' did not load after 90 LateUpdate attempts.");
			return false;
		}
		if (!Homm3ImportVisuals.TryLoadNativeResManagerGameObjectIl2Cpp(row.NativeResPath, log, out var template)
		    || !template)
			return false;
		var node = string.IsNullOrEmpty(ov.RendererPath) ? template.transform : template.transform.Find(ov.RendererPath);
		var renderer = node ? node.GetComponent<Renderer>() : null;
		var materials = renderer ? renderer.sharedMaterials : null;
		if (materials == null || ov.MaterialIndex < 0 || ov.MaterialIndex >= materials.Length || materials[ov.MaterialIndex] == null)
		{
			slot.LoadFailed = true;
			log?.LogError(
				"Homm3MeshFx: overlay id='" + row.Id + "' '" + row.NativeResPath + "' renderer '" + ov.RendererPath
				+ "' material[" + ov.MaterialIndex + "] not found (renderer=" + (renderer ? "yes" : "no") + ").");
			return false;
		}
		var copy = new Material(materials[ov.MaterialIndex]) { name = ChildNamePrefix + row.Id };
		(slot.OwnedMaterials ??= new List<Material>()).Add(copy);
		if (!ApplyOverlayTint(copy, row, log))
		{
			slot.LoadFailed = true;
			return false;
		}
		slot.OverlayMaterial = copy;
		return true;
	}

	/// <summary>Write the row's tint colours onto the private overlay copy and read each one back (fail closed).</summary>
	private static bool ApplyOverlayTint(Material copy, CatalogRow row, ManualLogSource log)
	{
		var ov = row.Overlay;
		for (var i = 0; i < ov.ColorProperties.Length; i++)
		{
			var property = ov.ColorProperties[i];
			var want = ov.ColorValues[i];
			if (!copy.HasProperty(property))
			{
				log?.LogError("Homm3MeshFx: overlay id='" + row.Id + "' '" + row.NativeResPath
				              + "' material has no tint property '" + property + "'; row disabled.");
				return false;
			}
			copy.SetColor(property, want);
			var got = copy.GetColor(property);
			if (Mathf.Abs(got.r - want.r) > 1e-3f || Mathf.Abs(got.g - want.g) > 1e-3f
			    || Mathf.Abs(got.b - want.b) > 1e-3f || Mathf.Abs(got.a - want.a) > 1e-3f)
			{
				log?.LogError("Homm3MeshFx: overlay id='" + row.Id + "' tint '" + property + "' did not read back as written; row disabled.");
				return false;
			}
		}
		return true;
	}

	/// <summary>Add (on) or remove (off) the slot's overlay on every owned body SMR, then read it back.</summary>
	private static bool SetOverlay(Homm3MeshFxHost host, Slot slot, bool on, ManualLogSource log)
	{
		var overlay = slot.OverlayMaterial;
		if (!overlay)
			return !on;
		var overlayId = overlay.GetInstanceID();
		Il2CppArrayBase<SkinnedMeshRenderer> skins;
		try
		{
			skins = host.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MeshFx: overlay id='" + slot.Row.Id + "' renderer scan failed: " + ex.Message + ".");
			return false;
		}
		var bodies = 0;
		for (var i = 0; skins != null && i < skins.Length; i++)
		{
			var skin = skins[i];
			if (!skin || IsFxDescendant(skin.transform))
				continue;
			bodies++;
			var current = skin.sharedMaterials;
			var kept = new List<Material>();
			var had = false;
			for (var j = 0; current != null && j < current.Length; j++)
			{
				if (current[j] != null && current[j].GetInstanceID() == overlayId)
					had = true;
				else
					kept.Add(current[j]);
			}
			if (had == on)
				continue;
			if (on)
				kept.Add(overlay);
			var next = new Il2CppReferenceArray<Material>(kept.Count);
			for (var j = 0; j < kept.Count; j++)
				next[j] = kept[j];
			skin.sharedMaterials = next;
			var readback = skin.sharedMaterials;
			var present = false;
			for (var j = 0; readback != null && j < readback.Length; j++)
			{
				if (readback[j] != null && readback[j].GetInstanceID() == overlayId)
					present = true;
			}
			if (present != on)
			{
				log?.LogError(
					"Homm3MeshFx: overlay id='" + slot.Row.Id + "' sharedMaterials readback on '" + skin.name
					+ "' did not " + (on ? "hold" : "drop") + " the overlay; row disabled.");
				return false;
			}
		}
		if (bodies == 0 && on)
		{
			log?.LogError("Homm3MeshFx: overlay id='" + slot.Row.Id + "' found no owned body SkinnedMeshRenderer; row disabled.");
			return false;
		}
		return true;
	}

	// ------------------------------------------------------------------ Hex/Lit emission-map layer

	/// <summary>
	/// Switch on the Hex/Lit emission map of an owned skinned body material (steady glow is emission, never a
	/// light). Called after the Hex/Lit rebind has sanitised the sheet, on every lane that rebinds it.
	/// </summary>
	internal static void TryApplyBodyEmission(
		Material material,
		Homm3ImportVisuals.Entry entry,
		string lane,
		ManualLogSource log)
	{
		if (material == null || entry == null)
			return;
		EnsureCatalog(log);
		if (_rows == null || _rows.Count == 0)
			return;
		var sids = CollectSkinnedMatchSids(entry);
		CatalogRow row = null;
		for (var i = 0; i < _rows.Count; i++)
		{
			var candidate = _rows[i];
			if (candidate?.Emission == null
			    || !string.Equals(candidate.Lane, LaneBattleEmission, StringComparison.Ordinal)
			    || !SidListIntersects(candidate.UnitSids, sids))
				continue;
			if (row != null)
			{
				log?.LogError(
					"Homm3MeshFx: two emission rows ('" + row.Id + "', '" + candidate.Id + "') match sids='"
					+ string.Join(",", sids) + "'; refusing both.");
				return;
			}
			row = candidate;
		}
		if (row == null)
			return;
		var texture = LoadEmissionTexture(row, log);
		if (!texture)
			return;
		var em = row.Emission;
		if (!material.HasProperty("_EmissionTex") || !material.HasProperty("_EmissionColor"))
		{
			if (EmissionFailures.Add(row.Id + "|props|" + lane))
				log?.LogError(
					"Homm3MeshFx: emission id='" + row.Id + "' lane=" + lane + " material '" + material.name
					+ "' shader '" + (material.shader ? material.shader.name : "?")
					+ "' has no _EmissionTex/_EmissionColor; body glow not applied.");
			return;
		}
		material.SetTexture("_EmissionTex", texture);
		material.SetColor("_EmissionColor", em.Color);
		var missing = new List<string>();
		SetFloatOrNote(material, "_EmissionMinPower", em.MinPower, missing);
		SetFloatOrNote(material, "_EmissionBlinkPower", em.BlinkPower, missing);
		SetFloatOrNote(material, "_EmissionBlinkSpeed", em.BlinkSpeed, missing);
		material.EnableKeyword(EmissionKeyword);
		if (!MaterialHasKeyword(material, EmissionKeyword))
		{
			if (EmissionFailures.Add(row.Id + "|keyword|" + lane))
				log?.LogError(
					"Homm3MeshFx: emission id='" + row.Id + "' lane=" + lane + " " + EmissionKeyword
					+ " did not stick on '" + material.name + "' (shaderKeywords readback).");
			return;
		}
		if (missing.Count > 0 && EmissionFailures.Add(row.Id + "|blink|" + lane))
			log?.LogError(
				"Homm3MeshFx: emission id='" + row.Id + "' lane=" + lane + " material lacks "
				+ string.Join(",", missing) + "; the glow is steady instead of the vanilla pulse.");
		if (EmissionAppliedLog.Add(row.Id + "|" + lane))
			log?.LogInfo(
				"Homm3MeshFx: emission id='" + row.Id + "' lane=" + lane + " material='" + material.name
				+ "' texture='" + em.Texture + "' proof=source/static.");
	}

	private static void SetFloatOrNote(Material material, string property, float value, List<string> missing)
	{
		if (material.HasProperty(property))
			material.SetFloat(property, value);
		else
			missing.Add(property);
	}

	private static bool MaterialHasKeyword(Material material, string keyword)
	{
		var keywords = material.shaderKeywords;
		if (keywords == null)
			return false;
		for (var i = 0; i < keywords.Length; i++)
		{
			if (string.Equals(keywords[i], keyword, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static Texture2D LoadEmissionTexture(CatalogRow row, ManualLogSource log)
	{
		var em = row.Emission;
		if (EmissionTextures.TryGetValue(em.Texture, out var cached) && cached)
			return cached;
		if (EmissionFailures.Contains("tex|" + em.Texture))
			return null;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath("homm3_mesh_fx/" + em.Texture);
		string failure = null;
		Texture2D texture = null;
		try
		{
			if (path == null || !File.Exists(path))
				failure = "file missing";
			else
			{
				var bytes = File.ReadAllBytes(path);
				string digest;
				using (var sha = SHA256.Create())
					digest = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", string.Empty).ToLowerInvariant();
				if (!string.Equals(digest, em.TextureSha256, StringComparison.Ordinal))
					failure = "sha256 " + digest + " != catalog " + em.TextureSha256;
				else
				{
					texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true);
					var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
					for (var i = 0; i < bytes.Length; i++)
						il2cppBytes[i] = bytes[i];
					if (!ImageConversion.LoadImage(texture, il2cppBytes))
					{
						UnityEngine.Object.Destroy(texture);
						texture = null;
						failure = "PNG decode failed";
					}
				}
			}
		}
		catch (Exception ex)
		{
			failure = ex.Message;
			texture = null;
		}
		if (failure != null)
		{
			EmissionFailures.Add("tex|" + em.Texture);
			log?.LogError("Homm3MeshFx: emission id='" + row.Id + "' texture '" + em.Texture + "': " + failure + ".");
			return null;
		}
		texture.name = "homm3_mesh_fx_emission_" + Path.GetFileNameWithoutExtension(em.Texture);
		texture.hideFlags = HideFlags.DontUnloadUnusedAsset;
		EmissionTextures[em.Texture] = texture;
		return texture;
	}

	private static void TryPrepareNativeHelper(GameObject instance, Transform socket)
	{
		if (!instance)
			return;
		var components = instance.GetComponentsInChildren<Component>(true);
		if (components == null)
			return;
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !IsEffectHelper(component))
				continue;
			TrySetBoolMember(component, GameSymbols.BattleEffect.SpawnAsChildFields, true);
			TryInvokeNamed(component, GameSymbols.BattleEffect.Init.NameHints, socket, false);
		}
	}

	private static void TryStartNativeHelper(GameObject instance, Slot slot, bool forceRestart)
	{
		if (!instance)
			return;
		var components = instance.GetComponentsInChildren<Component>(true);
		if (components == null)
			return;
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !IsEffectHelper(component))
				continue;
			if (forceRestart || !slot.HelperPrepared)
				TryInvokeNamed(component, GameSymbols.BattleEffect.StartPlaying.NameHints);
		}
	}

	private static bool IsEffectHelper(Component component)
	{
		var type = component.GetType();
		while (type != null && type != typeof(object))
		{
			var name = type.Name ?? string.Empty;
			var full = type.FullName ?? string.Empty;
			for (var i = 0; i < GameSymbols.BattleEffect.HelperTypeNames.Length; i++)
			{
				var hint = GameSymbols.BattleEffect.HelperTypeNames[i];
				if (string.Equals(name, hint, StringComparison.Ordinal)
				    || string.Equals(full, hint, StringComparison.Ordinal)
				    || full.EndsWith("." + hint, StringComparison.Ordinal))
					return true;
			}
			type = type.BaseType;
		}
		return false;
	}

	private static void TrySetBoolMember(object target, string[] names, bool value)
	{
		if (target == null || names == null)
			return;
		var type = target.GetType();
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, InvokeFlags);
				if (prop != null && prop.CanWrite && prop.PropertyType == typeof(bool))
				{
					prop.SetValue(target, value, null);
					return;
				}
				var field = type.GetField(name, InvokeFlags);
				if (field != null && field.FieldType == typeof(bool))
				{
					field.SetValue(target, value);
					return;
				}
			}
			catch
			{
				// Keep trying remaining names.
			}
		}
	}

	private static void TryInvokeNamed(object target, string[] names, params object[] args)
	{
		if (target == null || names == null)
			return;
		var type = target.GetType();
		var argCount = args?.Length ?? 0;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var methods = type.GetMethods(InvokeFlags);
				if (methods == null)
					continue;
				for (var m = 0; m < methods.Length; m++)
				{
					var method = methods[m];
					if (method == null || !string.Equals(method.Name, name, StringComparison.Ordinal))
						continue;
					var parms = method.GetParameters();
					if (parms == null || parms.Length != argCount)
						continue;
					method.Invoke(target, args);
					return;
				}
			}
			catch
			{
				// Keep trying remaining names.
			}
		}
	}

	private static void EnsureCatalog(ManualLogSource log)
	{
		if (_catalogLoadAttempted)
			return;
		_catalogLoadAttempted = true;
		_rows = new List<CatalogRow>();
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeCatalogPath);
		if (path == null || !File.Exists(path))
		{
			if (_catalogMissLogRemaining > 0)
			{
				_catalogMissLogRemaining--;
				log?.LogError("Homm3MeshFx: catalog missing at " + RelativeCatalogPath + ".");
			}
			return;
		}

		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			var schema = root["schema"]?.ToString() ?? string.Empty;
			if (!string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
			{
				log?.LogError(
					"Homm3MeshFx: catalog schema mismatch expected "
					+ CatalogSchema
					+ " got "
					+ schema
					+ ".");
				return;
			}
			var entriesToken = root["entries"];
			var entries = AsArray(entriesToken);
			if (entries == null)
			{
				log?.LogError("Homm3MeshFx: catalog missing entries array.");
				return;
			}
			for (var i = 0; i < entries.Count; i++)
			{
				var rowToken = AsObject(entries[i]);
				if (rowToken == null)
					continue;
				if (!TryParseRow(rowToken, log, out var row) || row == null)
					continue;
				_rows.Add(row);
			}
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MeshFx: catalog parse failed: " + ex.Message);
			_rows.Clear();
		}
	}

	private static bool TryParseRow(JObject row, ManualLogSource log, out CatalogRow parsed)
	{
		parsed = null;
		var id = ReadString(row, "id");
		var lane = ReadString(row, "lane");
		if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(lane))
			return false;
		if (string.Equals(lane, LaneBattleEmission, StringComparison.Ordinal))
			return TryParseEmissionRow(row, id.Trim(), log, out parsed);
		if (string.Equals(lane, LaneBattleBodyDisplacement, StringComparison.Ordinal))
			return TryParseDisplacementRow(row, id.Trim(), log, out parsed);
		if (string.Equals(lane, LaneBattleBodyOverlay, StringComparison.Ordinal))
			return TryParseOverlayRow(row, id.Trim(), log, out parsed);
		if (!string.Equals(lane, LaneMapBuilding, StringComparison.Ordinal)
		    && !string.Equals(lane, LaneBattleSkinned, StringComparison.Ordinal))
		{
			log?.LogError("Homm3MeshFx: unknown lane='" + lane + "' id='" + id + "'.");
			return false;
		}

		var match = AsObject(row["match"]);
		var source = AsObject(row["source"]);
		var socket = AsObject(row["socket"]);
		var trigger = AsObject(row["trigger"]);
		if (match == null || source == null || socket == null || trigger == null)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' missing match/source/socket/trigger.");
			return false;
		}

		var native = ReadString(source, "nativeResPath");
		var owned = ReadString(source, "ownedPrefabKey");
		var mapParticles = ReadBool(source, "mapObjectParticles", false);
		var hasNative = !string.IsNullOrWhiteSpace(native);
		var hasOwned = !string.IsNullOrWhiteSpace(owned);
		var sourceCount = (hasNative ? 1 : 0) + (hasOwned ? 1 : 0) + (mapParticles ? 1 : 0);
		if (sourceCount != 1)
		{
			log?.LogError(
				"Homm3MeshFx: id='"
				+ id
				+ "' source must be exactly one of nativeResPath, ownedPrefabKey, or mapObjectParticles.");
			return false;
		}
		if (string.Equals(lane, LaneMapBuilding, StringComparison.Ordinal) && hasNative && !IsMapFxResPath(native))
		{
			log?.LogError(
				"Homm3MeshFx: id='"
				+ id
				+ "' map_building nativeResPath='"
				+ native
				+ "' must be a Core map-object prefab (objects/…), not combat Prefabs_vfx.");
			return false;
		}
		if (string.Equals(lane, LaneBattleSkinned, StringComparison.Ordinal) && mapParticles)
		{
			log?.LogError(
				"Homm3MeshFx: id='"
				+ id
				+ "' mapObjectParticles is map_building only.");
			return false;
		}

		var socketKindText = ReadString(socket, "kind");
		SocketKind socketKind;
		if (string.Equals(socketKindText, "meshBounds", StringComparison.Ordinal))
			socketKind = SocketKind.MeshBounds;
		else if (string.Equals(socketKindText, "bones", StringComparison.Ordinal))
			socketKind = SocketKind.Bones;
		else
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' unknown socket.kind='" + socketKindText + "'.");
			return false;
		}

		var modeText = ReadString(trigger, "mode");
		TriggerMode mode;
		if (string.Equals(modeText, "always", StringComparison.Ordinal))
			mode = TriggerMode.Always;
		else if (string.Equals(modeText, "animator_state", StringComparison.Ordinal))
			mode = TriggerMode.AnimatorState;
		else if (string.Equals(modeText, "animator_window", StringComparison.Ordinal))
			mode = TriggerMode.AnimatorWindow;
		else
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' unknown trigger.mode='" + modeText + "'.");
			return false;
		}

		var prefabKeyContains = ReadString(match, "prefabKeyContains") ?? string.Empty;
		var unitSids = ReadStringArray(match, "unitSids");
		if (string.Equals(lane, LaneMapBuilding, StringComparison.Ordinal)
		    && string.IsNullOrWhiteSpace(prefabKeyContains))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' map_building match needs prefabKeyContains.");
			return false;
		}
		if (string.Equals(lane, LaneBattleSkinned, StringComparison.Ordinal)
		    && (unitSids == null || unitSids.Length == 0))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' battle_skinned match needs unitSids.");
			return false;
		}

		var boneNames = ReadStringArray(socket, "names");
		if (socketKind == SocketKind.Bones && (boneNames == null || boneNames.Length == 0))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' bones socket needs a non-empty names list.");
			return false;
		}

		var animatorStates = ReadStringArray(trigger, "states");
		if (mode != TriggerMode.Always && (animatorStates == null || animatorStates.Length == 0))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' animator trigger needs a non-empty states list.");
			return false;
		}

		var windowStart = 0f;
		var windowEnd = 1f;
		if (mode == TriggerMode.AnimatorWindow)
		{
			if (!TryReadFloatPair(trigger, "normalizedTime", out windowStart, out windowEnd))
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' animator_window needs normalizedTime [start, end].");
				return false;
			}
		}

		parsed = new CatalogRow
		{
			Id = id.Trim(),
			Lane = lane.Trim(),
			PrefabKeyContains = prefabKeyContains,
			UnitSids = unitSids,
			NativeResPath = hasNative ? native.Trim() : string.Empty,
			OwnedPrefabKey = hasOwned ? owned.Trim() : string.Empty,
			MapObjectParticles = mapParticles,
			Socket = socketKind,
			BoneNames = boneNames,
			NormalizedOffset = ReadVector3(socket, "normalizedOffset", Vector3.zero),
			LocalScale = ReadVector3(socket, "localScale", Vector3.one),
			Trigger = mode,
			AnimatorStates = animatorStates,
			WindowStart = windowStart,
			WindowEnd = windowEnd,
			KeepExistingGlow = ReadBool(row, "keepExistingGlow", false)
		};
		var vanillaToken = row["vanillaStyle"];
		if (vanillaToken != null && vanillaToken.Type != JTokenType.Null)
		{
			if ((!string.Equals(lane, LaneBattleSkinned, StringComparison.Ordinal)
			     && !string.Equals(lane, LaneMapBuilding, StringComparison.Ordinal))
			    || !hasNative)
			{
				log?.LogError(
					"Homm3MeshFx: id='" + id + "' vanillaStyle needs lane battle_skinned or map_building and nativeResPath.");
				parsed = null;
				return false;
			}
			if (mode == TriggerMode.AnimatorState)
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle triggers are always or animator_window.");
				parsed = null;
				return false;
			}
			if (!TryParseVanillaStyle(AsObject(vanillaToken), id, log, out var vanilla))
			{
				parsed = null;
				return false;
			}
			parsed.Vanilla = vanilla;
		}
		if (hasNative)
			Homm3ImportVisuals.RegisterNativeResManagerCacheInterest(parsed.NativeResPath);
		return true;
	}

	private static bool TryParseEmissionRow(JObject row, string id, ManualLogSource log, out CatalogRow parsed)
	{
		parsed = null;
		var match = AsObject(row["match"]);
		var emission = AsObject(row["emission"]);
		var unitSids = ReadStringArray(match, "unitSids");
		if (unitSids == null || unitSids.Length == 0 || emission == null)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' battle_emission needs match.unitSids and an emission object.");
			return false;
		}
		var texture = ReadString(emission, "texture");
		var digest = ReadString(emission, "textureSha256");
		var color = ReadVector3(emission, "color", new Vector3(-1f, -1f, -1f));
		if (string.IsNullOrEmpty(texture) || string.IsNullOrEmpty(digest) || color.x < 0f)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' emission needs texture, textureSha256 and color.");
			return false;
		}
		parsed = new CatalogRow
		{
			Id = id,
			Lane = LaneBattleEmission,
			UnitSids = unitSids,
			Emission = new EmissionSpec
			{
				Texture = texture,
				TextureSha256 = digest.ToLowerInvariant(),
				Color = new Color(color.x, color.y, color.z, 1f),
				MinPower = ReadFloat(emission, "minPower", 1f),
				BlinkPower = ReadFloat(emission, "blinkPower", 0f),
				BlinkSpeed = ReadFloat(emission, "blinkSpeed", 0f)
			}
		};
		return true;
	}

	private static bool TryParseDisplacementRow(JObject row, string id, ManualLogSource log, out CatalogRow parsed)
	{
		parsed = null;
		var match = AsObject(row["match"]);
		var disp = AsObject(row["displacement"]);
		var unitSids = ReadStringArray(match, "unitSids");
		if (unitSids == null || unitSids.Length == 0 || disp == null)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' battle_body_displacement needs match.unitSids and a displacement object.");
			return false;
		}
		var mode = ReadString(disp, "mode");
		var missing = new Vector3(float.NaN, float.NaN, float.NaN);
		var direction = ReadVector3(disp, "direction", missing);
		var power = ReadVector3(disp, "power", missing);
		var speed = ReadFloat(disp, "speed", float.NaN);
		if (!string.Equals(mode, "flag", StringComparison.Ordinal)
		    || float.IsNaN(direction.x) || float.IsNaN(power.x) || float.IsNaN(speed)
		    || power.sqrMagnitude <= 0f)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' displacement needs mode 'flag', direction, non-zero power and speed.");
			return false;
		}
		parsed = new CatalogRow
		{
			Id = id,
			Lane = LaneBattleBodyDisplacement,
			UnitSids = unitSids,
			Displacement = new DisplacementSpec
			{
				Direction = new Vector4(direction.x, direction.y, direction.z, 0f),
				Power = new Vector4(power.x, power.y, power.z, 0f),
				Speed = speed
			}
		};
		return true;
	}

	private static bool TryParseOverlayRow(JObject row, string id, ManualLogSource log, out CatalogRow parsed)
	{
		parsed = null;
		var match = AsObject(row["match"]);
		var source = AsObject(row["source"]);
		var trigger = AsObject(row["trigger"]);
		var unitSids = ReadStringArray(match, "unitSids");
		var native = ReadString(source, "nativeResPath");
		if (unitSids == null || unitSids.Length == 0 || source == null || trigger == null || string.IsNullOrWhiteSpace(native))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' battle_body_overlay needs match.unitSids, source.nativeResPath and trigger.");
			return false;
		}
		var indexToken = source["materialIndex"];
		if (indexToken == null || indexToken.Type != JTokenType.Integer || (int)indexToken < 0)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' overlay source.materialIndex must be an integer >= 0.");
			return false;
		}
		var modeText = ReadString(trigger, "mode");
		TriggerMode mode;
		var states = ReadStringArray(trigger, "states");
		var start = 0f;
		var end = 1f;
		if (string.Equals(modeText, "always", StringComparison.Ordinal))
			mode = TriggerMode.Always;
		else if (string.Equals(modeText, "animator_window", StringComparison.Ordinal)
		         && states != null && states.Length > 0
		         && TryReadFloatPair(trigger, "normalizedTime", out start, out end))
			mode = TriggerMode.AnimatorWindow;
		else
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' overlay trigger is always or animator_window with states and normalizedTime.");
			return false;
		}
		if (!TryReadOverlayTint(source["colors"], id, log, out var tintProps, out var tintValues))
			return false;
		parsed = new CatalogRow
		{
			Id = id,
			Lane = LaneBattleBodyOverlay,
			UnitSids = unitSids,
			NativeResPath = native.Trim(),
			OwnedPrefabKey = string.Empty,
			Trigger = mode,
			AnimatorStates = states,
			WindowStart = start,
			WindowEnd = end,
			Overlay = new OverlaySpec
			{
				RendererPath = ReadString(source, "rendererPath") ?? string.Empty,
				MaterialIndex = (int)indexToken,
				ColorProperties = tintProps,
				ColorValues = tintValues
			}
		};
		Homm3ImportVisuals.RegisterNativeResManagerCacheInterest(parsed.NativeResPath);
		return true;
	}

	/// <summary>source.colors: absent, or [{"property": "_Name", "rgba": [r, g, b, a]}] with distinct properties and
	/// finite components in [0, 16].</summary>
	private static bool TryReadOverlayTint(JToken token, string id, ManualLogSource log, out string[] properties, out Color[] values)
	{
		properties = Array.Empty<string>();
		values = Array.Empty<Color>();
		if (token == null)
			return true;
		var list = AsArray(token);
		if (list == null || list.Count == 0)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' overlay source.colors must be a non-empty array when present.");
			return false;
		}
		properties = new string[list.Count];
		values = new Color[list.Count];
		for (var i = 0; i < list.Count; i++)
		{
			var entry = AsObject(list[i]);
			var property = ReadString(entry, "property");
			var rgba = entry == null ? null : AsArray(entry["rgba"]);
			var ok = !string.IsNullOrWhiteSpace(property) && property.StartsWith("_", StringComparison.Ordinal)
			         && Array.IndexOf(properties, property) < 0 && rgba != null && rgba.Count == 4;
			var c = new float[4];
			for (var j = 0; ok && j < 4; j++)
			{
				ok = rgba[j].Type == JTokenType.Float || rgba[j].Type == JTokenType.Integer;
				c[j] = ok ? (float)rgba[j] : 0f;
				ok = ok && !float.IsNaN(c[j]) && c[j] >= 0f && c[j] <= 16f;
			}
			if (!ok)
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' overlay source.colors[" + i
				              + "] needs a distinct '_Property' and rgba of four numbers in [0, 16].");
				return false;
			}
			properties[i] = property;
			values[i] = new Color(c[0], c[1], c[2], c[3]);
		}
		return true;
	}

	private static bool TryParseVanillaStyle(JObject vs, string id, ManualLogSource log, out VanillaStyleSpec spec)
	{
		spec = null;
		if (vs == null)
			return false;
		var childPath = ReadString(vs, "childPath");
		var keepToken = AsArray(vs["keepNodes"]);
		if (string.IsNullOrEmpty(childPath) || keepToken == null || keepToken.Count == 0)
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle needs childPath and keepNodes.");
			return false;
		}
		// keepNodes may hold "" (the cloned root itself); ReadStringArray drops blanks, so read raw.
		var keep = new string[keepToken.Count];
		for (var i = 0; i < keepToken.Count; i++)
			keep[i] = keepToken[i]?.ToString() ?? string.Empty;
		var localToken = AsArray(vs["localScaleNodes"]);
		var local = new string[localToken?.Count ?? 0];
		for (var i = 0; i < local.Length; i++)
			local[i] = localToken[i]?.ToString() ?? string.Empty;
		var orient = ReadString(vs, "orient") ?? OrientBone;
		if (!string.Equals(orient, OrientBone, StringComparison.Ordinal)
		    && !string.Equals(orient, OrientEmitUp, StringComparison.Ordinal)
		    && !string.Equals(orient, OrientBody, StringComparison.Ordinal))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle unknown orient='" + orient + "'.");
			return false;
		}
		var follow = ReadString(vs, "follow") ?? FollowBone;
		if (!string.Equals(follow, FollowBone, StringComparison.Ordinal)
		    && !string.Equals(follow, FollowRelease, StringComparison.Ordinal))
		{
			log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle unknown follow='" + follow + "'.");
			return false;
		}
		var boneLocalRot = Quaternion.identity;
		if (vs["boneLocalRot"] is { } rotToken && rotToken.Type != JTokenType.Null)
		{
			var q = AsArray(rotToken);
			if (q == null || q.Count != 4 || string.Equals(orient, OrientBody, StringComparison.Ordinal))
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle boneLocalRot needs orient bone or emitUp and [x, y, z, w].");
				return false;
			}
			boneLocalRot = new Quaternion(
				TokenToFloat(q[0], 0f), TokenToFloat(q[1], 0f), TokenToFloat(q[2], 0f), TokenToFloat(q[3], 1f));
			var norm = Mathf.Sqrt(
				boneLocalRot.x * boneLocalRot.x + boneLocalRot.y * boneLocalRot.y
				+ boneLocalRot.z * boneLocalRot.z + boneLocalRot.w * boneLocalRot.w);
			if (Mathf.Abs(norm - 1f) > 1e-3f)
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle boneLocalRot is not a unit quaternion.");
				return false;
			}
		}
		var boneLocalPos = Vector3.zero;
		if (vs["boneLocalPos"] is { } posToken && posToken.Type != JTokenType.Null)
		{
			var p = AsArray(posToken);
			var posOk = p != null && p.Count == 3;
			var pc = new float[3];
			for (var j = 0; posOk && j < 3; j++)
			{
				posOk = p[j].Type == JTokenType.Float || p[j].Type == JTokenType.Integer;
				pc[j] = posOk ? (float)p[j] : 0f;
				posOk = posOk && !float.IsNaN(pc[j]) && !float.IsInfinity(pc[j]) && Mathf.Abs(pc[j]) <= 100f;
			}
			if (!posOk)
			{
				log?.LogError("Homm3MeshFx: id='" + id + "' vanillaStyle boneLocalPos needs [x, y, z] of finite numbers.");
				return false;
			}
			boneLocalPos = new Vector3(pc[0], pc[1], pc[2]);
		}
		var recolor = new List<RecolorSpec>();
		if (AsArray(vs["recolorNodes"]) is { } recolorToken)
		{
			for (var i = 0; i < recolorToken.Count; i++)
			{
				var r = AsObject(recolorToken[i]);
				if (r == null)
					continue;
				var gradient = AsObject(r["gradient"]);
				recolor.Add(new RecolorSpec
				{
					Node = r["node"]?.ToString() ?? string.Empty,
					GradientColor = gradient != null ? ReadFloatRows(gradient["color"], 4) : null,
					GradientAlpha = gradient != null ? ReadFloatRows(gradient["alpha"], 2) : null,
					MaterialColorMul = ReadVector3(r, "materialColorMul", Vector3.one)
				});
			}
		}
		spec = new VanillaStyleSpec
		{
			ChildPath = childPath,
			KeepNodes = keep,
			WorldScale = ReadFloat(vs, "worldScale", 1f),
			RateMul = ReadFloat(vs, "rateMul", 1f),
			Loop = ReadBool(vs, "loop", false),
			ZeroChildPositions = ReadBool(vs, "zeroChildPositions", false),
			Orient = orient,
			BodyYawDeg = ReadFloat(vs, "bodyYawDeg", 0f),
			BoneLocalRot = boneLocalRot,
			BoneLocalPos = boneLocalPos,
			AnchorNode = ReadString(vs, "anchorNode") ?? string.Empty,
			LocalScaleNodes = local,
			RecolorNodes = recolor.ToArray(),
			FollowRelease = string.Equals(follow, FollowRelease, StringComparison.Ordinal)
		};
		return true;
	}

	private static float[][] ReadFloatRows(JToken token, int width)
	{
		var rows = AsArray(token);
		if (rows == null || rows.Count == 0)
			return null;
		var result = new float[rows.Count][];
		for (var i = 0; i < rows.Count; i++)
		{
			var row = AsArray(rows[i]);
			if (row == null || row.Count != width)
				return null;
			result[i] = new float[width];
			for (var j = 0; j < width; j++)
				result[i][j] = TokenToFloat(row[j], 0f);
		}
		return result;
	}

	// A JSON null serialises to "" and Parse("") throws, which dropped the whole catalog in game
	// (2026-09-26, recolorNodes "gradient": null); non-objects read as absent, like AsArray.
	private static JObject AsObject(JToken token)
	{
		if (token == null || token.Type != JTokenType.Object)
			return null;
		return token as JObject ?? JObject.Parse(token.ToString());
	}

	// In game a bare `as JArray` / `is JArray` on a child token yields null (the catalog loads
	// through a different Newtonsoft identity than this assembly binds), so every array read
	// re-parses through the token text, like ReadStringArray. 2026-09-26: bare casts dropped every
	// vanillaStyle row ("needs childPath and keepNodes") and no particles rendered.
	private static JArray AsArray(JToken token)
	{
		if (token == null || token.Type != JTokenType.Array)
			return null;
		return token as JArray ?? JArray.Parse(token.ToString());
	}

	private static string ReadString(JToken parent, string property)
	{
		if (parent == null || string.IsNullOrEmpty(property))
			return null;
		var token = parent[property];
		if (token == null)
			return null;
		var text = token.ToString();
		return string.IsNullOrWhiteSpace(text) ? null : text.Trim();
	}

	private static bool ReadBool(JToken parent, string property, bool fallback)
	{
		var text = ReadString(parent, property);
		if (string.IsNullOrEmpty(text))
			return fallback;
		if (bool.TryParse(text, out var value))
			return value;
		return fallback;
	}

	private static string[] ReadStringArray(JToken parent, string property)
	{
		if (parent == null || string.IsNullOrEmpty(property))
			return Array.Empty<string>();
		var token = parent[property];
		var array = AsArray(token);
		if (array == null || array.Count == 0)
			return Array.Empty<string>();
		var list = new List<string>(array.Count);
		for (var i = 0; i < array.Count; i++)
		{
			var text = array[i]?.ToString();
			if (!string.IsNullOrWhiteSpace(text))
				list.Add(text.Trim());
		}
		return list.ToArray();
	}

	private static Vector3 ReadVector3(JToken parent, string property, Vector3 fallback)
	{
		if (parent == null || string.IsNullOrEmpty(property))
			return fallback;
		var token = parent[property];
		var array = AsArray(token);
		if (array == null || array.Count < 3)
			return fallback;
		return new Vector3(
			TokenToFloat(array[0], fallback.x),
			TokenToFloat(array[1], fallback.y),
			TokenToFloat(array[2], fallback.z));
	}

	private static float ReadFloat(JToken parent, string property, float fallback)
	{
		return parent == null ? fallback : TokenToFloat(parent[property], fallback);
	}

	// JValue.ToString() formats with the current culture; a numeric token converts invariantly.
	private static float TokenToFloat(JToken token, float fallback)
	{
		if (token == null)
			return fallback;
		if (token.Type == JTokenType.Float || token.Type == JTokenType.Integer)
			return (float)token;
		return ParseFloat(token.ToString(), fallback);
	}

	private static bool TryReadFloatPair(JToken parent, string property, out float a, out float b)
	{
		a = 0f;
		b = 1f;
		if (parent == null || string.IsNullOrEmpty(property))
			return false;
		var token = parent[property];
		if (token == null)
			return false;
		JArray array;
		try
		{
			array = token as JArray ?? JArray.Parse(token.ToString());
		}
		catch
		{
			return false;
		}
		if (array == null || array.Count < 2)
			return false;
		if (!Homm3JsonNumber.TryParseFloat(array[0]?.ToString(), out a))
			return false;
		if (!Homm3JsonNumber.TryParseFloat(array[1]?.ToString(), out b))
			return false;
		return true;
	}

	private static float ParseFloat(string text, float fallback)
	{
		if (string.IsNullOrEmpty(text))
			return fallback;
		return Homm3JsonNumber.TryParseFloat(text, out var value)
			? value
			: fallback;
	}

	private static List<string> CollectSkinnedMatchSids(Homm3ImportVisuals.Entry entry)
	{
		var sids = new List<string>();
		if (entry?.GameUnitSids != null)
		{
			for (var i = 0; i < entry.GameUnitSids.Count; i++)
			{
				var sid = entry.GameUnitSids[i];
				if (!string.IsNullOrWhiteSpace(sid) && !ContainsIgnoreCase(sids, sid))
					sids.Add(sid.Trim());
			}
		}
		var lab = TryLabSidFromBattlePrefab(entry?.BattlePrefabAssetPath);
		if (!string.IsNullOrEmpty(lab) && !ContainsIgnoreCase(sids, lab))
			sids.Add(lab);
		return sids;
	}

	private static string TryLabSidFromBattlePrefab(string battlePrefabAssetPath)
	{
		if (string.IsNullOrWhiteSpace(battlePrefabAssetPath))
			return null;
		var normalized = battlePrefabAssetPath.Replace('\\', '/');
		const string marker = "/homm3_lab/";
		var index = normalized.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (index < 0)
			return null;
		var rest = normalized.Substring(index + marker.Length);
		var slash = rest.IndexOf('/');
		var leaf = slash >= 0 ? rest.Substring(0, slash) : rest;
		return string.IsNullOrWhiteSpace(leaf) ? null : leaf.Trim();
	}

	private static bool SidListIntersects(string[] catalogSids, List<string> liveSids)
	{
		if (catalogSids == null || liveSids == null)
			return false;
		for (var i = 0; i < catalogSids.Length; i++)
		{
			if (ContainsIgnoreCase(liveSids, catalogSids[i]))
				return true;
		}
		return false;
	}

	private static bool ContainsIgnoreCase(List<string> list, string value)
	{
		if (list == null || string.IsNullOrEmpty(value))
			return false;
		for (var i = 0; i < list.Count; i++)
		{
			if (string.Equals(list[i], value, StringComparison.OrdinalIgnoreCase))
				return true;
		}
		return false;
	}

	private static void DestroyNamedDescendant(Transform root, string objectName)
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

	private static void SetLayerRecursive(GameObject root, int layer)
	{
		if (!root)
			return;
		var transforms = root.GetComponentsInChildren<Transform>(true);
		if (transforms == null)
			return;
		for (var i = 0; i < transforms.Length; i++)
		{
			if (transforms[i])
				transforms[i].gameObject.layer = layer;
		}
	}

	private static void EnsureTypeRegistered(ManualLogSource log)
	{
		if (_typeRegistered)
			return;
		ClassInjector.RegisterTypeInIl2Cpp<Homm3MeshFxHost>();
		_typeRegistered = true;
		log?.LogInfo("Homm3MeshFx: registered Il2Cpp host type.");
	}
}

public sealed class Homm3MeshFxHost : MonoBehaviour
{
	public Homm3MeshFxHost(IntPtr ptr)
		: base(ptr)
	{
	}

	private void LateUpdate()
	{
		Homm3MeshFx.Tick(this);
	}

	private void OnDestroy()
	{
		Homm3MeshFx.Unregister(this);
	}
}
