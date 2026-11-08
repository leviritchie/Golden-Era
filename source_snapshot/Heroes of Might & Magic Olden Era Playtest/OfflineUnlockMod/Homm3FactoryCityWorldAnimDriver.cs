using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using BepInEx;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// World-space HotA DEF overlay animator for Factory city art quads.
/// Frame 0 stays on the base MeshRenderer; frames 1..N cycle on a child overlay quad.
/// </summary>
public sealed class Homm3FactoryCityWorldAnimDriver : MonoBehaviour
{
	private const string OverlayName = "OfflineUnlockFactoryWorldAnimOverlay";
	private const string LogPrefix = "HoMM3 factory city world anim: ";

	private MeshRenderer _baseRenderer;
	private MeshRenderer _overlayRenderer;
	private Material _overlayMaterial;
	private Texture2D[] _frames;
	private float _frameRateMs = 100f;
	private float _timer;
	private int _currentFrame;
	private bool _ready;
	private string _layerId;

	public Homm3FactoryCityWorldAnimDriver(IntPtr ptr) : base(ptr) { }

	internal static void EnsureRegistered()
	{
		ClassInjector.RegisterTypeInIl2Cpp<Homm3FactoryCityWorldAnimDriver>();
	}

	internal static Homm3FactoryCityWorldAnimDriver TryAttach(
		GameObject artRoot, MeshRenderer baseRenderer, string fraction, string layerId,
		Material sharedMaterialTemplate)
	{
		if (artRoot == null || baseRenderer == null || string.IsNullOrEmpty(fraction)
			|| string.IsNullOrEmpty(layerId))
			return null;
		EnsureRegistered();
		var driver = artRoot.GetComponent<Homm3FactoryCityWorldAnimDriver>();
		if (driver == null)
			driver = artRoot.AddComponent<Homm3FactoryCityWorldAnimDriver>();
		driver.Initialize(baseRenderer, fraction, layerId, sharedMaterialTemplate);
		return driver;
	}

	private void Initialize(MeshRenderer baseRenderer, string fraction, string layerId,
		Material sharedMaterialTemplate)
	{
		_baseRenderer = baseRenderer;
		_layerId = layerId;
		_ready = false;
		_frames = null;

		var metaPath = ResolveMetadataPath(fraction);
		if (metaPath == null)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "metadata.json missing for layer '" + layerId + "'.");
			return;
		}

		JObject animMeta = null;
		try
		{
			var arr = JArray.Parse(File.ReadAllText(metaPath));
			for (var i = 0; i < arr.Count; i++)
			{
				var entry = JObject.Parse(arr[i].ToString());
				var id = entry["id"]?.ToString();
				if (string.Equals(id, layerId, StringComparison.OrdinalIgnoreCase))
				{
					animMeta = entry;
					break;
				}
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "metadata parse failed for '" + layerId + "': " + ex.Message);
			return;
		}

		if (animMeta == null)
		{
			// Not every Factory layer has a DEF anim extract — silent skip is OK, but only once per layer.
			return;
		}

		var frMs = animMeta["frameRateMs"];
		if (frMs != null)
			Homm3JsonNumber.TryParseFloat(frMs.ToString(), out _frameRateMs);
		if (_frameRateMs <= 0f)
			_frameRateMs = 100f;

		var framesToken = animMeta["frames"];
		if (framesToken == null)
			return;
		JArray framesArr;
		try
		{
			framesArr = JArray.Parse(framesToken.ToString());
		}
		catch
		{
			return;
		}

		var animId = animMeta["id"]?.ToString();
		if (string.IsNullOrWhiteSpace(animId))
			animId = layerId;

		var frameDir = ResolveExistingDirectory(Path.Combine(Path.GetDirectoryName(metaPath) ?? "", animId));
		if (frameDir == null)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "frame directory missing for '" + animId + "'.");
			return;
		}

		var loaded = new List<Texture2D>();
		for (var i = 0; i < framesArr.Count; i++)
		{
			var name = framesArr[i]?.ToString();
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var path = Path.Combine(frameDir, name);
			if (!File.Exists(path))
				continue;
			var tex = LoadFrameTexture(path, animId + "_" + name);
			if (tex != null)
				loaded.Add(tex);
		}

		if (loaded.Count < 2)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "need >=2 frames for '" + animId
				+ "' (loaded " + loaded.Count + ").");
			return;
		}

		_frames = loaded.ToArray();
		_baseRenderer.sharedMaterial = CloneMaterial(sharedMaterialTemplate, _frames[0]);
		EnsureOverlay(sharedMaterialTemplate);
		_overlayMaterial = CloneMaterial(sharedMaterialTemplate, _frames[1]);
		_overlayRenderer.sharedMaterial = _overlayMaterial;
		_currentFrame = 1;
		_timer = 0f;
		_ready = true;
		Plugin.LogSource?.LogInfo(LogPrefix + "playing '" + animId + "' frames=" + _frames.Length
			+ " on '" + gameObject.name + "'.");
	}

	private static string ResolveMetadataPath(string fraction)
	{
		var relative = Path.Combine(
			"homm3_runtime_assets",
			"town_scene_refs",
			fraction,
			"layers",
			"anims",
			"metadata.json");
		var underPlugin = Path.GetFullPath(Path.Combine(Paths.PluginPath, "OfflineUnlockMod", relative));
		if (File.Exists(underPlugin))
			return underPlugin;
		var underRoot = Path.GetFullPath(Path.Combine(Paths.PluginPath, relative));
		return File.Exists(underRoot) ? underRoot : null;
	}

	private void EnsureOverlay(Material sharedMaterialTemplate)
	{
		var child = transform.Find(OverlayName);
		GameObject go;
		if (child == null)
		{
			go = new GameObject(OverlayName);
			go.transform.SetParent(transform, false);
			go.transform.localRotation = Quaternion.identity;
			go.transform.localScale = Vector3.one;
			var mesh = _baseRenderer.GetComponent<MeshFilter>()?.sharedMesh;
			go.AddComponent<MeshFilter>().sharedMesh = mesh;
			_overlayRenderer = go.AddComponent<MeshRenderer>();
		}
		else
		{
			go = child.gameObject;
			_overlayRenderer = go.GetComponent<MeshRenderer>() ?? go.AddComponent<MeshRenderer>();
		}
		// Parent faces the camera with +local Z toward the viewer; positive Z puts the
		// overlay in front of the static base (negative Z was invisible behind it).
		go.transform.localPosition = new Vector3(0f, 0f, 0.002f);
		_overlayRenderer.enabled = true;
		_overlayRenderer.sortingOrder = _baseRenderer != null
			? _baseRenderer.sortingOrder + 1
			: 101;
	}

	private static Material CloneMaterial(Material template, Texture2D texture)
	{
		var mat = template != null
			? new Material(template)
			: new Material(Shader.Find("Sprites/Default"));
		mat.mainTexture = texture;
		if (mat.HasProperty("_MainTex"))
			mat.SetTexture("_MainTex", texture);
		if (mat.HasProperty("_Color"))
			mat.color = Color.white;
		return mat;
	}

	private static Texture2D LoadFrameTexture(string path, string name)
	{
		try
		{
			var rawBytes = File.ReadAllBytes(path);
			var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
			var il2cppBytes = new Il2CppStructArray<byte>(rawBytes.LongLength);
			for (var j = 0; j < rawBytes.Length; j++)
				il2cppBytes[j] = rawBytes[j];
			if (!ImageConversion.LoadImage(tex, il2cppBytes))
			{
				UnityEngine.Object.Destroy(tex);
				return null;
			}
			tex.name = name;
			tex.filterMode = FilterMode.Bilinear;
			tex.wrapMode = TextureWrapMode.Clamp;
			tex.hideFlags = HideFlags.DontUnloadUnusedAsset;
			return tex;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning(LogPrefix + "frame load failed '" + name + "': " + ex.Message);
			return null;
		}
	}

	private static string ResolveExistingDirectory(string path)
	{
		try
		{
			var full = Path.GetFullPath(path);
			return Directory.Exists(full) ? full : null;
		}
		catch
		{
			return null;
		}
	}

	private void Update()
	{
		if (!_ready || _frames == null || _frames.Length < 2 || _overlayMaterial == null)
			return;
		_timer += Time.deltaTime * 1000f;
		if (_timer < _frameRateMs)
			return;
		_timer -= _frameRateMs;
		_currentFrame++;
		if (_currentFrame >= _frames.Length)
			_currentFrame = 1;
		var frame = _frames[_currentFrame];
		_overlayMaterial.mainTexture = frame;
		if (_overlayMaterial.HasProperty("_MainTex"))
			_overlayMaterial.SetTexture("_MainTex", frame);
	}
}
