using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using Il2CppInterop.Runtime;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Gives owned skinned HoMM3 battle instances the native unit view helper (mono <c>BhUnitViewHelper</c>,
/// live type pinned in <see cref="GameSymbols.BattleVisual.UnitViewHelperTypeNames"/>).
///
/// Why: <c>ProjectilesProcessor.TrySpawnProjectile</c> needs <c>owner.GetViewHelper().projectileSpawnPoint</c>
/// and logs "Caster's ViewHelper not found" (no projectile) without it; the target end is
/// <c>target.meshHolder.GetComponent&lt;helper&gt;().projectileEndPoint</c>; buff / spawn-point effects read
/// shieldPoint (<c>BattleEffectSpawner.GetParentTransformByEnum</c>). Owned skinned prefabs carry no helper, and
/// the drawer captured its helper in <c>Init</c> from the pooled meshHolder (the <c>unit_cutout</c> stand-in when
/// the bundle path is a "Missing prefab"), so the drawer slot is written as well
/// (<see cref="GameSymbols.BattleVisual.DrawerViewHelperMembers"/>).
///
/// Points come from the unit's own skeleton: spawn on the right hand (left if the rig has no right), end and
/// shield on the chest (Spine2, else Spine1, else Spine). meshRenderer and idleVFX stay unset: every native
/// consumer null-checks them, and setting meshRenderer would let vanilla hit timelines append materials to the
/// owned skin. A rig without a hand or chest bone, or an unresolved helper type, gets no helper and one error
/// log per unit; nothing is guessed. Proof: source/static only until a runtime record shows a projectile.
/// </summary>
internal static class Homm3UnitViewHelperRuntime
{
	internal const string SpawnPointName = "__homm3_projectile_spawn__";
	internal const string EndPointName = "__homm3_projectile_end__";
	internal const string ShieldPointName = "__homm3_shield_point__";

	private static readonly string[] SpawnBoneNames = { "RightHand", "LeftHand" };
	private static readonly string[] ChestBoneNames = { "Spine2", "Spine1", "Spine" };
	private static readonly string[] PointProperties = { "projectileSpawnPoint", "projectileEndPoint", "shieldPoint" };

	private static Type _helperType;
	private static bool _helperTypeResolved;
	private static readonly HashSet<string> Logged = new(StringComparer.Ordinal);

	internal static Type ResolveHelperType(ManualLogSource log)
	{
		if (_helperTypeResolved)
			return _helperType;
		_helperTypeResolved = true;
		var type = GameMember.FindTypeFromHints("battle.visual.unitViewHelper", GameSymbols.BattleVisual.UnitViewHelperTypeNames);
		if (type == null)
		{
			log?.LogError("Homm3 unit view helper: no type in GameSymbols.BattleVisual.UnitViewHelperTypeNames resolved; owned skinned units will not spawn projectiles.");
			return null;
		}
		foreach (var name in PointProperties)
		{
			var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
			if (prop == null || prop.PropertyType != typeof(Transform) || !prop.CanWrite)
			{
				log?.LogError("Homm3 unit view helper: resolved " + type.FullName + " has no writable Transform '" + name + "'; refusing it (stale pin).");
				return null;
			}
		}
		if (!typeof(Component).IsAssignableFrom(type))
		{
			log?.LogError("Homm3 unit view helper: resolved " + type.FullName + " is not a Component; refusing it (stale pin).");
			return null;
		}
		_helperType = type;
		return type;
	}

	/// <summary>Adds (or reuses) the helper on the instance root and places its points. Null when refused (logged).</summary>
	internal static Component TryEnsure(GameObject instance, string unitKey, ManualLogSource log)
	{
		if (!instance)
			return null;
		var type = ResolveHelperType(log);
		if (type == null)
			return null;
		var key = unitKey ?? instance.name;
		var spawnBone = FindBone(instance.transform, SpawnBoneNames);
		var chestBone = FindBone(instance.transform, ChestBoneNames);
		if (spawnBone == null || chestBone == null)
		{
			LogOnce(log, "bones:" + key, true,
				"Homm3 unit view helper: '" + key + "' has no " + (spawnBone == null ? "hand bone (" + string.Join("/", SpawnBoneNames) + ")" : "chest bone (" + string.Join("/", ChestBoneNames) + ")")
				+ "; no helper attached, so this unit cannot spawn or receive projectiles at a body point.");
			return null;
		}
		try
		{
			var il2CppType = Il2CppType.From(type);
			var native = instance.GetComponent(il2CppType) ?? instance.AddComponent(il2CppType);
			if (native == null)
			{
				LogOnce(log, "add:" + key, true, "Homm3 unit view helper: AddComponent(" + type.FullName + ") returned null for '" + key + "'.");
				return null;
			}
			var helper = (Component)Activator.CreateInstance(type, native.Pointer);
			type.GetProperty("projectileSpawnPoint").SetValue(helper, EnsurePoint(spawnBone, SpawnPointName));
			type.GetProperty("projectileEndPoint").SetValue(helper, EnsurePoint(chestBone, EndPointName));
			type.GetProperty("shieldPoint").SetValue(helper, EnsurePoint(chestBone, ShieldPointName));
			LogOnce(log, "ok:" + key, false,
				"Homm3 unit view helper: '" + key + "' spawn=" + spawnBone.name + " end/shield=" + chestBone.name + " type=" + type.Name + ".");
			return helper;
		}
		catch (Exception ex)
		{
			LogOnce(log, "ex:" + key, true, "Homm3 unit view helper: attach failed for '" + key + "': " + ex.Message);
			return null;
		}
	}

	/// <summary>Writes the helper into the drawer's view-helper slot (captured at Init from the pooled meshHolder).</summary>
	internal static bool TryBindDrawer(object drawer, Component helper, string unitSid, ManualLogSource log)
	{
		if (drawer == null || helper == null)
			return false;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		var helperType = helper.GetType();
		for (var type = drawer.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in GameSymbols.BattleVisual.DrawerViewHelperMembers)
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.CanWrite && prop.GetIndexParameters().Length == 0 && prop.PropertyType.IsAssignableFrom(helperType))
				{
					prop.SetValue(drawer, helper);
					return true;
				}
				var field = type.GetField(name, flags);
				if (field != null && field.FieldType.IsAssignableFrom(helperType))
				{
					field.SetValue(drawer, helper);
					return true;
				}
			}
		}
		LogOnce(log, "drawer:" + drawer.GetType().FullName, true,
			"Homm3 unit view helper: drawer " + drawer.GetType().FullName + " has no view-helper slot in GameSymbols.BattleVisual.DrawerViewHelperMembers; '"
			+ (unitSid ?? "?") + "' keeps the pooled stand-in's helper and will not shoot.");
		return false;
	}

	private static Transform EnsurePoint(Transform bone, string name)
	{
		var existing = bone.Find(name);
		if (existing != null && existing)
			return existing;
		var go = new GameObject(name);
		go.transform.SetParent(bone, false);
		go.transform.localPosition = Vector3.zero;
		go.transform.localRotation = Quaternion.identity;
		return go.transform;
	}

	private static Transform FindBone(Transform root, string[] names)
	{
		var all = root.GetComponentsInChildren<Transform>(true);
		foreach (var wanted in names)
		{
			foreach (var t in all)
			{
				if (t == null || !t)
					continue;
				var n = t.name;
				if (string.Equals(n, wanted, StringComparison.Ordinal) || n.EndsWith(":" + wanted, StringComparison.Ordinal))
					return t;
			}
		}
		return null;
	}

	private static void LogOnce(ManualLogSource log, string key, bool error, string message)
	{
		if (log == null || !Logged.Add(key))
			return;
		if (error)
			log.LogError(message);
		else
			log.LogInfo(message);
	}
}
