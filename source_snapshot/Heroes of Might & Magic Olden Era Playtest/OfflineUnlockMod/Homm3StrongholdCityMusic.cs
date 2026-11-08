using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Sound;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Sidecar town BGM for HoMM3 custom factions. Owns playback via a dedicated AudioSource.
/// Core <c>DB/city_music_sounds.json</c> must route sidecar factions to
/// <c>sounds/city/music/&lt;faction_sid&gt;</c> (not a vanilla donor set) so SessionCity
/// does not layer donor music underneath this player.
/// </summary>
internal static class Homm3StrongholdCityMusic
{
	const string GroupName = "sounds/city/music";
	static readonly Dictionary<string, CityMusicEntry> Entries = new Dictionary<string, CityMusicEntry>(StringComparer.OrdinalIgnoreCase);
	static GameObject _playerObject;
	static AudioSource _playerSource;
	static string _currentFactionSid;
	static ManualLogSource _log;

	public static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		_log = log;
	}

	static bool IsHomm3MusicSetKey(string value)
	{
		return TryNormalizeFactionSid(value, out _);
	}

	public static bool HasTownMusicBundle(string factionSid)
	{
		return TryNormalizeFactionSid(factionSid, out var normalized)
			&& File.Exists(ResolveBundlePath(normalized));
	}

	public static void EnsureTownMusicPlaying(string factionSid)
	{
		try
		{
			if (!TryNormalizeFactionSid(factionSid, out var normalized))
			{
				StopTownMusic();
				return;
			}

			var entry = GetEntry(normalized);
			if (!EnsureClipLoaded(entry))
			{
				StopTownMusic();
				return;
			}

			if (_playerObject == null || !_playerObject)
			{
				_playerObject = new GameObject("OfflineUnlockHomm3TownMusic");
				UnityEngine.Object.DontDestroyOnLoad(_playerObject);
			}

			if (_playerSource == null || !_playerSource)
			{
				_playerSource = _playerObject.GetComponent<AudioSource>();
				if (_playerSource == null || !_playerSource)
				{
					_playerSource = _playerObject.AddComponent<AudioSource>();
				}

				_playerSource.playOnAwake = false;
				_playerSource.loop = true;
				_playerSource.spatialBlend = 0f;
				_playerSource.dopplerLevel = 0f;
				_playerSource.priority = 32;
			}

			_playerSource.volume = GetConfiguredVolume();

			if (_playerSource.clip != entry.Clip)
			{
				_playerSource.Stop();
				_playerSource.clip = entry.Clip;
			}

			if (!_playerSource.isPlaying)
			{
				_playerSource.Play();
				_log?.LogInfo("Homm3StrongholdCityMusic: started sidecar town music AudioSource for " + entry.FactionSid + ".");
			}

			_currentFactionSid = entry.FactionSid;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3StrongholdCityMusic: failed to start sidecar town music for " + factionSid + ": " + ex.Message);
			StopTownMusic();
		}
	}

	public static void StopTownMusic()
	{
		try
		{
			if (_playerSource != null && _playerSource)
			{
				_playerSource.Stop();
			}
			_currentFactionSid = null;
		}
		catch
		{
			// Best effort only; this is a city-screen scoped sidecar.
		}
	}

	static bool EnsureClipLoaded(CityMusicEntry entry)
	{
		if (IsClipCacheAlive(entry))
			return true;
		if (entry.LoadAttempted)
		{
			if (entry.Bundle != null && entry.Bundle)
			{
				if (TryReloadClipAssetsFromLiveBundle(entry))
					return true;
				return false;
			}

			// Missing bundle / prior hard failure: stay fail-closed. Do not reset LoadAttempted —
			// that re-logged "bundle missing" on every town sync (~200×/session).
			return false;
		}
		entry.LoadAttempted = true;

		try
		{
			var bundlePath = ResolveBundlePath(entry.FactionSid);
			if (string.IsNullOrEmpty(bundlePath) || !File.Exists(bundlePath))
			{
				_log?.LogWarning("Homm3StrongholdCityMusic: bundle missing for " + entry.FactionSid + "; sidecar town music is disabled for this town.");
				return false;
			}

			entry.Bundle = AssetBundle.LoadFromFile(bundlePath);
			if (entry.Bundle == null)
			{
				_log?.LogWarning("Homm3StrongholdCityMusic: AssetBundle.LoadFromFile returned null for " + bundlePath);
				return false;
			}

			entry.GroupConfig = LoadAsset<SoundGroupConfig>(entry, entry.GroupAssetPath);
			entry.SetConfig = LoadAsset<SoundSetConfig>(entry, entry.SetAssetPath);
			entry.Clip = LoadAsset<AudioClip>(entry, entry.ClipAssetPath);
			if (!IsClipCacheAlive(entry))
			{
				_log?.LogWarning("Homm3StrongholdCityMusic: bundle is missing group/set/clip assets for " + entry.FactionSid + ".");
				return false;
			}

			_log?.LogInfo("Homm3StrongholdCityMusic: loaded HoMM3 " + ToPascalFactionName(entry.FactionSid) + " town music clip from sidecar.");
			return true;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3StrongholdCityMusic: failed to load sidecar music for " + entry.FactionSid + ": " + ex.Message);
			return false;
		}
	}

	static bool TryReloadClipAssetsFromLiveBundle(CityMusicEntry entry)
	{
		try
		{
			entry.GroupConfig = LoadAsset<SoundGroupConfig>(entry, entry.GroupAssetPath);
			entry.SetConfig = LoadAsset<SoundSetConfig>(entry, entry.SetAssetPath);
			entry.Clip = LoadAsset<AudioClip>(entry, entry.ClipAssetPath);
			if (!IsClipCacheAlive(entry))
			{
				_log?.LogWarning("Homm3StrongholdCityMusic: live bundle asset reload returned invalid group/set/clip assets for " + entry.FactionSid + ".");
				return false;
			}

			_log?.LogInfo("Homm3StrongholdCityMusic: restored HoMM3 " + ToPascalFactionName(entry.FactionSid) + " town music clip from live sidecar bundle.");
			return true;
		}
		catch (Exception ex)
		{
			_log?.LogWarning("Homm3StrongholdCityMusic: failed to reload live sidecar music assets for " + entry.FactionSid + ": " + ex.Message);
			return false;
		}
	}

	static bool IsClipCacheAlive(CityMusicEntry entry)
	{
		return entry.GroupConfig != null && entry.GroupConfig
		       && entry.SetConfig != null && entry.SetConfig
		       && entry.Clip != null && entry.Clip;
	}

	static T LoadAsset<T>(CityMusicEntry entry, string assetPath) where T : UnityEngine.Object
	{
		return entry.Bundle.LoadAsset<T>(assetPath);
	}

	static float GetConfiguredVolume()
	{
		try
		{
			var cfg = LauncherConfigReader.TryLoad();
			return Mathf.Clamp01((float)(cfg?.Homm3StrongholdTownMusicVolume ?? 0.25));
		}
		catch
		{
			return 0.25f;
		}
	}

	static CityMusicEntry GetEntry(string factionSid)
	{
		if (!Entries.TryGetValue(factionSid, out var entry))
		{
			entry = new CityMusicEntry(factionSid);
			Entries.Add(factionSid, entry);
		}
		return entry;
	}

	static string ResolveBundlePath(string factionSid)
	{
		var baseDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
		if (string.IsNullOrEmpty(baseDir))
			return null;

		var bundleFileName = BundleNameFor(factionSid);
		var direct = Path.Combine(baseDir, bundleFileName);
		if (File.Exists(direct))
			return direct;

		var nested = Path.Combine(baseDir, "homm3_city_music", bundleFileName);
		return File.Exists(nested) ? nested : direct;
	}

	static bool TryNormalizeFactionSid(string value, out string factionSid)
	{
		factionSid = null;
		if (string.IsNullOrWhiteSpace(value))
			return false;

		var key = value.Trim();
		const string resourcePrefix = "sounds/city/music/";
		if (key.StartsWith(resourcePrefix, StringComparison.OrdinalIgnoreCase))
			key = key.Substring(resourcePrefix.Length);
		if (key.EndsWith("_city_music", StringComparison.OrdinalIgnoreCase))
			key = key.Substring(0, key.Length - "_city_music".Length);

		if (!Homm3CustomFactionRegistry.IsReleaseUiPresentationEnabledFactionSid(key))
			return false;

		factionSid = key;
		return true;
	}

	static string BundleNameFor(string factionSid)
	{
		return factionSid + "_city_music";
	}

	static string RootFor(string factionSid)
	{
		return "assets/customaudio/homm3" + ToPascalFactionName(factionSid).ToLowerInvariant() + "citymusic";
	}

	static string ClipKeyFor(string factionSid)
	{
		return "MUSIC_Town_HOMM3_" + ToPascalFactionName(factionSid);
	}

	static string ToPascalFactionName(string factionSid)
	{
		var key = factionSid ?? string.Empty;
		if (key.StartsWith("homm3_", StringComparison.OrdinalIgnoreCase))
			key = key.Substring("homm3_".Length);
		var parts = key.Split(new[] { '_' }, StringSplitOptions.RemoveEmptyEntries);
		var result = string.Empty;
		foreach (var part in parts)
			result += char.ToUpperInvariant(part[0]) + part.Substring(1).ToLowerInvariant();
		return result;
	}

	sealed class CityMusicEntry
	{
		public CityMusicEntry(string factionSid)
		{
			FactionSid = factionSid;
			var root = RootFor(factionSid);
			var clipName = ClipKeyFor(factionSid);
			ClipKey = clipName;
			GroupAssetPath = root + "/sounds/city/music/soundgroupconfig.asset";
			SetAssetPath = root + "/sounds/city/music/" + factionSid + "/soundsetconfig.asset";
			ClipAssetPath = root + "/sounds/city/music/" + factionSid + "/" + clipName.ToLowerInvariant() + ".mp3";
		}

		public string FactionSid { get; }
		public string ClipKey { get; }
		public string GroupAssetPath { get; }
		public string SetAssetPath { get; }
		public string ClipAssetPath { get; }
		public AssetBundle Bundle;
		public SoundGroupConfig GroupConfig;
		public SoundSetConfig SetConfig;
		public AudioClip Clip;
		public bool LoadAttempted;
	}
}
