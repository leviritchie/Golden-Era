using System;
using System.Collections.Generic;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Plays HoMM3 pikeman SFX on the bundle <c>battle</c> prefab without touching <c>Hex.Sound.*</c>.
/// AudioClips ship in <c>custom_units_esquire</c> (raw <c>.wav</c>) and are indexed by stem
/// (e.g. <c>ESQUIRE_Attack_1</c>) in <see cref="EsquirePikemanVisuals"/>. Motion is driven by billboard
/// <see cref="AnimationClip"/> names (<c>14.Attack</c>, …); <see cref="EsquireBattleClipAudioDriver"/> forwards
/// clip changes to <see cref="OnBillboardDominantClipChanged"/>.
/// </summary>
internal sealed class EsquireBattleAudioPlayer : MonoBehaviour
{
	private const float OneShotDebounceSeconds = 0.1f;
	/// <summary>2D SFX: battle uses <see cref="Animator.Play"/> on a billboard; vanilla rarely drives <c>SetTrigger</c> here, so clip-driven audio must be clearly audible (3D roll-off was easy to miss).</summary>
	private const float DefaultSpatialBlend = 0f;
	private const float DefaultMinDistance = 1.0f;
	private const float DefaultMaxDistance = 50.0f;

	private AudioSource _oneShot;
	private AudioSource _loop;
	private bool _initialized;
	private static int _victoryFlip;
	private static int _deathRotation;
	private string _debounceLastCategory;
	private float _debounceLastUnscaledTime = -999f;

	private readonly Dictionary<string, AudioClip[]> _byCategory = new(StringComparer.OrdinalIgnoreCase);
	private readonly Dictionary<string, int> _cursorByCategory = new(StringComparer.OrdinalIgnoreCase);

	// IL2CPP-injected types must expose the (IntPtr) ctor; default ctor stays empty.
	public EsquireBattleAudioPlayer(IntPtr ptr) : base(ptr) { }

	/// <summary>Registers Il2Cpp type (once) and adds this behaviour to <paramref name="battleRoot"/> if missing.</summary>
	internal static void TryAttach(GameObject battleRoot, ManualLogSource log)
	{
		if (battleRoot == null || !battleRoot)
			return;
		try
		{
			EsquirePikemanVisuals.EnsureEsquireBattleAudioPlayerTypeRegistered(log);
			if (battleRoot.GetComponent<EsquireBattleAudioPlayer>() != null)
				return;
			battleRoot.AddComponent<EsquireBattleAudioPlayer>();
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquireBattleAudioPlayer: TryAttach failed: " + ex.Message);
		}
	}

	private void Awake()
	{
		EnsureInitialized();
	}

	private void EnsureInitialized()
	{
		if (_initialized)
			return;
		_initialized = true;

		try
		{
			_oneShot = gameObject.AddComponent<AudioSource>();
			ConfigureAudioSource(_oneShot, loop: false);

			_loop = gameObject.AddComponent<AudioSource>();
			ConfigureAudioSource(_loop, loop: true);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquireBattleAudioPlayer: AddComponent<AudioSource> failed: " + ex);
			return;
		}

		BuildCategoryIndex();
		Plugin.LogSource?.LogInfo(
			"EsquireBattleAudioPlayer: ready; categories="
			+ _byCategory.Count
			+ " (attack="
			+ CountIn("attack")
			+ ", damage="
			+ CountIn("damage")
			+ ", walk="
			+ CountIn("walk")
			+ ", death_a="
			+ CountIn("death_a")
			+ ", death_b="
			+ CountIn("death_b")
			+ ", death_c="
			+ CountIn("death_c")
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

		AddVariants("attack", "ESQUIRE_Attack_", 1, 4);
		AddVariants("damage", "ESQUIRE_Damage_", 1, 4);
		AddVariants("walk", "ESQUIRE_Walk_", 1, 4);
		AddVariants("death_a", "ESQUIRE_Death_A_", 1, 4);
		AddVariants("death_b", "ESQUIRE_Death_B_", 1, 4);
		AddVariants("death_c", "ESQUIRE_Death_C_", 1, 4);
		AddVariants("victory_a", "ESQUIRE_Victory_A_", 1, 8);
		AddVariants("victory_b", "ESQUIRE_Victory_B_", 1, 3);
	}

	/// <summary>Stems matching <see cref="BuildCategoryIndex"/> (used to probe bundle paths when asset name enumeration is unreliable).</summary>
	internal static IEnumerable<string> EnumerateExpectedSfxStems()
	{
		for (var i = 1; i <= 4; i++)
			yield return "ESQUIRE_Attack_" + i;
		for (var i = 1; i <= 4; i++)
			yield return "ESQUIRE_Damage_" + i;
		for (var i = 1; i <= 4; i++)
			yield return "ESQUIRE_Walk_" + i;
		foreach (var row in new[] { "A", "B", "C" })
		{
			for (var i = 1; i <= 4; i++)
				yield return "ESQUIRE_Death_" + row + "_" + i;
		}

		for (var i = 1; i <= 8; i++)
			yield return "ESQUIRE_Victory_A_" + i;
		for (var i = 1; i <= 3; i++)
			yield return "ESQUIRE_Victory_B_" + i;
	}

	private void AddVariants(string category, string stemPrefix, int loInclusive, int hiInclusive)
	{
		var list = new List<AudioClip>(hiInclusive - loInclusive + 1);
		for (var i = loInclusive; i <= hiInclusive; i++)
		{
			var stem = stemPrefix + i;
			if (EsquirePikemanVisuals.TryGetEsquireAudioClip(stem, out var clip) && clip)
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
			Plugin.LogSource?.LogWarning("EsquireBattleAudioPlayer: PlayOneShot('" + category + "') failed: " + ex.Message);
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
			Plugin.LogSource?.LogWarning("EsquireBattleAudioPlayer: StartLoop('" + category + "') failed: " + ex.Message);
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

	/// <summary>
	/// Billboards drive motion via <c>Animator.Play</c> on clip names like <c>14.Attack</c> / <c>20.Damage</c> (see <c>EsquireBillboardAnimatorBuild.GeneratedClipNames</c>),
	/// not <c>SetTrigger</c>. <see cref="EsquireBattleClipAudioDriver"/> calls this when the dominant layer-0 clip changes.
	/// </summary>
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

	private static string NextDeathCategory()
	{
		var n = System.Threading.Interlocked.Increment(ref _deathRotation);
		return (n % 3) switch
		{
			0 => "death_a",
			1 => "death_b",
			_ => "death_c",
		};
	}

	internal static bool RootNameIsBattle(string name)
	{
		if (string.IsNullOrEmpty(name))
			return false;
		return string.Equals(name, "battle", StringComparison.Ordinal)
		       || name.StartsWith("battle(", StringComparison.Ordinal)
		       || name.StartsWith("battle (", StringComparison.Ordinal);
	}

	/// <summary>Walk parents from <paramref name="from"/>; battle unit animator lives under scene root (e.g. <c>ROOT/Unit/battle/…</c>), not <see cref="Transform.root"/> == <c>battle</c>.</summary>
	internal static Transform FindBattlePrefabRoot(Transform from)
	{
		if (from == null)
			return null;
		try
		{
			for (var t = from; t != null; t = t.parent)
			{
				if (RootNameIsBattle(t.gameObject.name))
					return t;
			}
		}
		catch
		{
		}

		return null;
	}
}
