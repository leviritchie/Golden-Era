using System;
using BepInEx.Logging;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: forwards the playing <see cref="Animator"/> state of a HoMM3 battle unit to <see cref="Homm3LabBattleAudioPlayer"/>
/// as an audio slot name ("14.Attack", "20.Damage", ...), the same clip-driven contract as <see cref="EsquireBattleClipAudioDriver"/>.
/// The slot comes from <see cref="Homm3LabClipAudioStates"/>: billboard controllers name their states after the slots, owned
/// skinned prefabs override the stock battle controller whose states are named differently.
/// </summary>
internal sealed class Homm3LabClipAudioDriver : MonoBehaviour
{
	private Homm3LabBattleAudioPlayer _player;
	private Animator _anim;
	private int _lastStateFullPathHash = int.MinValue;

	public Homm3LabClipAudioDriver(IntPtr ptr) : base(ptr) { }

	internal static void TryAttach(GameObject battleRoot, ManualLogSource log)
	{
		if (battleRoot == null || !battleRoot)
			return;
		try
		{
			Homm3ImportVisuals.EnsureHomm3LabClipAudioDriverTypeRegistered(log);
			if (battleRoot.GetComponent<Homm3LabClipAudioDriver>() != null)
				return;
			battleRoot.AddComponent<Homm3LabClipAudioDriver>();
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3LabClipAudioDriver: TryAttach failed: " + ex.Message);
		}
	}

	private void LateUpdate()
	{
		if (_player == null || !_player)
			_player = GetComponent<Homm3LabBattleAudioPlayer>();
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

		// During a cross-fade the state being entered is the one that sounds: the stock battle controller reaches
		// attack, damage and death through AnyState transitions, and waiting for the transition to finish played
		// every one-shot late. The hash then matches the entered state, so the end of the fade does not replay it.
		AnimatorStateInfo stateInfo;
		bool inTransition;
		try
		{
			inTransition = _anim.IsInTransition(0);
			stateInfo = inTransition ? _anim.GetNextAnimatorStateInfo(0) : _anim.GetCurrentAnimatorStateInfo(0);
		}
		catch
		{
			return;
		}

		var stateHash = stateInfo.fullPathHash;
		if (stateHash == _lastStateFullPathHash)
			return;
		_lastStateFullPathHash = stateHash;

		string slot;
		try
		{
			if (!Homm3LabClipAudioStates.TryPickSlot(stateInfo, out slot))
				slot = PickDominantClipNameFallback(_anim, inTransition);
		}
		catch
		{
			return;
		}

		if (string.IsNullOrEmpty(slot))
			return;
		_player.OnBillboardDominantClipChanged(slot);
	}

	/// <summary>Controllers that are neither billboard nor stock battle: the dominant playing clip's own name.</summary>
	static string PickDominantClipNameFallback(Animator anim, bool inTransition)
	{
		var infos = inTransition ? anim.GetNextAnimatorClipInfo(0) : anim.GetCurrentAnimatorClipInfo(0);
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

/// <summary>
/// Animator state -> battle audio slot for <see cref="Homm3LabClipAudioDriver"/>.
///
/// Billboard controllers (Homm3BillboardAnimatorBuild) name each state after its clip slot, so the slot is the state.
/// Owned skinned prefabs (Homm3OwnedSkinnedLabBuild) are an AnimatorOverrideController over the stock battle controller
/// <c>_Battle_Unit_Anim_ctrl_v2</c> (StockEsquireBattle.controller), whose states are "Attack Tree 2", "damage 0",
/// "DYING.die 0", "move 0", ... and whose override clips are Unit_AttackFront / Unit_Hitted / Unit_Move / Unit_Defence.
/// Before 2026-10-01 only the billboard names were listed, so an owned skinned unit fell through to the clip-name
/// fallback: "Unit_AttackFront" and "Unit_Death" still sounded, but damage ("Unit_Hitted"), walk/fly ("Unit_Move"),
/// shots ("Unit_ShootFront") and victory ("Unit_Defence") were silent. Pinned by
/// tools/validate_homm3_lab_clip_audio_driver_contract.py (this table, and the stock controller's state paths in the
/// installed owned skinned bundles).
/// </summary>
internal static class Homm3LabClipAudioStates
{
	internal static readonly (string State, string Slot)[] BillboardStateSlots =
	{
		("14.Attack", "14.Attack"),
		("15.Skill_1", "14.Attack"),
		("20.Damage", "20.Damage"),
		("21.Death", "21.Death"),
		("01.Walk", "01.Walk"),
		("22.Idle", "22.Idle"),
	};

	// Full state paths of the stock battle controller (IsName matches the full path hash).
	internal static readonly (string State, string Slot)[] StockStateSlots =
	{
		("Base Layer.Attack Tree 2", "14.Attack"),
		("Base Layer.Move Ability.moveAttack", "14.Attack"),
		("Base Layer.damage 0", "20.Damage"),
		("Base Layer.DYING.die 0", "21.Death"),
		("Base Layer.move 0", "01.Walk"),
		("Base Layer.Move Ability.moveAbility", "01.Walk"),
		("Base Layer.FLYING.fly 0", "01.Walk"),
		("Base Layer.Flying Ability.flyAbility", "01.Walk"),
		("Base Layer.idle", "22.Idle"),
		("Base Layer.rareIdle 0", "22.Idle"),
		("Base Layer.Victory", "27.Victory"),
	};

	internal static bool TryPickSlot(AnimatorStateInfo stateInfo, out string slot)
	{
		return TryPick(BillboardStateSlots, stateInfo, out slot) || TryPick(StockStateSlots, stateInfo, out slot);
	}

	private static bool TryPick((string State, string Slot)[] table, AnimatorStateInfo stateInfo, out string slot)
	{
		for (var i = 0; i < table.Length; i++)
		{
			if (stateInfo.IsName(table[i].State))
			{
				slot = table[i].Slot;
				return true;
			}
		}
		slot = null;
		return false;
	}
}
