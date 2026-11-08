using System;
using System.IO;
using BepInEx;
using UnityEngine;

namespace OfflineUnlockMod;

internal static class Homm3CovePirateShotAudio
{
	const string ClipName = "HOMM3_COVE_PIRTSHOT";
	const float MinPlayIntervalSeconds = 0.1f;
	static readonly string[] ShotPathParts =
	{
		"plugins",
		"OfflineUnlockMod",
		"homm3_runtime_assets",
		"cove",
		"homm3_cove",
		"sounds",
		"hota",
		"cove",
		"creatures",
		"pirate",
		"PIRTSHOT.wav"
	};

	static AudioClip _shotClip;
	static AudioSource _source;
	static GameObject _sourceObject;
	static bool _loadAttempted;
	static float _lastPlayTime = -999f;

	internal static bool TryPlayShot()
	{
		try
		{
			var now = Time.unscaledTime;
			if (now - _lastPlayTime < MinPlayIntervalSeconds)
				return false;

			EnsureLoaded();
			if (_shotClip == null || !_shotClip)
				return false;

			EnsureSource();
			if (_source == null || !_source)
				return false;

			_lastPlayTime = now;
			_source.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume * 0.8f);
			_source.PlayOneShot(_shotClip);
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CovePirateShotAudio: failed to play PIRTSHOT.wav: " + ex.Message);
			return false;
		}
	}

	static void EnsureLoaded()
	{
		if (_loadAttempted)
			return;
		_loadAttempted = true;

		var path = ResolveShotPath();
		if (string.IsNullOrEmpty(path) || !File.Exists(path))
		{
			Plugin.LogSource?.LogWarning("Homm3CovePirateShotAudio: missing " + path);
			return;
		}

		try
		{
			_shotClip = LoadPcmWav(path, ClipName);
			if (_shotClip != null && _shotClip)
				Plugin.LogSource?.LogInfo("Homm3CovePirateShotAudio: loaded " + path);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3CovePirateShotAudio: PIRTSHOT.wav load failed: " + ex.Message);
		}
	}

	static void EnsureSource()
	{
		if (_source != null && _source)
			return;

		_sourceObject = new GameObject("HOMM3_COVE_PIRTSHOT_AUDIO");
		UnityEngine.Object.DontDestroyOnLoad(_sourceObject);
		_source = _sourceObject.AddComponent<AudioSource>();
		_source.playOnAwake = false;
		_source.loop = false;
		_source.spatialBlend = 0f;
		_source.dopplerLevel = 0f;
		_source.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume * 0.8f);
	}

	static string ResolveShotPath()
	{
		var path = Paths.BepInExRootPath;
		for (var i = 0; i < ShotPathParts.Length; i++)
			path = Path.Combine(path, ShotPathParts[i]);
		return path;
	}

	static AudioClip LoadPcmWav(string path, string clipName)
	{
		var bytes = File.ReadAllBytes(path);
		if (bytes.Length < 44 || !HasTag(bytes, 0, "RIFF") || !HasTag(bytes, 8, "WAVE"))
			throw new InvalidDataException("not a RIFF/WAVE file");

		var offset = 12;
		var audioFormat = 0;
		var channels = 0;
		var sampleRate = 0;
		var bitsPerSample = 0;
		var dataOffset = -1;
		var dataSize = 0;

		while (offset + 8 <= bytes.Length)
		{
			var chunkSize = BitConverter.ToInt32(bytes, offset + 4);
			var chunkData = offset + 8;
			if (chunkSize < 0 || chunkData + chunkSize > bytes.Length)
				throw new InvalidDataException("invalid WAV chunk size");

			if (HasTag(bytes, offset, "fmt "))
			{
				if (chunkSize < 16)
					throw new InvalidDataException("short fmt chunk");
				audioFormat = BitConverter.ToInt16(bytes, chunkData);
				channels = BitConverter.ToInt16(bytes, chunkData + 2);
				sampleRate = BitConverter.ToInt32(bytes, chunkData + 4);
				bitsPerSample = BitConverter.ToInt16(bytes, chunkData + 14);
			}
			else if (HasTag(bytes, offset, "data"))
			{
				dataOffset = chunkData;
				dataSize = chunkSize;
			}

			offset = chunkData + chunkSize + (chunkSize & 1);
		}

		if (audioFormat != 1)
			throw new InvalidDataException("only PCM WAV is supported");
		if (channels <= 0 || sampleRate <= 0 || dataOffset < 0 || dataSize <= 0)
			throw new InvalidDataException("missing WAV fmt/data chunk");
		if (bitsPerSample != 8 && bitsPerSample != 16)
			throw new InvalidDataException("unsupported PCM bit depth " + bitsPerSample);

		var bytesPerSample = bitsPerSample / 8;
		var sampleCount = dataSize / bytesPerSample;
		var frameCount = sampleCount / channels;
		var samples = new float[sampleCount];

		for (var i = 0; i < sampleCount; i++)
		{
			var pos = dataOffset + i * bytesPerSample;
			samples[i] = bitsPerSample == 16
				? Mathf.Clamp(BitConverter.ToInt16(bytes, pos) / 32768f, -1f, 1f)
				: (bytes[pos] - 128) / 128f;
		}

		var clip = AudioClip.Create(clipName, frameCount, channels, sampleRate, false);
		clip.SetData(samples, 0);
		return clip;
	}

	static bool HasTag(byte[] bytes, int offset, string tag)
	{
		if (offset < 0 || offset + tag.Length > bytes.Length)
			return false;
		for (var i = 0; i < tag.Length; i++)
		{
			if (bytes[offset + i] != (byte)tag[i])
				return false;
		}
		return true;
	}
}
