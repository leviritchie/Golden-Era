using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Persistent host for adventure-map HoMM3 idle animation. It has no custom method parameters so IL2CPP
/// registration stays simple; material/frame state lives in the managed registry below.
/// </summary>
public sealed class Homm3MapIdleTextureAnimator : MonoBehaviour
{
	private const int RegisterRefreshIntervalFrames = 30;
	private Renderer _renderer;
	private int _registeredRendererId;
	private int _registeredMaterialId;
	private int _refreshFrames;
	private int _stableRegisterFrames;

	private void Awake()
	{
		TryRegisterLocalRenderer(force: true);
	}

	private void OnEnable()
	{
		_stableRegisterFrames = 0;
		TryRegisterLocalRenderer(force: true);
	}

	private void LateUpdate()
	{
		// After a few stable frames, only refresh registration periodically; Tick is frame-deduped globally.
		if (_registeredRendererId == 0 || _stableRegisterFrames < 3)
			TryRegisterLocalRenderer(force: false);
		else if (++_refreshFrames >= RegisterRefreshIntervalFrames)
		{
			_refreshFrames = 0;
			TryRegisterLocalRenderer(force: true);
		}
		Homm3MapIdleTextureAnimatorRegistry.Tick();
	}

	private void OnDisable()
	{
		if (_registeredRendererId == 0)
			return;
		Homm3MapIdleTextureAnimatorRegistry.UnregisterRenderer(_registeredRendererId);
		_registeredRendererId = 0;
		_stableRegisterFrames = 0;
	}

	private void OnDestroy()
	{
		OnDisable();
	}

	private bool TryRegisterLocalRenderer(bool force)
	{
		if (!_renderer)
			_renderer = GetComponent<Renderer>();
		if (!_renderer)
			return false;

		var id = _renderer.GetInstanceID();
		var materialId = GetPrimaryMaterialId(_renderer);
		if (_registeredRendererId != id || _registeredMaterialId != materialId)
		{
			_registeredRendererId = id;
			_registeredMaterialId = materialId;
			_refreshFrames = 0;
			_stableRegisterFrames = 0;
			Homm3MapIdleTextureAnimatorRegistry.RegisterRenderer(_renderer);
			return true;
		}

		_stableRegisterFrames++;
		if (force || ++_refreshFrames >= RegisterRefreshIntervalFrames)
		{
			_refreshFrames = 0;
			Homm3MapIdleTextureAnimatorRegistry.RefreshRenderer(_renderer);
		}
		return true;
	}

	private static int GetPrimaryMaterialId(Renderer renderer)
	{
		if (!renderer)
			return 0;
		try
		{
			var mats = renderer.sharedMaterials;
			if (mats != null)
				for (var i = 0; i < mats.Length; i++)
					if (mats[i])
						return mats[i].GetInstanceID();
		}
		catch
		{
		}
		var material = renderer.sharedMaterial;
		return material ? material.GetInstanceID() : 0;
	}
}

internal static class Homm3MapIdleTextureAnimatorRegistry
{
	private sealed class Entry
	{
		internal Material Material;
		internal string MaterialName;
		internal Texture2D[] Frames;
		internal float FrameMs;
		internal float TimerMs;
		internal int Index;
		internal int LastBroadcastIndex = -1;
	}

	private sealed class RendererEntry
	{
		internal Renderer Renderer;
		internal Entry Entry;
		internal int MaterialId;
		internal int LastAppliedIndex = -1;
	}

	private static readonly Dictionary<int, Entry> EntriesByMaterialId = new();
	private static readonly Dictionary<string, Entry> EntriesByMaterialName = new(StringComparer.OrdinalIgnoreCase);
	private static readonly Dictionary<int, RendererEntry> RenderersById = new();
	private static readonly List<int> StaleMaterialIds = new();
	private static readonly List<string> StaleMaterialNames = new();
	private static readonly List<int> StaleRendererIds = new();
	private static object CurrentMapInstance;
	private static string CurrentMapSceneKey;
	private static int _lastMapStateResetFrame = -100000;
	private static int _lastTickFrame = -1;
	private static int _lastPruneFrame = -1;
	private const int PruneIntervalFrames = 30;
	private static int _tickDiagRemaining = 12;
	private static int _rendererDiagRemaining = 16;

	internal static void ResetMapStateIfChanged(object mapInstance)
	{
		var sceneKey = GetActiveSceneKey();
		if (!string.IsNullOrEmpty(sceneKey))
		{
			if (string.Equals(CurrentMapSceneKey, sceneKey, StringComparison.Ordinal))
			{
				if (mapInstance != null && CurrentMapInstance != null && !SameMapInstance(CurrentMapInstance, mapInstance))
				{
					if (CanResetForMapIdentityChange())
					{
						CurrentMapInstance = mapInstance;
						ClearMapState();
						return;
					}
				}
				else if (mapInstance != null)
					CurrentMapInstance = mapInstance;
				return;
			}

			CurrentMapSceneKey = sceneKey;
			CurrentMapInstance = mapInstance;
			ClearMapState();
			return;
		}

		if (mapInstance == null)
			return;
		if (CurrentMapInstance != null)
			return;
		CurrentMapInstance = mapInstance;
		ClearMapState();
	}

	private static string GetActiveSceneKey()
	{
		try
		{
			var scene = SceneManager.GetActiveScene();
			return scene.IsValid() ? scene.handle + ":" + (scene.name ?? "") : null;
		}
		catch
		{
			return null;
		}
	}

	private static bool CanResetForMapIdentityChange()
	{
		var frame = Time.frameCount;
		if (frame - _lastMapStateResetFrame < 30)
			return false;
		return true;
	}

	private static bool SameMapInstance(object left, object right)
	{
		if (ReferenceEquals(left, right))
			return true;
		if (left == null || right == null)
			return false;
		try
		{
			return left.Equals(right);
		}
		catch
		{
			return false;
		}
	}

	private static void ClearMapState()
	{
		_lastMapStateResetFrame = Time.frameCount;
		EntriesByMaterialId.Clear();
		EntriesByMaterialName.Clear();
		RenderersById.Clear();
		StaleMaterialIds.Clear();
		StaleMaterialNames.Clear();
		StaleRendererIds.Clear();
		_lastTickFrame = -1;
		_tickDiagRemaining = 12;
		_rendererDiagRemaining = 16;
		Homm3ImportVisuals.ClearAdventureMapPrefabScaleNormalizationState();
		Plugin.LogSource?.LogInfo("Homm3Import: reset town-style unit idle animator map state.");
	}

	internal static void Register(Material material, Texture2D[] frames, float frameMs)
	{
		if (!material || frames == null || frames.Length <= 1)
			return;
		var materialName = NormalizeMaterialName(material.name);
		var id = material.GetInstanceID();
		var entry = new Entry
		{
			Material = material,
			MaterialName = materialName,
			Frames = frames,
			FrameMs = frameMs > 1f ? frameMs : 120f,
			TimerMs = 0f,
			Index = 0
		};
		EntriesByMaterialId[id] = entry;
		if (!string.IsNullOrEmpty(materialName))
			EntriesByMaterialName[materialName] = entry;
		Homm3ImportVisuals.RebindTownStyleUnitBillboardTexture(material, frames[0]);
	}

	internal static void RegisterRenderer(Renderer renderer)
	{
		RefreshRenderer(renderer, logMiss: true);
	}

	internal static void RefreshRenderer(Renderer renderer)
	{
		RefreshRenderer(renderer, logMiss: false);
	}

	private static void RefreshRenderer(Renderer renderer, bool logMiss)
	{
		if (!renderer)
			return;
		var mats = renderer.sharedMaterials;
		if (mats == null || mats.Length == 0)
			return;
		for (var i = 0; i < mats.Length; i++)
		{
			var material = mats[i];
			if (!TryGetEntryForMaterial(material, out var entry) || entry == null)
				continue;
			var rendererId = renderer.GetInstanceID();
			var materialId = material ? material.GetInstanceID() : 0;
			var rendererEntry = new RendererEntry
			{
				Renderer = renderer,
				Entry = entry,
				MaterialId = materialId
			};
			RenderersById[rendererId] = rendererEntry;
			ApplyFrameToRenderer(rendererEntry, entry.CurrentFrame());
			LogRendererRegistration(renderer, material, entry);
			return;
		}

		if (logMiss && _rendererDiagRemaining > 0)
		{
			_rendererDiagRemaining--;
			Plugin.LogSource?.LogInfo(
				"Homm3Import: town-style unit idle animator renderer had no registered material renderer='"
				+ (renderer.name ?? "?")
				+ "' mats="
				+ mats.Length
				+ ".");
		}
	}

	internal static void UnregisterRenderer(int rendererId)
	{
		if (rendererId != 0)
			RenderersById.Remove(rendererId);
	}

	internal static void Tick()
	{
		var currentFrame = Time.frameCount;
		if (_lastTickFrame == currentFrame)
			return;
		_lastTickFrame = currentFrame;
		if (_lastPruneFrame < 0 || currentFrame - _lastPruneFrame >= PruneIntervalFrames)
		{
			_lastPruneFrame = currentFrame;
			PruneStaleEntries();
		}
		if (EntriesByMaterialId.Count == 0)
			return;
		var deltaMs = Time.deltaTime * 1000f;
		foreach (var kv in EntriesByMaterialId)
		{
			var e = kv.Value;
			if (e == null || !e.Material || e.Frames == null || e.Frames.Length <= 1)
				continue;

			e.TimerMs += deltaMs;
			if (e.TimerMs < e.FrameMs)
				continue;

			var steps = Math.Max(1, Mathf.FloorToInt(e.TimerMs / e.FrameMs));
			e.TimerMs -= steps * e.FrameMs;
			e.Index = (e.Index + steps) % e.Frames.Length;
			var frame = e.Frames[e.Index];
			if (!frame)
				continue;
			if (e.LastBroadcastIndex == e.Index)
				continue;
			e.LastBroadcastIndex = e.Index;
			ApplyFrameToMaterial(e.Material, frame);
			LogTick(e, frame);
		}

		StaleRendererIds.Clear();
		foreach (var kv in RenderersById)
		{
			var re = kv.Value;
			if (re == null || !re.Renderer || re.Entry == null)
			{
				StaleRendererIds.Add(kv.Key);
				continue;
			}
			if (re.LastAppliedIndex == re.Entry.Index)
				continue;
			re.LastAppliedIndex = re.Entry.Index;
			ApplyFrameToRenderer(re, re.Entry.CurrentFrame());
		}

		for (var i = 0; i < StaleRendererIds.Count; i++)
			RenderersById.Remove(StaleRendererIds[i]);
	}

	private static Texture2D CurrentFrame(this Entry entry)
	{
		if (entry == null || entry.Frames == null || entry.Frames.Length == 0)
			return null;
		var index = Mathf.Clamp(entry.Index, 0, entry.Frames.Length - 1);
		return entry.Frames[index];
	}

	private static bool TryGetEntryForMaterial(Material material, out Entry entry)
	{
		entry = null;
		if (!material)
			return false;
		var id = material.GetInstanceID();
		if (EntriesByMaterialId.TryGetValue(id, out entry) && entry != null)
			return true;

		var name = NormalizeMaterialName(material.name);
		if (string.IsNullOrEmpty(name) || !EntriesByMaterialName.TryGetValue(name, out var template) || template == null)
			return false;

		entry = new Entry
		{
			Material = material,
			MaterialName = name,
			Frames = template.Frames,
			FrameMs = template.FrameMs,
			TimerMs = template.TimerMs,
			Index = template.Index
		};
		EntriesByMaterialId[id] = entry;
		ApplyFrameToMaterial(material, entry.CurrentFrame());
		return true;
	}

	private static void ApplyFrameToMaterial(Material material, Texture texture)
	{
		if (!material || !texture)
			return;
		Homm3ImportVisuals.RebindTownStyleUnitBillboardTexture(material, texture);
	}

	private static void ApplyFrameToRenderer(RendererEntry rendererEntry, Texture texture)
	{
		var renderer = rendererEntry?.Renderer;
		if (!renderer || !texture)
			return;
		var materialId = rendererEntry.MaterialId;
		try
		{
			var mats = renderer.sharedMaterials;
			for (var i = 0; mats != null && i < mats.Length; i++)
			{
				var m = mats[i];
				if (!m)
					continue;
				if (materialId != 0 && m.GetInstanceID() != materialId)
					continue;
				ApplyFrameToMaterial(m, texture);
			}
		}
		catch
		{
		}
	}

	private static void PruneStaleEntries()
	{
		StaleMaterialIds.Clear();
		foreach (var kv in EntriesByMaterialId)
			if (kv.Value == null || !kv.Value.Material || kv.Value.Frames == null || kv.Value.Frames.Length <= 1)
				StaleMaterialIds.Add(kv.Key);
		for (var i = 0; i < StaleMaterialIds.Count; i++)
			EntriesByMaterialId.Remove(StaleMaterialIds[i]);

		StaleMaterialNames.Clear();
		foreach (var kv in EntriesByMaterialName)
			if (kv.Value == null || kv.Value.Frames == null || kv.Value.Frames.Length <= 1 || !HasAnyLiveFrame(kv.Value.Frames))
				StaleMaterialNames.Add(kv.Key);
		for (var i = 0; i < StaleMaterialNames.Count; i++)
			EntriesByMaterialName.Remove(StaleMaterialNames[i]);
	}

	private static bool HasAnyLiveFrame(Texture2D[] frames)
	{
		if (frames == null)
			return false;
		for (var i = 0; i < frames.Length; i++)
			if (frames[i])
				return true;
		return false;
	}

	private static string NormalizeMaterialName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return string.Empty;
		const string instanceSuffix = " (Instance)";
		var n = name.Trim();
		if (n.EndsWith(instanceSuffix, StringComparison.Ordinal))
			n = n.Substring(0, n.Length - instanceSuffix.Length);
		return n;
	}

	private static void LogTick(Entry entry, Texture frame)
	{
		if (_tickDiagRemaining <= 0 || entry == null || !entry.Material || !frame)
			return;
		_tickDiagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3Import: town-style unit idle animator tick material='"
			+ (entry.Material.name ?? "?")
			+ "' frame='"
			+ (frame.name ?? "?")
			+ "' index="
			+ entry.Index
			+ "/"
			+ entry.Frames.Length
			+ ".");
	}

	private static void LogRendererRegistration(Renderer renderer, Material material, Entry entry)
	{
		if (_rendererDiagRemaining <= 0 || !renderer || !material || entry == null)
			return;
		_rendererDiagRemaining--;
		Plugin.LogSource?.LogInfo(
			"Homm3Import: town-style unit idle animator registered live renderer='"
			+ (renderer.name ?? "?")
			+ "' material='"
			+ (material.name ?? "?")
			+ "' frames="
			+ (entry.Frames?.Length ?? 0)
			+ ".");
	}
}
