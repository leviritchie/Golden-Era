using System;
using System.Collections.Generic;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: HoMM3 lab bundle battle SFX (stems <c>HOMM3_&lt;unitSid&gt;_Attack_1</c>, …) on the <c>battle</c> root, same clip-driven
/// contract as <see cref="EsquireBattleAudioPlayer"/> / <see cref="Homm3LabClipAudioDriver"/>.
/// </summary>
internal sealed class Homm3LabBattleAudioPlayer : MonoBehaviour
{
	private const float OneShotDebounceSeconds = 0.1f;
	private const float DefaultSpatialBlend = 0f;
	private const float DefaultMinDistance = 1.0f;
	private const float DefaultMaxDistance = 50.0f;

	private static string _pendingBundleName;
	private static string _pendingStemPrefix;

	private string _bundleName;
	private string _stemPrefix;
	private AudioSource _oneShot;
	private AudioSource _loop;
	private bool _initialized;
	private static int _victoryFlip;
	private int _deathSeq;
	private string _debounceLastCategory;
	private float _debounceLastUnscaledTime = -999f;

	private readonly Dictionary<string, AudioClip[]> _byCategory = new(StringComparer.OrdinalIgnoreCase);
	private readonly Dictionary<string, int> _cursorByCategory = new(StringComparer.OrdinalIgnoreCase);

	public Homm3LabBattleAudioPlayer(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, string bundleName, string stemPrefix, ManualLogSource log)
	{
		if (battleRoot == null || !battleRoot || string.IsNullOrEmpty(bundleName) || string.IsNullOrEmpty(stemPrefix))
			return;
		try
		{
			Homm3ImportVisuals.EnsureHomm3LabBattleAudioPlayerTypeRegistered(log);
			if (battleRoot.GetComponent<Homm3LabBattleAudioPlayer>() != null)
				return;
			_pendingBundleName = bundleName;
			_pendingStemPrefix = stemPrefix;
			battleRoot.AddComponent<Homm3LabBattleAudioPlayer>();
			_pendingBundleName = null;
			_pendingStemPrefix = null;
		}
		catch (Exception ex)
		{
			_pendingBundleName = null;
			_pendingStemPrefix = null;
			log?.LogWarning("Homm3LabBattleAudioPlayer: TryAttach failed: " + ex.Message);
		}
	}

	private void Awake()
	{
		_bundleName = _pendingBundleName;
		_stemPrefix = _pendingStemPrefix;
		_pendingBundleName = null;
		_pendingStemPrefix = null;
		EnsureInitialized();
	}

	private void EnsureInitialized()
	{
		if (_initialized)
			return;
		_initialized = true;

		if (string.IsNullOrEmpty(_bundleName) || string.IsNullOrEmpty(_stemPrefix))
		{
			Plugin.LogSource?.LogWarning("Homm3LabBattleAudioPlayer: missing bundle/stem prefix — skip audio.");
			return;
		}

		try
		{
			_oneShot = gameObject.AddComponent<AudioSource>();
			ConfigureAudioSource(_oneShot, loop: false);

			_loop = gameObject.AddComponent<AudioSource>();
			ConfigureAudioSource(_loop, loop: true);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3LabBattleAudioPlayer: AddComponent<AudioSource> failed: " + ex);
			return;
		}

		BuildCategoryIndex();
		if (Homm3DiagnosticFlags.IsEnabled("homm3_battle_visual_diag.flag"))
			Plugin.LogSource?.LogInfo(
				"Homm3LabBattleAudioPlayer: ready bundle="
					+ _bundleName
					+ "; categories="
					+ _byCategory.Count
					+ " (attack="
					+ CountIn("attack")
					+ ", damage="
					+ CountIn("damage")
					+ ", walk="
					+ CountIn("walk")
					+ ").");
	}

	private int CountIn(string cat)
	{
		return _byCategory.TryGetValue(cat, out var arr) && arr != null ? arr.Length : 0;
	}

	private static void ConfigureAudioSource(AudioSource a, bool loop)
	{
		if (!a)
			return;
		a.playOnAwake = false;
		a.loop = loop;
		a.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume);
		a.spatialBlend = DefaultSpatialBlend;
		a.minDistance = DefaultMinDistance;
		a.maxDistance = DefaultMaxDistance;
		a.dopplerLevel = 0f;
	}

	private void BuildCategoryIndex()
	{
		_byCategory.Clear();
		_cursorByCategory.Clear();
		var p = _stemPrefix;
		AddVariants("attack", p + "Attack_", 1, 4);
		AddVariants("damage", p + "Damage_", 1, 4);
		AddVariants("walk", p + "Walk_", 1, 4);
		AddVariants("death_a", p + "Death_A_", 1, 4);
		AddVariants("death_b", p + "Death_B_", 1, 4);
		AddVariants("death_c", p + "Death_C_", 1, 4);
		AddVariants("victory_a", p + "Victory_A_", 1, 8);
		AddVariants("victory_b", p + "Victory_B_", 1, 3);
	}

	private void AddVariants(string category, string stemPrefix, int loInclusive, int hiInclusive)
	{
		var list = new List<AudioClip>(hiInclusive - loInclusive + 1);
		for (var i = loInclusive; i <= hiInclusive; i++)
		{
			var stem = stemPrefix + i;
			if (Homm3ImportVisuals.TryGetHomm3LabAudioClip(_bundleName, stem, out var clip) && clip)
				list.Add(clip);
		}

		if (list.Count > 0)
			_byCategory[category] = list.ToArray();
	}

	private bool TryNextVariant(string category, out AudioClip clip)
	{
		clip = null;
		if (!_byCategory.TryGetValue(category, out var arr) || arr == null || arr.Length == 0)
			return false;
		_cursorByCategory.TryGetValue(category, out var c);
		var idx = c % arr.Length;
		_cursorByCategory[category] = c + 1;
		clip = arr[idx];
		return clip != null;
	}

	private void PlayOneShot(string category)
	{
		EnsureInitialized();
		if (!_oneShot)
			return;
		float now;
		try
		{
			now = Time.unscaledTime;
		}
		catch
		{
			now = 0f;
		}

		if (_debounceLastCategory != null
		    && string.Equals(_debounceLastCategory, category, StringComparison.Ordinal)
		    && now - _debounceLastUnscaledTime < OneShotDebounceSeconds)
			return;
		if (!TryNextVariant(category, out var clip))
			return;
		_debounceLastCategory = category;
		_debounceLastUnscaledTime = now;
		try
		{
			_oneShot.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume);
		}
		catch
		{
		}

		try
		{
			_oneShot.PlayOneShot(clip);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3LabBattleAudioPlayer: PlayOneShot('" + category + "') failed: " + ex.Message);
		}
	}

	private void StartLoop(string category)
	{
		EnsureInitialized();
		if (!_loop)
			return;
		try
		{
			_loop.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume);
		}
		catch
		{
		}

		if (!TryNextVariant(category, out var clip))
			return;
		try
		{
			if (_loop.clip != clip)
				_loop.clip = clip;
			if (!_loop.isPlaying)
				_loop.Play();
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3LabBattleAudioPlayer: StartLoop('" + category + "') failed: " + ex.Message);
		}
	}

	private void StopLoop()
	{
		if (!_loop)
			return;
		try
		{
			if (_loop.isPlaying)
				_loop.Stop();
		}
		catch
		{
		}
	}

	private void PlayVictoryOneShot()
	{
		EnsureInitialized();
		var hasA = _byCategory.TryGetValue("victory_a", out var arrA) && arrA != null && arrA.Length > 0;
		var hasB = _byCategory.TryGetValue("victory_b", out var arrB) && arrB != null && arrB.Length > 0;
		if (!hasA && !hasB)
			return;
		var useA = (System.Threading.Interlocked.Increment(ref _victoryFlip) & 1) == 0;
		if (useA && hasA)
			PlayOneShot("victory_a");
		else if (!useA && hasB)
			PlayOneShot("victory_b");
		else if (hasA)
			PlayOneShot("victory_a");
		else
			PlayOneShot("victory_b");
	}

	internal void OnBillboardDominantClipChanged(string clipName)
	{
		if (string.IsNullOrEmpty(clipName))
			return;
		EnsureInitialized();
		if (!_oneShot)
			return;

		if (clipName.IndexOf("victory", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			PlayVictoryOneShot();
			return;
		}

		if (clipName.IndexOf("attack", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			PlayOneShot("attack");
			return;
		}

		if (clipName.IndexOf("damage", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			PlayOneShot("damage");
			return;
		}

		if (clipName.IndexOf("death", StringComparison.OrdinalIgnoreCase) >= 0
		    || clipName.IndexOf("die", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			PlayOneShot(NextDeathCategory());
			return;
		}

		if (clipName.IndexOf("walk", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			StartLoop("walk");
			return;
		}

		if (clipName.IndexOf("idle", StringComparison.OrdinalIgnoreCase) >= 0)
			StopLoop();
	}

	private string NextDeathCategory()
	{
		var n = ++_deathSeq;
		return (n % 3) switch
		{
			0 => "death_a",
			1 => "death_b",
			_ => "death_c",
		};
	}
}
