using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>Simple unscaled-time sprite flipbook for HoMM3 recruitment portraits.</summary>
internal static class Homm3HireUnitPortraitAnimator
{
	private const float MinimumFrameMs = 8f;
	private const float RecruitmentRifeUiScale = 3f;

	private sealed class Player
	{
		internal Image Image;
		internal Homm3ImportPortraitAnimationCache.Clip Clip;
		internal string Key;
		internal float FrameRateMs;
		internal float TimerMs;
		internal int Index;
		internal bool UsedUnityRife;
		internal bool ScaleRife;
	}

	private sealed class RawPlayer
	{
		internal RawImage Image;
		internal Homm3ImportPortraitAnimationCache.Clip Clip;
		internal string Key;
		internal float FrameRateMs;
		internal float TimerMs;
		internal int Index;
	}

	private static readonly Dictionary<int, Player> PlayersByImageId = new();
	private static readonly Dictionary<int, RawPlayer> RawPlayersByImageId = new();
	private static readonly Dictionary<int, Vector3> BaseImageScaleById = new();
	private static readonly List<int> RemoveBuffer = new();

	internal static void Apply(Image image, string sid, Sprite fallback)
	{
		Apply(image, sid, fallback, idleOnly: false, scaleRife: true);
	}

	internal static bool TryApplyShowcase(Image image, string sid, Sprite fallback, bool scaleRife)
	{
		return Apply(image, sid, fallback, idleOnly: false, scaleRife: scaleRife, out _);
	}

	internal static bool TryApplyRifeShowcase(Image image, string sid, Sprite fallback, bool scaleRife)
	{
		return Apply(image, sid, fallback, idleOnly: false, scaleRife: scaleRife, out _, rifeShowcaseOnly: true);
	}

	internal static void ApplyIdle(Image image, string sid, Sprite fallback)
	{
		Apply(image, sid, fallback, idleOnly: true, scaleRife: true);
	}

	internal static bool TryApplyIdle(Image image, string sid, Sprite fallback)
	{
		return Apply(image, sid, fallback, idleOnly: true, scaleRife: true, out _);
	}

	internal static bool TryApplyIdle(Image image, string sid, Sprite fallback, out bool usedUnityRife)
	{
		return Apply(image, sid, fallback, idleOnly: true, scaleRife: true, out usedUnityRife);
	}

	internal static void ApplyRawIdle(RawImage image, string sid, Texture fallback)
	{
		if (!image || string.IsNullOrWhiteSpace(sid))
			return;

		try
		{
			var sidKey = sid.Trim();
			var playerKey = "raw-idle:" + sidKey;
			var id = image.GetInstanceID();
			if (Homm3DiagnosticFlags.IsEnabled("homm3_disable_recruit_portrait_anim.flag"))
			{
				RawPlayersByImageId.Remove(id);
				if (fallback)
					image.texture = fallback;
				return;
			}

			if (RawPlayersByImageId.TryGetValue(id, out var player) && IsRunningFor(player, image, playerKey))
				return;

			if (!Homm3ImportPortraitAnimationCache.TryGetRecruitmentIdleClip(sidKey, out var clip, out var frameRateMs))
			{
				RawPlayersByImageId.Remove(id);
				if (fallback)
					image.texture = fallback;
				return;
			}

			Homm3PreviewApplyNextFrame.Ensure(Plugin.LogSource);
			RawPlayersByImageId[id] = new RawPlayer
			{
				Image = image,
				Clip = clip,
				Key = playerKey,
				FrameRateMs = Mathf.Max(MinimumFrameMs, frameRateMs),
				TimerMs = 0f,
				Index = 0,
			};
			var first = clip.GetSprite(0);
			if (first && first.texture)
				image.texture = first.texture;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 hire portrait animator: raw idle apply failed for sid='" + sid + "': " + ex.Message);
			if (fallback)
				image.texture = fallback;
		}
	}

	internal static void StopRaw(RawImage image)
	{
		if (!image)
			return;
		RawPlayersByImageId.Remove(image.GetInstanceID());
	}

	internal static void Stop(Image image)
	{
		if (!image)
			return;
		var id = image.GetInstanceID();
		PlayersByImageId.Remove(id);
		ApplyRecruitmentImageScale(image, id, useRifeScale: false);
	}

	private static bool Apply(Image image, string sid, Sprite fallback, bool idleOnly, bool scaleRife)
	{
		return Apply(image, sid, fallback, idleOnly, scaleRife, out _);
	}

	private static bool Apply(Image image, string sid, Sprite fallback, bool idleOnly, bool scaleRife, out bool usedUnityRife)
	{
		return Apply(image, sid, fallback, idleOnly, scaleRife, out usedUnityRife, rifeShowcaseOnly: false);
	}

	private static bool Apply(Image image, string sid, Sprite fallback, bool idleOnly, bool scaleRife, out bool usedUnityRife, bool rifeShowcaseOnly)
	{
		usedUnityRife = false;
		if (!image || string.IsNullOrWhiteSpace(sid))
			return false;

		try
		{
			var sidKey = sid.Trim();
			var playerKey = (idleOnly ? "idle:" : "full:") + sidKey;
			var id = image.GetInstanceID();
			if (Homm3DiagnosticFlags.IsEnabled("homm3_disable_recruit_portrait_anim.flag"))
			{
				PlayersByImageId.Remove(id);
				ApplyRecruitmentImageScale(image, id, useRifeScale: false);
				if (fallback)
					image.sprite = fallback;
				return false;
			}

			if (PlayersByImageId.TryGetValue(id, out var player)
			    && IsRunningFor(player, image, playerKey, scaleRife)
			    && (!rifeShowcaseOnly || player.UsedUnityRife))
			{
				usedUnityRife = player.UsedUnityRife;
				ApplyRecruitmentImageScale(image, id, usedUnityRife && player.ScaleRife);
				return true;
			}

			Homm3ImportPortraitAnimationCache.Clip clip;
			float frameRateMs;
			var hasClip = idleOnly
				? Homm3ImportPortraitAnimationCache.TryGetRecruitmentIdleClip(sidKey, out clip, out frameRateMs, out usedUnityRife)
				: rifeShowcaseOnly
					? Homm3ImportPortraitAnimationCache.TryGetUnityRifeShowcaseClip(sidKey, out clip, out frameRateMs)
				: Homm3ImportPortraitAnimationCache.TryGetClip(sidKey, out clip, out frameRateMs);
			if (!idleOnly)
				usedUnityRife = clip != null && clip.UseRifeScale;
			if (!hasClip)
			{
				PlayersByImageId.Remove(id);
				ApplyRecruitmentImageScale(image, id, useRifeScale: false);
				if (fallback)
					image.sprite = fallback;
				return false;
			}

			Homm3PreviewApplyNextFrame.Ensure(Plugin.LogSource);
			PlayersByImageId[id] = new Player
			{
				Image = image,
				Clip = clip,
				Key = playerKey,
				FrameRateMs = Mathf.Max(MinimumFrameMs, frameRateMs),
				TimerMs = 0f,
				Index = 0,
				UsedUnityRife = usedUnityRife,
				ScaleRife = scaleRife,
			};
			var first = clip.GetSprite(0);
			if (first)
			{
				ApplyRecruitmentImageScale(image, id, usedUnityRife && scaleRife);
				image.sprite = first;
				return true;
			}
			ApplyRecruitmentImageScale(image, id, useRifeScale: false);
			if (fallback)
				image.sprite = fallback;
			return false;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 hire portrait animator: apply failed for sid='" + sid + "': " + ex.Message);
			ApplyRecruitmentImageScale(image, image.GetInstanceID(), useRifeScale: false);
			if (fallback)
				image.sprite = fallback;
			return false;
		}
	}

	private static bool IsRunningFor(Player player, Image image, string key, bool scaleRife)
	{
		return player != null
		       && player.Image == image
		       && player.Clip != null
		       && player.Clip.FrameCount > 1
		       && player.ScaleRife == scaleRife
		       && string.Equals(player.Key, key, StringComparison.Ordinal);
	}

	private static void ApplyRecruitmentImageScale(Image image, int id, bool useRifeScale)
	{
		if (!image)
			return;
		var rect = image.rectTransform;
		if (!rect)
			return;
		if (!BaseImageScaleById.TryGetValue(id, out var baseScale))
		{
			baseScale = rect.localScale;
			BaseImageScaleById[id] = baseScale;
		}
		rect.localScale = useRifeScale
			? new Vector3(baseScale.x * RecruitmentRifeUiScale, baseScale.y * RecruitmentRifeUiScale, baseScale.z)
			: baseScale;
	}

	private static bool IsRunningFor(RawPlayer player, RawImage image, string key)
	{
		return player != null
		       && player.Image == image
		       && player.Clip != null
		       && player.Clip.FrameCount > 1
		       && string.Equals(player.Key, key, StringComparison.Ordinal);
	}

	internal static void TickAll()
	{
		if (PlayersByImageId.Count == 0 && RawPlayersByImageId.Count == 0)
			return;

		RemoveBuffer.Clear();
		foreach (var kvp in PlayersByImageId)
		{
			var player = kvp.Value;
			if (player == null || !player.Image || player.Clip == null || player.Clip.FrameCount <= 1)
			{
				if (player != null && player.Image)
					ApplyRecruitmentImageScale(player.Image, kvp.Key, useRifeScale: false);
				RemoveBuffer.Add(kvp.Key);
				continue;
			}

			player.TimerMs += Time.unscaledDeltaTime * 1000f;
			var duration = GetFrameDuration(player);
			while (player.TimerMs >= duration)
			{
				player.TimerMs -= duration;
				player.Index = (player.Index + 1) % player.Clip.FrameCount;
				duration = GetFrameDuration(player);
			}

			var sprite = player.Clip.GetSprite(player.Index);
			if (sprite && player.Image.sprite != sprite)
				player.Image.sprite = sprite;
		}

		for (var i = 0; i < RemoveBuffer.Count; i++)
			PlayersByImageId.Remove(RemoveBuffer[i]);

		RemoveBuffer.Clear();
		foreach (var kvp in RawPlayersByImageId)
		{
			var player = kvp.Value;
			if (player == null || !player.Image || player.Clip == null || player.Clip.FrameCount <= 1)
			{
				RemoveBuffer.Add(kvp.Key);
				continue;
			}

			player.TimerMs += Time.unscaledDeltaTime * 1000f;
			var duration = GetFrameDuration(player);
			while (player.TimerMs >= duration)
			{
				player.TimerMs -= duration;
				player.Index = (player.Index + 1) % player.Clip.FrameCount;
				duration = GetFrameDuration(player);
			}

			var sprite = player.Clip.GetSprite(player.Index);
			if (sprite && sprite.texture && player.Image.texture != sprite.texture)
				player.Image.texture = sprite.texture;
		}

		for (var i = 0; i < RemoveBuffer.Count; i++)
			RawPlayersByImageId.Remove(RemoveBuffer[i]);
	}

	private static float GetFrameDuration(Player player)
	{
		var durations = player.Clip.DurationsMs;
		if (durations != null && player.Index >= 0 && player.Index < durations.Length)
			return Mathf.Max(MinimumFrameMs, durations[player.Index]);
		return player.FrameRateMs;
	}

	private static float GetFrameDuration(RawPlayer player)
	{
		var durations = player.Clip.DurationsMs;
		if (durations != null && player.Index >= 0 && player.Index < durations.Length)
			return Mathf.Max(MinimumFrameMs, durations[player.Index]);
		return player.FrameRateMs;
	}
}
