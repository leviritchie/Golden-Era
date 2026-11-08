using System;
using System.Collections.Generic;
using UnityEngine;

namespace OfflineUnlockMod;

public sealed class Homm3HeroMapBillboardAnimator : MonoBehaviour
{
	private const int RegisterRefreshIntervalFrames = 30;
	private Renderer _renderer;
	private int _registeredRendererId;
	private int _stableRegisterFrames;
	private int _refreshFrames;

	public Homm3HeroMapBillboardAnimator(IntPtr ptr)
		: base(ptr)
	{
	}

	private void Awake()
	{
		TryRegisterLocalRenderer();
	}

	private void OnEnable()
	{
		_stableRegisterFrames = 0;
		TryRegisterLocalRenderer();
	}

	private void LateUpdate()
	{
		if (_registeredRendererId == 0 || _stableRegisterFrames < 3)
			TryRegisterLocalRenderer();
		else if (++_refreshFrames >= RegisterRefreshIntervalFrames)
		{
			_refreshFrames = 0;
			TryRegisterLocalRenderer();
		}
		Homm3HeroMapBillboardAnimatorRegistry.Tick();
	}

	private void OnDisable()
	{
		// Pooled adventure-map visuals can be disabled and re-enabled without rebuilding
		// their replacement quad. Keep the registry entry until the object is destroyed.
	}

	private void OnDestroy()
	{
		if (_registeredRendererId == 0)
			return;
		Homm3HeroMapBillboardAnimatorRegistry.UnregisterRenderer(_registeredRendererId);
		_registeredRendererId = 0;
		_stableRegisterFrames = 0;
	}

	private bool TryRegisterLocalRenderer()
	{
		if (!_renderer)
			_renderer = GetComponent<Renderer>();
		if (!_renderer)
			return false;

		var id = _renderer.GetInstanceID();
		if (_registeredRendererId != id)
		{
			_registeredRendererId = id;
			_stableRegisterFrames = 0;
			_refreshFrames = 0;
			Homm3HeroMapBillboardAnimatorRegistry.RefreshRenderer(_renderer);
		}
		else
			_stableRegisterFrames++;
		return true;
	}
}

internal sealed class Homm3HeroMapSpriteSet
{
	internal string Key;
	internal Texture2D[] IdleByFacing;
	internal Texture2D[][] WalkByFacing;

	internal Texture2D IdleFrame(int facing)
	{
		if (IdleByFacing == null || IdleByFacing.Length == 0)
			return null;
		return IdleByFacing[Mathf.Clamp(facing, 0, IdleByFacing.Length - 1)];
	}

	internal Texture2D WalkFrame(int facing, int frame)
	{
		if (WalkByFacing == null || WalkByFacing.Length == 0)
			return null;
		var frames = WalkByFacing[Mathf.Clamp(facing, 0, WalkByFacing.Length - 1)];
		if (frames == null || frames.Length == 0)
			return null;
		return frames[Mathf.Clamp(frame, 0, frames.Length - 1)];
	}

	internal int WalkFrameCount(int facing)
	{
		if (WalkByFacing == null || WalkByFacing.Length == 0)
			return 0;
		var frames = WalkByFacing[Mathf.Clamp(facing, 0, WalkByFacing.Length - 1)];
		return frames?.Length ?? 0;
	}

	internal bool IsAlive(int expectedWalkFrames)
	{
		if (IdleByFacing == null || WalkByFacing == null)
			return false;
		for (var facing = 0; facing < 5; facing++)
		{
			if (!IdleFrame(facing))
				return false;
			if (WalkFrameCount(facing) != expectedWalkFrames)
				return false;
			for (var frame = 0; frame < expectedWalkFrames; frame++)
				if (!WalkFrame(facing, frame))
					return false;
		}
		return true;
	}
}

internal static class Homm3HeroMapBillboardAnimatorRegistry
{
	private sealed class Entry
	{
		internal Renderer Renderer;
		internal Transform Quad;
		internal Transform Root;
		internal Material Material;
		internal Homm3HeroMapSpriteSet SpriteSet;
		internal Vector3 BaseScale;
		internal Vector3 LastRootPosition;
		internal int Facing = 2;
		internal int FrameIndex;
		internal float FrameMs;
		internal float TimerMs;
		internal bool Moving;
		internal bool Mirrored;
	}

	private struct FacingSample
	{
		internal int Facing;
		internal bool Mirror;
	}

	private const float MoveEpsilonSqr = 0.000004f;
	private static readonly Dictionary<int, Entry> EntriesByRendererId = new();
	private static readonly List<int> StaleRendererIds = new();
	private static int _lastTickFrame = -1;
	private static int _diagRemaining = 24;

	internal static void Register(Renderer renderer, Transform quad, Transform root, Material material, Homm3HeroMapSpriteSet spriteSet, float frameMs)
	{
		if (!renderer || !quad || !root || !material || spriteSet == null)
			return;
		var id = renderer.GetInstanceID();
		var entry = new Entry
		{
			Renderer = renderer,
			Quad = quad,
			Root = root,
			Material = material,
			SpriteSet = spriteSet,
			BaseScale = AbsScale(quad.localScale),
			LastRootPosition = root.position,
			FrameMs = frameMs > 1f ? frameMs : 120f
		};
		EntriesByRendererId[id] = entry;
		ApplyFrame(entry, entry.SpriteSet.IdleFrame(entry.Facing), entry.Mirrored);
		Log("registered renderer='" + (renderer.name ?? "?") + "' spriteSet='" + (spriteSet.Key ?? "?") + "'.");
	}

	internal static void CollectLiveRenderers(List<Renderer> dest)
	{
		if (dest == null)
			return;
		foreach (var kv in EntriesByRendererId)
		{
			var renderer = kv.Value?.Renderer;
			if (renderer)
				dest.Add(renderer);
		}
	}

	internal static void RefreshRenderer(Renderer renderer)
	{
		if (!renderer)
			return;
		var id = renderer.GetInstanceID();
		if (EntriesByRendererId.TryGetValue(id, out var entry) && entry != null)
			entry.Renderer = renderer;
	}

	internal static void UnregisterRenderer(int rendererId)
	{
		if (rendererId != 0)
			EntriesByRendererId.Remove(rendererId);
	}

	internal static bool IsRendererUsingLiveSpriteSet(Renderer renderer, string spriteKey, int expectedWalkFrames)
	{
		if (!renderer || string.IsNullOrWhiteSpace(spriteKey))
			return false;
		var id = renderer.GetInstanceID();
		if (!EntriesByRendererId.TryGetValue(id, out var entry) || entry == null)
			return false;
		return entry.SpriteSet != null
		       && string.Equals(entry.SpriteSet.Key, spriteKey, StringComparison.Ordinal)
		       && entry.SpriteSet.IsAlive(expectedWalkFrames);
	}

	internal static void Tick()
	{
		var currentFrame = Time.frameCount;
		if (_lastTickFrame == currentFrame)
			return;
		_lastTickFrame = currentFrame;

		StaleRendererIds.Clear();
		var deltaMs = Time.deltaTime * 1000f;
		foreach (var kv in EntriesByRendererId)
		{
			var entry = kv.Value;
			if (entry == null || !entry.Renderer || !entry.Quad || !entry.Root || !entry.Material || entry.SpriteSet == null)
			{
				StaleRendererIds.Add(kv.Key);
				continue;
			}
			TickEntry(entry, deltaMs);
		}
		for (var i = 0; i < StaleRendererIds.Count; i++)
			EntriesByRendererId.Remove(StaleRendererIds[i]);
	}

	private static void TickEntry(Entry entry, float deltaMs)
	{
		FaceCamera(entry.Quad);

		var position = entry.Root.position;
		var delta = position - entry.LastRootPosition;
		entry.LastRootPosition = position;
		delta.y = 0f;
		var moving = delta.sqrMagnitude > MoveEpsilonSqr;
		if (moving)
		{
			var sample = ResolveFacing(delta);
			if (entry.Facing != sample.Facing || !entry.Moving)
			{
				entry.Facing = sample.Facing;
				entry.FrameIndex = 0;
				entry.TimerMs = 0f;
			}
			entry.Mirrored = sample.Mirror;
			entry.Moving = true;
			entry.TimerMs += deltaMs;
			if (entry.TimerMs >= entry.FrameMs)
			{
				var count = Math.Max(1, entry.SpriteSet.WalkFrameCount(entry.Facing));
				var steps = Math.Max(1, Mathf.FloorToInt(entry.TimerMs / entry.FrameMs));
				entry.TimerMs -= steps * entry.FrameMs;
				entry.FrameIndex = (entry.FrameIndex + steps) % count;
			}
			ApplyFrame(entry, entry.SpriteSet.WalkFrame(entry.Facing, entry.FrameIndex), sample.Mirror);
			return;
		}

		if (entry.Moving)
		{
			entry.Moving = false;
			entry.FrameIndex = 0;
			entry.TimerMs = 0f;
		}
		ApplyFrame(entry, entry.SpriteSet.IdleFrame(entry.Facing), entry.Mirrored);
	}

	private static void FaceCamera(Transform quad)
	{
		var camera = Camera.main;
		if (!camera)
			return;
		var toCamera = quad.position - camera.transform.position;
		toCamera.y = 0f;
		if (toCamera.sqrMagnitude < 0.0001f)
			return;
		quad.rotation = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
	}

	private static FacingSample ResolveFacing(Vector3 delta)
	{
		if (delta.sqrMagnitude < MoveEpsilonSqr)
			return new FacingSample { Facing = 2 };
		// Unity map movement Z is inverted relative to HoMM3 adventure-map facing groups.
		var angle = Mathf.Atan2(delta.x, -delta.z) * Mathf.Rad2Deg;
		if (angle < 0f)
			angle += 360f;
		var sector = Mathf.RoundToInt(angle / 45f) & 7;
		switch (sector)
		{
			case 0:
				return new FacingSample { Facing = 4 };
			case 1:
				return new FacingSample { Facing = 3 };
			case 2:
				return new FacingSample { Facing = 2 };
			case 3:
				return new FacingSample { Facing = 1 };
			case 4:
				return new FacingSample { Facing = 0 };
			case 5:
				return new FacingSample { Facing = 1, Mirror = true };
			case 6:
				return new FacingSample { Facing = 2, Mirror = true };
			default:
				return new FacingSample { Facing = 3, Mirror = true };
		}
	}

	private static void ApplyFrame(Entry entry, Texture2D frame, bool mirror)
	{
		if (entry == null || !frame || !entry.Material)
			return;
		Homm3ImportVisuals.RebindTownStyleUnitBillboardTexture(entry.Material, frame);
		if (entry.Quad)
			entry.Quad.localScale = entry.BaseScale;
		ApplyTextureMirror(entry.Material, mirror);
	}

	private static void ApplyTextureMirror(Material material, bool mirror)
	{
		if (!material)
			return;
		var scale = mirror ? new Vector2(-1f, 1f) : Vector2.one;
		var offset = mirror ? new Vector2(1f, 0f) : Vector2.zero;
		material.mainTextureScale = scale;
		material.mainTextureOffset = offset;
		SetTextureTransformIfPresent(material, "_MainTex", scale, offset);
		SetTextureTransformIfPresent(material, "_BaseMap", scale, offset);
		SetTextureTransformIfPresent(material, "_BaseColorMap", scale, offset);
		SetTextureTransformIfPresent(material, "_AlbedoMap", scale, offset);
		SetTextureTransformIfPresent(material, "_DiffuseMap", scale, offset);
		SetTextureTransformIfPresent(material, "_MainTexture", scale, offset);
		SetTextureTransformIfPresent(material, "_EmissionTex", scale, offset);
		SetTextureTransformIfPresent(material, "_EmissionMap", scale, offset);
	}

	private static void SetTextureTransformIfPresent(Material material, string propertyName, Vector2 scale, Vector2 offset)
	{
		if (!material || !material.HasProperty(propertyName))
			return;
		try
		{
			material.SetTextureScale(propertyName, scale);
			material.SetTextureOffset(propertyName, offset);
		}
		catch
		{
		}
	}

	private static Vector3 AbsScale(Vector3 scale)
	{
		return new Vector3(Mathf.Abs(scale.x), Mathf.Abs(scale.y), Mathf.Abs(scale.z));
	}

	private static void Log(string message)
	{
		if (_diagRemaining <= 0)
			return;
		_diagRemaining--;
		Plugin.LogSource?.LogInfo("Homm3HeroMapBillboardAnimator: " + message);
	}
}
