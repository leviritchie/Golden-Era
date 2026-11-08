using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Hex.Session.Battle.BattleLog;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3GlobalCombatMusic
{
	const string BundleFileName = "homm3_combat_music";
	static readonly List<AudioClip> Clips = new();
	static AssetBundle _bundle;
	static bool _attached;
	static bool _patched;
	static bool _loadAttempted;
	static int _nextClipIndex;
	static GameObject _go;
	static AudioSource _source;
	static ManualLogSource _log;

	internal static void Ensure(ManualLogSource log, Harmony harmony)
	{
		if (_attached)
			return;

		_log = log;
		try
		{
			PatchBattleLifecycle(harmony);
			_go = new GameObject("OfflineUnlockHomm3GlobalCombatMusic");
			_go.hideFlags = HideFlags.HideAndDontSave;
			_source = _go.AddComponent<AudioSource>();
			ConfigureSource(_source);
			UnityEngine.Object.DontDestroyOnLoad(_go);
			_attached = true;
			_log?.LogInfo("Homm3GlobalCombatMusic: lifecycle-driven HoMM3 combat music attached.");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3GlobalCombatMusic: attach failed: " + ex.Message);
		}
	}

	static void PatchBattleLifecycle(Harmony harmony)
	{
		if (_patched || harmony == null)
			return;

		var start = AccessTools.Method(typeof(BhBattleLog), "Start", Type.EmptyTypes);
		if (start == null)
		{
			_log?.LogWarning("Homm3GlobalCombatMusic: BhBattleLog.Start not found; combat music sidecar will not start.");
			return;
		}

		harmony.Patch(start, postfix: new HarmonyMethod(typeof(Homm3GlobalCombatMusic), nameof(PostfixBattleLogStart)));
		var exit = AccessTools.Method(typeof(BhBattleEnd), nameof(BhBattleEnd.OnBtnExit), Type.EmptyTypes);
		if (exit != null)
			harmony.Patch(exit, prefix: new HarmonyMethod(typeof(Homm3GlobalCombatMusic), nameof(PrefixBattleEndExit)));
		_patched = true;
		_log?.LogInfo("Homm3GlobalCombatMusic: patched BhBattleLog.Start as battle lifecycle signal.");
	}

	static void ConfigureSource(AudioSource source)
	{
		if (source == null)
			return;
		TrySetPlayOnAwake(source, false);
		source.loop = true;
		source.spatialBlend = 0f;
		source.dopplerLevel = 0f;
		source.priority = 16;
		source.volume = 0.35f;
	}

	static void TrySetPlayOnAwake(AudioSource source, bool value)
	{
		// Live Golden Era / Unity 6 IL2CPP interop can omit AudioSource.set_playOnAwake.
		// A hard property write JITs that missing setter into Ensure() and BepInEx then
		// aborts the entire plugin load. Keep the token out of Ensure and fail only music.
		try
		{
			var prop = typeof(AudioSource).GetProperty("playOnAwake", BindingFlags.Instance | BindingFlags.Public);
			prop?.SetValue(source, value, null);
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3GlobalCombatMusic: playOnAwake unavailable: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	internal static void LogInfo(string message)
	{
		_log?.LogInfo("Homm3GlobalCombatMusic: " + message);
	}

	internal static void LogWarning(string message)
	{
		_log?.LogWarning("Homm3GlobalCombatMusic: " + message);
	}

	internal static string ResolveBundlePath()
	{
		var baseDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
		if (string.IsNullOrEmpty(baseDir))
			return null;

		var direct = Path.Combine(baseDir, BundleFileName);
		if (File.Exists(direct))
			return direct;

		var nested = Path.Combine(baseDir, "homm3_combat_music", BundleFileName);
		return File.Exists(nested) ? nested : direct;
	}

	static void PostfixBattleLogStart()
	{
		StartCombatMusic();
	}

	static void PrefixBattleEndExit()
	{
		StopCombatMusic();
	}

	static void StartCombatMusic()
	{
		if (!EnsureClipLoaded())
			return;

		if (_source == null)
		{
			_source = _go != null ? _go.GetComponent<AudioSource>() : null;
			if (_source == null)
				_source = _go != null ? _go.AddComponent<AudioSource>() : null;
			if (_source == null)
				return;
			ConfigureSource(_source);
		}

		var clip = Clips[_nextClipIndex % Clips.Count];
		_nextClipIndex++;
		if (_source.clip != clip)
		{
			_source.Stop();
			_source.clip = clip;
		}

		if (!_source.isPlaying)
		{
			_source.Play();
			Homm3GlobalCombatMusic.LogInfo("started global sidecar combat music clip '" + clip.name + "'.");
		}
	}

	static void StopCombatMusic()
	{
		if (_source != null && _source)
		{
			_source.Stop();
			Homm3GlobalCombatMusic.LogInfo("stopped global sidecar combat music.");
		}
	}

	static bool EnsureClipLoaded()
	{
		if (Clips.Count > 0)
			return true;
		if (_loadAttempted)
			return false;
		_loadAttempted = true;

		try
		{
			var bundlePath = Homm3GlobalCombatMusic.ResolveBundlePath();
			if (string.IsNullOrEmpty(bundlePath) || !File.Exists(bundlePath))
			{
				Homm3GlobalCombatMusic.LogWarning("bundle missing; expected " + bundlePath);
				return false;
			}

			_bundle = AssetBundle.LoadFromFile(bundlePath);
			if (_bundle == null)
			{
				Homm3GlobalCombatMusic.LogWarning("AssetBundle.LoadFromFile returned null for " + bundlePath);
				return false;
			}

			var clips = _bundle.LoadAllAssets<AudioClip>();
			for (var i = 0; i < clips.Length; i++)
			{
				var clip = clips[i];
				if (clip != null && clip)
					Clips.Add(clip);
			}

			if (Clips.Count == 0)
			{
				Homm3GlobalCombatMusic.LogWarning("bundle loaded but contained no AudioClip assets.");
				return false;
			}

			Clips.Sort((a, b) => string.Compare(a.name, b.name, StringComparison.OrdinalIgnoreCase));
			Homm3GlobalCombatMusic.LogInfo("loaded " + Clips.Count + " HoMM3 combat music clip(s).");
			return true;
		}
		catch (Exception ex)
		{
			Homm3GlobalCombatMusic.LogWarning("failed to load combat music bundle: " + ex.Message);
			return false;
		}
	}
}
