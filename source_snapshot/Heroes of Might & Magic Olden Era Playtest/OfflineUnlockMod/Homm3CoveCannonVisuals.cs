using System;
using System.Collections.Generic;
using System.IO;
using BepInEx;
using BepInEx.Logging;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3CoveCannonVisuals
{
	internal const string UnitSid = "h3_cannon";
	internal const string BattleUnitVisualName = "HOMM3_COVE_CANNON_UNIT";
	const string ProjectileMarker = "HOMM3_COVE_CANNON_PROJECTILE";
	const string CannonFrameRelativePath = "homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/02_00.png";
	const string ProjectileFrameRelativePath = "homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcanx.dir/00_00.png";
	const float CannonBattleUnitHeightWorld = 12.8f;
	const float CannonBattleUnitVerticalOffsetWorld = 2.0f;
	const float ProjectileHeightWorld = 0.42f;
	static readonly string[] CannonAttackFrameRelativePaths =
	{
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_00.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_01.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_02.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_03.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_04.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_05.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_06.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_07.png",
		"homm3_runtime_assets/cannon/homm3_cove/sprites/hota/battle/smcannon.dir/04_08.png",
	};
	static Texture2D _cannonTexture;
	static Texture2D _projectileTexture;
	static Texture2D[] _cannonAttackTextures;
	static readonly List<Homm3CoveCannonBattleAnimator> BattleAnimators = new();
	static readonly List<CannonTransferIdentity> CannonTransferIdentities = new();
	static int _loggedShow;
	static int _loggedFailure;

	internal static bool TryPresentShot(GameObject projectileShell, ManualLogSource log)
	{
		if (!projectileShell)
			return false;
		var cannonOk = TryPlayShootAnimationNear(projectileShell.transform.position, log);
		var projectileOk = TryAttachProjectileFrame(projectileShell, log);
		return cannonOk || projectileOk;
	}

	internal static bool TryCreateBattleUnitVisual(GameObject nativeVisual, GameObject host, ManualLogSource log, out GameObject visual)
	{
		visual = null;
		var texture = LoadTexture(CannonFrameRelativePath, ref _cannonTexture, log);
		if (!texture)
			return false;
		visual = CreateBillboardRoot(BattleUnitVisualName, texture, CannonBattleUnitHeightWorld, log, CannonBattleUnitVerticalOffsetWorld);
		if (!visual)
			return false;
		TryAttachBattleAnimator(visual, texture, log);
		if (nativeVisual)
		{
			visual.transform.SetParent(nativeVisual.transform.parent, false);
			visual.transform.localPosition = nativeVisual.transform.localPosition;
			visual.transform.localRotation = nativeVisual.transform.localRotation;
			visual.transform.localScale = nativeVisual.transform.localScale;
			SetLayerRecursive(visual, nativeVisual.layer);
		}
		else if (host)
		{
			visual.transform.SetParent(host.transform, false);
			visual.transform.localPosition = Vector3.zero;
			visual.transform.localRotation = Quaternion.identity;
			visual.transform.localScale = Vector3.one;
			SetLayerRecursive(visual, nativeVisual ? nativeVisual.layer : host.layer);
		}
		Homm3BattleBillboardCameraFacing.TryAttach(visual, log);
		if (_loggedShow < 8)
		{
			_loggedShow++;
			log?.LogInfo("Homm3 Cove Cannon: created HotA cannon battle unit visual.");
		}
		return true;
	}

	internal static bool IsCannonVisualRoot(GameObject root)
	{
		if (!root)
			return false;
		if (string.Equals(root.name, BattleUnitVisualName, StringComparison.Ordinal))
			return true;
		try
		{
			var animator = root.GetComponent<Homm3CoveCannonBattleAnimator>()
			               ?? root.GetComponentInChildren<Homm3CoveCannonBattleAnimator>(true);
			return animator != null && animator;
		}
		catch
		{
			return false;
		}
	}

	internal static void RememberBattleTransfer(TransferUnit transfer, GameObject visualRoot)
	{
		var pointer = GetIl2CppPointer(transfer);
		if (pointer == IntPtr.Zero || !visualRoot)
			return;
		PruneRememberedBattleTransfers();
		for (var i = 0; i < CannonTransferIdentities.Count; i++)
		{
			if (CannonTransferIdentities[i].TransferPointer != pointer)
				continue;
			CannonTransferIdentities[i].VisualRoot = visualRoot;
			return;
		}
		CannonTransferIdentities.Add(new CannonTransferIdentity(pointer, visualRoot));
		while (CannonTransferIdentities.Count > 64)
			CannonTransferIdentities.RemoveAt(0);
	}

	internal static bool TryResolveRememberedUnitSid(object transfer, out string sid)
	{
		sid = null;
		var pointer = GetIl2CppPointer(transfer);
		if (pointer == IntPtr.Zero)
			return false;
		PruneRememberedBattleTransfers();
		for (var i = 0; i < CannonTransferIdentities.Count; i++)
		{
			var identity = CannonTransferIdentities[i];
			if (identity.TransferPointer != pointer)
				continue;
			sid = UnitSid;
			return true;
		}
		return false;
	}

	internal static bool TryPlayShootAnimationNear(Vector3 projectileStartPosition, ManualLogSource log)
	{
		Homm3CoveCannonBattleAnimator best = null;
		var bestDistanceSq = 10000f;
		for (var i = BattleAnimators.Count - 1; i >= 0; i--)
		{
			var animator = BattleAnimators[i];
			if (!animator || !animator.gameObject)
			{
				BattleAnimators.RemoveAt(i);
				continue;
			}
			var distanceSq = (animator.transform.position - projectileStartPosition).sqrMagnitude;
			if (distanceSq < bestDistanceSq)
			{
				bestDistanceSq = distanceSq;
				best = animator;
			}
		}
		if (!best || bestDistanceSq > 36f)
			return false;
		return best.PlayShoot();
	}

	internal static bool TryPlayShootAnimation(GameObject battleRoot, ManualLogSource log)
	{
		if (!battleRoot)
			return false;
		try
		{
			var animator = battleRoot.GetComponent<Homm3CoveCannonBattleAnimator>()
			               ?? battleRoot.GetComponentInChildren<Homm3CoveCannonBattleAnimator>(true);
			return animator != null && animator && animator.PlayShoot();
		}
		catch (Exception ex)
		{
			LogFailure(log, "battle shoot animator trigger failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	static bool TryAttachProjectileFrame(GameObject projectileShell, ManualLogSource log)
	{
		if (!projectileShell)
			return false;
		if (projectileShell.transform.Find(ProjectileMarker) != null)
			return true;
		var texture = LoadTexture(ProjectileFrameRelativePath, ref _projectileTexture, log);
		if (!texture)
			return false;
		foreach (var renderer in projectileShell.GetComponentsInChildren<Renderer>(true))
		{
			if (renderer && renderer.transform && renderer.transform.GetComponentInParent<Transform>() != null)
				renderer.enabled = false;
		}
		var root = CreateBillboardRoot(ProjectileMarker, texture, ProjectileHeightWorld, log);
		if (!root)
			return false;
		root.transform.SetParent(projectileShell.transform, false);
		root.transform.localPosition = Vector3.zero;
		root.transform.localRotation = Quaternion.identity;
		SetLayerRecursive(root, projectileShell.layer);
		Homm3BattleBillboardCameraFacing.TryAttach(root, log);
		if (_loggedShow < 8)
		{
			_loggedShow++;
			log?.LogInfo("Homm3 Cove Cannon: attached HotA cannon projectile frame to shell '" + (projectileShell.name ?? "?") + "'.");
		}
		return true;
	}

	static GameObject CreateBillboardRoot(string name, Texture2D texture, float heightWorld, ManualLogSource log, float verticalOffsetWorld = 0f)
	{
		var material = CreateMaterial(texture, name + "_mat", log);
		if (!material)
			return null;
		var root = new GameObject(name);
		var billboard = new GameObject("billboard");
		billboard.transform.SetParent(root.transform, false);
		if (Math.Abs(verticalOffsetWorld) > 0.0001f)
			billboard.transform.localPosition = Vector3.up * verticalOffsetWorld;
		var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
		quad.name = "quad";
		quad.transform.SetParent(billboard.transform, false);
		var renderer = quad.GetComponent<MeshRenderer>();
		if (!renderer)
		{
			UnityEngine.Object.Destroy(root);
			return null;
		}
		renderer.sharedMaterial = material;
		var aspect = texture.height > 0 ? (float)texture.width / texture.height : 1f;
		quad.transform.localScale = new Vector3(heightWorld * aspect, heightWorld, 1f);
		return root;
	}

	static void TryAttachBattleAnimator(GameObject visual, Texture2D idleTexture, ManualLogSource log)
	{
		try
		{
			if (!visual || !idleTexture)
				return;
			var renderer = visual.GetComponentInChildren<MeshRenderer>(true);
			if (!renderer || !renderer.sharedMaterial)
				return;
			var frames = LoadAttackTextures(log);
			if (frames == null || frames.Length == 0)
				return;
			if (!Homm3CoveCannonBattleAnimator.EnsureRegistered(log))
				return;
			var animator = visual.AddComponent<Homm3CoveCannonBattleAnimator>();
			animator.Init(renderer.sharedMaterial, idleTexture, frames);
			BattleAnimators.Add(animator);
		}
		catch (Exception ex)
		{
			LogFailure(log, "battle shoot animator attach failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	static Texture2D[] LoadAttackTextures(ManualLogSource log)
	{
		if (_cannonAttackTextures != null)
			return _cannonAttackTextures;
		var frames = new List<Texture2D>(CannonAttackFrameRelativePaths.Length);
		for (var i = 0; i < CannonAttackFrameRelativePaths.Length; i++)
		{
			Texture2D texture = null;
			texture = LoadTexture(CannonAttackFrameRelativePaths[i], ref texture, log);
			if (texture)
				frames.Add(texture);
		}
		_cannonAttackTextures = frames.ToArray();
		return _cannonAttackTextures;
	}

	static Material CreateMaterial(Texture2D texture, string name, ManualLogSource log)
	{
		var shader = Shader.Find("Sprites/Default");
		if (!shader)
		{
			LogFailure(log, "Shader.Find(\"Sprites/Default\") failed for Cove Cannon visuals.");
			return null;
		}
		var material = new Material(shader)
		{
			name = name,
			mainTexture = texture,
			renderQueue = 3000
		};
		if (material.HasProperty("_MainTex"))
			material.SetTexture("_MainTex", texture);
		if (material.HasProperty("_Color"))
			material.SetColor("_Color", Color.white);
		return material;
	}

	static Texture2D LoadTexture(string relativePath, ref Texture2D cache, ManualLogSource log)
	{
		if (cache)
			return cache;
		var path = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", relativePath.Replace('/', Path.DirectorySeparatorChar));
		if (!File.Exists(path))
		{
			LogFailure(log, "missing Cove Cannon frame: " + path);
			return null;
		}
		try
		{
			var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			if (!Homm3ImportVisuals.TryLoadTextureImage(texture, File.ReadAllBytes(path)))
			{
				UnityEngine.Object.Destroy(texture);
				LogFailure(log, "failed loading Cove Cannon frame image: " + path);
				return null;
			}
			texture.name = Path.GetFileNameWithoutExtension(path);
			texture.filterMode = FilterMode.Point;
			texture.wrapMode = TextureWrapMode.Clamp;
			cache = texture;
			return cache;
		}
		catch (Exception ex)
		{
			LogFailure(log, "failed reading Cove Cannon frame '" + path + "': " + ex.Message);
			return null;
		}
	}

	static void SetLayerRecursive(GameObject root, int layer)
	{
		if (!root)
			return;
		root.layer = layer;
		foreach (var child in root.GetComponentsInChildren<Transform>(true))
		{
			if (child && child.gameObject)
				child.gameObject.layer = layer;
		}
	}

	static void PruneRememberedBattleTransfers()
	{
		for (var i = CannonTransferIdentities.Count - 1; i >= 0; i--)
		{
			var identity = CannonTransferIdentities[i];
			if (identity.TransferPointer == IntPtr.Zero || !identity.VisualRoot)
				CannonTransferIdentities.RemoveAt(i);
		}
	}

	static IntPtr GetIl2CppPointer(object value)
	{
		return value is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero
			? il2Cpp.Pointer
			: IntPtr.Zero;
	}

	sealed class CannonTransferIdentity
	{
		internal readonly IntPtr TransferPointer;
		internal GameObject VisualRoot;

		internal CannonTransferIdentity(IntPtr transferPointer, GameObject visualRoot)
		{
			TransferPointer = transferPointer;
			VisualRoot = visualRoot;
		}
	}

	static void LogFailure(ManualLogSource log, string message)
	{
		if (_loggedFailure >= 8)
			return;
		_loggedFailure++;
		log?.LogWarning("Homm3 Cove Cannon: " + message);
	}
}

public sealed class Homm3CoveCannonBattleAnimator : MonoBehaviour
{
	const float FrameSeconds = 0.055f;
	static bool _typeRegistered;
	Material _material;
	Texture2D _idleTexture;
	Texture2D[] _shootFrames;
	float _elapsed;
	float _lastPlayRealtime = -100f;
	int _index;
	bool _playing;

	public Homm3CoveCannonBattleAnimator(IntPtr ptr) : base(ptr) { }

	internal static bool EnsureRegistered(ManualLogSource log)
	{
		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3CoveCannonBattleAnimator>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 Cove Cannon: registered battle animator Il2Cpp type.");
			}
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 Cove Cannon: battle animator Il2Cpp type registration failed: " + ex.GetType().Name + ": " + ex.Message);
			return false;
		}
	}

	internal void Init(Material material, Texture2D idleTexture, Texture2D[] shootFrames)
	{
		_material = material;
		_idleTexture = idleTexture;
		_shootFrames = shootFrames;
		SetTexture(_idleTexture);
	}

	internal bool PlayShoot()
	{
		if (_shootFrames == null || _shootFrames.Length == 0 || !_material)
			return false;
		var now = Time.realtimeSinceStartup;
		if (_playing || now - _lastPlayRealtime < 0.35f)
			return false;
		_lastPlayRealtime = now;
		_playing = true;
		_elapsed = 0f;
		_index = 0;
		SetTexture(_shootFrames[0]);
		return true;
	}

	void LateUpdate()
	{
		if (!_playing || _shootFrames == null || _shootFrames.Length == 0 || !_material)
			return;
		_elapsed += Time.deltaTime;
		while (_elapsed >= FrameSeconds)
		{
			_elapsed -= FrameSeconds;
			_index++;
			if (_index >= _shootFrames.Length)
			{
				_playing = false;
				SetTexture(_idleTexture);
				return;
			}
			SetTexture(_shootFrames[_index]);
		}
	}

	void OnDisable()
	{
		_playing = false;
		SetTexture(_idleTexture);
	}

	void SetTexture(Texture texture)
	{
		if (!_material || !texture)
			return;
		if (_material.HasProperty("_MainTex"))
			_material.SetTexture("_MainTex", texture);
		_material.mainTexture = texture;
	}
}
