using System;
using HarmonyLib;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.Video;

namespace OfflineUnlockMod;

/// <summary>
/// Shorten cold-start / menu <b>publisher</b> video intros for automated playtest iteration.
/// Seeks to near end-of-clip right after <see cref="VideoPlayer.Play"/>, only when
/// <see cref="LauncherConfig.SkipIntroCinematics"/> and the clip is a known publisher
/// boot intro (Ubisoft / Unfrozen / Hooded_Horse / Trailer). Campaign StoryHub clips
/// such as <c>Campaign_Intro</c> / <c>Cgood1</c> / <c>Good1a</c> must play their full duration.
/// </summary>
[HarmonyPatch(typeof(VideoPlayer), nameof(VideoPlayer.Play))]
internal static class IntroVideoPlayerPlayFastForwardPatch
{
	private static readonly string[] PublisherIntroNameNeedles =
	{
		"Ubisoft",
		"Unfrozen",
		"Hooded_Horse",
		"Hooded Horse",
		"Trailer",
	};

	private static bool _loggedOnce;

	private static void Postfix(VideoPlayer __instance)
	{
		if (__instance == null)
		{
			return;
		}

		var cfg = LauncherConfigReader.TryLoad();
		if (cfg == null || !cfg.SkipIntroCinematics)
		{
			return;
		}

		if (Time.realtimeSinceStartup > cfg.SkipIntroCinematicsBootRealtimeCapSec)
		{
			return;
		}

		var sceneName = SceneManager.GetActiveScene().name ?? "";
		if (IsGameplayLikeScene(sceneName))
		{
			return;
		}

		if (!IsPublisherBootIntro(__instance))
		{
			return;
		}

		try
		{
			double len;
			if (__instance.clip != null)
			{
				len = __instance.clip.length;
			}
			else
			{
				len = __instance.length;
			}

			if (len < 0.25 || len > 900.0)
			{
				return;
			}

			__instance.time = Math.Max(0.0, len - 0.05);

			if (!_loggedOnce)
			{
				_loggedOnce = true;
				Plugin.LogSource?.LogInfo(
					"Intro skip: fast-forwarded publisher VideoPlayer clip (scene="
					+ sceneName
					+ ", len="
					+ len.ToString(System.Globalization.CultureInfo.InvariantCulture)
					+ "s). Campaign clips are not skipped. Set skipIntroCinematics=false to disable.");
			}
		}
		catch
		{
			// Il2Cpp URLs / unprepared players — ignore
		}
	}

	private static bool IsPublisherBootIntro(VideoPlayer player)
	{
		var identity = BuildClipIdentity(player);
		if (string.IsNullOrEmpty(identity))
		{
			// Fail closed: unknown clip identity must not be fast-forwarded
			// (would nuke StoryHub PlayVideo / Campaign_Intro / Cgood1).
			return false;
		}

		for (var i = 0; i < PublisherIntroNameNeedles.Length; i++)
		{
			if (identity.IndexOf(PublisherIntroNameNeedles[i], StringComparison.OrdinalIgnoreCase) >= 0)
			{
				return true;
			}
		}

		return false;
	}

	private static string BuildClipIdentity(VideoPlayer player)
	{
		try
		{
			if (player.clip != null && !string.IsNullOrEmpty(player.clip.name))
			{
				return player.clip.name;
			}
		}
		catch
		{
			// ignore
		}

		try
		{
			var url = player.url;
			if (!string.IsNullOrEmpty(url))
			{
				return url;
			}
		}
		catch
		{
			// ignore
		}

		return "";
	}

	private static bool IsGameplayLikeScene(string sceneName)
	{
		if (string.IsNullOrEmpty(sceneName))
		{
			return false;
		}

		if (sceneName.IndexOf("world", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		if (sceneName.IndexOf("battle", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		if (sceneName.IndexOf("arena", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		if (sceneName.IndexOf("combat", StringComparison.OrdinalIgnoreCase) >= 0)
		{
			return true;
		}

		return false;
	}
}
