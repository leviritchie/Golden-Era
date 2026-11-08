using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Rebinds generated HoMM3 battle billboard frame materials to the disk frames for the resolved lab unit.
/// This keeps alternate-upgrade battle sprites from inheriting stale donor/generated material textures.
/// </summary>
public sealed class Homm3BattleDiskTextureRemap : MonoBehaviour
{
	private const int GroupIdle = 2;
	private const int GroupMovement = 0;
	private const int GroupMouseOver = 1;
	private const int GroupHitted = 3;
	private const int GroupDeath = 5;
	private const int GroupAttackUp = 11;
	private const int GroupAttackFront = 12;
	private const int GroupAttackDown = 13;
	private const int GroupShootUp = 14;
	private const int GroupShootFront = 15;
	private const int GroupShootDown = 16;
	private const int GroupTeleportLeave = 20;
	private const int GroupTeleportArrive = 21;
	private const int NonDirectionalGroup = -1;

	private static readonly int[] FixedGroupOrder = { GroupIdle, GroupMovement, GroupHitted, GroupDeath };
	private static readonly int[] MovementGroupPreference = { GroupMovement, GroupMouseOver };
	private static readonly string[] BillboardTextureProperties =
	{
		"_MainTex",
		"_BaseMap",
		"_BaseColorMap",
		"_AlbedoMap",
		"_DiffuseMap",
		"_MainTexture",
		"_EmissionTex",
		"_EmissionMap"
	};
	private static readonly HashSet<string> TeleportDiveMovementLabSids = new(StringComparer.Ordinal)
	{
		"hota_cove_nymph",
		"hota_cove_oceanid",
		"hota_cove_nereid",
	};
	/// <summary>
	/// HotA stores these Factory battle animations as palette-keyed cyan PNG
	/// sequences, not alpha-bearing DEF frames. They must bypass baked textures.
	/// </summary>
	private static readonly HashSet<string> CyanKeyedFactoryLabSids = new(StringComparer.Ordinal)
	{
		"hota_factory_sandworm",
		"hota_factory_olgoi_khorkhoi",
		"h3_sandworm_upg_alt",
		"hota_factory_dreadnought",
		"hota_factory_juggernaut",
		"h3_dreadnought_upg_alt",
		"hota_factory_sandworm_larva",
	};
	private static readonly int[] MeleeAttackGroupPreference = { GroupAttackFront, GroupAttackUp, GroupAttackDown };
	private static readonly int[] ShootAttackGroupPreference = { GroupShootFront, GroupShootUp, GroupShootDown };
	private static readonly Dictionary<string, BattleFrameSet> FramesByLabSid = new(StringComparer.Ordinal);
	private static bool LooseHomm3LabFramePngFallbackEnabled => false;
	private static bool _typeRegistered;
	private static int _attachDiagRemaining = 16;
	private static int _missDiagRemaining = 16;
	private static int _tickDiagRemaining = 16;
	private static int _directionDiagRemaining = 12;
	private static int _activeAttackFrameDiagRemaining = 24;

	private sealed class BattleFrameSet
	{
		internal Texture2D[] OrderedFrames;
		internal int AttackStartIndex = -1;
		internal int AttackLength;
		internal int BaseAttackGroup = GroupAttackFront;
		internal readonly Dictionary<int, Texture2D[]> AttackFramesByGroup = new();

		internal bool HasAttackFrames =>
			OrderedFrames != null
			&& AttackStartIndex >= 0
			&& AttackLength > 0
			&& AttackStartIndex + AttackLength <= OrderedFrames.Length;
	}

	private Renderer _renderer;
	private string _labSid;
	private BattleFrameSet _frameSet;
	private MaterialPropertyBlock _propertyBlock;
	private int _lastAppliedFrame = -1;
	private int _lastAppliedGroup = int.MinValue;
	private Vector3 _attackTargetWorldPosition;
	private float _attackTargetUntil;
	private bool _hasAttackTargetWorldPosition;
	private Camera _camera;

	public Homm3BattleDiskTextureRemap(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, Homm3ImportVisuals.Entry entry, ManualLogSource log)
	{
		if (!battleRoot || entry == null)
			return;
		var labSid = Homm3ImportVisuals.TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid))
			return;
		if (Homm3BattleArrayBillboard.IsArrayPrototypeLabSid(labSid))
			return;

		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattleDiskTextureRemap>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 battle disk texture remap: registered Il2Cpp type.");
			}

			if (battleRoot.GetComponent<Homm3BattleDiskTextureRemap>() != null)
				return;
			if (!TryLoadFrames(entry, labSid, log, out var frameSet) || frameSet?.OrderedFrames == null || frameSet.OrderedFrames.Length == 0)
				return;

			var c = battleRoot.AddComponent<Homm3BattleDiskTextureRemap>();
			c._labSid = labSid;
			c._frameSet = frameSet;
			if (_attachDiagRemaining > 0)
			{
				_attachDiagRemaining--;
				log?.LogInfo(
					"Homm3 battle disk texture remap: attached labSid='"
					+ labSid
					+ "' frames="
					+ frameSet.OrderedFrames.Length
					+ " attackRange="
					+ frameSet.AttackStartIndex
					+ "+"
					+ frameSet.AttackLength
					+ " baseAttackGroup="
					+ frameSet.BaseAttackGroup
					+ ".");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle disk texture remap: attach failed for labSid='" + labSid + "': " + ex.Message);
		}
	}

	internal static bool TryApplyAttackDirection(GameObject battleRoot, Vector3 targetWorldPosition, float durationSeconds)
	{
		if (!battleRoot || !battleRoot.transform)
			return false;
		var helper = battleRoot.GetComponent<Homm3BattleDiskTextureRemap>();
		if (helper == null || !helper)
			return false;
		helper.ApplyAttackDirection(targetWorldPosition, durationSeconds);
		return true;
	}

	private void Awake()
	{
		_renderer = FindBattleQuadRenderer(gameObject);
	}

	private void ApplyAttackDirection(Vector3 targetWorldPosition, float durationSeconds)
	{
		_attackTargetWorldPosition = targetWorldPosition;
		_attackTargetUntil = Time.time + Mathf.Max(0.2f, durationSeconds);
		_hasAttackTargetWorldPosition = true;
		_lastAppliedFrame = -1;
		_lastAppliedGroup = int.MinValue;
		if (_activeAttackFrameDiagRemaining > 0)
		{
			_activeAttackFrameDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 battle disk texture remap: attack window labSid='"
				+ (_labSid ?? "?")
				+ "' seconds="
				+ durationSeconds.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture)
				+ " attackRange="
				+ (_frameSet?.AttackStartIndex ?? -1)
				+ "+"
				+ (_frameSet?.AttackLength ?? 0)
				+ ".");
		}
	}

	private void LateUpdate()
	{
		if (!_renderer)
			_renderer = FindBattleQuadRenderer(gameObject);
		if (!_renderer || _frameSet?.OrderedFrames == null || _frameSet.OrderedFrames.Length == 0)
			return;

		var material = CurrentMaterial(_renderer);
		if (!material)
			return;
		if (!TryParseGeneratedFrameIndex(material.name, out var frameIndex))
			return;
		if (frameIndex < 0 || frameIndex >= _frameSet.OrderedFrames.Length)
		{
			LogMiss("frame index " + frameIndex + " outside disk frame count " + _frameSet.OrderedFrames.Length + " material='" + material.name + "'");
			return;
		}

		if (!TryResolveTextureForFrame(frameIndex, out var frame, out var sourceGroup))
			return;
		LogActiveAttackFrame(frameIndex, sourceGroup);
		if (_lastAppliedFrame == frameIndex && _lastAppliedGroup == sourceGroup)
			return;

		if (!frame)
			return;

		ApplyFramePropertyBlock(_renderer, frame);
		_lastAppliedFrame = frameIndex;
		_lastAppliedGroup = sourceGroup;
		if (_tickDiagRemaining > 0)
		{
			_tickDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 battle disk texture remap: labSid='"
				+ (_labSid ?? "?")
				+ "' material='"
				+ (material.name ?? "?")
				+ "' frame='"
				+ (frame.name ?? "?")
				+ "' sourceGroup="
				+ sourceGroup
				+ ".");
		}
	}

	private static Renderer FindBattleQuadRenderer(GameObject root)
	{
		if (!root)
			return null;
		var quad = root.transform?.Find("billboard/quad");
		if (quad != null)
		{
			var r = quad.GetComponent<Renderer>();
			if (r)
				return r;
		}
		var renderers = root.GetComponentsInChildren<MeshRenderer>(true);
		return renderers != null && renderers.Length > 0 ? renderers[0] : null;
	}

	private static Material CurrentMaterial(Renderer renderer)
	{
		if (!renderer)
			return null;
		try
		{
			var mats = renderer.sharedMaterials;
			if (mats != null && mats.Length > 0 && mats[0])
				return mats[0];
		}
		catch
		{
		}
		return renderer.sharedMaterial;
	}

	private bool TryResolveTextureForFrame(int frameIndex, out Texture2D frame, out int sourceGroup)
	{
		frame = null;
		sourceGroup = NonDirectionalGroup;
		if (_frameSet?.OrderedFrames == null || frameIndex < 0 || frameIndex >= _frameSet.OrderedFrames.Length)
			return false;

		if (IsAttackFrameIndex(frameIndex)
		    && TryResolveDirectionalAttackGroup(out var attackGroup)
		    && TryResolveAttackFrame(frameIndex, attackGroup, out frame))
		{
			sourceGroup = attackGroup;
			return frame != null && frame;
		}

		frame = _frameSet.OrderedFrames[frameIndex];
		sourceGroup = IsAttackFrameIndex(frameIndex) ? _frameSet.BaseAttackGroup : NonDirectionalGroup;
		return frame != null && frame;
	}

	private void LogActiveAttackFrame(int frameIndex, int sourceGroup)
	{
		if (!_hasAttackTargetWorldPosition || Time.time > _attackTargetUntil || _activeAttackFrameDiagRemaining <= 0)
			return;
		_activeAttackFrameDiagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3 battle disk texture remap: active attack material labSid='"
			+ (_labSid ?? "?")
			+ "' frameIndex="
			+ frameIndex
			+ " inAttackRange="
			+ IsAttackFrameIndex(frameIndex)
			+ " sourceGroup="
			+ sourceGroup
			+ " remaining="
			+ (_attackTargetUntil - Time.time).ToString("0.##", System.Globalization.CultureInfo.InvariantCulture)
			+ ".");
	}

	private bool TryResolveDirectionalAttackGroup(out int attackGroup)
	{
		attackGroup = GroupAttackFront;
		if (!_hasAttackTargetWorldPosition || Time.time > _attackTargetUntil || _frameSet == null || !_frameSet.HasAttackFrames)
		{
			_hasAttackTargetWorldPosition = false;
			return false;
		}

		var cam = GetCamera();
		if (cam == null || !cam || !TryResolveAttackScreenDelta(cam, out var delta))
			return false;

		var threshold = Mathf.Max(8f, Mathf.Abs(delta.x) * 0.18f);
		var useShootFamily = IsShootAttackGroup(_frameSet.BaseAttackGroup);
		if (delta.y > threshold)
			attackGroup = useShootFamily ? GroupShootUp : GroupAttackUp;
		else if (delta.y < -threshold)
			attackGroup = useShootFamily ? GroupShootDown : GroupAttackDown;
		else
			attackGroup = useShootFamily ? GroupShootFront : GroupAttackFront;

		if (!_frameSet.AttackFramesByGroup.ContainsKey(attackGroup))
			attackGroup = _frameSet.BaseAttackGroup;
		if (_directionDiagRemaining > 0)
		{
			_directionDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3 battle disk texture remap: attack direction labSid='"
				+ (_labSid ?? "?")
				+ "' screenDelta=("
				+ delta.x.ToString("0.#", System.Globalization.CultureInfo.InvariantCulture)
				+ ","
				+ delta.y.ToString("0.#", System.Globalization.CultureInfo.InvariantCulture)
				+ ") group="
				+ attackGroup
				+ ".");
		}
		return true;
	}

	private bool TryResolveAttackFrame(int frameIndex, int attackGroup, out Texture2D frame)
	{
		frame = null;
		if (!IsAttackFrameIndex(frameIndex) || _frameSet == null)
			return false;
		if (!_frameSet.AttackFramesByGroup.TryGetValue(attackGroup, out var frames) || frames == null || frames.Length == 0)
			return false;
		var localIndex = frameIndex - _frameSet.AttackStartIndex;
		if (localIndex < 0)
			localIndex = 0;
		if (localIndex >= frames.Length)
			localIndex = frames.Length - 1;
		frame = frames[localIndex];
		return frame != null && frame;
	}

	private bool IsAttackFrameIndex(int frameIndex)
	{
		return _frameSet != null
		       && _frameSet.HasAttackFrames
		       && frameIndex >= _frameSet.AttackStartIndex
		       && frameIndex < _frameSet.AttackStartIndex + _frameSet.AttackLength;
	}

	private bool TryResolveAttackScreenDelta(Camera cam, out Vector2 delta)
	{
		delta = default;
		if (cam == null || !cam)
			return false;
		var from = cam.WorldToScreenPoint(transform.position);
		var to = cam.WorldToScreenPoint(_attackTargetWorldPosition);
		if (from.z < 0f || to.z < 0f)
			return false;
		delta = new Vector2(to.x - from.x, to.y - from.y);
		return delta.sqrMagnitude >= 4f;
	}

	private Camera GetCamera()
	{
		if (_camera != null && _camera)
			return _camera;
		_camera = Camera.main;
		if (_camera != null && _camera)
			return _camera;
		var cameras = Camera.allCameras;
		if (cameras == null || cameras.Length == 0)
			return null;
		for (var i = 0; i < cameras.Length; i++)
		{
			var c = cameras[i];
			if (c != null && c && c.isActiveAndEnabled)
			{
				_camera = c;
				return _camera;
			}
		}
		return null;
	}

	private void ApplyFramePropertyBlock(Renderer renderer, Texture texture)
	{
		if (!renderer || !texture)
			return;
		try
		{
			_propertyBlock ??= new MaterialPropertyBlock();
			renderer.GetPropertyBlock(_propertyBlock);
			for (var i = 0; i < BillboardTextureProperties.Length; i++)
				_propertyBlock.SetTexture(BillboardTextureProperties[i], texture);
			renderer.SetPropertyBlock(_propertyBlock);
		}
		catch
		{
		}
	}

	private static bool TryLoadFrames(Homm3ImportVisuals.Entry entry, string labSid, ManualLogSource log, out BattleFrameSet frameSet)
	{
		frameSet = null;
		if (string.IsNullOrEmpty(labSid))
			return false;
		if (FramesByLabSid.TryGetValue(labSid, out var cached) && cached?.OrderedFrames != null && cached.OrderedFrames.Length > 0)
		{
			frameSet = cached;
			return true;
		}

		var cyanKeyedSource = CyanKeyedFactoryLabSids.Contains(labSid);
		if (!cyanKeyedSource
		    && Homm3ImportVisuals.TryGetBundleBattleFrameTextures(entry, log, out var bundleFrames, out var bundleSource)
		    && bundleFrames != null
		    && bundleFrames.Length > 0)
		{
			frameSet = new BattleFrameSet
			{
				OrderedFrames = bundleFrames
			};
			FramesByLabSid[labSid] = frameSet;
			log?.LogInfo("Homm3 battle disk texture remap: loaded " + bundleFrames.Length + " bundled frame texture(s) for labSid='" + labSid + "' from " + (bundleSource ?? "?") + ".");
			return true;
		}
		if (!cyanKeyedSource && !LooseHomm3LabFramePngFallbackEnabled)
		{
			LogMiss("missing bundled battle frames for labSid='" + labSid + "' and loose homm3_lab PNG fallback is disabled");
			return false;
		}

		var unitRoot = Homm3ImportVisuals.FindHomm3LabExtractedBattleRoot(labSid);
		if (string.IsNullOrEmpty(unitRoot))
		{
			LogMiss("missing extracted_battle root for labSid='" + labSid + "'");
			return false;
		}

		var framePaths = OrderedBattleFramePaths(unitRoot, out var attackStartIndex, out var attackLength, out var baseAttackGroup);
		if (framePaths.Count == 0)
		{
			LogMiss("no ordered battle frames under " + unitRoot);
			return false;
		}

		var loaded = LoadTextures(labSid, framePaths, log, cyanKeyedSource);

		if (loaded.Count == 0)
			return false;
		frameSet = new BattleFrameSet
		{
			OrderedFrames = loaded.ToArray(),
			AttackStartIndex = attackStartIndex,
			AttackLength = attackLength,
			BaseAttackGroup = baseAttackGroup
		};

		LoadAttackGroups(unitRoot, MeleeAttackGroupPreference, frameSet, labSid, log);
		LoadAttackGroups(unitRoot, ShootAttackGroupPreference, frameSet, labSid, log);

		FramesByLabSid[labSid] = frameSet;
		return true;
	}

	private static List<Texture2D> LoadTextures(string labSid, IList<string> framePaths, ManualLogSource log, bool keyCornerColor)
	{
		var loaded = new List<Texture2D>(framePaths?.Count ?? 0);
		if (framePaths == null)
			return loaded;
		for (var i = 0; i < framePaths.Count; i++)
		{
			var path = framePaths[i];
			try
			{
				var bytes = File.ReadAllBytes(path);
				var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
				if (!Homm3ImportVisuals.TryLoadTextureImage(tex, bytes))
				{
					UnityEngine.Object.Destroy(tex);
					continue;
				}
				tex.name = "HOMM3_battle_disk_" + labSid + "_" + Path.GetFileNameWithoutExtension(path);
				tex.filterMode = FilterMode.Point;
				tex.wrapMode = TextureWrapMode.Clamp;
				if (keyCornerColor)
					ApplyExactCornerChromaKey(tex, labSid, path);
				loaded.Add(tex);
			}
			catch (Exception ex)
			{
				log?.LogWarning("Homm3 battle disk texture remap: failed to load '" + path + "': " + ex.Message);
			}
		}

		return loaded;
	}

	private static void ApplyExactCornerChromaKey(Texture2D texture, string labSid, string path)
	{
		if (!texture || texture.width <= 0 || texture.height <= 0)
			throw new InvalidOperationException("invalid texture");
		try
		{
			var pixels = texture.GetPixels32();
			if (pixels == null || pixels.Length != texture.width * texture.height)
				throw new InvalidOperationException("unreadable texture pixels");
			var key = pixels[0];
			var changed = 0;
			for (var i = 0; i < pixels.Length; i++)
			{
				var pixel = pixels[i];
				if (pixel.r != key.r || pixel.g != key.g || pixel.b != key.b || pixel.a == 0)
					continue;
				pixel.a = 0;
				pixels[i] = pixel;
				changed++;
			}
			if (changed == 0)
				throw new InvalidOperationException("corner key did not match an opaque pixel");
			texture.SetPixels32(pixels);
			texture.Apply(false, false);
		}
		catch (Exception ex)
		{
			throw new InvalidOperationException(
				"required Factory chroma-key conversion failed for labSid='" + labSid + "' frame='" + path + "': " + ex.Message,
				ex);
		}
	}

	private static List<string> OrderedBattleFramePaths(string unitRoot, out int attackStartIndex, out int attackLength, out int baseAttackGroup)
	{
		var result = new List<string>();
		attackStartIndex = -1;
		attackLength = 0;
		baseAttackGroup = GroupAttackFront;
		AddGroupFrames(unitRoot, GroupIdle, result);
		AddMovementFamily(unitRoot, result);
		var preferShoot = HasAnyGroupFrames(unitRoot, ShootAttackGroupPreference);
		var primaryAttackGroups = preferShoot ? ShootAttackGroupPreference : MeleeAttackGroupPreference;
		var fallbackAttackGroups = preferShoot ? MeleeAttackGroupPreference : ShootAttackGroupPreference;
		if (!AddFirstAvailableAttackFamily(unitRoot, primaryAttackGroups, result, ref attackStartIndex, ref attackLength, ref baseAttackGroup))
			AddFirstAvailableAttackFamily(unitRoot, fallbackAttackGroups, result, ref attackStartIndex, ref attackLength, ref baseAttackGroup);
		for (var i = 2; i < FixedGroupOrder.Length; i++)
			AddGroupFrames(unitRoot, FixedGroupOrder[i], result);
		return result;
	}

	private static bool HasAnyGroupFrames(string unitRoot, int[] groups)
	{
		for (var i = 0; i < groups.Length; i++)
			if (GroupFramePaths(unitRoot, groups[i]).Count > 0)
				return true;
		return false;
	}

	private static void AddFirstAvailableMovementFamily(string unitRoot, List<string> result)
	{
		for (var i = 0; i < MovementGroupPreference.Length; i++)
		{
			var before = result.Count;
			AddGroupFrames(unitRoot, MovementGroupPreference[i], result);
			if (result.Count > before)
				return;
		}
	}

	private static void AddMovementFamily(string unitRoot, List<string> result)
	{
		if (ShouldUseTeleportDiveMovement(unitRoot))
		{
			AddGroupFrames(unitRoot, GroupTeleportLeave, result);
			AddGroupFrames(unitRoot, GroupTeleportArrive, result);
			return;
		}
		AddFirstAvailableMovementFamily(unitRoot, result);
	}

	private static bool ShouldUseTeleportDiveMovement(string unitRoot)
	{
		var labSid = TryLabSidFromExtractedBattleRoot(unitRoot);
		return !string.IsNullOrEmpty(labSid)
		       && TeleportDiveMovementLabSids.Contains(labSid)
		       && GroupFramePaths(unitRoot, GroupTeleportLeave).Count > 0
		       && GroupFramePaths(unitRoot, GroupTeleportArrive).Count > 0;
	}

	private static string TryLabSidFromExtractedBattleRoot(string unitRoot)
	{
		if (string.IsNullOrEmpty(unitRoot))
			return "";
		try
		{
			var dir = new DirectoryInfo(unitRoot);
			while (dir != null)
			{
				if (string.Equals(dir.Name, "homm3_lab", StringComparison.OrdinalIgnoreCase))
					return "";
				if (Directory.Exists(Path.Combine(dir.FullName, "extracted_battle")))
					return dir.Name;
				dir = dir.Parent;
			}
		}
		catch
		{
		}
		return "";
	}

	private static bool AddFirstAvailableAttackFamily(
		string unitRoot,
		int[] groups,
		List<string> result,
		ref int attackStartIndex,
		ref int attackLength,
		ref int baseAttackGroup)
	{
		for (var i = 0; i < groups.Length; i++)
		{
			var before = result.Count;
			var group = groups[i];
			AddGroupFrames(unitRoot, group, result);
			if (result.Count <= before)
				continue;
			attackStartIndex = before;
			attackLength = result.Count - before;
			baseAttackGroup = group;
			return true;
		}
		return false;
	}

	private static void LoadAttackGroups(string unitRoot, int[] groups, BattleFrameSet frameSet, string labSid, ManualLogSource log)
	{
		for (var i = 0; i < groups.Length; i++)
		{
			var group = groups[i];
			var groupPaths = GroupFramePaths(unitRoot, group);
			if (groupPaths.Count == 0)
				continue;
			var groupTextures = LoadTextures(labSid, groupPaths, log, CyanKeyedFactoryLabSids.Contains(labSid));
			if (groupTextures.Count > 0)
				frameSet.AttackFramesByGroup[group] = groupTextures.ToArray();
		}
	}

	private static bool IsShootAttackGroup(int group)
	{
		return group == GroupShootUp || group == GroupShootFront || group == GroupShootDown;
	}

	private static void AddGroupFrames(string unitRoot, int group, List<string> result)
	{
		var files = GroupFramePaths(unitRoot, group);
		for (var i = 0; i < files.Count; i++)
			result.Add(files[i]);
	}

	private static List<string> GroupFramePaths(string unitRoot, int group)
	{
		if (string.IsNullOrEmpty(unitRoot))
			return new List<string>();
		string[] files;
		try
		{
			files = Directory.GetFiles(unitRoot, group.ToString("00") + "_*.png", SearchOption.AllDirectories);
		}
		catch
		{
			return new List<string>();
		}
		if (files == null || files.Length == 0)
			return new List<string>();
		Array.Sort(files, StringComparer.OrdinalIgnoreCase);
		return new List<string>(files);
	}

	private static bool TryParseGeneratedFrameIndex(string materialName, out int index)
	{
		index = -1;
		if (string.IsNullOrWhiteSpace(materialName))
			return false;
		var n = materialName.Trim();
		const string instanceSuffix = " (Instance)";
		if (n.EndsWith(instanceSuffix, StringComparison.Ordinal))
			n = n.Substring(0, n.Length - instanceSuffix.Length);
		const string prefix = "homm3_frame_";
		var p = n.IndexOf(prefix, StringComparison.OrdinalIgnoreCase);
		if (p < 0)
			return false;
		p += prefix.Length;
		var end = p;
		while (end < n.Length && char.IsDigit(n[end]))
			end++;
		return end > p && int.TryParse(n.Substring(p, end - p), out index);
	}

	private static void LogMiss(string reason)
	{
		if (_missDiagRemaining <= 0)
			return;
		_missDiagRemaining--;
		Plugin.LogSource?.LogInfo("Homm3 battle disk texture remap skipped: " + (reason ?? "?") + ".");
	}
}
