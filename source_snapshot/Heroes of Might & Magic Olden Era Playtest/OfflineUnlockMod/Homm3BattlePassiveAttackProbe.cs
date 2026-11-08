using System;
using System.Globalization;
using System.IO;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3BattlePassiveAttackProbe : MonoBehaviour
{
	private const string FlagFileName = "homm3_battle_passive_attack_probe.flag";
	private const int GroupIdle = 2;
	private const int GroupMovement = 0;
	private const int GroupAttackUp = 11;
	private const int GroupAttackFront = 12;
	private const int GroupAttackDown = 13;
	private const int GroupHitted = 3;
	private const int GroupDeath = 5;
	private const int MaxLogs = 180;

	private static bool _typeRegistered;
	private static int _attachLogs = 12;
	private static int _logs;

	private string _labSid;
	private Renderer _renderer;
	private Transform _quad;
	private int _attackStart = -1;
	private int _attackLength;
	private int _lastFrame = int.MinValue;
	private bool _wasInAttack;
	private Vector3 _lastRootPosition;
	private bool _hasLastRootPosition;

	public Homm3BattlePassiveAttackProbe(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, Homm3ImportVisuals.Entry entry, ManualLogSource log)
	{
		if (!battleRoot || entry == null || !Homm3DiagnosticFlags.IsEnabled(FlagFileName))
			return;
		var labSid = Homm3ImportVisuals.TryHomm3LabSidFromPrefabPath(entry.BattlePrefabAssetPath);
		if (string.IsNullOrEmpty(labSid))
			return;

		try
		{
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3BattlePassiveAttackProbe>();
				_typeRegistered = true;
				log?.LogInfo("Homm3 battle passive attack probe: registered Il2Cpp type.");
			}

			if (battleRoot.GetComponent<Homm3BattlePassiveAttackProbe>() != null)
				return;
			if (!TryResolveAttackRange(labSid, out var attackStart, out var attackLength))
			{
				log?.LogInfo("Homm3 battle passive attack probe: no attack frame range for labSid='" + labSid + "'.");
				return;
			}

			var probe = battleRoot.AddComponent<Homm3BattlePassiveAttackProbe>();
			probe._labSid = labSid;
			probe._attackStart = attackStart;
			probe._attackLength = attackLength;
			if (_attachLogs > 0)
			{
				_attachLogs--;
				log?.LogInfo(
					"Homm3 battle passive attack probe: attached labSid='"
					+ labSid
					+ "' attackRange="
					+ attackStart
					+ "+"
					+ attackLength
					+ ".");
			}
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3 battle passive attack probe attach failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private void Awake()
	{
		_renderer = FindRenderer(gameObject);
		_quad = transform.Find("billboard/quad") ?? _renderer?.transform;
		_lastRootPosition = transform.position;
		_hasLastRootPosition = true;
	}

	private void LateUpdate()
	{
		if (_logs >= MaxLogs || _attackStart < 0 || _attackLength <= 0)
			return;
		if (!_renderer)
			_renderer = FindRenderer(gameObject);
		if (!_renderer)
			return;
		if (_quad == null || !_quad)
			_quad = transform.Find("billboard/quad") ?? _renderer.transform;

		var material = CurrentMaterial(_renderer);
		if (!material || !TryParseFrameIndex(material.name, out var frame))
			return;

		var inAttack = frame >= _attackStart && frame < _attackStart + _attackLength;
		if (!inAttack && !_wasInAttack)
		{
			_lastFrame = frame;
			TrackRootMotion(out _);
			return;
		}
		if (frame == _lastFrame && inAttack == _wasInAttack)
		{
			TrackRootMotion(out _);
			return;
		}

		TrackRootMotion(out var rootDelta);
		_logs++;
		Plugin.LogSource?.LogInfo(
			"Homm3 battle passive attack probe: labSid='"
			+ (_labSid ?? "?")
			+ "' frame="
			+ frame
			+ " inAttack="
			+ inAttack
			+ " attackRange="
			+ _attackStart
			+ "+"
			+ _attackLength
			+ " rootPos="
			+ FormatVector(transform.position)
			+ " rootRot="
			+ FormatVector(transform.rotation.eulerAngles)
			+ " rootLocalRot="
			+ FormatVector(transform.localRotation.eulerAngles)
			+ " rootDelta="
			+ FormatVector(rootDelta)
			+ " quadScale="
			+ (_quad ? FormatVector(_quad.localScale) : "?")
			+ " quadLocalPos="
			+ (_quad ? FormatVector(_quad.localPosition) : "?")
			+ " material='"
			+ (material.name ?? "?")
			+ "'.");
		_lastFrame = frame;
		_wasInAttack = inAttack;
	}

	private static bool TryResolveAttackRange(string labSid, out int attackStart, out int attackLength)
	{
		attackStart = -1;
		attackLength = 0;
		var root = Homm3ImportVisuals.FindHomm3LabExtractedBattleRoot(labSid);
		if (string.IsNullOrEmpty(root))
			return false;

		var count = GroupFrameCount(root, GroupIdle) + GroupFrameCount(root, GroupMovement);
		var attackCount = GroupFrameCount(root, GroupAttackFront);
		if (attackCount <= 0)
			attackCount = GroupFrameCount(root, GroupAttackUp);
		if (attackCount <= 0)
			attackCount = GroupFrameCount(root, GroupAttackDown);
		if (attackCount <= 0)
			return false;
		attackStart = count;
		attackLength = attackCount;
		_ = GroupFrameCount(root, GroupHitted) + GroupFrameCount(root, GroupDeath);
		return true;
	}

	private static int GroupFrameCount(string root, int group)
	{
		try
		{
			return Directory.GetFiles(root, group.ToString("00") + "_*.png", SearchOption.AllDirectories).Length;
		}
		catch
		{
			return 0;
		}
	}

	private void TrackRootMotion(out Vector3 delta)
	{
		var current = transform.position;
		if (!_hasLastRootPosition)
		{
			_lastRootPosition = current;
			_hasLastRootPosition = true;
			delta = Vector3.zero;
			return;
		}
		delta = current - _lastRootPosition;
		_lastRootPosition = current;
	}

	private static Renderer FindRenderer(GameObject root)
	{
		if (!root)
			return null;
		var quad = root.transform?.Find("billboard/quad");
		if (quad)
		{
			var renderer = quad.GetComponent<Renderer>();
			if (renderer)
				return renderer;
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
		catch { }
		return renderer.sharedMaterial;
	}

	private static bool TryParseFrameIndex(string materialName, out int index)
	{
		index = -1;
		if (string.IsNullOrWhiteSpace(materialName))
			return false;
		var n = materialName.Trim();
		const string prefix = "homm3_frame_";
		var p = n.IndexOf(prefix, StringComparison.OrdinalIgnoreCase);
		if (p < 0)
			return false;
		p += prefix.Length;
		var end = p;
		while (end < n.Length && char.IsDigit(n[end]))
			end++;
		return end > p && int.TryParse(n.Substring(p, end - p), NumberStyles.Integer, CultureInfo.InvariantCulture, out index);
	}

	private static string FormatVector(Vector3 v) =>
		"("
		+ v.x.ToString("0.###", CultureInfo.InvariantCulture)
		+ ","
		+ v.y.ToString("0.###", CultureInfo.InvariantCulture)
		+ ","
		+ v.z.ToString("0.###", CultureInfo.InvariantCulture)
		+ ")";
}
