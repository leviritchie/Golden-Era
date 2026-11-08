using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Harmony postfixes on <see cref="Animator"/>: optional verbose logging for battle hierarchy under a <c>battle</c> root.
/// Esquire bundle SFX is driven by <see cref="EsquireBattleClipAudioDriver"/> (clip names), not these setters.
/// </summary>
internal static class EsquireBattleAnimatorSetHook
{
	private static bool _patched;

	internal static void Cancel()
	{
		_patched = false;
	}

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched)
			return;
		try
		{
			var t = typeof(Animator);
			var flags = BindingFlags.Public | BindingFlags.Instance;
			var patched = new List<string>();
			var miss = new List<string>();

			void Try(string method, Type[] sig, string postfix)
			{
				var m = t.GetMethod(method, flags, null, sig, null);
				if (m == null)
				{
					miss.Add(method + "(" + string.Join(",", Array.ConvertAll(sig, s => s.Name)) + ")");
					return;
				}

				try
				{
					h.Patch(m, postfix: new HarmonyMethod(typeof(EsquireBattleAnimatorSetHook), postfix));
					patched.Add(m.Name + "(" + string.Join(", ", Array.ConvertAll(sig, s => s.Name)) + ")");
				}
				catch (Exception ex)
				{
					log?.LogWarning(
						"EsquirePikeman: Animator hook patch failed for "
						+ method
						+ "("
						+ string.Join(", ", Array.ConvertAll(sig, s => s.Name))
						+ "): "
						+ ex.Message);
				}
			}

			Try(nameof(Animator.SetFloat), new[] { typeof(int), typeof(float) }, nameof(PostfixSetFloat2));
			Try(nameof(Animator.SetFloat), new[] { typeof(int), typeof(float), typeof(float), typeof(float) }, nameof(PostfixSetFloat4));
			Try(nameof(Animator.SetBool), new[] { typeof(int), typeof(bool) }, nameof(PostfixSetBool));
			Try(nameof(Animator.SetInteger), new[] { typeof(int), typeof(int) }, nameof(PostfixSetInteger));
			Try(nameof(Animator.SetTrigger), new[] { typeof(int) }, nameof(PostfixSetTrigger));
			Try(nameof(Animator.ResetTrigger), new[] { typeof(int) }, nameof(PostfixResetTrigger));

			Try(nameof(Animator.SetFloat), new[] { typeof(string), typeof(float) }, nameof(PostfixSetFloatStr2));
			Try(nameof(Animator.SetFloat), new[] { typeof(string), typeof(float), typeof(float), typeof(float) }, nameof(PostfixSetFloatStr4));
			Try(nameof(Animator.SetBool), new[] { typeof(string), typeof(bool) }, nameof(PostfixSetBoolStr));
			Try(nameof(Animator.SetInteger), new[] { typeof(string), typeof(int) }, nameof(PostfixSetIntegerStr));
			Try(nameof(Animator.SetTrigger), new[] { typeof(string) }, nameof(PostfixSetTriggerStr));
			Try(nameof(Animator.ResetTrigger), new[] { typeof(string) }, nameof(PostfixResetTriggerStr));

			Try(nameof(Animator.Play), new[] { typeof(int), typeof(int), typeof(float) }, nameof(PostfixPlayInt));
			Try(nameof(Animator.Play), new[] { typeof(string), typeof(int), typeof(float) }, nameof(PostfixPlayStr));
			Try(nameof(Animator.CrossFade), new[] { typeof(int), typeof(float) }, nameof(PostfixCrossFade2));
			Try(nameof(Animator.CrossFade), new[] { typeof(int), typeof(float), typeof(int) }, nameof(PostfixCrossFade3));
			Try(nameof(Animator.CrossFade), new[] { typeof(int), typeof(float), typeof(int), typeof(float) }, nameof(PostfixCrossFade4));
			Try(nameof(Animator.CrossFade), new[] { typeof(int), typeof(float), typeof(int), typeof(float), typeof(float) }, nameof(PostfixCrossFade5));
			Try(nameof(Animator.CrossFade), new[] { typeof(string), typeof(float) }, nameof(PostfixCrossFadeStr2));
			Try(nameof(Animator.CrossFade), new[] { typeof(string), typeof(float), typeof(int) }, nameof(PostfixCrossFadeStr3));
			Try(nameof(Animator.CrossFade), new[] { typeof(string), typeof(float), typeof(int), typeof(float) }, nameof(PostfixCrossFadeStr4));
			Try(nameof(Animator.CrossFade), new[] { typeof(string), typeof(float), typeof(int), typeof(float), typeof(float) }, nameof(PostfixCrossFadeStr5));

			Try(nameof(Animator.PlayInFixedTime), new[] { typeof(int), typeof(int), typeof(float) }, nameof(PostfixPlayInFixedTime));
			Try(nameof(Animator.CrossFadeInFixedTime), new[] { typeof(int), typeof(float), typeof(int), typeof(float), typeof(float) }, nameof(PostfixCrossFadeInFixedTime5));

			_patched = true;
			if (patched.Count > 0)
			{
				log?.LogInfo(
					"EsquirePikeman: Harmony postfix on Animator (verbose-only Set*/Play/CrossFade on battle hierarchy): "
					+ string.Join("; ", patched));
			}

			if (miss.Count > 0)
			{
				log?.LogWarning(
					"EsquirePikeman: Animator setter hook: signature(s) not found (ok if Unity trimmed API): "
					+ string.Join(", ", miss));
			}
		}
		catch (Exception ex)
		{
			log?.LogError("EsquirePikeman: Animator setter hook failed: " + ex);
		}
	}

	private static bool IsEsquireBattleHierarchy(Animator anim)
	{
		if (anim == null)
			return false;
		try
		{
			return EsquireBattleAudioPlayer.FindBattlePrefabRoot(anim.transform) != null;
		}
		catch
		{
			return false;
		}
	}

	/// <summary>Labels for <c>_Battle_Unit_Anim_ctrl_v2</c> parameter name hashes (Unity 6000 <c>Animator.StringToHash</c>); see <c>tools/reference/AnimatorStringToHash_report.tsv</c>.</summary>
	private static string HintForId(int id) =>
		id switch
		{
			-281135240 => "move",
			-1400428176 => "moveAbility",
			-662202739 => "teleport",
			950686776 => "teleportAbility",
			1401586611 => "fly",
			1361439892 => "flyAbility",
			-1387820227 => "rotateLeft",
			-1357058045 => "rotateRight",
			-995794305 => "battleSpeed",
			-318988523 => "rareIdle",
			1203776827 => "attack",
			298341484 => "damage",
			1276664872 => "isDead",
			964231127 => "die",
			1891303514 => "victory",
			-1065424594 => "attackVariant",
			-350899940 => "revive",
			1447969220 => "stanceIn",
			-1265719960 => "stanceOut",
			-1555555164 => "battleSlowIdle",
			_ => string.Empty,
		};

	private static void LogCall(Animator __instance, string op, int id, string valueText)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || !IsEsquireBattleHierarchy(__instance))
			return;
		var hint = HintForId(id);
		var hx = id.ToString("X8");
		var fc = -1;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
		}

		var hintPart = string.IsNullOrEmpty(hint) ? string.Empty : " hint=" + hint;
		Plugin.LogSource?.LogInfo(
			"Esquire battle Animator write: "
			+ op
			+ " id="
			+ id
			+ " 0x"
			+ hx
			+ hintPart
			+ " "
			+ valueText
			+ " frame="
			+ fc);
	}

	private static void LogStateBlend(Animator __instance, string op, int stateHash, string detail)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || !IsEsquireBattleHierarchy(__instance))
			return;
		var hx = stateHash.ToString("X8");
		var fc = -1;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
		}

		Plugin.LogSource?.LogInfo(
			"Esquire battle Animator state: "
			+ op
			+ " stateHash="
			+ stateHash
			+ " 0x"
			+ hx
			+ " "
			+ detail
			+ " frame="
			+ fc);
	}

	private static void LogStateBlendStr(Animator __instance, string op, string stateName, int stateHash, string detail)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || !IsEsquireBattleHierarchy(__instance))
			return;
		var name = string.IsNullOrEmpty(stateName) ? "?" : stateName;
		var hx = stateHash.ToString("X8");
		var fc = -1;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
		}

		Plugin.LogSource?.LogInfo(
			"Esquire battle Animator state: "
			+ op
			+ " name="
			+ name
			+ " stateHash="
			+ stateHash
			+ " 0x"
			+ hx
			+ " "
			+ detail
			+ " frame="
			+ fc);
	}

	private static string F(float x) => x.ToString("0.####");

	private static void LogCallString(Animator __instance, string op, string paramName, string valueText)
	{
		if (!EsquirePikemanVisuals.VerboseEsquireHooks || !IsEsquireBattleHierarchy(__instance))
			return;
		var name = string.IsNullOrEmpty(paramName) ? "?" : paramName;
		var id = Animator.StringToHash(name);
		var hint = HintForId(id);
		var hx = id.ToString("X8");
		var fc = -1;
		try
		{
			fc = Time.frameCount;
		}
		catch
		{
		}

		var hintPart = string.IsNullOrEmpty(hint) ? string.Empty : " hint=" + hint;
		Plugin.LogSource?.LogInfo(
			"Esquire battle Animator write: "
			+ op
			+ " name="
			+ name
			+ " id="
			+ id
			+ " 0x"
			+ hx
			+ hintPart
			+ " "
			+ valueText
			+ " frame="
			+ fc);
	}

	public static void PostfixSetFloat2(Animator __instance, [HarmonyArgument(0)] int id, [HarmonyArgument(1)] float value) =>
		LogCall(__instance, "SetFloat", id, "value=" + value.ToString("0.####"));

	public static void PostfixSetFloat4(
		Animator __instance,
		[HarmonyArgument(0)] int id,
		[HarmonyArgument(1)] float value,
		[HarmonyArgument(2)] float dampTime,
		[HarmonyArgument(3)] float deltaTime) =>
		LogCall(
			__instance,
			"SetFloat(damped)",
			id,
			"value="
			+ value.ToString("0.####")
			+ " damp="
			+ dampTime.ToString("0.####")
			+ " dt="
			+ deltaTime.ToString("0.####"));

	public static void PostfixSetBool(Animator __instance, [HarmonyArgument(0)] int id, [HarmonyArgument(1)] bool value)
	{
		LogCall(__instance, "SetBool", id, "value=" + (value ? "true" : "false"));
	}

	public static void PostfixSetInteger(Animator __instance, [HarmonyArgument(0)] int id, [HarmonyArgument(1)] int value) =>
		LogCall(__instance, "SetInteger", id, "value=" + value);

	public static void PostfixSetTrigger(Animator __instance, [HarmonyArgument(0)] int id)
	{
		LogCall(__instance, "SetTrigger", id, "trigger");
	}

	public static void PostfixResetTrigger(Animator __instance, [HarmonyArgument(0)] int id) =>
		LogCall(__instance, "ResetTrigger", id, "reset");

	public static void PostfixSetFloatStr2(Animator __instance, [HarmonyArgument(0)] string name, [HarmonyArgument(1)] float value) =>
		LogCallString(__instance, "SetFloat", name, "value=" + value.ToString("0.####"));

	public static void PostfixSetFloatStr4(
		Animator __instance,
		[HarmonyArgument(0)] string name,
		[HarmonyArgument(1)] float value,
		[HarmonyArgument(2)] float dampTime,
		[HarmonyArgument(3)] float deltaTime) =>
		LogCallString(
			__instance,
			"SetFloat(damped)",
			name,
			"value="
			+ value.ToString("0.####")
			+ " damp="
			+ dampTime.ToString("0.####")
			+ " dt="
			+ deltaTime.ToString("0.####"));

	public static void PostfixSetBoolStr(Animator __instance, [HarmonyArgument(0)] string name, [HarmonyArgument(1)] bool value)
	{
		LogCallString(__instance, "SetBool", name, "value=" + (value ? "true" : "false"));
	}

	public static void PostfixSetIntegerStr(Animator __instance, [HarmonyArgument(0)] string name, [HarmonyArgument(1)] int value) =>
		LogCallString(__instance, "SetInteger", name, "value=" + value);

	public static void PostfixSetTriggerStr(Animator __instance, [HarmonyArgument(0)] string name)
	{
		LogCallString(__instance, "SetTrigger", name, "trigger");
	}

	public static void PostfixResetTriggerStr(Animator __instance, [HarmonyArgument(0)] string name) =>
		LogCallString(__instance, "ResetTrigger", name, "reset");

	public static void PostfixPlayInt(
		Animator __instance,
		[HarmonyArgument(0)] int stateNameHash,
		[HarmonyArgument(1)] int layer,
		[HarmonyArgument(2)] float normalizedTime) =>
		LogStateBlend(
			__instance,
			"Play",
			stateNameHash,
			"layer=" + layer + " normTime=" + F(normalizedTime));

	public static void PostfixPlayStr(
		Animator __instance,
		[HarmonyArgument(0)] string stateName,
		[HarmonyArgument(1)] int layer,
		[HarmonyArgument(2)] float normalizedTime)
	{
		var h = string.IsNullOrEmpty(stateName) ? 0 : Animator.StringToHash(stateName);
		LogStateBlendStr(__instance, "Play", stateName, h, "layer=" + layer + " normTime=" + F(normalizedTime));
	}

	public static void PostfixCrossFade2(
		Animator __instance,
		[HarmonyArgument(0)] int stateHashName,
		[HarmonyArgument(1)] float normalizedTransitionDuration) =>
		LogStateBlend(__instance, "CrossFade", stateHashName, "dur=" + F(normalizedTransitionDuration));

	public static void PostfixCrossFade3(
		Animator __instance,
		[HarmonyArgument(0)] int stateHashName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer) =>
		LogStateBlend(
			__instance,
			"CrossFade",
			stateHashName,
			"dur=" + F(normalizedTransitionDuration) + " layer=" + layer);

	public static void PostfixCrossFade4(
		Animator __instance,
		[HarmonyArgument(0)] int stateHashName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer,
		[HarmonyArgument(3)] float normalizedTimeOffset) =>
		LogStateBlend(
			__instance,
			"CrossFade",
			stateHashName,
			"dur="
			+ F(normalizedTransitionDuration)
			+ " layer="
			+ layer
			+ " off="
			+ F(normalizedTimeOffset));

	public static void PostfixCrossFade5(
		Animator __instance,
		[HarmonyArgument(0)] int stateHashName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer,
		[HarmonyArgument(3)] float normalizedTimeOffset,
		[HarmonyArgument(4)] float normalizedTransitionTime) =>
		LogStateBlend(
			__instance,
			"CrossFade",
			stateHashName,
			"dur="
			+ F(normalizedTransitionDuration)
			+ " layer="
			+ layer
			+ " off="
			+ F(normalizedTimeOffset)
			+ " trans="
			+ F(normalizedTransitionTime));

	public static void PostfixCrossFadeStr2(
		Animator __instance,
		[HarmonyArgument(0)] string stateName,
		[HarmonyArgument(1)] float normalizedTransitionDuration)
	{
		var h = string.IsNullOrEmpty(stateName) ? 0 : Animator.StringToHash(stateName);
		LogStateBlendStr(__instance, "CrossFade", stateName, h, "dur=" + F(normalizedTransitionDuration));
	}

	public static void PostfixCrossFadeStr3(
		Animator __instance,
		[HarmonyArgument(0)] string stateName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer)
	{
		var h = string.IsNullOrEmpty(stateName) ? 0 : Animator.StringToHash(stateName);
		LogStateBlendStr(
			__instance,
			"CrossFade",
			stateName,
			h,
			"dur=" + F(normalizedTransitionDuration) + " layer=" + layer);
	}

	public static void PostfixCrossFadeStr4(
		Animator __instance,
		[HarmonyArgument(0)] string stateName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer,
		[HarmonyArgument(3)] float normalizedTimeOffset)
	{
		var h = string.IsNullOrEmpty(stateName) ? 0 : Animator.StringToHash(stateName);
		LogStateBlendStr(
			__instance,
			"CrossFade",
			stateName,
			h,
			"dur="
			+ F(normalizedTransitionDuration)
			+ " layer="
			+ layer
			+ " off="
			+ F(normalizedTimeOffset));
	}

	public static void PostfixCrossFadeStr5(
		Animator __instance,
		[HarmonyArgument(0)] string stateName,
		[HarmonyArgument(1)] float normalizedTransitionDuration,
		[HarmonyArgument(2)] int layer,
		[HarmonyArgument(3)] float normalizedTimeOffset,
		[HarmonyArgument(4)] float normalizedTransitionTime)
	{
		var h = string.IsNullOrEmpty(stateName) ? 0 : Animator.StringToHash(stateName);
		LogStateBlendStr(
			__instance,
			"CrossFade",
			stateName,
			h,
			"dur="
			+ F(normalizedTransitionDuration)
			+ " layer="
			+ layer
			+ " off="
			+ F(normalizedTimeOffset)
			+ " trans="
			+ F(normalizedTransitionTime));
	}

	public static void PostfixPlayInFixedTime(
		Animator __instance,
		[HarmonyArgument(0)] int stateNameHash,
		[HarmonyArgument(1)] int layer,
		[HarmonyArgument(2)] float fixedTime) =>
		LogStateBlend(__instance, "PlayInFixedTime", stateNameHash, "layer=" + layer + " fixedTime=" + F(fixedTime));

	public static void PostfixCrossFadeInFixedTime5(
		Animator __instance,
		[HarmonyArgument(0)] int stateHashName,
		[HarmonyArgument(1)] float fixedTransitionDuration,
		[HarmonyArgument(2)] int layer,
		[HarmonyArgument(3)] float fixedTimeOffset,
		[HarmonyArgument(4)] float fixedTransitionTime) =>
		LogStateBlend(
			__instance,
			"CrossFadeInFixedTime",
			stateHashName,
			"fdur="
			+ F(fixedTransitionDuration)
			+ " layer="
			+ layer
			+ " foff="
			+ F(fixedTimeOffset)
			+ " ftrans="
			+ F(fixedTransitionTime));
}
