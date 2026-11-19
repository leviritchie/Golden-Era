using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using R = OfflineUnlockMod.Homm3CoveTreasureRuntime;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Cove Treasure Hunting map markers (mockup v2, approved 2026-11-17): the local side's revealed map pieces (a scroll
/// over the holder, or lying on the tile when loose), the possible treasure sites (ground X + "?") and the exact site
/// (ground X + "!"), plus the short "Map piece n/5" notice over the tile where a piece was taken. A piece that
/// newly appears gets a brief gold glow and one soft synthesized chime (user, 2026-11-17: "nothing too dramatic").
/// One screen-space overlay canvas (no raycasts), so markers show through fog and never block clicks. Positions are
/// projected from the map node's world position and move only when the camera moved; marker size follows the zoom.
/// Cost when no Cove hero ever ticked the runtime: nothing (no host object exists). With a host: one integer compare
/// per frame until there is something to show. Art: homm3_ui/cove_treasure/*.png, built by
/// tools/cove_treasure/build_marker_art.py from vanilla scroll and quest-mark textures.
/// Proof tier: build only; runtime unproven.
/// </summary>
internal static class Homm3CoveTreasureMarkers
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_COVE_TREASURE_MARKERS";
	private const string ArtFolder = "cove_treasure";
	private const int SortingOrder = 5;
	private const float ViewCheckSeconds = 0.5f;
	private const float NoticeSeconds = 3f;
	private const float NoticeFadeSeconds = 0.6f;
	/// <summary>Canvas pixels one map tile spans at marker scale 1.</summary>
	private const float ReferenceTilePixels = 70f;
	private const float MinScale = 0.5f;
	private const float MaxScale = 1.5f;

	private sealed class Item
	{
		internal R.Marker Marker;
		internal Vector3 World;
		internal RectTransform Root;
		internal Image Glow;
		/// <summary>Soft gold halo that breathes for as long as the marker is shown.</summary>
		internal readonly List<Image> Pulse = new();
		internal float PulseBase;
		internal float Born;
	}

	private static readonly List<Item> Items = new();
	private static readonly List<R.Marker> Wanted = new();
	private static readonly Dictionary<string, Sprite> Sprites = new(StringComparer.Ordinal);
	private static GameObject _hostObject;
	private static bool _hostTypeRegistered;
	private static GameObject _canvasObject;
	private static RectTransform _canvasRect;
	private static int _seenVersion = -1;
	private static bool _needsBuild;
	private static float _nextViewCheck;
	private static bool _viewOk;
	private static bool _shown;
	private static Camera _camera;
	private static object _map;
	private static MethodInfo _nodeToWorld;
	private static Type _nodeToWorldOwner;
	private static bool _warned;

	// A piece that was not on screen before gets a short gold glow and (once per batch) a soft chime.
	private const float GlowSeconds = 1.6f;
	private const float GlowAlpha = 0.5f;
	private const float ChimeVolume = 0.45f;
	private static readonly HashSet<int> KnownPieces = new();
	private static readonly HashSet<int> NowPieces = new();
	private static int _glowing;
	private static AudioClip _chime;
	private static AudioSource _chimeSource;
	private static float _lastChime = -999f;

	private static RectTransform _noticeRoot;
	private static TextMeshProUGUI _noticeText, _noticeShadow;
	private static Vector3 _noticeWorld;
	private static float _noticeUntil;

	/// <summary>Called by the runtime after a tick that changed what a side sees. Creates the per-frame host on first use.</summary>
	internal static void EnsureHost()
	{
		if (_hostObject != null)
			return;
		try
		{
			if (!_hostTypeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3CoveTreasureMarkersHost>();
				_hostTypeRegistered = true;
			}
			_hostObject = new GameObject("Homm3CoveTreasureMarkersHost");
			UnityObject.DontDestroyOnLoad(_hostObject);
			_hostObject.AddComponent<Homm3CoveTreasureMarkersHost>();
		}
		catch (Exception ex)
		{
			_hostObject = null;
			Warn("host failed (" + ex.GetBaseException().Message + "); no map markers.");
		}
	}

	internal static void HostDestroyed() => _hostObject = null;

	private static void Warn(string message)
	{
		if (_warned)
			return;
		_warned = true;
		Plugin.LogSource?.LogWarning(R.LogPrefix + "markers: " + message);
	}

	// ---------------------------------------------------------------- tick (host, every frame)

	// Everything the first marker, notice and popup need, loaded one item per frame as soon as the host exists.
	// Loading it all in the frame the first marker appeared was a visible hitch (user report 2026-11-17).
	private static readonly string[] WarmArt =
	{
		"map_piece", "map_piece_glow", "mark_question", "mark_question_glow", "mark_exclaim", "mark_exclaim_glow",
		"ground_x", "ground_x_glow", "hole", "popup_paper", "popup_button", "popup_button_hover",
		"popup_title_piece", "popup_title_spot", "popup_title_treasure", "popup_title_hole", "popup_title_chart",
	};
	private static int _warmStep;
	private static double _warmMs, _warmWorstMs;
	private static bool _firstBuildLogged;

	private static void WarmStep()
	{
		var total = WarmArt.Length + 3;
		if (_warmStep >= total)
			return;
		var watch = System.Diagnostics.Stopwatch.StartNew();
		try
		{
			if (_warmStep < WarmArt.Length)
				Sprite(WarmArt[_warmStep]);
			else if (_warmStep == WarmArt.Length)
				SoftDisc();
			else if (_warmStep == WarmArt.Length + 1)
				EnsureChime();
			else
				A.WarmFont(P.FontMedium);
		}
		catch
		{
		}
		var ms = watch.Elapsed.TotalMilliseconds;
		_warmMs += ms;
		_warmWorstMs = Math.Max(_warmWorstMs, ms);
		if (++_warmStep == total)
			Plugin.LogSource?.LogInfo(R.LogPrefix + "markers: art, chime and font preloaded over " + total + " frames: " + _warmMs.ToString("0.0")
				+ " ms in all, slowest frame " + _warmWorstMs.ToString("0.0") + " ms.");
	}

	internal static void Tick()
	{
		WarmStep();
		var version = R.Version;
		if (version != _seenVersion)
		{
			_seenVersion = version;
			_needsBuild = true;
		}
		var now = Time.realtimeSinceStartup;
		var noticePending = R.PendingNotice != null;
		if (!_needsBuild && !noticePending && Items.Count == 0 && _noticeRoot == null)
			return;
		if (now >= _nextViewCheck || _needsBuild || noticePending)
		{
			_nextViewCheck = now + ViewCheckSeconds;
			_viewOk = Homm3FactoryLogisticsAdventureView.TryAdventureView(out _camera, out _map);
		}
		if (!_viewOk || _camera == null)
		{
			// Off the adventure map (town, battle, menu): keep the wanted state, hide, rebuild when back.
			SetShown(false);
			return;
		}
		if (_needsBuild)
		{
			_needsBuild = false;
			var watch = System.Diagnostics.Stopwatch.StartNew();
			Rebuild();
			_layerDirty = true;
			if (!_firstBuildLogged && Items.Count > 0)
			{
				_firstBuildLogged = true;
				Plugin.LogSource?.LogInfo(R.LogPrefix + "markers: first build of " + Items.Count + " marker(s) took " + watch.Elapsed.TotalMilliseconds.ToString("0.0") + " ms.");
			}
		}
		if (noticePending)
		{
			StartNotice(now);
			_layerDirty = true;
		}
		BindCanvasCamera();
		if (_layerDirty && _canvas != null)
		{
			_layerDirty = false;
			ApplyLayer(_canvas.transform);
		}
		if (_noticeRoot != null && now >= _noticeUntil)
			EndNotice();
		if (Items.Count == 0 && _noticeRoot == null)
		{
			SetShown(false);
			return;
		}
		SetShown(true);
		Reposition(force: noticePending);
		if (_glowing > 0)
			AnimateGlows(now);
		AnimatePulse(now);
		if (_noticeRoot != null)
			FadeNotice(now);
	}

	// ---------------------------------------------------------------- contents

	private static void Rebuild()
	{
		Wanted.Clear();
		try
		{
			if (Homm3FactoryLogisticsEffects.TryGetData(out var data, out _) && data != null)
				R.CollectMarkers(R.LocalSide(data), Wanted);
		}
		catch (Exception ex)
		{
			Wanted.Clear();
			Warn("collect threw " + ex.GetBaseException().Message);
		}
		DestroyItems();
		NowPieces.Clear();
		if (Wanted.Count == 0 || !EnsureCanvas())
		{
			KnownPieces.Clear();
			return;
		}
		var now = Time.realtimeSinceStartup;
		var fresh = false;
		foreach (var marker in Wanted)
		{
			if (!TryNodeToWorld(_map, marker.Node, out var world))
				continue;
			var item = new Item { Marker = marker, World = world };
			var piece = marker.Kind == R.MarkerKind.Piece || marker.Kind == R.MarkerKind.LoosePiece;
			var isNew = piece && !KnownPieces.Contains(marker.Node);
			if (piece)
				NowPieces.Add(marker.Node);
			try
			{
				item.Root = BuildMarker(marker.Kind, isNew, out item.Glow, item.Pulse, out item.PulseBase);
				if (item.Glow != null)
				{
					item.Born = now;
					_glowing++;
					fresh = true;
				}
			}
			catch (Exception ex)
			{
				Warn("build threw " + ex.GetBaseException().Message);
				break;
			}
			if (item.Root != null)
				Items.Add(item);
		}
		KnownPieces.Clear();
		foreach (var node in NowPieces)
			KnownPieces.Add(node);
		Reposition(force: true);
		if (fresh)
			PlayChime(now);
	}

	private const float PulseSeconds = 2.6f;

	/// <summary>A map piece's outline swings between gold and blue over this many seconds (there and back).</summary>
	private const float PieceHueSeconds = 3.2f;

	private static readonly Color PulseBlue = new(0.36f, 0.74f, 1f);

	/// <summary>Slow, light breathing of each marker's fitted gold outline (alpha: base x 0.55 to base x 1). A map
	/// piece's outline also alternates gold and blue, so no terrain can hide it (user, 2026-11-18).</summary>
	private static void AnimatePulse(float now)
	{
		var wave = 0.775f + 0.225f * Mathf.Sin(now * (2f * Mathf.PI / PulseSeconds));
		var hue = 0.5f - 0.5f * Mathf.Cos(now * (2f * Mathf.PI / PieceHueSeconds));
		var pieceTint = Color.Lerp(PulseGold, PulseBlue, hue);
		foreach (var item in Items)
		{
			if (item.Pulse.Count == 0)
				continue;
			var tint = item.Marker.Kind == R.MarkerKind.Piece || item.Marker.Kind == R.MarkerKind.LoosePiece ? pieceTint : PulseGold;
			var color = new Color(tint.r, tint.g, tint.b, item.PulseBase * wave);
			try
			{
				foreach (var image in item.Pulse)
					image.color = color;
			}
			catch { item.Pulse.Clear(); }
		}
	}

	private static void AnimateGlows(float now)
	{
		var left = 0;
		foreach (var item in Items)
		{
			if (item.Glow == null)
				continue;
			var t = (now - item.Born) / GlowSeconds;
			try
			{
				if (t >= 1f)
				{
					UnityObject.Destroy(item.Glow.gameObject);
					item.Glow = null;
					continue;
				}
				// Quick rise, slow fade; the disc widens a little as it fades.
				var a = t < 0.15f ? t / 0.15f : 1f - (t - 0.15f) / 0.85f;
				item.Glow.color = new Color(1f, 0.82f, 0.36f, GlowAlpha * a);
				var s = 0.8f + 0.5f * t;
				item.Glow.rectTransform.localScale = new Vector3(s, s, 1f);
				left++;
			}
			catch
			{
				item.Glow = null;
			}
		}
		_glowing = left;
	}

	private static void PlayChime(float now)
	{
		if (now - _lastChime < 0.5f)
			return;
		_lastChime = now;
		try
		{
			EnsureChime();
			_chimeSource.volume = Mathf.Clamp01(EsquirePikemanVisuals.BattleSfxVolume * ChimeVolume);
			_chimeSource.PlayOneShot(_chime);
		}
		catch (Exception ex)
		{
			Warn("chime failed " + ex.GetBaseException().Message);
		}
	}

	private static void EnsureChime()
	{
		if (_chime == null || !_chime)
			_chime = BuildChime();
		if (_chimeSource == null || !_chimeSource)
		{
			var go = new GameObject("HOMM3_COVE_TREASURE_CHIME");
			UnityObject.DontDestroyOnLoad(go);
			_chimeSource = go.AddComponent<AudioSource>();
			_chimeSource.playOnAwake = false;
			_chimeSource.loop = false;
			_chimeSource.spatialBlend = 0f;
		}
	}

	/// <summary>Two soft bell notes a fifth apart, synthesized (no audio asset): about 0.8 s, quiet.</summary>
	private static AudioClip BuildChime()
	{
		const int rate = 44100;
		const float seconds = 0.8f;
		var count = (int)(rate * seconds);
		var samples = new float[count];
		AddBell(samples, rate, 0f, 1318.5f, 0.30f);
		AddBell(samples, rate, 0.10f, 1975.5f, 0.24f);
		var clip = AudioClip.Create("HOMM3_COVE_TREASURE_CHIME", count, 1, rate, false);
		clip.SetData(samples, 0);
		return clip;
	}

	private static void AddBell(float[] samples, int rate, float start, float hz, float gain)
	{
		var first = (int)(start * rate);
		for (var i = first; i < samples.Length; i++)
		{
			var t = (i - first) / (float)rate;
			var env = Mathf.Min(1f, t / 0.004f) * Mathf.Exp(-t / 0.16f);
			var tail = Mathf.Clamp01((samples.Length - i) / (rate * 0.05f));
			var phase = 2f * Mathf.PI * hz * t;
			samples[i] += gain * env * tail * (Mathf.Sin(phase) + 0.22f * Mathf.Sin(2.01f * phase) + 0.08f * Mathf.Sin(3.02f * phase));
		}
	}

	/// <summary>One marker, centred on the tile's screen point; child offsets are in canvas pixels at scale 1 (y up).</summary>
	private static readonly Color PulseGold = new(1f, 0.84f, 0.42f);

	/// <summary>The map piece over a holder object: sprite height and how far its centre floats above the tile centre,
	/// in canvas pixels at marker scale 1. Its lower edge is 86 px up, clear of most map objects.</summary>
	private const float PieceHeight = 48f;
	private const float PieceLift = 110f;

	private static RectTransform BuildMarker(R.MarkerKind kind, bool fresh, out Image glow, List<Image> pulse, out float pulseBase)
	{
		glow = null;
		pulseBase = 0.62f;
		var root = A.NewRect("Marker", _canvasRect);
		root.anchorMin = root.anchorMax = root.pivot = new Vector2(0.5f, 0.5f);
		root.sizeDelta = Vector2.zero;
		switch (kind)
		{
			case R.MarkerKind.Piece:
				// Small and high: at 76 px tall and 70 px up it sat on top of the object holding it (user, 2026-11-18).
				if (fresh)
					glow = AddShadow(root, 0f, PieceLift, 104f, 104f, 0f, new Color(1f, 0.82f, 0.36f));
				AddSprite(root, "map_piece", 3f, PieceLift - 5f, PieceHeight, 0f, new Color(0f, 0f, 0f, 0.45f));
				AddGlow(pulse, root, "map_piece", 0f, PieceLift, PieceHeight, 0f);
				AddSprite(root, "map_piece", 0f, PieceLift, PieceHeight, 0f, Color.white);
				break;
			case R.MarkerKind.LoosePiece:
				if (fresh)
					glow = AddShadow(root, 0f, 4f, 150f, 110f, 0f, new Color(1f, 0.82f, 0.36f));
				AddShadow(root, 0f, -6f, 74f, 22f, 0.42f);
				AddGlow(pulse, root, "map_piece", 0f, 4f, 64f, -8f, 0.62f);
				AddSprite(root, "map_piece", 0f, 4f, 64f, -8f, Color.white, 0.62f);
				break;
			case R.MarkerKind.Hole:
				AddSprite(root, "hole", 0f, 0f, 36f, 0f, Color.white);
				break;
			case R.MarkerKind.Lead:
				pulseBase = 0.5f;
				AddGlow(pulse, root, "ground_x", 0f, 0f, 30f, 0f);
				AddSprite(root, "ground_x", 0f, 0f, 30f, 0f, Color.white);
				AddSprite(root, "mark_question", 3f, 52f, 60f, 0f, new Color(0f, 0f, 0f, 0.4f));
				AddGlow(pulse, root, "mark_question", 0f, 58f, 60f, 0f);
				AddSprite(root, "mark_question", 0f, 58f, 60f, 0f, Color.white);
				break;
			default:
				pulseBase = 0.8f;
				AddGlow(pulse, root, "ground_x", 0f, 0f, 42f, 0f);
				AddSprite(root, "ground_x", 0f, 0f, 42f, 0f, Color.white);
				AddSprite(root, "mark_exclaim", 3f, 72f, 84f, 0f, new Color(0f, 0f, 0f, 0.4f));
				AddGlow(pulse, root, "mark_exclaim", 0f, 80f, 84f, 0f);
				AddSprite(root, "mark_exclaim", 0f, 80f, 84f, 0f, Color.white);
				break;
		}
		return root;
	}

	/// <summary>Padding of the baked "_glow" sprites per side, as a fraction of the art height (build_marker_art.GLOW_PAD).</summary>
	private const float GlowPad = 0.18f;

	/// <summary>Gold outline glow fitted to a sprite's silhouette, drawn behind it and pulsed by AnimatePulse.</summary>
	private static void AddGlow(List<Image> pulse, RectTransform parent, string name, float x, float y, float height, float tilt, float squash = 1f)
	{
		var image = AddSprite(parent, name + "_glow", x, y, height * (1f + 2f * GlowPad), tilt, new Color(PulseGold.r, PulseGold.g, PulseGold.b, 0f), squash);
		if (image != null)
			pulse.Add(image);
	}

	private static Image AddSprite(RectTransform parent, string name, float x, float y, float height, float tilt, Color tint, float squash = 1f)
	{
		var sprite = Sprite(name);
		if (sprite == null)
			return null;
		var rect = sprite.rect;
		var width = rect.height > 0f ? height * rect.width / rect.height : height;
		var image = A.NewImage(name, parent, sprite, Color.white);
		image.color = tint;
		image.preserveAspect = false;
		var rt = image.rectTransform;
		rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
		rt.anchoredPosition = new Vector2(x, y);
		rt.sizeDelta = new Vector2(width, height * squash);
		if (tilt != 0f)
			rt.localRotation = Quaternion.Euler(0f, 0f, tilt);
		return image;
	}

	/// <summary>Soft contact shadow (or the exact site's gold glow) under a marker.</summary>
	private static Image AddShadow(RectTransform parent, float x, float y, float w, float h, float alpha, Color? tint = null)
	{
		var color = tint ?? Color.black;
		var image = A.NewImage("Shadow", parent, SoftDisc(), new Color(color.r, color.g, color.b, alpha));
		image.color = new Color(color.r, color.g, color.b, alpha);
		var rt = image.rectTransform;
		rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
		rt.anchoredPosition = new Vector2(x, y);
		rt.sizeDelta = new Vector2(w, h);
		return image;
	}

	// ---------------------------------------------------------------- notice

	private static void StartNotice(float now)
	{
		var text = R.PendingNotice;
		var node = R.PendingNoticeNode;
		R.PendingNotice = null;
		R.PendingNoticeNode = -1;
		if (string.IsNullOrEmpty(text) || !TryNodeToWorld(_map, node, out var world) || !EnsureCanvas())
			return;
		try
		{
			EndNotice();
			var root = A.NewRect("Notice", _canvasRect);
			root.anchorMin = root.anchorMax = root.pivot = new Vector2(0.5f, 0.5f);
			root.sizeDelta = Vector2.zero;
			const float w = 700f, h = 40f, size = 28f;
			_noticeShadow = A.AddText(root, P.FontMedium, size, text, 0f, 0f, w, h, new Color(0.07f, 0.05f, 0.03f, 0.95f), TextAlignmentOptions.Center);
			_noticeText = A.AddText(root, P.FontMedium, size, text, 0f, 0f, w, h, new Color(1f, 0.89f, 0.59f, 1f), TextAlignmentOptions.Center);
			CentreText(_noticeShadow, 2f, -2f, w, h);
			CentreText(_noticeText, 0f, 0f, w, h);
			_noticeRoot = root;
			_noticeWorld = world;
			_noticeUntil = now + NoticeSeconds;
		}
		catch (Exception ex)
		{
			EndNotice();
			Warn("notice threw " + ex.GetBaseException().Message);
		}
	}

	private static void CentreText(TextMeshProUGUI text, float x, float y, float w, float h)
	{
		if (text == null)
			return;
		var rt = text.rectTransform;
		rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
		rt.anchoredPosition = new Vector2(x, y);
		rt.sizeDelta = new Vector2(w, h);
	}

	private static void FadeNotice(float now)
	{
		var left = _noticeUntil - now;
		var alpha = left >= NoticeFadeSeconds ? 1f : Mathf.Clamp01(left / NoticeFadeSeconds);
		try
		{
			if (_noticeText != null)
				_noticeText.alpha = alpha;
			if (_noticeShadow != null)
				_noticeShadow.alpha = alpha * 0.95f;
		}
		catch
		{
			EndNotice();
		}
	}

	private static void EndNotice()
	{
		var root = _noticeRoot;
		_noticeRoot = null;
		_noticeText = _noticeShadow = null;
		if (root == null)
			return;
		try { UnityObject.Destroy(root.gameObject); }
		catch { }
	}

	// ---------------------------------------------------------------- projection

	internal static bool TryNodeToWorld(object map, int node, out Vector3 world)
	{
		world = default;
		if (map == null || node < 0)
			return false;
		try
		{
			var type = map.GetType();
			if (_nodeToWorldOwner != type)
			{
				_nodeToWorldOwner = type;
				_nodeToWorld = GameMember.FindFirstMethodByNames(type, new[] { typeof(int) }, GameSymbols.AiDriverScreenDump.MapNodeToWorld);
				if (_nodeToWorld != null && _nodeToWorld.ReturnType != typeof(Vector3))
					_nodeToWorld = null;
				if (_nodeToWorld == null)
					Warn("map node-to-world unresolved on " + type.Name + "; no map markers.");
			}
			if (_nodeToWorld == null || _nodeToWorld.Invoke(map, new object[] { node }) is not Vector3 v)
				return false;
			world = v;
			return true;
		}
		catch (Exception ex)
		{
			Warn("node-to-world threw " + ex.GetBaseException().Message);
			return false;
		}
	}

	private static void Reposition(bool force)
	{
		if (_camera == null || _canvasRect == null || (Items.Count == 0 && _noticeRoot == null))
			return;
		// Every frame: a handful of markers, and no camera signature catches every way the game moves its view.
		try
		{
			_canvasCentre = _camera.pixelRect.center;
			_canvasScale = _canvas != null ? _canvas.scaleFactor : 0f;
		}
		catch { _viewOk = false; return; }
		if (_canvasScale <= 0.0001f)
			_canvasScale = Screen.height / (float)P.ReferenceHeight;
		var scale = 1f;
		var scaled = false;
		foreach (var item in Items)
		{
			if (item.Root == null)
				continue;
			var on = TryCanvasPoint(item.World, out var local);
			if (on)
			{
				if (!scaled)
				{
					scaled = true;
					scale = MarkerScale(item, local);
				}
				item.Root.anchoredPosition = local;
				item.Root.localScale = new Vector3(scale, scale, 1f);
			}
			if (item.Root.gameObject.activeSelf != on)
				item.Root.gameObject.SetActive(on);
		}
		if (_noticeRoot != null)
		{
			var on = TryCanvasPoint(_noticeWorld, out var local);
			if (on)
				_noticeRoot.anchoredPosition = local + new Vector2(0f, 120f);
			if (_noticeRoot.gameObject.activeSelf != on)
				_noticeRoot.gameObject.SetActive(on);
		}
	}

	private static bool TryCanvasPoint(Vector3 world, out Vector2 local)
	{
		local = default;
		var screen = _camera.WorldToScreenPoint(world);
		if (screen.z <= 0f || screen.x < -120f || screen.y < -120f || screen.x > Screen.width + 120f || screen.y > Screen.height + 120f)
			return false;
		local = ToCanvas(screen);
		return true;
	}

	private static Vector2 _canvasCentre;
	private static float _canvasScale = 1f;

	/// <summary>Screen pixels to canvas units from the canvas centre. Computed, not read back from the canvas
	/// transform: Unity moves a camera-space canvas after the camera, so that transform lags a moving view.</summary>
	private static Vector2 ToCanvas(Vector3 screen) => new((screen.x - _canvasCentre.x) / _canvasScale, (screen.y - _canvasCentre.y) / _canvasScale);

	/// <summary>Zoom factor from the on-screen distance between the marker's tile and its right-hand neighbour.</summary>
	private static float MarkerScale(Item item, Vector2 local)
	{
		var width = R.MapWidth;
		if (width <= 1)
			return 1f;
		var neighbour = item.Marker.Node % width == width - 1 ? item.Marker.Node - 1 : item.Marker.Node + 1;
		if (!TryNodeToWorld(_map, neighbour, out var world))
			return 1f;
		var screen = _camera.WorldToScreenPoint(world);
		if (screen.z <= 0f)
			return 1f;
		var tile = (ToCanvas(screen) - local).magnitude;
		return tile <= 1f ? 1f : Mathf.Clamp(tile / ReferenceTilePixels, MinScale, MaxScale);
	}

	// ---------------------------------------------------------------- canvas and art

	private static bool EnsureCanvas()
	{
		if (_canvasObject != null)
			return true;
		try
		{
			var go = new GameObject(CanvasObjectName, new Il2CppSystem.Type[]
			{
				Il2CppType.Of<RectTransform>(),
				Il2CppType.Of<Canvas>(),
				Il2CppType.Of<CanvasScaler>(),
			});
			UnityObject.DontDestroyOnLoad(go);
			var canvas = go.GetComponent<Canvas>();
			var scaler = go.GetComponent<CanvasScaler>();
			if (canvas == null || scaler == null)
			{
				UnityObject.Destroy(go);
				return false;
			}
			// Drawn by the map camera itself, so every game window, panel and tooltip covers the markers like any
			// other part of the map (an overlay canvas bled through them).
			_canvas = canvas;
			_canvasCamera = null;
			BindCanvasCamera();
			scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
			scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
			scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
			scaler.matchWidthOrHeight = 1f;
			_canvasObject = go;
			_canvasRect = go.GetComponent<RectTransform>();
			_shown = true;
			return true;
		}
		catch (Exception ex)
		{
			Warn("canvas failed " + ex.GetBaseException().Message);
			DestroyAll();
			return false;
		}
	}

	private static Canvas _canvas;
	private static Camera _canvasCamera;
	private static int _canvasLayer;
	private static bool _layerDirty;

	/// <summary>Attaches the marker canvas to the current map camera, on a layer that camera renders.</summary>
	private static void BindCanvasCamera()
	{
		if (_canvas == null || _camera == null)
			return;
		var rebound = _canvasCamera == null || _canvasCamera.Pointer != _camera.Pointer;
		if (rebound)
		{
			_canvasCamera = _camera;
			_canvas.renderMode = RenderMode.ScreenSpaceCamera;
			_canvas.worldCamera = _camera;
			_canvas.overrideSorting = true;
			_canvas.sortingOrder = SortingOrder;
			_boundMask = 0;
			_boundNear = _boundFar = -1f;
		}
		// The map camera changes its clip planes as it zooms. A plane distance fixed at bind time then sits in
		// front of the near plane (zoomed out) or behind the terrain (zoomed in) and the markers vanish, so the
		// canvas follows the near plane every frame.
		var near = _camera.nearClipPlane;
		var far = _camera.farClipPlane;
		var mask = _camera.cullingMask;
		if (!rebound && mask == _boundMask && Math.Abs(near - _boundNear) < 0.0005f && Math.Abs(far - _boundFar) < 0.0005f)
			return;
		if (mask != _boundMask)
		{
			var layer = (mask & 1) != 0 ? 0 : -1;
			for (var i = 1; layer < 0 && i < 32; i++)
				if ((mask & (1 << i)) != 0)
					layer = i;
			_canvasLayer = layer < 0 ? 0 : layer;
			ApplyLayer(_canvas.transform);
		}
		_boundMask = mask;
		_boundNear = near;
		_boundFar = far;
		_canvas.planeDistance = near + 0.05f + near * 0.01f;
		if (_cameraLogs < 12)
		{
			_cameraLogs++;
			Plugin.LogSource?.LogInfo(R.LogPrefix + "markers: camera " + (rebound ? "bound" : "changed") + ": near=" + near.ToString("0.###") + " far=" + far.ToString("0.#")
				+ (_camera.orthographic ? " ortho=" + _camera.orthographicSize.ToString("0.##") : " fov=" + _camera.fieldOfView.ToString("0.##"))
				+ " mask=0x" + mask.ToString("X") + " layer=" + _canvasLayer + " plane=" + _canvas.planeDistance.ToString("0.###") + ".");
		}
	}

	private static int _boundMask, _cameraLogs;
	private static float _boundNear = -1f, _boundFar = -1f;

	private static void ApplyLayer(Transform t)
	{
		if (t == null)
			return;
		t.gameObject.layer = _canvasLayer;
		for (var i = t.childCount - 1; i >= 0; i--)
			ApplyLayer(t.GetChild(i));
	}

	private static void SetShown(bool shown)
	{
		if (_canvasObject == null || _shown == shown)
			return;
		_shown = shown;
		try
		{
			_canvasObject.SetActive(shown);
			if (shown)
				Reposition(force: true);
		}
		catch
		{
			DestroyAll();
		}
	}

	private static void DestroyItems()
	{
		foreach (var item in Items)
		{
			if (item.Root == null)
				continue;
			try { UnityObject.Destroy(item.Root.gameObject); }
			catch { }
		}
		Items.Clear();
		_glowing = 0;
	}

	private static void DestroyAll()
	{
		Items.Clear();
		_glowing = 0;
		_noticeRoot = null;
		_noticeText = _noticeShadow = null;
		var go = _canvasObject;
		_canvasObject = null;
		_canvasRect = null;
		_canvas = null;
		_canvasCamera = null;
		_shown = false;
		_needsBuild = true;
		if (go == null)
			return;
		try { UnityObject.Destroy(go); }
		catch { }
	}

	/// <summary>Cove treasure art by file name (homm3_ui/cove_treasure/&lt;name&gt;.png), cached.</summary>
	internal static Sprite Art(string name) => Sprite(name);

	private static Sprite Sprite(string name)
	{
		if (Sprites.TryGetValue(name, out var sprite) && sprite)
			return sprite;
		var path = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", "homm3_ui", ArtFolder, name + ".png");
		if (!File.Exists(path))
		{
			Warn("art missing: " + path);
			return null;
		}
		var bytes = File.ReadAllBytes(path);
		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		// One block copy into the array's data (after the four-pointer IL2CPP array header). The per-element indexer
		// is an interop call per byte, which took a visible share of the first-marker hitch.
		System.Runtime.InteropServices.Marshal.Copy(bytes, 0, il2cppBytes.Pointer + IntPtr.Size * 4, bytes.Length);
		if (!ImageConversion.LoadImage(texture, il2cppBytes))
		{
			UnityObject.Destroy(texture);
			Warn("art unreadable: " + path);
			return null;
		}
		texture.name = "homm3_cove_treasure_" + name;
		texture.filterMode = FilterMode.Trilinear;
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		sprite = UnityEngine.Sprite.Create(texture, new Rect(0f, 0f, texture.width, texture.height), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
		sprite.name = texture.name;
		sprite.hideFlags = HideFlags.HideAndDontSave;
		Sprites[name] = sprite;
		return sprite;
	}

	/// <summary>A white radial falloff disc, tinted per use (contact shadows and the exact-site glow).</summary>
	private static Sprite SoftDisc()
	{
		const string key = "__soft_disc";
		if (Sprites.TryGetValue(key, out var sprite) && sprite)
			return sprite;
		const int size = 64;
		var texture = new Texture2D(size, size, TextureFormat.RGBA32, mipChain: false);
		var pixels = new Il2CppStructArray<Color32>(size * size);
		for (var y = 0; y < size; y++)
		{
			for (var x = 0; x < size; x++)
			{
				var dx = (x + 0.5f) / size * 2f - 1f;
				var dy = (y + 0.5f) / size * 2f - 1f;
				var d = Mathf.Clamp01(1f - Mathf.Sqrt(dx * dx + dy * dy));
				pixels[y * size + x] = new Color32(255, 255, 255, (byte)(255f * d * d * (3f - 2f * d)));
			}
		}
		texture.SetPixels32(pixels);
		texture.Apply(false, true);
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		sprite = UnityEngine.Sprite.Create(texture, new Rect(0f, 0f, size, size), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
		sprite.hideFlags = HideFlags.HideAndDontSave;
		Sprites[key] = sprite;
		return sprite;
	}
}

public sealed class Homm3CoveTreasureMarkersHost : MonoBehaviour
{
	public Homm3CoveTreasureMarkersHost(IntPtr ptr) : base(ptr) { }

	private void Update()
	{
		try
		{
			Homm3CoveTreasurePopup.Tick();
			Homm3CoveTreasureChart.Tick();
			Homm3CoveTreasureMarkers.Tick();
		}
		catch
		{
		}
		try
		{
			R.FlushAiPayouts();
		}
		catch
		{
		}
		R.FlushSave(Time.realtimeSinceStartup);
	}

	private void OnDestroy() => Homm3CoveTreasureMarkers.HostDestroyed();
}
