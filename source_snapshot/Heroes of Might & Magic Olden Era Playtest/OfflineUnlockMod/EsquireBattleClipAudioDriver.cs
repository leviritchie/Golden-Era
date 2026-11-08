using System;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Esquire battle billboard uses <see cref="Animator.Play"/> on flip-book clips (<c>14.Attack</c>, <c>20.Damage</c>, …) — not <c>SetTrigger</c>.
/// Watches layer 0 dominant clip name and forwards transitions to <see cref="EsquireBattleAudioPlayer"/>.
/// </summary>
internal sealed class EsquireBattleClipAudioDriver : MonoBehaviour
{
	private EsquireBattleAudioPlayer _player;
	private Animator _anim;
	private string _lastDominantClip;

	public EsquireBattleClipAudioDriver(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, ManualLogSource log)
	{
		if (battleRoot == null || !battleRoot)
			return;
		try
		{
			EsquirePikemanVisuals.EnsureEsquireBattleClipAudioDriverTypeRegistered(log);
			if (battleRoot.GetComponent<EsquireBattleClipAudioDriver>() != null)
				return;
			battleRoot.AddComponent<EsquireBattleClipAudioDriver>();
		}
		catch (Exception ex)
		{
			log?.LogWarning("EsquireBattleClipAudioDriver: TryAttach failed: " + ex.Message);
		}
	}

	private void LateUpdate()
	{
		if (_player == null || !_player)
			_player = GetComponent<EsquireBattleAudioPlayer>();
		if (_player == null || !_player)
			return;
		if (_anim == null || !_anim)
		{
			try
			{
				_anim = GetComponentInChildren<Animator>(true);
			}
			catch
			{
				_anim = null;
			}
		}

		if (_anim == null || !_anim)
			return;

		string dominant;
		try
		{
			dominant = PickDominantClipName(_anim);
		}
		catch
		{
			return;
		}

		if (string.IsNullOrEmpty(dominant))
			return;
		if (string.Equals(_lastDominantClip, dominant, StringComparison.Ordinal))
			return;
		_lastDominantClip = dominant;
		_player.OnBillboardDominantClipChanged(dominant);
	}

	private static string PickDominantClipName(Animator anim)
	{
		var infos = anim.GetCurrentAnimatorClipInfo(0);
		if (infos == null || infos.Length == 0)
			return null;
		AnimationClip best = null;
		var bestW = 0f;
		for (var i = 0; i < infos.Length; i++)
		{
			var c = infos[i].clip;
			if (c == null || !c)
				continue;
			var w = infos[i].weight;
			if (w > bestW)
			{
				bestW = w;
				best = c;
			}
		}

		return best != null && best ? best.name : null;
	}
}
