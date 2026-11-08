using System;
using System.Collections.Generic;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Size and ground placement of an owned skinned unit in every UI unit preview (detail window, town hire screen,
/// <c>BhUnitPreviews</c> pool). One rule for every lane: the battle fit.
/// <para>
/// Native framing (Mono demo Hex.dll; Golden Era keeps the same shape under drifted names): <c>UiModelsSpawner.Spawn</c>
/// instantiates the battle prefab at world scale 1, writes <c>sign * UnitViewConfig.scale</c> onto the prefab's first
/// child, and <c>BhUnitPreviews.LoadModel</c> / <c>BhUnitWindowPreview.SpawnModel</c> /
/// <c>BhHireUnitItemView.PresetModels</c> repeat that first-child write and put the model root at
/// <c>localPosition = 0</c>. One fixed camera (<c>UiConstants.UnitCamParams</c>) frames every unit; there is no bounds
/// framing. A vanilla unit therefore stands in the preview at its battle size, feet on the model root.
/// </para>
/// <para>
/// Owned rule: world height = <c>battleHeightHexes * battleWorldHeightPerHex</c> through
/// <see cref="Homm3ImportVisuals.FitSkinnedBattleMesh"/> (the exact battle fit, so preview and battle cannot drift),
/// lowest idle-0 vertex planted on the model root. The plant lives on the Orientation / MocapDeliveryRoot wrap, not
/// the root, because native zeroes the root position after we return; the native first-child scale write is applied
/// before the fit so its later repeat is idempotent. Never the donor's height or bounds (the retired rule sized the
/// detail window to whatever stock prefab was the donor, and the pool to raw bundle size times the donor-copied view
/// scale: 0.13x to 87x the battle size). No donor fallback: a unit without <c>battleHeightHexes</c> or a wrap node
/// is refused with an error.
/// </para>
/// Contract: tools/validate_homm3_owned_preview_framing_contract.py; fleet measurement
/// tools/homm3_import/measure_owned_preview_framing.py (generated artifact; runtime look unproven until an in-game check).
/// </summary>
internal static class Homm3OwnedSkinnedPreviewFraming
{
	private static int _logged;

	/// <summary>
	/// Frame <paramref name="skinned"/> in its preview rig.
	/// </summary>
	/// <param name="nativeModel">The rig's native 3D model this mesh replaces (its local pose and scale_roll facing are
	/// taken), or null when there is none (synthetic supply, or re-framing an owned model already in the rig).</param>
	/// <param name="keepPose">Re-framing an owned model already in the rig: keep its root rotation and wrap facing.</param>
	/// <param name="nativeFirstChildScale">The view scale native writes on the prefab's first child after this call
	/// returns (synthetic loader supply), or 0 when no such write follows.</param>
	internal static bool TryFrame(
		GameObject skinned,
		Homm3ImportVisuals.Entry entry,
		GameObject nativeModel,
		bool keepPose,
		float nativeFirstChildScale,
		string lane,
		ManualLogSource log)
	{
		if (!skinned)
			return false;
		var root = skinned.transform;
		if (entry == null || !entry.BattleHeightHexes.HasValue)
		{
			log?.LogError(
				"Homm3Import skinned preview framing (" + lane + "): '" + (skinned.name ?? "?")
				+ "' has no homm3_import battleHeightHexes; refusing to size the preview from a donor.");
			return false;
		}

		var wrap = FindWrap(root);
		if (!wrap)
		{
			log?.LogError(
				"Homm3Import skinned preview framing (" + lane + "): '" + (skinned.name ?? "?")
				+ "' has no Orientation/MocapDeliveryRoot child to plant on; preview left unframed.");
			return false;
		}

		var useNative = nativeModel
		                && nativeModel.GetInstanceID() != skinned.GetInstanceID()
		                && !Homm3ImportVisuals.LooksLikeHomm3BillboardPreviewDonor(nativeModel);
		var savedFacing = keepPose ? CaptureWrapRotations(root) : null;

		if (nativeFirstChildScale > 0f && !float.IsNaN(nativeFirstChildScale) && !float.IsInfinity(nativeFirstChildScale)
		    && root.childCount > 0)
		{
			var first = root.GetChild(0);
			var s = first.localScale;
			first.localScale = new Vector3(Mathf.Sign(s.x), Mathf.Sign(s.y), Mathf.Sign(s.z)) * nativeFirstChildScale;
		}

		// Battle fit: localScale 1, wrap yaw zeroed, idle t=0 sampled, world height = hexes * perHex.
		Homm3ImportVisuals.FitSkinnedBattleMesh(null, skinned, entry, log);

		if (useNative)
		{
			root.localPosition = nativeModel.transform.localPosition;
			root.localRotation = nativeModel.transform.localRotation;
			Homm3ImportVisuals.TryApplyOwnedSkinnedNativeModelFacing(nativeModel, skinned, "preview", log);
		}
		else if (keepPose)
		{
			root.localPosition = Vector3.zero;
			RestoreWrapRotations(savedFacing);
		}
		else
		{
			root.localPosition = Vector3.zero;
			root.localRotation = Quaternion.identity;
			Homm3ImportVisuals.TryApplyOwnedSkinnedBattlePrefabFacing(skinned, "preview-synthetic", log);
		}

		// Feet on the model root, as native units stand. Preview roots only ever turn about Y (native yaw 22 /
		// user drag), so world up is the root's up.
		if (!Homm3ImportVisuals.TryGetRenderableWorldBounds(skinned, out var bounds) || bounds.size.y < 1e-4f)
		{
			log?.LogError("Homm3Import skinned preview framing (" + lane + "): '" + (skinned.name ?? "?") + "' has no measurable bounds after the fit.");
			return false;
		}
		var plant = root.position.y - bounds.min.y;
		wrap.position += Vector3.up * plant;

		if (_logged < 32)
		{
			_logged++;
			log?.LogInfo(
				"Homm3Import skinned preview framing (" + lane + "): entry='" + (entry.BattleResPath ?? "?")
				+ "' hexes=" + entry.BattleHeightHexes.Value.ToString("F3")
				+ " worldY=" + bounds.size.y.ToString("F3")
				+ " rootScale=" + root.localScale.x.ToString("F4")
				+ " firstChildScale=" + (nativeFirstChildScale > 0f ? nativeFirstChildScale.ToString("0.###") : "kept")
				+ " plant=" + plant.ToString("F3")
				+ " pose=" + (useNative ? "native-model" : keepPose ? "kept" : "synthetic") + ".");
		}
		return true;
	}

	/// <summary>The wrap every owned prefab carries as a direct child; it holds the bones (import contract).</summary>
	private static Transform FindWrap(Transform root)
	{
		Transform fallback = null;
		for (var i = 0; i < root.childCount; i++)
		{
			var c = root.GetChild(i);
			if (!c)
				continue;
			if (string.Equals(c.name, "Orientation", StringComparison.Ordinal))
				return c;
			if (!fallback && string.Equals(c.name, "MocapDeliveryRoot", StringComparison.Ordinal))
				fallback = c;
		}
		return fallback;
	}

	private static List<KeyValuePair<Transform, Quaternion>> CaptureWrapRotations(Transform root)
	{
		var saved = new List<KeyValuePair<Transform, Quaternion>>();
		foreach (var t in root.GetComponentsInChildren<Transform>(true))
		{
			if (t && t != root
			      && (string.Equals(t.name, "Orientation", StringComparison.Ordinal)
			          || string.Equals(t.name, "MocapDeliveryRoot", StringComparison.Ordinal)))
				saved.Add(new KeyValuePair<Transform, Quaternion>(t, t.localRotation));
		}
		return saved;
	}

	private static void RestoreWrapRotations(List<KeyValuePair<Transform, Quaternion>> saved)
	{
		if (saved == null)
			return;
		foreach (var kv in saved)
		{
			if (kv.Key)
				kv.Key.localRotation = kv.Value;
		}
	}
}
