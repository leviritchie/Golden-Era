using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using L = OfflineUnlockMod.Homm3FactoryLogisticsViewerLayout;
using Ui = OfflineUnlockMod.Homm3FactoryLogisticsUi;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Logistics Network viewer, opened by the free "Logistics Network" world spell (lane CORE calls <see cref="Open"/>).
/// A pannable (drag), zoomable (wheel, +/-) tile map drawn from <see cref="Homm3FactoryLogistics.TryGetTerrainTile"/>
/// (one texture: terrain colour, roads, water, fog, thin grid lines), with the network on top:
/// - routes as thin lines stepping tile to tile, coloured by their source building (matching dot on its marker); sources
///   sharing a tile edge run side by side (one lane per source, to the right of travel, in a stable order); chevrons flow
///   along each route;
/// - a red X where a route runs out of range, with stacked red labels naming the source's active enhancement, the building,
///   the target and the missing range levels;
/// - neutral stacks that block a link: their tile and its 8 guard tiles tinted red and pulsing, with CORE's label;
/// - building markers with the "UC n" Upgrade Center / "CC n" Command Center badge, "!" when unvisited and "Tomorrow"
///   while something is under construction; towns and heroes as ringed markers.
/// UX pass 2026-11-16 (Homm3FactoryLogisticsViewerExtras.cs): primer, glossary, totals bar, range overlay, cut fixes,
/// to-do list and filters, keys, delivery preview, Recruit all.
/// The selected building's card (docked bottom-right) has the tabs "Active enhancement" (weekly switch, applied next day),
/// "Build / Upgrade" (remote orders up to the building's Upgrade Center level, active next day) and, for a dwelling whose
/// active enhancement is the Rail Network, "Hire" (unit count and a reachable town / hero).
/// The viewer never mutates state: every action is a <see cref="Homm3FactoryLogistics"/> command, then the network is re-read.
/// Mockups: V:/olden_port_work/factory_logistics/mockups/network_viewer*.png (tools/factory_logistics/network_viewer_mockup.py).
/// Proof tier: source/static until compiled; runtime unproven.
/// </summary>
internal static partial class Homm3FactoryLogisticsViewer
{
	private const string CanvasObjectName = "OFFLINE_UNLOCK_MOD_FACTORY_LOGISTICS_VIEWER";

	private sealed class Chevron
	{
		public RectTransform Rect;
		public Vector2[] Points;
		public float[] Cumulative;
		public float Offset;
		public UnityImage[] Core;
		public UnityImage[] Halo;
		public Color Colour;
	}

	private static GameObject _canvasObject;
	private static RectTransform _window;
	private static RectTransform _viewport;
	private static RectTransform _content;
	private static RectTransform _overlay;
	private static RectTransform _cardRoot;
	private static RectTransform _cardRect;
	private static TextMeshProUGUI _statusText;
	private static LogisticsNetworkView _net;
	private static long _selectedKey;
	private static bool _hasSelection;
	private static LogisticsBuildingView _remote;
	private static string _remoteFail;
	private static int _tab;
	private static string _status;
	private static int _hireCount = 1;
	private static int _hireTarget;
	private static int _hireUnit;   // 0 = the dwelling's own stock, n = the n-th Arcane upgraded stock entry
	private static int _tickFrame;

	private static Texture2D _mapTexture;
	private static Sprite _mapSprite;
	private static Texture2D _glowTexture;
	private static Sprite _glowSprite;
	private static UnityImage _glowImage;
	private static LogisticsNetworkView _glowFor;
	private static float _glowTile;
	private static int _mapW;
	private static int _mapH;
	private static int _level;
	private static float _tile = L.DefaultTile;
	private static Vector2 _pan;
	private static bool _panning;
	private static Vector2 _panLast;

	private static readonly List<Ui.Clickable> ChromeButtons = new();
	private static readonly List<Ui.Clickable> CardButtons = new();
	private static readonly List<(RectTransform Rect, long Key)> Markers = new();
	private static readonly List<Chevron> Chevrons = new();
	private static readonly List<UnityImage> Pulsing = new();
	private static readonly List<Rect> Placed = new();

	/// <summary>A hover tip on a card element: title, then lines (one may be highlighted, e.g. the built level).</summary>
	private sealed class Tip
	{
		public RectTransform Rect;
		public string Title;
		public string[] Lines;
		public int Highlight = -1;
		/// <summary>Lines computed when the tip is first shown (before/after previews, no-path reasons); cached in the tip.</summary>
		public Func<string[]> More;
		public string[] MoreCache;
		/// <summary>Shown next to the mouse (chrome tips) instead of left of the card.</summary>
		public bool NearMouse;
	}

	private static readonly List<Tip> Tips = new();
	private static Tip _shownTip;
	private static RectTransform _tipRoot;
	private static float _cardX0;

	internal static bool IsOpen => _net != null;

	/// <summary>Building to select and centre on when the viewer next opens (-1 = none). Set by OpenFocused.</summary>
	internal static long PendingFocusKey = -1;

	/// <summary>Opens the viewer centred on <paramref name="focusKey"/> with that building's card selected.</summary>
	internal static bool OpenFocused(object dataHero, long focusKey, out string fail)
	{
		PendingFocusKey = focusKey;
		var ok = Open(dataHero, out fail);
		if (!ok)
			PendingFocusKey = -1;
		return ok;
	}

	/// <summary>Opens the viewer for the local player's network. Fails closed (nothing shown) with a reason.</summary>
	internal static bool Open(object dataHero, out string fail)
	{
		fail = null;
		if (_net != null || Homm3FactoryLogisticsUpgradePanel.IsOpen)
		{
			fail = "a Logistics panel is already open";
			return false;
		}
		try
		{
			if (!Homm3FactoryLogistics.TryGetNetwork(out var net, out fail))
				return false;
			if (net == null || net.Buildings == null)
			{
				fail = "network view is empty";
				return false;
			}
			var mw = Homm3FactoryLogistics.MapWidth;
			var mh = Homm3FactoryLogistics.MapHeight;
			if (mw <= 0 || mh <= 0 || mw > 1024 || mh > 1024)
			{
				fail = "map size not available (" + mw + "x" + mh + ")";
				return false;
			}
			_mapW = mw;
			_mapH = mh;
			_level = net.Buildings.Count > 0 && net.Buildings[0] != null ? net.Buildings[0].Level : 0;
			if (!TryBuildMapTexture(out var tiles, out fail))
				return false;
			if (!Ui.TryCreateCanvas(CanvasObjectName, L.Width, L.Height, out _canvasObject, out _window, out fail))
			{
				DestroyMapTexture();
				return false;
			}
			_net = net;
			_hasSelection = false;
			_remote = null;
			_remoteFail = null;
			_tab = 0;
			_status = null;
			_hireCount = 1;
			_hireTarget = 0;
			_hireUnit = 0;
			_panning = false;
			ResetExtras();
			FrameNetwork();
			Homm3TowerArtificingPickerInputBlock.Begin();
			BuildAll();
			AfterOpen();
			var cut = 0;
			foreach (var r in Routes())
				cut += r.Cut ? 1 : 0;
			Ui.LogInfo("viewer opened: map=" + mw + "x" + mh + " level=" + _level + " tilesRead=" + tiles + " buildings=" + net.Buildings.Count + " towns=" + (net.Towns?.Count ?? 0)
				+ " heroes=" + (net.Heroes?.Count ?? 0) + " routes=" + (net.Routes?.Count ?? 0) + " cut=" + cut + " blockingStacks=" + (net.BlockingStacks?.Count ?? 0)
				+ " logisticsLevel=" + net.LogisticsLevel + " tilePx=" + _tile);
			return true;
		}
		catch (Exception ex)
		{
			fail = "viewer build failed: " + ex.GetType().Name + ": " + ex.GetBaseException().Message;
			var wasOpen = _net != null;
			Forget();
			if (wasOpen)
				Homm3TowerArtificingPickerInputBlock.End();
			return false;
		}
	}

	private static void Forget()
	{
		var canvas = _canvasObject;
		_canvasObject = null;
		_window = null;
		_viewport = _content = _overlay = _cardRoot = _cardRect = null;
		_statusText = null;
		_net = null;
		_remote = null;
		ChromeButtons.Clear();
		CardButtons.Clear();
		Markers.Clear();
		Chevrons.Clear();
		Pulsing.Clear();
		Tips.Clear();
		_shownTip = null;
		_tipRoot = null;
		ForgetExtras();
		Ui.DestroyCanvas(canvas);
		DestroyMapTexture();
		DestroyGlow();
		_glowImage = null;
		_glowFor = null;
	}

	private static void Close(string why)
	{
		if (_net == null)
			return;
		Forget();
		Homm3TowerArtificingPickerInputBlock.End();
		Ui.LogInfo("viewer closed (" + why + ")");
	}

	internal static void HostDestroyed()
	{
		// Another Logistics canvas being destroyed also lands here; only react when this panel's own canvas is gone.
		if (_net == null || _canvasObject)
			return;
		_canvasObject = null;
		Forget();
		Homm3TowerArtificingPickerInputBlock.End();
		Ui.LogWarning("viewer canvas was destroyed while open; closed");
	}

	private static IReadOnlyList<LogisticsRoute> Routes() => _net?.Routes ?? Array.Empty<LogisticsRoute>();

	// ---------------------------------------------------------------- map texture

	/// <summary>
	/// One texture for the whole map, drawn the way the approved mockup draws it (network_viewer_mockup.py map_base):
	/// strategic biome colour per tile (custom HoMM3 biomes included) with a little per-tile variation, obstacle glyphs on
	/// object-blocked tiles, wavelets on water, continuous anti-aliased road bands through tile centres (diagonals too),
	/// the strategic dim, then thin grid lines. Mipmapped so the far zoom steps stay clean.
	/// </summary>
	private static bool TryBuildMapTexture(out int tilesRead, out string fail)
	{
		fail = null;
		tilesRead = 0;
		var span = Math.Max(_mapW, _mapH);
		var cell = span <= 160 ? L.CellPixels : span <= 320 ? 8 : 4;
		var tw = _mapW * cell;
		var th = _mapH * cell;
		var n = _mapW * _mapH;
		var kind = new byte[n];     // 0 = no data, 1 = land, 2 = water, 3 = fog
		var terrain = new byte[n];
		var roads = new bool[n];
		var blocked = new bool[n];
		// Resolve the viewer side once: a per-tile side lookup stalled large maps.
		if (!Homm3FactoryLogistics.TryGetViewerSide(out var viewerSide))
		{
			fail = "no local human side for the map view";
			return false;
		}
		for (var y = 0; y < _mapH; y++)
		{
			for (var x = 0; x < _mapW; x++)
			{
				if (!Homm3FactoryLogistics.TryGetTerrainTile(viewerSide, x, y, _level, out var t, out var road, out var water, out var block, out var fogged))
					continue;
				tilesRead++;
				var i = x + y * _mapW;
				terrain[i] = t;
				kind[i] = fogged ? (byte)3 : water ? (byte)2 : (byte)1;
				roads[i] = road && !fogged && !water;
				blocked[i] = block && !fogged && !water;
			}
		}
		if (tilesRead == 0)
		{
			fail = "no map tile could be read";
			return false;
		}
		var pixels = new Color32[tw * th];
		for (var y = 0; y < _mapH; y++)
		{
			for (var x = 0; x < _mapW; x++)
			{
				var i = x + y * _mapW;
				var j = L.Jitter(x, y);
				Color32 c;
				switch (kind[i])
				{
					case 1:
						c = L.Strategic(L.TerrainColour(terrain[i]), j);
						if (blocked[i])
							c = L.Darker(c, 0.76f);
						break;
					case 2:
						c = L.Strategic(L.Water, j);
						break;
					case 3:
						var k = (byte)(16 + (int)((j - 0.94f) * 50f));
						c = L.Strategic(new Color32(k, (byte)(k + 4), (byte)(k + 16), 255), 1f);
						break;
					default:
						c = L.NoData;
						break;
				}
				for (var py = 0; py < cell; py++)
				{
					var row = (y * cell + py) * tw + x * cell;
					for (var px = 0; px < cell; px++)
						pixels[row + px] = c;
				}
				if (cell < 8)
					continue;
				if (kind[i] == 1 && blocked[i])
					ObstacleGlyph(pixels, tw, x * cell, y * cell, cell, c);
				else if (kind[i] == 2 && L.Hash(x, y) < 0.4f)
					Wavelet(pixels, tw, x * cell, y * cell, cell, L.Strategic(new Color32(74, 112, 148, 255), 1f));
			}
		}

		// Roads: one band per road tile pair (orthogonal, or diagonal when no orthogonal pair joins them), outline then core.
		var segs = new List<(float ax, float ay, float bx, float by)>();
		for (var y = 0; y < _mapH; y++)
		{
			for (var x = 0; x < _mapW; x++)
			{
				if (!roads[x + y * _mapW])
					continue;
				var ax = (x + 0.5f) * cell;
				var ay = (y + 0.5f) * cell;
				segs.Add((ax, ay, ax, ay));
				foreach (var (dx, dy) in RoadNeighbours)
				{
					int nx = x + dx, ny = y + dy;
					if (nx < 0 || ny < 0 || nx >= _mapW || ny >= _mapH || !roads[nx + ny * _mapW])
						continue;
					if (dx != 0 && dy != 0 && (roads[nx + y * _mapW] || roads[x + ny * _mapW]))
						continue;
					segs.Add((ax, ay, (nx + 0.5f) * cell, (ny + 0.5f) * cell));
				}
			}
		}
		if (segs.Count > 0)
		{
			var cover = new float[tw * th];
			// Roads shorten routes, so they read at a glance: undimmed pale core on a dark outline (the dimmed mockup tones
			// vanished on foundry/sand ground, owner 2026-11-16).
			StrokeSegments(pixels, cover, tw, th, segs, cell * L.RoadEdgeRadius, L.RoadEdge);
			StrokeSegments(pixels, cover, tw, th, segs, cell * L.RoadCoreRadius, L.Road);
		}

		// Grid: the cell's east column and south row darker (not over fog).
		if (cell >= 6)
		{
			for (var y = 0; y < _mapH; y++)
			{
				for (var x = 0; x < _mapW; x++)
				{
					if (kind[x + y * _mapW] == 3)
						continue;
					for (var q = 0; q < cell; q++)
					{
						var e = (y * cell + q) * tw + x * cell + cell - 1;
						pixels[e] = L.Darker(pixels[e], 0.6f);
						var s = (y * cell) * tw + x * cell + q;
						if (q != cell - 1)
							pixels[s] = L.Darker(pixels[s], 0.6f);
					}
				}
			}
		}

		var texture = new Texture2D(tw, th, TextureFormat.RGBA32, true);
		texture.filterMode = FilterMode.Trilinear;
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.anisoLevel = 2;
		texture.hideFlags = HideFlags.HideAndDontSave;
		texture.SetPixels32(pixels);
		texture.Apply(true, false);
		var sprite = Sprite.Create(texture, new Rect(0f, 0f, tw, th), new Vector2(0.5f, 0.5f), 100f);
		if (sprite == null)
		{
			UnityObject.Destroy(texture);
			fail = "map sprite could not be created";
			return false;
		}
		sprite.hideFlags = HideFlags.HideAndDontSave;
		_mapTexture = texture;
		_mapSprite = sprite;
		return true;
	}

	private static readonly (int dx, int dy)[] RoadNeighbours = { (1, 0), (0, 1), (1, 1), (-1, 1) };

	/// <summary>A small peak (rows run south to north): dark body, lit cap. The mockup's obstacle read for blocked tiles.</summary>
	private static void ObstacleGlyph(Color32[] pixels, int tw, int x0, int y0, int cell, Color32 tile)
	{
		var dark = L.Darker(tile, 0.5f);
		var lit = L.Lighter(tile, 1.45f, 22);
		var cx = cell / 2f;
		var top = cell * 0.84f;
		var bottom = cell * 0.18f;
		var half = cell * 0.38f;
		for (var py = 0; py < cell; py++)
		{
			var fy = py + 0.5f;
			if (fy < bottom || fy > top)
				continue;
			var w = half * (top - fy) / (top - bottom);
			for (var px = 0; px < cell; px++)
			{
				var d = Math.Abs(px + 0.5f - cx);
				if (d > w + 0.5f)
					continue;
				var a = Mathf.Clamp01(w + 0.5f - d);
				var colour = fy > top - (top - bottom) * 0.3f ? lit : dark;
				var idx = (y0 + py) * tw + x0 + px;
				pixels[idx] = Color32.Lerp(pixels[idx], colour, a);
			}
		}
	}

	private static void Wavelet(Color32[] pixels, int tw, int x0, int y0, int cell, Color32 colour)
	{
		var y = cell / 2;
		for (var px = cell / 4; px < cell * 3 / 4; px++)
		{
			var dy = (px / Math.Max(1, cell / 8)) % 2 == 0 ? 0 : 1;
			pixels[(y0 + y + dy) * tw + x0 + px] = colour;
		}
	}

	/// <summary>Round-capped bands of <paramref name="radius"/> along every segment: coverage is the max over segments (no seams), blended once.</summary>
	private static void StrokeSegments(Color32[] pixels, float[] cover, int tw, int th, List<(float ax, float ay, float bx, float by)> segs, float radius, Color32 colour)
	{
		Array.Clear(cover, 0, cover.Length);
		var pad = radius + 1.5f;
		foreach (var (ax, ay, bx, by) in segs)
		{
			var x0 = Math.Max(0, (int)(Math.Min(ax, bx) - pad));
			var x1 = Math.Min(tw - 1, (int)(Math.Max(ax, bx) + pad));
			var y0 = Math.Max(0, (int)(Math.Min(ay, by) - pad));
			var y1 = Math.Min(th - 1, (int)(Math.Max(ay, by) + pad));
			for (var y = y0; y <= y1; y++)
			{
				for (var x = x0; x <= x1; x++)
				{
					var d = SegmentDistance(x + 0.5f, y + 0.5f, ax, ay, bx, by);
					var a = radius + 0.5f - d;
					if (a <= 0f)
						continue;
					var idx = y * tw + x;
					if (a > cover[idx])
						cover[idx] = Math.Min(1f, a);
				}
			}
		}
		for (var i = 0; i < pixels.Length; i++)
		{
			if (cover[i] > 0f)
				pixels[i] = Color32.Lerp(pixels[i], colour, cover[i]);
		}
	}

	private static float SegmentDistance(float px, float py, float ax, float ay, float bx, float by)
	{
		var dx = bx - ax;
		var dy = by - ay;
		var len2 = dx * dx + dy * dy;
		var t = len2 > 1e-6f ? Mathf.Clamp01(((px - ax) * dx + (py - ay) * dy) / len2) : 0f;
		var ex = px - (ax + t * dx);
		var ey = py - (ay + t * dy);
		return Mathf.Sqrt(ex * ex + ey * ey);
	}

	// ---------------------------------------------------------------- route glow texture

	/// <summary>
	/// The mockup's neon halo (Neon.apply: a blurred wide layer plus a tighter halo per colour, added on the map) as one
	/// soft texture in tile space: <see cref="L.GlowPixels"/> pixels per tile, bilinear, zoom-independent. Each source's
	/// routes take the max (shared edges and joints do not double up), sources add. Guard zones of blocking stacks glow
	/// red. The crisp core lines and chevrons stay UI geometry above it.
	/// </summary>
	private static void BuildGlow()
	{
		_glowFor = _net;
		_glowTile = _tile;
		DestroyGlow();
		if (_glowImage == null)
			return;
		_glowImage.enabled = false;
		var routes = Routes();
		var stacks = _net?.BlockingStacks;
		if (routes.Count == 0 && (stacks == null || stacks.Count == 0))
			return;
		var span = Math.Max(_mapW, _mapH);
		var g = span <= 160 ? L.GlowPixels : span <= 320 ? 6 : 3;
		int gw = _mapW * g, gh = _mapH * g;
		var acc = new float[gw * gh * 3];
		var one = new float[gw * gh];
		var bySource = new SortedDictionary<int, List<LogisticsRoute>>();
		foreach (var r in routes)
		{
			if (r?.Tiles == null || r.Tiles.Count == 0 || Hidden(r.FromKey))
				continue;
			var src = SourceIndex(r.FromKey);
			if (!bySource.TryGetValue(src, out var list))
				bySource[src] = list = new List<LogisticsRoute>();
			list.Add(r);
		}
		var lanes = LaneOffsets(routes, _tile / L.DefaultTile);
		foreach (var kv in bySource)
		{
			Array.Clear(one, 0, one.Length);
			foreach (var r in kv.Value)
			{
				var pts = LanePoints(r, kv.Key, lanes);
				if (pts.Length == 1)
					GlowSplat(one, gw, gh, g, pts[0], pts[0]);
				for (var i = 1; i < pts.Length; i++)
					GlowSplat(one, gw, gh, g, pts[i - 1], pts[i]);
			}
			AddGlow(acc, one, L.SourceColour(kv.Key));
		}
		if (stacks != null && stacks.Count > 0)
		{
			Array.Clear(one, 0, one.Length);
			foreach (var s in stacks)
			{
				if (s != null)
					GlowDisc(one, gw, gh, g, TileCentre(s.TileX, s.TileY), 1.25f);
			}
			AddGlow(acc, one, L.Red);
		}
		var pixels = new Color32[gw * gh];
		for (var i = 0; i < pixels.Length; i++)
		{
			float r = acc[i * 3], gg = acc[i * 3 + 1], b = acc[i * 3 + 2];
			var a = Math.Min(1f, Math.Max(r, Math.Max(gg, b)));
			if (a <= 0.004f)
				continue;
			// Straight alpha that reproduces "add": out = rgb * a + dst * (1 - a) with rgb * a = acc.
			pixels[i] = new Color32((byte)Math.Min(255f, r / a * 255f), (byte)Math.Min(255f, gg / a * 255f), (byte)Math.Min(255f, b / a * 255f), (byte)(a * 255f));
		}
		var texture = new Texture2D(gw, gh, TextureFormat.RGBA32, false);
		texture.filterMode = FilterMode.Bilinear;
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		texture.SetPixels32(pixels);
		texture.Apply(false, false);
		var sprite = Sprite.Create(texture, new Rect(0f, 0f, gw, gh), new Vector2(0.5f, 0.5f), 100f);
		if (sprite == null)
		{
			UnityObject.Destroy(texture);
			return;
		}
		sprite.hideFlags = HideFlags.HideAndDontSave;
		_glowTexture = texture;
		_glowSprite = sprite;
		_glowImage.sprite = sprite;
		_glowImage.color = Color.white;
		_glowImage.enabled = true;
	}

	/// <summary>Content-space point (y down, current tile size) to glow-texture pixels (rows south to north).</summary>
	private static Vector2 GlowPoint(Vector2 p, int g) => new(p.x / _tile * g, (_mapH - p.y / _tile) * g);

	private static void GlowSplat(float[] buf, int gw, int gh, int g, Vector2 a, Vector2 b)
	{
		var pa = GlowPoint(a, g);
		var pb = GlowPoint(b, g);
		var reach = L.GlowReach * g;
		var x0 = Math.Max(0, (int)(Math.Min(pa.x, pb.x) - reach));
		var x1 = Math.Min(gw - 1, (int)(Math.Max(pa.x, pb.x) + reach));
		var y0 = Math.Max(0, (int)(Math.Min(pa.y, pb.y) - reach));
		var y1 = Math.Min(gh - 1, (int)(Math.Max(pa.y, pb.y) + reach));
		float tight = 2f * L.GlowTight * L.GlowTight, wide = 2f * L.GlowWide * L.GlowWide;
		for (var y = y0; y <= y1; y++)
		{
			for (var x = x0; x <= x1; x++)
			{
				var d = SegmentDistance(x + 0.5f, y + 0.5f, pa.x, pa.y, pb.x, pb.y) / g;
				var v = L.GlowTightGain * Mathf.Exp(-d * d / tight) + L.GlowWideGain * Mathf.Exp(-d * d / wide);
				var idx = y * gw + x;
				if (v > buf[idx])
					buf[idx] = v;
			}
		}
	}

	private static void GlowDisc(float[] buf, int gw, int gh, int g, Vector2 centre, float radiusTiles)
	{
		var pc = GlowPoint(centre, g);
		var reach = (radiusTiles + 1f) * g;
		var x0 = Math.Max(0, (int)(pc.x - reach));
		var x1 = Math.Min(gw - 1, (int)(pc.x + reach));
		var y0 = Math.Max(0, (int)(pc.y - reach));
		var y1 = Math.Min(gh - 1, (int)(pc.y + reach));
		for (var y = y0; y <= y1; y++)
		{
			for (var x = x0; x <= x1; x++)
			{
				var dx = (x + 0.5f - pc.x) / g;
				var dy = (y + 0.5f - pc.y) / g;
				var d = Mathf.Sqrt(dx * dx + dy * dy);
				var v = 0.5f * Mathf.Clamp01(1f - Math.Max(0f, d - radiusTiles * 0.6f) / (radiusTiles * 0.8f));
				var idx = y * gw + x;
				if (v > buf[idx])
					buf[idx] = v;
			}
		}
	}

	private static void AddGlow(float[] acc, float[] one, Color colour)
	{
		for (var i = 0; i < one.Length; i++)
		{
			var v = one[i];
			if (v <= 0f)
				continue;
			acc[i * 3] += v * colour.r;
			acc[i * 3 + 1] += v * colour.g;
			acc[i * 3 + 2] += v * colour.b;
		}
	}

	private static void DestroyGlow()
	{
		try
		{
			if (_glowSprite)
				UnityObject.Destroy(_glowSprite);
			if (_glowTexture)
				UnityObject.Destroy(_glowTexture);
		}
		catch
		{
		}
		_glowSprite = null;
		_glowTexture = null;
	}

	private static void DestroyMapTexture()
	{
		try
		{
			if (_mapSprite)
				UnityObject.Destroy(_mapSprite);
			if (_mapTexture)
				UnityObject.Destroy(_mapTexture);
		}
		catch
		{
		}
		_mapSprite = null;
		_mapTexture = null;
	}

	// ---------------------------------------------------------------- pan / zoom

	private static Vector2 TileCentre(int x, int y) => new((x + 0.5f) * _tile, (_mapH - 1 - y + 0.5f) * _tile);

	/// <summary>Largest zoom step (up to the default) that shows every building, town and hero; centred on them.</summary>
	private static void FrameNetwork()
	{
		int x0 = int.MaxValue, y0 = int.MaxValue, x1 = int.MinValue, y1 = int.MinValue;
		void Add(int x, int y)
		{
			x0 = Math.Min(x0, x);
			y0 = Math.Min(y0, y);
			x1 = Math.Max(x1, x);
			y1 = Math.Max(y1, y);
		}
		foreach (var b in _net.Buildings)
		{
			if (b != null)
				Add(b.TileX, b.TileY);
		}
		if (_net.Towns != null)
		{
			foreach (var t in _net.Towns)
				Add(t.x, t.y);
		}
		if (_net.Heroes != null)
		{
			foreach (var h in _net.Heroes)
				Add(h.x, h.y);
		}
		if (x0 > x1)
		{
			x0 = y0 = 0;
			x1 = _mapW - 1;
			y1 = _mapH - 1;
		}
		var spanX = x1 - x0 + 7;
		var spanY = y1 - y0 + 7;
		_tile = L.ZoomSteps[0];
		foreach (var step in L.ZoomSteps)
		{
			if (step <= L.DefaultTile && spanX * step <= L.MapWidth && spanY * step <= L.MapHeight)
				_tile = step;
		}
		var centre = TileCentre((x0 + x1) / 2, (y0 + y1) / 2);
		_pan = new Vector2(centre.x - L.MapWidth / 2f, centre.y - L.MapHeight / 2f);
		ClampPan();
	}

	private static void ClampPan()
	{
		var cw = _mapW * _tile;
		var ch = _mapH * _tile;
		_pan.x = cw <= L.MapWidth ? (cw - L.MapWidth) / 2f : Mathf.Clamp(_pan.x, 0f, cw - L.MapWidth);
		_pan.y = ch <= L.MapHeight ? (ch - L.MapHeight) / 2f : Mathf.Clamp(_pan.y, 0f, ch - L.MapHeight);
	}

	private static void ApplyPan()
	{
		if (_content != null)
			A.Place(_content, -_pan.x, -_pan.y, _mapW * _tile, _mapH * _tile);
	}

	/// <summary>Steps the zoom, keeping the map point under <paramref name="anchor"/> (viewport space) in place.</summary>
	private static void Zoom(int direction, Vector2 anchor)
	{
		var index = 0;
		for (var i = 0; i < L.ZoomSteps.Length; i++)
		{
			if (Math.Abs(L.ZoomSteps[i] - _tile) < Math.Abs(L.ZoomSteps[index] - _tile))
				index = i;
		}
		var next = Mathf.Clamp(index + direction, 0, L.ZoomSteps.Length - 1);
		if (next == index)
			return;
		var k = L.ZoomSteps[next] / _tile;
		_pan = (_pan + anchor) * k - anchor;
		_tile = L.ZoomSteps[next];
		ClampPan();
		ApplyPan();
		BuildOverlay();
	}

	// ---------------------------------------------------------------- input (host Update)

	internal static void Tick()
	{
		if (_net == null || _canvasObject == null || _tickFrame == Time.frameCount)
			return;
		_tickFrame = Time.frameCount;
		try
		{
			Homm3TowerArtificingPickerInputBlock.Hold();
			if (Input.GetKeyDown(KeyCode.Escape))
			{
				if (!EscapeExtras())
					Close("Esc");
				return;
			}
			var mouse = (Vector2)Input.mousePosition;
			Animate();
			if (TickPopup(mouse))
				return;
			HandleKeys();
			if (_net == null || _popup != PopupNone)
				return;
			Ui.HoverButtons(ChromeButtons, mouse);
			Ui.HoverButtons(CardButtons, mouse);
			Ui.HoverButtons(PanelButtons, mouse);
			UpdateTip(mouse);
			var overCard = Ui.Over(_cardRect, mouse);
			var overPanel = !overCard && Ui.Over(_panelRect, mouse);
			var overMap = !overCard && !overPanel && Ui.Over(_viewport, mouse);
			var wheel = Input.mouseScrollDelta.y;
			if (overMap && Math.Abs(wheel) > 0.01f && Ui.TryWindowPoint(_window, mouse, out var at))
			{
				Zoom(wheel > 0f ? 1 : -1, new Vector2(at.x - L.MapX, at.y - L.MapY));
				return;
			}
			if (Input.GetMouseButtonDown(0))
			{
				_panning = false;
				if (Ui.ClickButtons(CardButtons, mouse) || overCard)
					return;
				if (Ui.ClickButtons(PanelButtons, mouse) || overPanel)
					return;
				if (Ui.ClickButtons(ChromeButtons, mouse))
					return;
				if (overMap)
				{
					if (ClickCut(mouse))
						return;
					for (var i = Markers.Count - 1; i >= 0; i--)
					{
						if (!Ui.Over(Markers[i].Rect, mouse))
							continue;
						Select(Markers[i].Key);
						return;
					}
					if (Ui.TryWindowPoint(_window, mouse, out _panLast))
						_panning = true;
				}
				return;
			}
			if (_panning)
			{
				if (!Input.GetMouseButton(0))
				{
					_panning = false;
				}
				else if (Ui.TryWindowPoint(_window, mouse, out var now))
				{
					_pan -= now - _panLast;
					_panLast = now;
					ClampPan();
					ApplyPan();
				}
			}
		}
		catch (Exception ex)
		{
			Ui.LogWarning("viewer input failed; closing: " + ex.GetBaseException().Message);
			Close("panel error");
		}
	}

	private static void Animate()
	{
		var t = Time.unscaledTime;
		foreach (var c in Chevrons)
		{
			if (c.Rect == null)
				continue;
			var total = c.Cumulative[c.Cumulative.Length - 1];
			if (total <= 0.5f)
				continue;
			var d = (c.Offset + t * L.ChevronSpeed * _tile) % total;
			var seg = 1;
			while (seg < c.Cumulative.Length - 1 && c.Cumulative[seg] < d)
				seg++;
			var a = c.Points[seg - 1];
			var b = c.Points[seg];
			var len = c.Cumulative[seg] - c.Cumulative[seg - 1];
			var p = len > 0.001f ? Vector2.Lerp(a, b, (d - c.Cumulative[seg - 1]) / len) : a;
			c.Rect.anchoredPosition = new Vector2(p.x, -p.y);
			c.Rect.localRotation = Quaternion.Euler(0f, 0f, Mathf.Atan2(-(b.y - a.y), b.x - a.x) * Mathf.Rad2Deg);
			// Bright crest travelling from the source to the receiver (mockup: 110 + 145 * crest of 255).
			var period = L.CrestPeriod * _tile;
			var k = ((d - t * L.CrestSpeed * _tile) % period + period) % period / period;
			var crest = Mathf.Exp(-(k - 0.5f) * (k - 0.5f) / 0.02f);
			var coreAlpha = 0.43f + 0.57f * crest;
			var core = Color.Lerp(c.Colour, Color.white, 0.15f + 0.4f * crest);
			core.a = coreAlpha;
			if (c.Core != null)
			{
				foreach (var image in c.Core)
				{
					if (image != null)
						image.color = core;
				}
			}
			if (c.Halo != null)
			{
				var halo = new Color(c.Colour.r, c.Colour.g, c.Colour.b, 0.1f + 0.32f * crest);
				foreach (var image in c.Halo)
				{
					if (image != null)
						image.color = halo;
				}
			}
		}
		var pulse = 0.5f + 0.5f * Mathf.Sin(t * 3.2f);
		foreach (var image in Pulsing)
		{
			if (image == null)
				continue;
			var colour = image.color;
			colour.a = Mathf.Lerp(0.16f, 0.42f, pulse);
			image.color = colour;
		}
	}

	private static void Select(long key)
	{
		if (!_hasSelection || _selectedKey != key)
		{
			_tab = 0;
			_hireCount = 1;
			_hireTarget = 0;
			_hireUnit = 0;
			_status = null;
		}
		_hasSelection = true;
		_selectedKey = key;
		ReadRemote();
		BuildOverlay();
		BuildCard();
	}

	/// <summary>The selected building as the Upgrade Center sees it (no hero: remote caps and next-day orders).</summary>
	private static void ReadRemote()
	{
		_remote = null;
		_remoteFail = null;
		if (!_hasSelection)
			return;
		if (!Homm3FactoryLogistics.TryGetBuilding(_selectedKey, null, out _remote, out _remoteFail))
			_remote = null;
	}

	/// <summary>Runs a facade command, then re-reads the network (recomputed by CORE) and redraws.</summary>
	private static void Run(string what, Func<(bool Ok, string Fail)> command)
	{
		var (ok, fail) = command();
		Ui.LogInfo("viewer: " + what + " on object " + _selectedKey + " -> " + (ok ? "ok" : "refused: " + fail));
		_status = ok ? null : fail ?? what + " refused";
		if (Homm3FactoryLogistics.TryGetNetwork(out var net, out var netFail) && net != null && net.Buildings != null)
			_net = net;
		else
			Ui.LogWarning("viewer: network re-read failed after " + what + " (" + netFail + "); showing the previous one");
		InvalidateExtras();
		if (_hasSelection && Building(_selectedKey) == null)
			_hasSelection = false;
		ReadRemote();
		BuildOverlay();
		BuildCard();
	}

	private static LogisticsBuildingView Building(long key)
	{
		foreach (var b in _net.Buildings)
		{
			if (b != null && b.ObjectKey == key)
				return b;
		}
		return null;
	}

	private static int SourceIndex(long key)
	{
		for (var i = 0; i < _net.Buildings.Count; i++)
		{
			if (_net.Buildings[i] != null && _net.Buildings[i].ObjectKey == key)
				return i;
		}
		return -1;
	}

	private static string EnhancementName(LogisticsBuildingView b, string id)
	{
		if (string.IsNullOrEmpty(id))
			return null;
		if (b?.Options != null)
		{
			foreach (var o in b.Options)
			{
				if (o != null && o.Id == id && !string.IsNullOrEmpty(o.Name))
					return o.Name;
			}
		}
		if (_remote?.Options != null && b != null && _remote.ObjectKey == b.ObjectKey)
		{
			foreach (var o in _remote.Options)
			{
				if (o != null && o.Id == id && !string.IsNullOrEmpty(o.Name))
					return o.Name;
			}
		}
		var words = id.Replace('_', ' ').Split(' ', StringSplitOptions.RemoveEmptyEntries);
		for (var i = 0; i < words.Length; i++)
			words[i] = char.ToUpperInvariant(words[i][0]) + words[i].Substring(1);
		return string.Join(" ", words);
	}

	private static int BuiltLevel(LogisticsBuildingView b, string id)
	{
		if (b?.Built == null || id == null)
			return 0;
		foreach (var e in b.Built)
		{
			if (e != null && e.Id == id)
				return e.Level;
		}
		return 0;
	}

	private static string TargetName(string kind, long key)
	{
		if (kind == "building")
			return Building(key)?.DisplayName ?? "building";
		var list = kind == "town" ? _net.Towns : _net.Heroes;
		if (list != null)
		{
			foreach (var t in list)
			{
				if (t.key == key)
					return string.IsNullOrEmpty(t.name) ? kind : t.name;
			}
		}
		return kind ?? "target";
	}

	// ---------------------------------------------------------------- build: window

	private static void BuildAll()
	{
		ChromeButtons.Clear();
		Tips.Clear();
		_shownTip = null;
		_tipRoot = null;
		Ui.ClearChildren(_window);
		var w = L.Width;
		var h = L.Height;
		Ui.Shell(_window, w, h, "Logistics Network", 0f);

		// Map viewport (masked), its content (texture + overlay), then the chrome on top of it.
		var view = Ui.Flat(_window, L.MapX, L.MapY, L.MapWidth, L.MapHeight, new Color(0.03f, 0.04f, 0.07f, 1f));
		var mask = view.gameObject.AddComponent<Mask>();
		if (mask != null)
			mask.showMaskGraphic = true;
		_viewport = view.rectTransform;
		_content = A.NewRect("Content", _viewport);
		ApplyPan();
		var map = A.NewImage("Map", _content, _mapSprite, Color.black);
		A.Stretch(map.rectTransform);
		_glowImage = A.NewImage("Glow", _content, null, Color.clear);
		A.Stretch(_glowImage.rectTransform);
		_glowImage.raycastTarget = false;
		_glowFor = null;
		_rangeImage = A.NewImage("Range", _content, null, Color.clear);
		A.Stretch(_rangeImage.rectTransform);
		_rangeImage.raycastTarget = false;
		_rangeImage.enabled = false;
		_rangeFor = null;
		_overlay = A.NewRect("Overlay", _content);
		A.Stretch(_overlay);
		BuildOverlay();

		// Zoom buttons (top-right of the map) and Close (header, right).
		var zx = L.MapX + L.MapWidth - L.ZoomSize - 12f;
		AddIconButton(Ui.SpritePlus, "+", zx, L.MapY + 12f, L.ZoomSize, () => Zoom(1, new Vector2(L.MapWidth / 2f, L.MapHeight / 2f)));
		AddIconButton(Ui.SpriteMinus, "-", zx, L.MapY + 18f + L.ZoomSize, L.ZoomSize, () => Zoom(-1, new Vector2(L.MapWidth / 2f, L.MapHeight / 2f)));
		var close = Ui.Image(_window, P.SpriteClose, w - L.CloseSize - 6f, 23f - L.CloseSize / 2f, L.CloseSize, L.CloseSize, new Color(0.45f, 0.2f, 0.15f, 1f));
		if (close.sprite == null)
			Ui.Text(_window, P.FontBook, P.SizeSubHeader, "X", w - L.CloseSize - 6f, 23f - L.CloseSize / 2f, L.CloseSize, L.CloseSize, P.ButtonText, TextAlignmentOptions.Center);
		ChromeButtons.Add(new Ui.Clickable { Rect = close.rectTransform, Image = close, Normal = Ui.Sprite(P.SpriteClose), Hover = Ui.Sprite(P.SpriteCloseHover), Click = () => Close("Close") });

		BuildLegend();
		BuildChromeExtras();
		_statusText = Ui.Text(_window, P.FontMedium, P.SizeSmall, _status ?? "", L.MapX, L.StatusY, L.MapWidth, 26f, P.TipWarn, TextAlignmentOptions.Center);
		_cardRoot = A.NewRect("Card", _window);
		A.Stretch(_cardRoot);
		_popupRoot = A.NewRect("Popup", _window);
		A.Stretch(_popupRoot);
		BuildCard();
		BuildPopup();
	}

	private static void AddIconButton(string sprite, string fallbackGlyph, float x, float y, float size, Action click)
	{
		var image = Ui.Image(_window, sprite, x, y, size, size, new Color(0.12f, 0.16f, 0.26f, 0.95f));
		if (image.sprite == null)
			Ui.Text(_window, P.FontBook, P.SizeHeaderBig, fallbackGlyph, x, y, size, size, P.TipTitle, TextAlignmentOptions.Center);
		ChromeButtons.Add(new Ui.Clickable { Rect = image.rectTransform, Image = image, Click = click });
	}

	private static void BuildLegend()
	{
		var y = L.LegendTop;
		Ui.Flat(_window, L.MapX, y, L.MapWidth, L.LegendHeight, new Color(0.05f, 0.07f, 0.12f, 0.9f));
		// Row 1: routes, cuts, stacks, roads, range overlay.
		var cy = y + L.LegendHeight * 0.27f;
		var x = L.MapX + 22f;
		for (var i = 0; i < 3; i++)
			Ui.Line(_window, x, cy - 6f + i * 6f, x + 58f, cy - 6f + i * 6f, 2.5f, L.SourceColour(i));
		x += 70f;
		x = LegendText("Route (colour = source)", x, cy) + 30f;
		Ui.Line(_window, x, cy, x + 26f, cy, 2.5f, L.SourceColour(0));
		CutMark(_window, x + 36f, cy, 7f);
		x = LegendText("Cut: needs more range (click it)", x + 56f, cy) + 30f;
		Ui.Flat(_window, x, cy - 9f, 18f, 18f, new Color(L.Red.r, L.Red.g, L.Red.b, 0.55f));
		x = LegendText("Blocking stack", x + 28f, cy) + 30f;
		Ui.Line(_window, x, cy, x + 34f, cy, 7f, (Color)L.RoadEdge);
		Ui.Line(_window, x, cy, x + 34f, cy, 3.5f, (Color)L.Road);
		x = LegendText("Road (range goes further)", x + 44f, cy) + 30f;
		var shade = L.SourceColour(0);
		Ui.Flat(_window, x, cy - 9f, 18f, 18f, new Color(shade.r, shade.g, shade.b, 0.4f));
		Ui.Flat(_window, x + 20f, cy - 9f, 18f, 18f, new Color(L.HubRing.r, L.HubRing.g, L.HubRing.b, 0.4f));
		LegendText("Range (R; pale = refreshed by a hub)", x + 48f, cy);
		// Row 2: marker badges.
		cy = y + L.LegendHeight * 0.73f;
		x = L.MapX + 22f;
		Ui.Flat(_window, x, cy - 10f, 44f, 20f, L.Plate);
		Ui.Text(_window, P.FontMedium, 13f, "UC 2", x, cy - 10f, 44f, 20f, P.TipTitle, TextAlignmentOptions.Center);
		x = LegendText("Upgrade Center 2", x + 54f, cy) + 26f;
		Ui.Flat(_window, x, cy - 10f, 44f, 20f, L.Plate);
		Ui.Text(_window, P.FontMedium, 13f, "CC 2", x, cy - 10f, 44f, 20f, L.CommandCenter, TextAlignmentOptions.Center);
		x = LegendText("Command Center 2", x + 54f, cy) + 26f;
		Ui.Flat(_window, x, cy - 10f, 20f, 20f, L.Unvisited);
		Ui.Text(_window, P.FontBook, 15f, "!", x, cy - 10f, 20f, 20f, P.Ink, TextAlignmentOptions.Center);
		x = LegendText("Not yet visited", x + 30f, cy) + 26f;
		Ui.Flat(_window, x, cy - 10f, 70f, 20f, L.Plate);
		Ui.Text(_window, P.FontMedium, 12f, "Tomorrow", x, cy - 10f, 70f, 20f, P.TipWarn, TextAlignmentOptions.Center);
		x = LegendText("Under construction / switching", x + 80f, cy) + 26f;
		Ui.Centered(_window, P.SpritePanelRing, x + 12f, cy, 26f, 26f, Color.clear).color = L.HubRing;
		LegendText("Logistics Hub / Rail Station (gives range back)", x + 32f, cy);
		Ui.Text(_window, P.FontMedium, P.SizeSmall, "Network range " + Days(_net.LogisticsLevel * _net.RangeMpPerLevel), L.MapX + L.MapWidth - 300f, cy - 13f, 280f, 26f, P.TipNote, TextAlignmentOptions.Right);
	}

	private static float LegendText(string text, float x, float cy)
	{
		var tw = Ui.TextWidth(text, P.SizeSmall);
		Ui.Text(_window, P.FontMedium, P.SizeSmall, text, x, cy - 13f, tw + 30f, 26f, P.TipBody);
		return x + tw;
	}

	private static void CutMark(Transform parent, float cx, float cy, float r)
	{
		Ui.Line(parent, cx - r, cy - r, cx + r, cy + r, 3f, L.Red);
		Ui.Line(parent, cx - r, cy + r, cx + r, cy - r, 3f, L.Red);
	}

	// ---------------------------------------------------------------- build: map overlay (content space)

	private static void BuildOverlay()
	{
		Markers.Clear();
		Chevrons.Clear();
		Pulsing.Clear();
		Placed.Clear();
		CutHits.Clear();
		if (_overlay == null)
			return;
		Ui.ClearChildren(_overlay);
		RefreshRange();
		if (_glowFor != _net || _glowTile != _tile)
			BuildGlow();
		var scale = Mathf.Clamp(_tile / L.DefaultTile, 0.55f, 1.25f);

		// 1. Blocking stacks: the stack tile and its 8 guard tiles, tinted red and pulsing.
		if (_net.BlockingStacks != null)
		{
			foreach (var s in _net.BlockingStacks)
			{
				if (s == null)
					continue;
				var c = TileCentre(s.TileX, s.TileY);
				Pulsing.Add(Ui.Flat(_overlay, c.x - 1.5f * _tile, c.y - 1.5f * _tile, 3f * _tile, 3f * _tile, new Color(L.Red.r, L.Red.g, L.Red.b, 0.3f)));
				Ui.Flat(_overlay, c.x - _tile / 2f, c.y - _tile / 2f, _tile, _tile, new Color(L.Red.r, L.Red.g, L.Red.b, 0.55f));
			}
		}

		// 2. Routes: one lane per source per tile edge, side by side.
		var routes = Routes();
		var lanes = LaneOffsets(routes, scale);
		var drawn = new HashSet<(long Edge, int Source, bool Forward)>();
		var cuts = new Dictionary<(long Source, int X, int Y), List<LogisticsRoute>>();
		var cutPoints = new Dictionary<(long Source, int X, int Y), Vector2>();
		var chevronBudget = L.MaxChevrons;
		foreach (var route in routes)
		{
			if (route?.Tiles == null || route.Tiles.Count == 0 || Hidden(route.FromKey))
				continue;
			var src = SourceIndex(route.FromKey);
			var colour = L.SourceColour(src);
			var points = LanePoints(route, src, lanes);
			DrawRoute(route, src, points, colour, drawn, scale);
			if (points.Length >= 2 && chevronBudget > 0)
				chevronBudget -= AddChevrons(points, colour, scale, chevronBudget);
			// A cut needs at least one step: a route with no path at all (CORE: NoPath) carries no tiles and draws nothing.
			if (route.Cut && route.Tiles.Count >= 2)
			{
				var last = route.Tiles[route.Tiles.Count - 1];
				var key = (route.FromKey, last.x, last.y);
				if (!cuts.TryGetValue(key, out var list))
				{
					cuts[key] = list = new List<LogisticsRoute>();
					cutPoints[key] = points[points.Length - 1];
				}
				list.Add(route);
			}
		}

		// 3. Markers (their boxes are reserved before any label is placed).
		var m = Mathf.Clamp(_tile * 2f, 30f, L.Marker);
		foreach (var b in _net.Buildings)
		{
			if (b != null)
				BuildingMarker(b, m);
		}
		if (_net.Towns != null)
		{
			foreach (var t in _net.Towns)
				TownMarker(t.key, TileCentre(t.x, t.y), Mathf.Clamp(_tile * 2.2f, 30f, L.TownSize));
		}
		if (_net.Heroes != null)
		{
			foreach (var hr in _net.Heroes)
				HeroMarker(hr.key, TileCentre(hr.x, hr.y), Mathf.Clamp(_tile * 1.8f, 26f, L.HeroSize));
		}
		if (_net.BlockingStacks != null)
		{
			foreach (var s in _net.BlockingStacks)
			{
				if (s == null)
					continue;
				var c = TileCentre(s.TileX, s.TileY);
				Placed.Add(new Rect(c.x - 1.5f * _tile, c.y - 1.5f * _tile, 3f * _tile, 3f * _tile));
			}
		}

		// 4. Cut marks over the markers.
		foreach (var kv in cutPoints)
		{
			CutMark(_overlay, kv.Value.x, kv.Value.y, 8f * scale + 2f);
			AddCutHit(kv.Key.Source, kv.Key.X, kv.Key.Y, kv.Value);
			Placed.Add(new Rect(kv.Value.x - 12f, kv.Value.y - 12f, 24f, 24f));
		}

		// 5. Labels: marker names, the stack notes, then the cut labels.
		foreach (var b in _net.Buildings)
		{
			if (b == null || Hidden(b.ObjectKey))
				continue;
			var c = TileCentre(b.TileX, b.TileY);
			var builtLevel = BuiltLevel(b, b.ActiveEnhancementId);
			var second = !string.IsNullOrEmpty(b.ActiveEnhancementId)
				? EnhancementName(b, b.ActiveEnhancementId) + " " + builtLevel + (b.ActivePoweredLevel > builtLevel ? " (powered " + b.ActivePoweredLevel + ")" : "")
				: b.UpgradeCenterLevel <= 0 ? "Not yet visited" : "No active enhancement";
			Plate(c, m / 2f + 6f, new[] { b.DisplayName ?? "Building", second }, new[] { P.TipBody, string.IsNullOrEmpty(b.ActiveEnhancementId) ? P.TipWarn : P.TipNote }, new[] { L.LabelSize, 14f }, true);
		}
		if (_net.Towns != null)
		{
			foreach (var t in _net.Towns)
				Plate(TileCentre(t.x, t.y), Mathf.Clamp(_tile * 2.2f, 30f, L.TownSize) / 2f + 4f, new[] { string.IsNullOrEmpty(t.name) ? "Town" : t.name }, new[] { P.TipTitle }, new[] { L.LabelSize }, true);
		}
		if (_net.Heroes != null)
		{
			foreach (var hr in _net.Heroes)
				Plate(TileCentre(hr.x, hr.y), Mathf.Clamp(_tile * 1.8f, 26f, L.HeroSize) / 2f + 4f, new[] { string.IsNullOrEmpty(hr.name) ? "Hero" : hr.name }, new[] { P.TipBody }, new[] { L.LabelSize }, true);
		}
		if (_net.BlockingStacks != null)
		{
			foreach (var s in _net.BlockingStacks)
			{
				if (s != null && !string.IsNullOrEmpty(s.Label))
					Plate(TileCentre(s.TileX, s.TileY), 1.5f * _tile + 6f, new[] { s.Label }, new[] { L.Red }, new[] { L.LabelSize }, true);
			}
		}
		foreach (var kv in cuts)
		{
			var source = Building(kv.Key.Source);
			var lines = new List<string>();
			var enh = source == null ? null : EnhancementName(source, source.ActiveEnhancementId);
			lines.Add((enh ?? "Route") + " (" + (source?.DisplayName ?? "building") + ")");
			foreach (var r in kv.Value)
				lines.Add("-> " + TargetName(r.ToKind, r.ToKey) + ": " + Homm3FactoryLogistics.NeedsRange(r.MissingMp));
			var colours = new Color[lines.Count];
			var sizes = new float[lines.Count];
			for (var i = 0; i < lines.Count; i++)
			{
				colours[i] = L.Red;
				sizes[i] = L.LabelSize;
			}
			var at = cutPoints[kv.Key];
			var rect = Plate(at, 16f, lines.ToArray(), colours, sizes, false);
			// Leader line when the plate does not touch the mark.
			var px = Mathf.Clamp(at.x, rect.xMin, rect.xMax);
			var py = Mathf.Clamp(at.y, rect.yMin, rect.yMax);
			if ((new Vector2(px, py) - at).magnitude > 20f)
				Ui.Line(_overlay, at.x, at.y, px, py, 1.5f, new Color(L.Red.r, L.Red.g, L.Red.b, 0.8f));
		}
	}

	/// <summary>
	/// One lane per source building on every tile edge. Lanes sit side by side (transit-map style): the offset is measured
	/// to the right of the travel direction and ordered by source index, so the order holds along a shared stretch; sources
	/// travelling an edge in opposite directions keep to their own right-hand side.
	/// </summary>
	private static Dictionary<(long Edge, int Source, bool Forward), float> LaneOffsets(IReadOnlyList<LogisticsRoute> routes, float scale)
	{
		var use = new Dictionary<long, SortedSet<(bool Forward, int Source)>>();
		foreach (var route in routes)
		{
			if (route?.Tiles == null)
				continue;
			var src = SourceIndex(route.FromKey);
			for (var i = 1; i < route.Tiles.Count; i++)
			{
				var edge = Edge(route.Tiles[i - 1], route.Tiles[i], out var forward);
				if (!use.TryGetValue(edge, out var set))
					use[edge] = set = new SortedSet<(bool, int)>();
				set.Add((forward, src));
			}
		}
		var offsets = new Dictionary<(long, int, bool), float>();
		foreach (var kv in use)
		{
			var fwd = new List<int>();
			var back = new List<int>();
			foreach (var (forward, src) in kv.Value)
				(forward ? fwd : back).Add(src);
			var n = fwd.Count + back.Count;
			var gap = n > 1 ? Math.Min(L.BundleGap, L.BundleMaxWidth / (n - 1)) * scale : 0f;
			var both = fwd.Count > 0 && back.Count > 0;
			for (var i = 0; i < fwd.Count; i++)
				offsets[(kv.Key, fwd[i], true)] = both ? (i + 0.5f) * gap : (i - (fwd.Count - 1) / 2f) * gap;
			for (var i = 0; i < back.Count; i++)
				offsets[(kv.Key, back[i], false)] = both ? (i + 0.5f) * gap : (i - (back.Count - 1) / 2f) * gap;
		}
		return offsets;
	}

	private static long Edge((int x, int y) a, (int x, int y) b, out bool forward)
	{
		long na = a.x + (long)a.y * _mapW;
		long nb = b.x + (long)b.y * _mapW;
		forward = na < nb;
		return forward ? na << 32 | nb : nb << 32 | na;
	}

	/// <summary>The route's polyline in content space, each point shifted by the average lane offset of its two edges.</summary>
	private static Vector2[] LanePoints(LogisticsRoute route, int src, Dictionary<(long, int, bool), float> lanes)
	{
		var tiles = route.Tiles;
		var n = tiles.Count;
		var shift = new Vector2[Math.Max(0, n - 1)];
		for (var i = 1; i < n; i++)
		{
			var a = TileCentre(tiles[i - 1].x, tiles[i - 1].y);
			var b = TileCentre(tiles[i].x, tiles[i].y);
			var d = b - a;
			var len = d.magnitude;
			var edge = Edge(tiles[i - 1], tiles[i], out var forward);
			var o = lanes.TryGetValue((edge, src, forward), out var value) ? value : 0f;
			shift[i - 1] = len > 0.001f ? new Vector2(-d.y / len * o, d.x / len * o) : Vector2.zero;   // right of travel (y points down)
		}
		var points = new Vector2[n];
		for (var i = 0; i < n; i++)
		{
			var p = TileCentre(tiles[i].x, tiles[i].y);
			if (n > 1)
				p += i == 0 ? shift[0] : i == n - 1 ? shift[n - 2] : (shift[i - 1] + shift[i]) / 2f;
			points[i] = p;
		}
		return points;
	}

	/// <summary>
	/// Draws the route's not-yet-drawn lane edges (a source's routes share one line per edge); straight runs merge. The
	/// core is the mockup's hue-true core (85% colour, 15% white) with round caps at every run end, over the glow texture.
	/// </summary>
	private static void DrawRoute(LogisticsRoute route, int src, Vector2[] points, Color colour, HashSet<(long, int, bool)> drawn, float scale)
	{
		var tiles = route.Tiles;
		var core = Mathf.Max(2f, L.LineWidth * scale);
		var line = Color.Lerp(colour, Color.white, 0.15f);
		var halo = new Color(colour.r, colour.g, colour.b, 0.35f);
		var knob = Ui.Sprite("Knob");
		var start = -1;
		for (var i = 1; i <= tiles.Count; i++)
		{
			var fresh = false;
			if (i < tiles.Count)
			{
				var edge = Edge(tiles[i - 1], tiles[i], out var forward);
				fresh = drawn.Add((edge, src, forward));
			}
			var straight = fresh && start >= 0 && i >= 2
				&& tiles[i].x - tiles[i - 1].x == tiles[i - 1].x - tiles[i - 2].x && tiles[i].y - tiles[i - 1].y == tiles[i - 1].y - tiles[i - 2].y
				&& Vector2.Distance(points[i] - points[i - 1], points[i - 1] - points[i - 2]) < 0.05f;
			if (start >= 0 && !straight)
			{
				var a = points[start];
				var b = points[i - 1];
				Ui.Line(_overlay, a.x, a.y, b.x, b.y, core + 3f, halo);
				Ui.Line(_overlay, a.x, a.y, b.x, b.y, core, line);
				if (knob != null)
				{
					Ui.SpriteImage(_overlay, knob, a.x - core / 2f, a.y - core / 2f, core, core).color = line;
					Ui.SpriteImage(_overlay, knob, b.x - core / 2f, b.y - core / 2f, core, core).color = line;
				}
				start = -1;
			}
			if (fresh && start < 0)
				start = i - 1;
		}
	}

	private static int AddChevrons(Vector2[] points, Color colour, float scale, int budget)
	{
		var cumulative = new float[points.Length];
		for (var i = 1; i < points.Length; i++)
			cumulative[i] = cumulative[i - 1] + Vector2.Distance(points[i - 1], points[i]);
		var total = cumulative[points.Length - 1];
		if (total < _tile * 1.5f)
			return 0;
		var count = Mathf.Clamp(Mathf.RoundToInt(total / (_tile * L.ChevronSpacing)), 1, Math.Min(budget, L.MaxChevronsPerRoute));
		var size = L.ChevronSize * scale + 0.5f;
		var knob = Ui.Sprite("Knob");
		for (var k = 0; k < count; k++)
		{
			var rect = A.NewRect("Chevron", _overlay);
			rect.anchorMin = rect.anchorMax = new Vector2(0f, 1f);
			rect.pivot = new Vector2(0.5f, 0.5f);
			rect.sizeDelta = Vector2.zero;
			var halo = new[]
			{
				Ui.Line(rect, size, 0f, -size, -size, 6f, Color.clear),
				Ui.Line(rect, size, 0f, -size, size, 6f, Color.clear),
			};
			var core = new List<UnityImage>
			{
				Ui.Line(rect, size, 0f, -size, -size, 2.2f, colour),
				Ui.Line(rect, size, 0f, -size, size, 2.2f, colour),
			};
			if (knob != null)
				core.Add(Ui.SpriteImage(rect, knob, size - 1.6f, -1.6f, 3.2f, 3.2f));
			Chevrons.Add(new Chevron { Rect = rect, Points = points, Cumulative = cumulative, Offset = total * k / count, Core = core.ToArray(), Halo = halo, Colour = colour });
		}
		return count;
	}

	private static void BuildingMarker(LogisticsBuildingView b, float m)
	{
		var c = TileCentre(b.TileX, b.TileY);
		var selected = _hasSelection && b.ObjectKey == _selectedKey;
		if (selected)
		{
			var r = m / 2f + 6f;
			Ui.Flat(_overlay, c.x - r, c.y - r, 2f * r, 2f, P.TipTitle);
			Ui.Flat(_overlay, c.x - r, c.y + r - 2f, 2f * r, 2f, P.TipTitle);
			Ui.Flat(_overlay, c.x - r, c.y - r, 2f, 2f * r, P.TipTitle);
			Ui.Flat(_overlay, c.x + r - 2f, c.y - r, 2f, 2f * r, P.TipTitle);
		}
		if (IsHub(b))
		{
			var ring = m + 22f;
			Ui.Centered(_overlay, P.SpritePanelRing, c.x, c.y, ring, ring, Color.clear).color = L.HubRing;
		}
		var back = Ui.Centered(_overlay, P.SpriteCellBack, c.x, c.y, m, m, new Color(0.3f, 0.27f, 0.22f, 1f));
		var icon = Ui.BuildingIcon(b);
		if (icon != null)
			Ui.SpriteImage(_overlay, icon, c.x - m / 2f + 4f, c.y - m / 2f + 4f, m - 8f, m - 8f);
		Ui.Centered(_overlay, P.SpriteCellFrame, c.x, c.y, m + 6f, m + 6f, new Color(0.7f, 0.58f, 0.3f, 0.6f));
		Markers.Add((back.rectTransform, b.ObjectKey));
		// Source colour dot (top-left), as the colour of every route that starts here.
		var dot = Mathf.Max(9f, m * 0.26f);
		var colour = L.SourceColour(SourceIndex(b.ObjectKey));
		Ui.Flat(_overlay, c.x - m / 2f - dot / 2f - 1f, c.y - m / 2f - dot / 2f - 1f, dot + 2f, dot + 2f, new Color(0.03f, 0.04f, 0.07f, 1f));
		var knob = Ui.Sprite("Knob");
		if (knob != null)
			Ui.SpriteImage(_overlay, knob, c.x - m / 2f - dot / 2f, c.y - m / 2f - dot / 2f, dot, dot).color = colour;
		else
			Ui.Flat(_overlay, c.x - m / 2f - dot / 2f, c.y - m / 2f - dot / 2f, dot, dot, colour);
		// Active enhancement badge (bottom-right) with its built level, as the mockup.
		if (!string.IsNullOrEmpty(b.ActiveEnhancementId))
		{
			var bs = Mathf.Clamp(m * 0.5f, 16f, 26f);
			var bx = c.x + m / 2f - 4f;
			var by = c.y + m / 2f - 6f;
			Ui.Centered(_overlay, P.SpriteCellBack, bx, by, bs + 4f, bs + 4f, new Color(0.2f, 0.18f, 0.15f, 1f));
			var enh = Ui.EnhancementIcon(b.ActiveEnhancementId, null);
			if (enh != null)
				Ui.SpriteImage(_overlay, enh, bx - bs / 2f, by - bs / 2f, bs, bs);
			var lv = BuiltLevel(b, b.ActiveEnhancementId);
			if (lv > 0)
			{
				var ls = Mathf.Clamp(bs * 0.78f, 14f, 20f);
				var lx = bx + bs / 2f;
				var ly = by - bs / 2f;
				Ui.Centered(_overlay, P.SpriteTierBadge, lx, ly, ls, ls, new Color(0.8f, 0.74f, 0.58f, 1f));
				Ui.Text(_overlay, P.FontBook, ls * 0.66f, lv.ToString(), lx - ls / 2f, ly - ls / 2f, ls, ls, P.Ink, TextAlignmentOptions.Center);
			}
		}
		// Upgrade Center badge (top-right) on visited buildings.
		if (b.UpgradeCenterLevel > 0)
		{
			const float bw = 40f, bh = 18f;
			Ui.Flat(_overlay, c.x + m / 2f - 12f, c.y - m / 2f - 10f, bw, bh, L.Plate);
			Ui.Text(_overlay, P.FontMedium, 13f, (b.ViaCommandCenter ? "CC " : "UC ") + b.UpgradeCenterLevel, c.x + m / 2f - 12f, c.y - m / 2f - 10f, bw, bh, b.ViaCommandCenter ? L.CommandCenter : P.TipTitle, TextAlignmentOptions.Center);
		}
		else if ((b.Built?.Count ?? 0) == 0)
		{
			// Unvisited: amber "!" where the Upgrade Center badge goes.
			Ui.Flat(_overlay, c.x + m / 2f - 10f, c.y - m / 2f - 10f, 18f, 18f, L.Unvisited);
			Ui.Text(_overlay, P.FontBook, 14f, "!", c.x + m / 2f - 10f, c.y - m / 2f - 10f, 18f, 18f, P.Ink, TextAlignmentOptions.Center);
		}
		if (UnderConstruction(b))
		{
			const float pw = 62f, ph = 16f;
			Ui.Flat(_overlay, c.x - m / 2f - 6f, c.y + m / 2f - 8f, pw, ph, L.Plate);
			Ui.Text(_overlay, P.FontMedium, 11f, "Tomorrow", c.x - m / 2f - 6f, c.y + m / 2f - 8f, pw, ph, P.TipWarn, TextAlignmentOptions.Center);
		}
		Placed.Add(new Rect(c.x - m / 2f - 8f, c.y - m / 2f - 12f, m + 38f, m + 20f));
	}

	/// <summary>Logistics Hub / Rail Station: the mockup's pale hub ring around the marker.</summary>
	private static bool IsHub(LogisticsBuildingView b) =>
		b?.ActiveEnhancementId != null && (b.ActiveEnhancementId == L.HubEnhancementId || b.ActiveEnhancementId == L.RailStationEnhancementId);

	/// <summary>The town's faction banner (custom-faction icon registry); a "T" ring when it does not resolve.</summary>
	private static void TownMarker(long key, Vector2 c, float size)
	{
		Sprite banner = null;
		if (_net.TownFactions != null && _net.TownFactions.TryGetValue(key, out var faction) && !string.IsNullOrEmpty(faction))
		{
			if (!(Homm3CustomUiIconHook.TryResolveSprite(faction + L.FactionBannerSuffix, out banner) && banner))
				banner = null;
		}
		if (banner == null)
		{
			RingMarker(c, size, "T", new Color(0.36f, 0.27f, 0.12f, 1f));
			return;
		}
		Ui.SpriteImage(_overlay, banner, c.x - size / 2f, c.y - size / 2f, size, size);
		Placed.Add(new Rect(c.x - size / 2f, c.y - size / 2f, size, size));
	}

	/// <summary>The hero's portrait in a round mask inside the panel ring; an "H" ring when the portrait does not resolve.</summary>
	private static void HeroMarker(long key, Vector2 c, float size)
	{
		Sprite portrait = null;
		if (_net.HeroSids != null && _net.HeroSids.TryGetValue(key, out var sid) && !string.IsNullOrEmpty(sid))
		{
			if (!(Homm3HeroPortraitHook.TryGetHeroPortraitSprite(sid, out portrait) && portrait))
				portrait = null;
		}
		var knob = Ui.Sprite("Knob");
		if (portrait == null || knob == null)
		{
			RingMarker(c, size, "H", new Color(0.16f, 0.22f, 0.4f, 1f));
			return;
		}
		var inner = size - 6f;
		var disc = Ui.SpriteImage(_overlay, knob, c.x - inner / 2f, c.y - inner / 2f, inner, inner);
		disc.color = new Color(0.08f, 0.1f, 0.16f, 1f);
		var mask = disc.gameObject.AddComponent<Mask>();
		if (mask != null)
			mask.showMaskGraphic = true;
		var face = Ui.SpriteImage(disc.rectTransform, portrait, 0f, 0f, inner, inner, false);
		face.raycastTarget = false;
		Ui.Centered(_overlay, P.SpritePanelRing, c.x, c.y, size + 6f, size + 6f, Color.clear);
		Placed.Add(new Rect(c.x - size / 2f, c.y - size / 2f, size, size));
	}

	private static void RingMarker(Vector2 c, float size, string glyph, Color fill)
	{
		var knob = Ui.Sprite("Knob");
		if (knob != null)
			Ui.SpriteImage(_overlay, knob, c.x - size / 2f + 3f, c.y - size / 2f + 3f, size - 6f, size - 6f).color = fill;
		else
			Ui.Flat(_overlay, c.x - size / 2f + 3f, c.y - size / 2f + 3f, size - 6f, size - 6f, fill);
		Ui.Text(_overlay, P.FontBook, size * 0.42f, glyph, c.x - size / 2f, c.y - size / 2f, size, size, P.TipTitle, TextAlignmentOptions.Center);
		Ui.Centered(_overlay, P.SpritePanelRing, c.x, c.y, size, size, Color.clear);
		Placed.Add(new Rect(c.x - size / 2f, c.y - size / 2f, size, size));
	}

	/// <summary>
	/// A dark label plate near a point: the first of below / above / right / left (at growing gaps) that is clear of
	/// everything placed so far; when nothing is free, straight below.
	/// </summary>
	private static Rect Plate(Vector2 at, float gap, string[] lines, Color[] colours, float[] sizes, bool centred)
	{
		var tw = 0f;
		for (var i = 0; i < lines.Length; i++)
			tw = Math.Max(tw, Ui.TextWidth(lines[i], sizes[i]));
		var pw = tw + 14f;
		var ph = L.LabelLine * lines.Length + 4f;
		var chosen = new Rect(at.x - pw / 2f, at.y + gap, pw, ph);
		var found = false;
		foreach (var extra in L.LabelGaps)
		{
			var g = gap + extra;
			var candidates = new[]
			{
				new Rect(at.x - pw / 2f, at.y + g, pw, ph),
				new Rect(at.x - pw / 2f, at.y - g - ph, pw, ph),
				new Rect(at.x + g, at.y - ph / 2f, pw, ph),
				new Rect(at.x - g - pw, at.y - ph / 2f, pw, ph),
				new Rect(at.x + g, at.y + g * 0.6f, pw, ph),
				new Rect(at.x + g, at.y - g * 0.6f - ph, pw, ph),
				new Rect(at.x - g - pw, at.y + g * 0.6f, pw, ph),
				new Rect(at.x - g - pw, at.y - g * 0.6f - ph, pw, ph),
			};
			foreach (var candidate in candidates)
			{
				var clear = candidate.xMin >= 0f && candidate.yMin >= 0f && candidate.xMax <= _mapW * _tile && candidate.yMax <= _mapH * _tile;
				for (var i = 0; clear && i < Placed.Count; i++)
					clear = !candidate.Overlaps(Placed[i]);
				if (!clear)
					continue;
				chosen = candidate;
				found = true;
				break;
			}
			if (found)
				break;
		}
		Placed.Add(chosen);
		Ui.Flat(_overlay, chosen.x, chosen.y, pw, ph, L.Plate);
		for (var i = 0; i < lines.Length; i++)
		{
			// The text box is wider than the plate so a slightly low width estimate never shortens the label.
			if (centred)
				Ui.Text(_overlay, P.FontMedium, sizes[i], lines[i], chosen.x - 30f, chosen.y + 2f + i * L.LabelLine, pw + 60f, L.LabelLine, colours[i], TextAlignmentOptions.Center);
			else
				Ui.Text(_overlay, P.FontMedium, sizes[i], lines[i], chosen.x + 7f, chosen.y + 2f + i * L.LabelLine, pw + 40f, L.LabelLine, colours[i]);
		}
		return chosen;
	}

	// ---------------------------------------------------------------- build: selected-building card (window space)

	private static bool RailNetworkActive(LogisticsBuildingView b)
	{
		var id = b?.ActiveEnhancementId;
		return b != null && b.Kind == LogisticsBuildingKind.Dwelling && !string.IsNullOrEmpty(b.UnitSid) && id != null
			&& id.IndexOf("rail", StringComparison.OrdinalIgnoreCase) >= 0 && id.IndexOf("station", StringComparison.OrdinalIgnoreCase) < 0;
	}

	/// <summary>Towns and heroes the selected dwelling's routes reach (CORE decides which of them a hire may use).</summary>
	private static List<(string Kind, long Key, string Name)> HireTargets(LogisticsBuildingView b)
	{
		var list = new List<(string, long, string)>();
		foreach (var r in Routes())
		{
			if (r == null || r.Cut || r.NoPath || r.FromKey != b.ObjectKey || r.ToKind != "town" && r.ToKind != "hero")
				continue;
			list.Add((r.ToKind, r.ToKey, (r.ToKind == "town" ? "Town: " : "Hero: ") + TargetName(r.ToKind, r.ToKey)));
		}
		return list;
	}

	private static void BuildCard()
	{
		CardButtons.Clear();
		Tips.Clear();
		HideTip();
		_cardRect = null;
		if (_cardRoot == null)
			return;
		Ui.ClearChildren(_cardRoot);
		if (_statusText != null)
			_statusText.text = _status ?? "";
		BuildPanel();
		var b = _hasSelection ? Building(_selectedKey) : null;
		if (b == null)
		{
			const float hw = 330f, hh = 34f;
			var hx = L.MapX + L.MapWidth - 14f - hw;
			var hy = L.MapY + L.MapHeight - 14f - hh;
			Ui.Flat(_cardRoot, hx, hy, hw, hh, L.Plate);
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Click a building (or press Tab) to manage it", hx, hy, hw, hh, P.TipNote, TextAlignmentOptions.Center);
			return;
		}
		var hire = RailNetworkActive(b);
		if (_tab == 2 && !hire)
			_tab = 0;
		var built = b.Built?.Count ?? 0;
		var options = _remote?.Options?.Count ?? 0;
		var pendingSwitch = b.PendingActiveId != null;
		var rowH = pendingSwitch ? L.CardRowPending : L.CardRow;
		float cw, body;
		switch (_tab)
		{
			case 1:
				cw = L.RemoteCardWidth;
				body = b.UpgradeCenterLevel <= 0 || _remote == null ? 64f : 52f + options * (L.RemoteRow + 4f) + 30f;
				break;
			case 2:
				cw = L.RemoteCardWidth;
				body = HireBodyHeight(b, cw - 36f);
				break;
			default:
				cw = hire ? L.RemoteCardWidth : L.CardWidth;
				body = built == 0 ? 64f : built * (rowH + 6f) + 2f * L.CardNote + 8f;
				break;
		}
		var h = L.CardHeader + L.CardTabs + 8f + body + 14f;
		var x0 = L.MapX + L.MapWidth - 14f - cw;
		var y0 = L.MapY + L.MapHeight - 14f - h;
		_cardX0 = x0;
		var backing = Ui.Flat(_cardRoot, x0, y0, cw, h, new Color(0.05f, 0.07f, 0.15f, 0.96f));
		_cardRect = backing.rectTransform;
		Ui.Sliced(_cardRoot, P.SpritePanelBody, x0, y0 + L.CardHeader - 12f, cw, h - L.CardHeader + 12f, P.PanelSliceMultiplier, Color.clear);
		Ui.Sliced(_cardRoot, P.SpritePanelHeader, x0, y0, cw, L.CardHeader, P.PanelSliceMultiplier, Color.clear);

		// Header: icon, name, the building's Upgrade Center.
		const float ring = 64f, ricon = 46f;
		var rcx = x0 + 18f + ring / 2f;
		var rcy = y0 + L.CardHeader / 2f;
		var icon = Ui.BuildingIcon(b);
		if (icon != null)
			Ui.SpriteImage(_cardRoot, icon, rcx - ricon / 2f, rcy - ricon / 2f, ricon, ricon);
		Ui.Centered(_cardRoot, P.SpritePanelRing, rcx, rcy, ring, ring, Color.clear);
		var tx = x0 + 18f + ring + 12f;
		var tw = cw - (tx - x0) - 16f;
		Ui.Text(_cardRoot, P.FontBook, P.SizeSubHeader, b.DisplayName ?? "Building", tx, y0 + 10f, tw, 28f, P.TipTitle);
		BuildCardHeaderExtras(b, x0, cw, tx, tw, y0);

		// Tabs.
		var ix = x0 + 18f;
		var iw = cw - 36f;
		var ty = y0 + L.CardHeader + 2f;
		var dwelling = b.Kind == LogisticsBuildingKind.Dwelling;
		var names = hire || dwelling ? new[] { "Switch active (1)", "Remote build (2)", "Hire (3)" } : new[] { "Switch active (1)", "Remote build (2)" };
		var tabW = (iw - 6f * (names.Length - 1)) / names.Length;
		for (var j = 0; j < names.Length; j++)
		{
			var tab = j;
			if (j == 2 && !hire)
			{
				// Hire greyed with its reason (item 14).
				var grey = Ui.Image(_cardRoot, Ui.SpriteTab, ix + j * (tabW + 6f), ty, tabW, L.CardTabs - 6f, new Color(0.08f, 0.09f, 0.12f, 1f));
				grey.color = new Color(0.55f, 0.55f, 0.55f, 0.7f);
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, names[j], ix + j * (tabW + 6f), ty, tabW, L.CardTabs - 6f, P.ButtonTextDisabled, TextAlignmentOptions.Center);
				AddTip(grey.rectTransform, "Hire (Rail Network)", new[] { "Hire needs the Rail Network as this dwelling's active enhancement.", "Build it under Remote build, then switch to it (takes effect tomorrow)." }, -1);
				continue;
			}
			Ui.Tab(_cardRoot, CardButtons, names[j], ix + j * (tabW + 6f), ty, tabW, L.CardTabs - 6f, j == _tab, () =>
			{
				_tab = tab;
				_status = null;
				BuildCard();
			});
		}
		var y = ty + L.CardTabs + 2f;
		switch (_tab)
		{
			case 1:
				BuildRemoteTab(b, ix, y, iw);
				break;
			case 2:
				BuildHireTab(b, ix, y, iw);
				break;
			default:
				BuildActiveTab(b, ix, y, iw, rowH);
				break;
		}
	}

	/// <summary>"Active enhancement": the built enhancements, one active; a click switches (once a week, applied next day).</summary>
	private static void BuildActiveTab(LogisticsBuildingView b, float ix, float y, float iw, float rowH)
	{
		if (b.Built == null || b.Built.Count == 0)
		{
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "No enhancement built yet.", ix, y + 6f, iw, 24f, P.TipBody, TextAlignmentOptions.Center);
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "A hero with the skill builds on site.", ix, y + 30f, iw, 24f, P.TipNote, TextAlignmentOptions.Center);
			return;
		}
		var pending = b.PendingActiveId;
		var canSwitch = pending == null && !b.SwitchUsedThisWeek;
		foreach (var e in b.Built)
		{
			if (e == null)
				continue;
			var active = e.Id == b.ActiveEnhancementId;
			var next = e.Id == pending;
			var row = Ui.Sliced(_cardRoot, active || next ? Ui.SpriteRowSelected : Ui.SpriteRow, ix, y, iw, rowH, 1f, active ? new Color(0.14f, 0.22f, 0.36f, 1f) : new Color(0.09f, 0.12f, 0.19f, 1f));
			AddEnhancementTip(row.rectTransform, b, e.Id, EnhancementName(b, e.Id), e.Level);
			var replaces = OptionReplaces(b, e.Id);
			var switchId = e.Id;
			var switchLevel = e.Level;
			var selectedKey = b.ObjectKey;
			AugmentTip(row.rectTransform, EnhancementName(b, e.Id), new[] { "", (active ? "Now: " : "When active: ") + (e.EffectText ?? "no numbers available"), Tag(replaces) },
				active || !canSwitch ? null : () => Concat(new[] { "", "If you switch to it (takes effect tomorrow):" }, PreviewOf(selectedKey, switchId, switchLevel)));
			var cy = y + rowH / 2f;
			// Radio: ring, filled green for the active one, amber for the one that takes over tomorrow.
			Ui.Flat(_cardRoot, ix + 12f, cy - 9f, 18f, 18f, new Color(0.75f, 0.72f, 0.62f, 1f));
			Ui.Flat(_cardRoot, ix + 14f, cy - 7f, 14f, 14f, new Color(0.06f, 0.08f, 0.14f, 1f));
			if (active || next)
				Ui.Flat(_cardRoot, ix + 17f, cy - 4f, 8f, 8f, active ? P.CostOk : P.TipWarn);
			var icon = Ui.EnhancementIcon(e.Id, null);
			if (icon != null)
				Ui.SpriteImage(_cardRoot, icon, ix + 40f, cy - 15f, 30f, 30f);
			var name = EnhancementName(b, e.Id);
			var twoLine = pending != null && (active || next);
			Ui.Text(_cardRoot, P.FontBook, P.SizeMain, name, ix + 80f, y + 4f, iw - 260f, 26f, active ? P.TipTitle : P.ButtonText);
			var powered = active && b.ActivePoweredLevel > e.Level ? " (powered " + b.ActivePoweredLevel + ")" : "";
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Level " + e.Level + powered, ix + iw - 180f, y + 5f, 120f, 24f, P.TipNote);
			Ui.Text(_cardRoot, P.FontMedium, 13f, (FirstClause(e.EffectText) ?? "") + "  \u00b7  " + Tag(replaces), ix + 80f, y + 30f, iw - 90f, 20f, TagColour(replaces));
			if (twoLine)
				Ui.Text(_cardRoot, P.FontMedium, 14f, active ? "Active until end of day" : "Active tomorrow", ix + 80f, y + 49f, iw - 100f, 20f, active ? P.TipNote : P.TipWarn);
			else if (active)
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Active", ix + iw - 90f, y + 5f, 80f, 24f, P.CostOk, TextAlignmentOptions.Right);
			if (!active && canSwitch)
			{
				var id = e.Id;
				CardButtons.Add(new Ui.Clickable
				{
					Rect = row.rectTransform, Image = row, Normal = Ui.Sprite(Ui.SpriteRow), Hover = Ui.Sprite(Ui.SpriteRowSelected),
					Click = () => Run("set active " + id, () => (Homm3FactoryLogistics.TrySetActive(_selectedKey, id, out var f), f)),
				});
			}
			y += rowH + 6f;
		}
		string first, second;
		Color firstColour, secondColour;
		if (pending != null)
		{
			(first, firstColour) = ("Switch applies at the start of tomorrow", P.TipWarn);
			(second, secondColour) = ("Next switch: start of next week", P.TipNote);
		}
		else if (b.SwitchUsedThisWeek)
		{
			(first, firstColour) = ("Switch used this week", P.TipWarn);
			(second, secondColour) = ("Next switch: start of next week", P.TipWarn);
		}
		else
		{
			(first, firstColour) = (b.Built.Count > 1 ? "1 switch left this week" : "Only one enhancement is built", P.TipBody);
			(second, secondColour) = (b.Built.Count > 1 ? "Click a row to switch (takes effect tomorrow)." : "Build more on site or under Remote build.", P.TipNote);
		}
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, first, ix, y + 2f, iw, L.CardNote, firstColour, TextAlignmentOptions.Center);
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, second, ix, y + 2f + L.CardNote, iw, L.CardNote, secondColour, TextAlignmentOptions.Center);
	}

	/// <summary>"Build / Upgrade": this building's own enhancements, ordered remotely up to its Upgrade Center level.</summary>
	private static void BuildRemoteTab(LogisticsBuildingView b, float ix, float y, float iw)
	{
		if (b.UpgradeCenterLevel <= 0)
		{
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "No Upgrade Center yet: a Logistics Network hero must visit (or a Mobile Command Center hero be in range)", ix, y + 6f, iw, 48f, P.TipWarn, TextAlignmentOptions.Center, true);
			return;
		}
		if (_remote?.Options == null)
		{
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, _remoteFail ?? "Remote building is not available here.", ix, y + 18f, iw, 24f, P.TipWarn, TextAlignmentOptions.Center);
			return;
		}
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, (b.ViaCommandCenter ? "Command Center " : "Upgrade Center ") + b.UpgradeCenterLevel + ": remote builds up to level " + b.UpgradeCenterLevel + ",", ix, y, iw, 22f, P.TipBody, TextAlignmentOptions.Center);
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "same cost, takes effect tomorrow", ix, y + 21f, iw, 22f, P.TipBody, TextAlignmentOptions.Center);
		y += 52f;
		var recommended = RecommendationOf(b.ObjectKey);
		foreach (var o in _remote.Options)
		{
			if (o == null)
				continue;
			var pendingLevel = 0;
			if (_remote.Built != null)
			{
				foreach (var e in _remote.Built)
				{
					if (e != null && e.Id == o.Id)
						pendingLevel = e.PendingLevel;
				}
			}
			var active = o.BuiltLevel > 0 && o.Id == _remote.ActiveEnhancementId;
			var optionRow = Ui.Sliced(_cardRoot, pendingLevel > 0 ? Ui.SpriteRowSelected : Ui.SpriteRow, ix, y, iw, L.RemoteRow, 1f, pendingLevel > 0 ? new Color(0.14f, 0.22f, 0.36f, 1f) : new Color(0.09f, 0.12f, 0.19f, 1f));
			AddTip(optionRow.rectTransform, o.Name ?? o.Id, LevelLinesText(o.LevelLines), o.BuiltLevel - 1);
			var isRecommended = recommended.Id == o.Id;
			var optionId = o.Id;
			var previewLevel = Math.Min(3, o.BuiltLevel + 1);
			var optionKey = b.ObjectKey;
			AugmentTip(optionRow.rectTransform, o.Name ?? o.Id,
				new[] { "", "At level " + o.EffectLevel + " here: " + (o.EffectText ?? "no numbers available"), Tag(o.ReplacesOutput), isRecommended ? "Recommended: " + recommended.Reason : null },
				o.BuiltLevel >= 3 ? null : () => Concat(new[] { "", "If active at level " + previewLevel + " (tomorrow):" }, PreviewOf(optionKey, optionId, previewLevel)));
			if (isRecommended)
				Ui.Flat(_cardRoot, ix, y, 4f, L.RemoteRow, P.CostOk);
			var icon = Ui.EnhancementIcon(o.Id, o.Name);
			if (icon != null)
				Ui.SpriteImage(_cardRoot, icon, ix + 8f, y + 8f, L.RemoteRow - 16f, L.RemoteRow - 16f);
			var nx = ix + L.RemoteRow + 4f;
			Ui.Text(_cardRoot, P.FontBook, P.SizeMain, o.Name ?? o.Id, nx, y + 4f, 200f, 26f, P.ButtonText);
			var next = o.BuiltLevel + 1;
			var right = ix + iw - 10f;
			if (pendingLevel > 0)
			{
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Under construction - active tomorrow", nx, y + 30f, iw - L.RemoteRow - 14f, 24f, P.TipWarn);
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Level " + pendingLevel + " ordered", right - 170f, y + 5f, 170f, 24f, P.TipWarn, TextAlignmentOptions.Right);
			}
			else
			{
				var state = (isRecommended ? "Recommended \u00b7 " : "") + (o.BuiltLevel > 0 ? "Level " + o.BuiltLevel + (active ? " active" : " built") : "Not built")
							+ " \u00b7 " + Tag(o.ReplacesOutput) + (o.EffectText != null ? " \u00b7 " + FirstClause(o.EffectText) : "");
				Ui.Text(_cardRoot, P.FontMedium, 13f, state, nx, y + 26f, ix + iw - 240f - nx, 34f, active ? P.CostOk : isRecommended ? P.TipTitle : P.TipNote, TextAlignmentOptions.TopLeft, true);
				if (next > 3)
					Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Fully upgraded", right - 200f, y + 18f, 200f, 24f, P.CostOk, TextAlignmentOptions.Right);
				else if (next > o.MaxLevelNow)
					Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Level " + next + " needs Upgrade Center " + next, right - 250f, y + 30f, 250f, 24f, P.TipWarn, TextAlignmentOptions.Right);
				else
				{
					Ui.Cost(_cardRoot, o.NextCost, right - 220f, y + 15f, 220f, 22f, P.SizeSmall, o.CanAfford ? P.TipBody : P.CostBad);
					var id = o.Id;
					var enabled = o.BlockReason == null && o.CanAfford;
					Ui.Button(_cardRoot, CardButtons, o.BuiltLevel > 0 ? "Upgrade to " + next : "Build level 1", right - 150f, y + 31f, 150f, 24f, enabled, false,
						() => Run("remote build " + id, () => (Homm3FactoryLogistics.TryBuild(_selectedKey, id, null, out var f), f)), P.SizeSmall);
					if (!enabled && o.BlockReason != null && _status == null && _statusText != null)
						_statusText.text = o.Name + ": " + o.BlockReason;
				}
			}
			y += L.RemoteRow + 4f;
		}
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Same cost as on site. A hero on site builds immediately. Hover a row for its numbers.", ix, y + 2f, iw, 24f, P.TipNote, TextAlignmentOptions.Center);
	}

	/// <summary>
	/// "Hire" (dwelling with an active Rail Network), with what the native hire window offers: the unit's card (portrait,
	/// tier, stats, abilities with their text on hover), the stock left, price per unit and in total, a Max button (the
	/// most the side can pay for out of the stock) and a Hire button that greys out when nothing can be hired.
	/// </summary>
	private static void BuildHireTab(LogisticsBuildingView b, float ix, float y, float iw)
	{
		var targets = HireTargets(b);
		var stock = b.UpgradedStock ?? Array.Empty<LogisticsUpgradedStockView>();
		_hireUnit = ((_hireUnit % (stock.Count + 1)) + stock.Count + 1) % (stock.Count + 1);
		var upgraded = _hireUnit > 0 ? stock[_hireUnit - 1] : null;
		var unitSid = upgraded?.UnitSid ?? b.UnitSid;
		var unitName = Homm3UnitDisplayNames.Resolve(unitSid);
		var mid = ix + iw / 2f;
		Ui.Text(_cardRoot, P.FontBook, P.SizeMain, "Hire " + unitName + " through the Rail Network", ix, y + 2f, iw, 26f, P.TipTitle, TextAlignmentOptions.Center);
		y += L.HireTitle;
		if (stock.Count > 0)
		{
			// Unit: [<] dwelling stock / upgraded stock (Arcane Manufactory) [>].
			var uy = y + 14f;
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Unit", ix + 10f, uy - 13f, 90f, 26f, P.TipNote);
			Step("<", mid - 130f, uy, () => { _hireUnit--; _hireCount = 1; });
			Step(">", mid + 100f, uy, () => { _hireUnit++; _hireCount = 1; });
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, upgraded == null ? "Dwelling stock" : "Upgraded stock", mid - 96f, uy - 13f, 192f, 26f,
				upgraded == null ? P.TipBody : P.TipTitle, TextAlignmentOptions.Center);
			y += L.HireSelector;
		}

		// Unit card.
		var unit = Homm3ConfluxFusionGlossary.DescribeUnit(unitSid);
		var portrait = Ui.UnitPortrait(unitSid);
		Ui.Centered(_cardRoot, P.SpriteCellBack, ix + L.HirePortrait / 2f, y + L.HirePortrait / 2f, L.HirePortrait, L.HirePortrait, new Color(0.2f, 0.18f, 0.15f, 1f));
		if (portrait != null)
			Ui.SpriteImage(_cardRoot, portrait, ix + 4f, y + 4f, L.HirePortrait - 8f, L.HirePortrait - 8f);
		Ui.Centered(_cardRoot, P.SpriteCellFrame, ix + L.HirePortrait / 2f, y + L.HirePortrait / 2f, L.HirePortrait + 6f, L.HirePortrait + 6f, Color.clear);
		var sx = ix + L.HirePortrait + 12f;
		var sw = iw - L.HirePortrait - 12f;
		var tier = b.UnitTier > 0 ? "Tier " + b.UnitTier + (upgraded != null ? ", upgraded" : "") : upgraded != null ? "Upgraded" : "";
		Ui.Text(_cardRoot, P.FontBook, P.SizeMain, unit?.Name ?? unitName, sx, y - 2f, sw - 110f, 26f, P.TipTitle);
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, tier, sx + sw - 140f, y, 140f, 24f, P.TipNote, TextAlignmentOptions.Right);
		if (unit != null && unit.HasStats)
		{
			var cells = new (string Label, string Value)[]
			{
				("Attack", unit.Attack.ToString()), ("Defence", unit.Defence.ToString()), ("Damage", unit.DamageMin + "-" + unit.DamageMax),
				("Health", unit.Hp.ToString()), ("Speed", unit.Speed.ToString()), ("Initiative", unit.Initiative.ToString()),
			};
			var colW = sw / 3f;
			for (var i = 0; i < cells.Length; i++)
			{
				var cx = sx + (i % 3) * colW;
				var cy = y + 28f + (i / 3) * 24f;
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, cells[i].Label, cx, cy, colW * 0.62f, 22f, P.TipNote);
				Ui.Text(_cardRoot, P.FontBook, P.SizeSmall, cells[i].Value, cx + colW * 0.58f, cy, colW * 0.42f, 22f, P.TipBody);
			}
			var traits = (unit.Ranged ? "Ranged" : "") + (unit.Ranged && unit.Flying ? ", " : "") + (unit.Flying ? "Flying" : "");
			if (traits.Length > 0)
				Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, traits, sx, y + 78f, sw, 22f, P.TipNote);
		}
		else
		{
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Unit stats unavailable", sx, y + 30f, sw, 22f, P.TipWarn);
		}
		y += L.HireUnitBlock;

		// Abilities: one chip each, the text on hover.
		var chips = ChipLayout(unit, iw);
		if (chips.Count > 0)
		{
			foreach (var (card, cx, cy, cwid) in chips)
			{
				var plate = Ui.Flat(_cardRoot, ix + cx, y + cy, cwid, L.ChipHeight, card.Active ? new Color(0.16f, 0.2f, 0.32f, 1f) : new Color(0.11f, 0.14f, 0.22f, 1f));
				Ui.Text(_cardRoot, P.FontMedium, L.ChipText, card.Name, ix + cx, y + cy, cwid, L.ChipHeight, card.Active ? P.TipTitle : P.TipBody, TextAlignmentOptions.Center);
				AddTip(plate.rectTransform, card.Name, new[] { string.IsNullOrEmpty(card.Text) ? "(no description)" : card.Text }, -1);
			}
			y += ChipRowsHeight(chips) + 6f;
		}

		// Stock and price.
		if (!Homm3FactoryLogistics.TryGetHireInfo(b.ObjectKey, unitSid, upgraded != null, out var info, out var infoFail))
			info = null;
		var available = info?.Available ?? 0;
		var cap = Math.Max(1, available);
		_hireCount = Math.Max(1, Math.Min(_hireCount, cap));
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, info == null ? "Stock unreadable" : "Available: " + Ui.N(available), ix + 10f, y + 2f, 180f, 24f,
			info == null || available == 0 ? P.CostBad : P.TipBody);
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Each", ix + iw - 250f, y + 2f, 50f, 24f, P.TipNote);
		if (info?.UnitCost != null)
			Ui.Cost(_cardRoot, info.UnitCost, ix + iw - 200f, y + 14f, 200f, 22f, P.SizeSmall, P.TipBody);
		y += L.HireRow;

		// Count: [-] n [+] [Max].
		var countY = y + 16f;
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Count", ix + 10f, countY - 13f, 90f, 26f, P.TipNote);
		Step("-", mid - 100f, countY, () => _hireCount = Math.Max(1, _hireCount - (ShiftHeld() ? 10 : 1)));
		Ui.Text(_cardRoot, P.FontBook, P.SizeSubHeader, Ui.N(_hireCount), mid - 60f, countY - 14f, 120f, 28f, P.TipBody, TextAlignmentOptions.Center);
		Step("+", mid + 70f, countY, () => _hireCount = Math.Min(cap, _hireCount + (ShiftHeld() ? 10 : 1)));
		var maxCount = info == null ? 0 : Math.Min(available, info.MaxAffordable);
		Ui.Button(_cardRoot, CardButtons, "Max", mid + 120f, countY - 15f, 80f, 30f, maxCount > 0, false, () =>
		{
			_hireCount = Math.Max(1, maxCount);
			BuildCard();
		}, P.SizeSmall);
		y += L.HireCountRow;

		// Target: [<] name [>].
		var targetY = y + 16f;
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Deliver to", ix + 10f, targetY - 13f, 100f, 26f, P.TipNote);
		(string Kind, long Key, string Name) target = default;
		if (targets.Count == 0)
		{
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "No town or hero in range", mid - 120f, targetY - 13f, 260f, 26f, P.TipWarn, TextAlignmentOptions.Center);
		}
		else
		{
			_hireTarget = ((_hireTarget % targets.Count) + targets.Count) % targets.Count;
			if (targets.Count > 1)
			{
				Step("<", mid - 130f, targetY, () => _hireTarget--);
				Step(">", mid + 100f, targetY, () => _hireTarget++);
			}
			target = targets[_hireTarget];
			Ui.Text(_cardRoot, P.FontMedium, P.SizeMain, target.Name, mid - 96f, targetY - 14f, 192f, 28f, P.TipBody, TextAlignmentOptions.Center);
			Ui.Text(_cardRoot, P.FontMedium, 13f, DeliveryLine(DeliveryOf(target.Kind, target.Key, unitSid), unitSid), ix + 10f, targetY + 16f, iw - 20f, 20f, P.TipNote, TextAlignmentOptions.Center);
		}
		y += L.HireCountRow + L.HireDelivery;

		// Total, then Hire (grey when nothing can be hired) with the reason.
		var count = _hireCount;
		var total = info?.PriceOf?.Invoke(count);
		var affordable = info != null && count <= info.MaxAffordable;
		Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, "Total", ix + iw - 250f, y + 2f, 50f, 24f, P.TipNote);
		if (total != null)
			Ui.Cost(_cardRoot, total, ix + iw - 200f, y + 14f, 200f, 22f, P.SizeSmall, affordable ? P.TipBody : P.CostBad);
		string reason = null;
		if (info == null)
			reason = infoFail ?? "Stock unreadable";
		else if (available <= 0)
			reason = "None available";
		else if (count > available)
			reason = "Only " + Ui.N(available) + " available";
		else if (!affordable)
			reason = info.MaxAffordable > 0 ? "Not enough resources (you can pay for " + Ui.N(info.MaxAffordable) + ")" : "Not enough resources";
		else if (targets.Count == 0)
			reason = "No delivery target in range";
		if (reason != null)
			Ui.Text(_cardRoot, P.FontMedium, P.SizeSmall, reason, ix + 10f, y + 2f, iw - 270f, 24f, P.CostBad);
		y += L.HireRow;
		var enabled = reason == null;
		if (upgraded != null)
			Ui.Button(_cardRoot, CardButtons, "Hire", mid - 90f, y + 4f, 180f, 34f, enabled, true,
				() => Run("remote upgraded hire " + count + "x " + unitSid + " -> " + target.Kind + " " + target.Key,
					() => (Homm3FactoryLogistics.TryRemoteHireUpgraded(b.ObjectKey, unitSid, count, target.Kind, target.Key, out var f), f)), P.SizeMain);
		else
			Ui.Button(_cardRoot, CardButtons, "Hire", mid - 90f, y + 4f, 180f, 34f, enabled, true,
				() => Run("remote hire " + count + "x " + b.UnitSid + " -> " + target.Kind + " " + target.Key,
					() => (Homm3FactoryLogistics.TryRemoteHire(b.ObjectKey, b.UnitSid, count, target.Kind, target.Key, out var f), f)), P.SizeMain);
	}

	/// <summary>The hire tab's height for <see cref="BuildCard"/>; mirrors <see cref="BuildHireTab"/>'s rows.</summary>
	private static float HireBodyHeight(LogisticsBuildingView b, float iw)
	{
		var stock = b.UpgradedStock ?? Array.Empty<LogisticsUpgradedStockView>();
		var index = ((_hireUnit % (stock.Count + 1)) + stock.Count + 1) % (stock.Count + 1);
		var sid = index > 0 ? stock[index - 1].UnitSid : b.UnitSid;
		var chips = ChipLayout(Homm3ConfluxFusionGlossary.DescribeUnit(sid), iw);
		return L.HireTitle + (stock.Count > 0 ? L.HireSelector : 0f) + L.HireUnitBlock + (chips.Count > 0 ? ChipRowsHeight(chips) + 6f : 0f)
		       + L.HireRow + 2f * L.HireCountRow + L.HireDelivery + L.HireRow + 44f;
	}

	/// <summary>Ability chips laid out left to right, wrapping at <paramref name="width"/>: (card, x, y, width) relative to the block.</summary>
	private static List<(Homm3ConfluxFusionGlossary.Card Card, float X, float Y, float W)> ChipLayout(Homm3ConfluxFusionGlossary.Entry unit, float width)
	{
		var list = new List<(Homm3ConfluxFusionGlossary.Card, float, float, float)>();
		if (unit?.Cards == null)
			return list;
		float x = 0f, y = 0f;
		foreach (var card in unit.Cards)
		{
			if (card == null || string.IsNullOrEmpty(card.Name))
				continue;
			var w = Math.Min(width, Ui.TextWidth(card.Name, L.ChipText) + 20f);
			if (x > 0f && x + w > width)
			{
				x = 0f;
				y += L.ChipHeight + 6f;
			}
			list.Add((card, x, y, w));
			x += w + 6f;
		}
		return list;
	}

	private static float ChipRowsHeight(List<(Homm3ConfluxFusionGlossary.Card Card, float X, float Y, float W)> chips) =>
		chips.Count == 0 ? 0f : chips[chips.Count - 1].Y + L.ChipHeight;

	// ---------------------------------------------------------------- hover tips

	private static void AddTip(RectTransform rect, string title, string[] lines, int highlight)
	{
		if (rect != null && (lines?.Length ?? 0) > 0)
			Tips.Add(new Tip { Rect = rect, Title = title, Lines = lines, Highlight = highlight });
	}

	private static string[] LevelLinesText(string[] lines)
	{
		if (lines == null || lines.Length == 0)
			return null;
		var text = new string[lines.Length];
		for (var i = 0; i < lines.Length; i++)
			text[i] = "Level " + (i + 1) + ": " + (lines[i] ?? "");
		return text;
	}

	/// <summary>An enhancement row's tip: what each level does (from the remote options, else the building's own), the built level lit.</summary>
	private static void AddEnhancementTip(RectTransform rect, LogisticsBuildingView b, string id, string name, int level)
	{
		string[] lines = null;
		foreach (var list in new[] { _remote?.Options, b?.Options })
		{
			if (list == null || lines != null)
				continue;
			foreach (var o in list)
			{
				if (o != null && o.Id == id)
				{
					lines = o.LevelLines;
					break;
				}
			}
		}
		AddTip(rect, name, LevelLinesText(lines), level - 1);
	}

	private static void UpdateTip(Vector2 mouse)
	{
		Tip over = null;
		for (var i = Tips.Count - 1; i >= 0 && over == null; i--)
		{
			if (Tips[i].Rect != null && Ui.Over(Tips[i].Rect, mouse))
				over = Tips[i];
		}
		for (var i = ChromeTips.Count - 1; i >= 0 && over == null; i--)
		{
			if (ChromeTips[i].Rect != null && Ui.Over(ChromeTips[i].Rect, mouse))
				over = ChromeTips[i];
		}
		if (over == _shownTip)
			return;
		HideTip();
		if (over == null || _window == null || !Ui.TryWindowPoint(_window, mouse, out var at))
			return;
		if (over.More != null && over.MoreCache == null)
		{
			try
			{
				over.MoreCache = over.More() ?? Array.Empty<string>();
			}
			catch (Exception ex)
			{
				over.MoreCache = new[] { "(details unavailable: " + ex.GetBaseException().Message + ")" };
			}
		}
		var all = over.MoreCache == null || over.MoreCache.Length == 0 ? over.Lines : Concat(over.Lines, over.MoreCache);
		_shownTip = over;
		_tipRoot = A.NewRect("Tip", _window);
		A.Stretch(_tipRoot);
		const float w = L.TipWidth, pad = 12f;
		var textW = w - 2f * pad;
		var rows = new float[all.Length];
		var h = pad + 26f + 4f;
		for (var i = 0; i < all.Length; i++)
		{
			var n = Math.Max(1, Mathf.CeilToInt(Ui.TextWidth(all[i], L.TipText) / textW));
			rows[i] = string.IsNullOrEmpty(all[i]) ? 8f : n * L.TipLine + 4f;
			h += rows[i];
		}
		h += pad - 4f;
		var x = over.NearMouse ? Mathf.Clamp(at.x + 18f, 8f, L.Width - w - 8f) : Mathf.Max(8f, _cardX0 - w - 10f);
		var y = over.NearMouse ? Mathf.Clamp(at.y + 18f, 8f, L.Height - h - 8f) : Mathf.Clamp(at.y - 20f, 8f, L.Height - h - 8f);
		Ui.Flat(_tipRoot, x - 1f, y - 1f, w + 2f, h + 2f, new Color(P.TipTitle.r, P.TipTitle.g, P.TipTitle.b, 0.55f));
		Ui.Flat(_tipRoot, x, y, w, h, new Color(0.03f, 0.04f, 0.08f, 0.97f));
		Ui.Text(_tipRoot, P.FontBook, P.SizeMain, over.Title ?? "", x + pad, y + pad - 2f, textW, 26f, P.TipTitle);
		var ly = y + pad + 30f;
		for (var i = 0; i < all.Length; i++)
		{
			Ui.Text(_tipRoot, P.FontMedium, L.TipText, all[i] ?? "", x + pad, ly, textW, rows[i], i == over.Highlight ? P.CostOk : P.TipBody, TextAlignmentOptions.TopLeft, true);
			ly += rows[i];
		}
	}

	private static bool OptionReplaces(LogisticsBuildingView b, string id)
	{
		foreach (var list in new[] { _remote?.Options, b?.Options })
		{
			if (list == null)
				continue;
			foreach (var o in list)
				if (o != null && o.Id == id)
					return o.ReplacesOutput;
		}
		return b != null && b.ActiveEnhancementId == id && b.ActiveReplacesOutput;
	}

	private static void HideTip()
	{
		_shownTip = null;
		if (_tipRoot == null)
			return;
		try
		{
			UnityObject.Destroy(_tipRoot.gameObject);
		}
		catch
		{
		}
		_tipRoot = null;
	}

	private static bool ShiftHeld() => Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);

	private static void Step(string glyph, float x, float cy, Action change)
	{
		const float s = 30f;
		var image = Ui.Image(_cardRoot, Ui.SpriteTab, x, cy - s / 2f, s, s, new Color(0.12f, 0.16f, 0.26f, 1f));
		Ui.Text(_cardRoot, P.FontBook, P.SizeSubHeader, glyph, x, cy - s / 2f, s, s, P.ButtonText, TextAlignmentOptions.Center);
		CardButtons.Add(new Ui.Clickable
		{
			Rect = image.rectTransform, Image = image, Normal = Ui.Sprite(Ui.SpriteTab), Hover = Ui.Sprite(Ui.SpriteTabHover),
			Click = () =>
			{
				change();
				BuildCard();
			},
		});
	}
}

/// <summary>
/// Geometry and colours of the Logistics Network viewer (window space: top-left origin, y down, 1920x1080 reference
/// canvas). Mirrors class Lay / the palette in tools/factory_logistics/network_viewer_mockup.py; keep the two in step.
/// </summary>
internal static class Homm3FactoryLogisticsViewerLayout
{
	internal const float Width = 1680f;
	internal const float Height = 1000f;
	internal const float MapX = 22f;
	internal const float MapY = 58f;
	internal const float MapWidth = 1636f;
	internal const float MapHeight = 806f;
	internal const float LegendTop = 870f;
	internal const float LegendHeight = 70f;
	internal const float StatusY = 946f;
	internal const float CloseSize = 44f;
	internal const float ZoomSize = 44f;
	internal const float DefaultTile = 26f;
	internal static readonly float[] ZoomSteps = { 8f, 11f, 15f, 20f, 26f, 34f, 44f };
	internal const int CellPixels = 16;
	internal const int GlowPixels = 8;          // glow texture pixels per tile (bilinear)
	internal const float GlowReach = 1.6f;      // tiles
	internal const float GlowTight = 0.13f;     // sigma, tiles (mockup halo layer)
	internal const float GlowTightGain = 0.40f;
	internal const float GlowWide = 0.45f;      // sigma, tiles (mockup wide layer)
	internal const float GlowWideGain = 0.13f;
	internal const float Marker = 52f;
	internal const float TownSize = 64f;
	internal const float HeroSize = 50f;
	internal const float LineWidth = 2.6f;
	internal const float BundleGap = 9f;
	internal const float BundleMaxWidth = 20f;
	internal const float ChevronSize = 5.5f;
	internal const float ChevronSpacing = 1.7f;   // tiles between chevrons (mockup: 44 px at 26 px tiles)
	internal const float CrestPeriod = 8.5f;      // tiles between pulse crests (mockup: 220 px)
	internal const float CrestSpeed = 4f;         // tiles per second: the bright crest outruns the chevrons
	internal const float ChevronSpeed = 1.6f;      // tiles per second
	internal const int MaxChevrons = 360;
	internal const int MaxChevronsPerRoute = 40;
	internal const float LabelSize = 15f;
	internal const float LabelLine = 20f;
	internal static readonly float[] LabelGaps = { 0f, 14f, 30f, 52f, 80f };
	internal const float CardWidth = 470f;
	internal const float RemoteCardWidth = 560f;
	internal const float CardHeader = 90f;
	internal const float CardTabs = 34f;
	internal const float CardRow = 54f;
	internal const float CardRowPending = 72f;
	internal const float CardNote = 26f;
	internal const float HireTitle = 32f;
	internal const float HireSelector = 36f;
	internal const float HirePortrait = 76f;
	internal const float HireUnitBlock = 104f;
	internal const float HireRow = 30f;
	internal const float HireCountRow = 40f;
	internal const float HireDelivery = 20f;
	internal const float ChipHeight = 26f;
	internal const float ChipText = 14f;
	internal const float TipWidth = 380f;
	internal const float TipText = 15f;
	internal const float TipLine = 20f;
	internal const float RemoteRow = 60f;

	internal static readonly Color Red = new(1f, 0.25f, 0.22f, 1f);
	internal static readonly Color Plate = new(0.04f, 0.05f, 0.09f, 0.88f);
	internal static readonly Color32 Water = new(40, 74, 108, 255);          // pre-dim, as the mockup
	internal static readonly Color32 Fog = new(9, 11, 18, 255);
	internal static readonly Color32 NoData = new(4, 5, 8, 255);
	internal static readonly Color32 Road = new(228, 210, 162, 255);         // road core, undimmed
	internal static readonly Color32 RoadEdge = new(26, 20, 14, 255);        // road outline, undimmed
	internal const float RoadEdgeRadius = 0.22f;  // of a tile
	internal const float RoadCoreRadius = 0.12f;
	internal static readonly Color HubRing = new(0.88f, 0.93f, 1f, 0.9f);
	internal static readonly Color CommandCenter = new(0.55f, 0.85f, 1f, 1f);
	internal static readonly Color Unvisited = new(0.95f, 0.7f, 0.25f, 1f);
	internal const string HubEnhancementId = "logistics_hub";
	internal const string RailStationEnhancementId = "rail_station";
	internal const string FactionBannerSuffix = "_faction_banner";

	/// <summary>Colour-blind-friendly neon hues, one per source building (red is reserved for cuts and blocking stacks).</summary>
	private static readonly Color[] Sources =
	{
		new(0.24f, 0.86f, 1f, 1f),      // cyan
		new(0.27f, 0.47f, 1f, 1f),      // blue
		new(0.24f, 0.9f, 0.59f, 1f),    // green
		new(1f, 0.67f, 0.16f, 1f),      // orange
		new(0.94f, 0.59f, 1f, 1f),      // pink
		new(1f, 0.88f, 0.24f, 1f),      // yellow
		new(0.62f, 0.45f, 1f, 1f),      // violet
		new(0.78f, 0.95f, 0.45f, 1f),   // lime
	};

	internal static Color SourceColour(int index) => Sources[(index % Sources.Length + Sources.Length) % Sources.Length];

	/// <summary>
	/// Strategic-view colour per MapData.tilesMap code, before the dim (<see cref="Strategic"/>): vanilla 1-7 as the mockup
	/// (tiles.json biomes), the HoMM3 custom biomes 8-30 from the mean of their own ground textures
	/// (homm3_runtime_assets/custom_biomes), unknown codes a neutral earth.
	/// </summary>
	internal static Color32 TerrainColour(byte terrain) => terrain switch
	{
		1 => new Color32(80, 108, 58, 255),     // grass
		2 => new Color32(156, 138, 96, 255),    // sand
		3 => new Color32(92, 84, 92, 255),      // deathland
		4 => new Color32(150, 160, 176, 255),   // snow
		5 => new Color32(132, 104, 56, 255),    // autumn
		6 => new Color32(104, 58, 46, 255),     // lava
		7 => new Color32(114, 94, 66, 255),     // dirt
		8 => new Color32(58, 92, 64, 255),      // swamp
		9 => new Color32(172, 180, 194, 255),   // tundra
		10 => new Color32(92, 112, 62, 255),    // hills
		11 => new Color32(146, 116, 88, 255),   // wasteland
		12 => new Color32(72, 112, 70, 255),    // tropical
		13 => new Color32(78, 128, 50, 255),    // greenlands
		14 => new Color32(80, 80, 86, 255),     // curselands
		15 => new Color32(98, 84, 68, 255),     // burrow
		16 => new Color32(86, 118, 60, 255),    // valleys
		17 => new Color32(100, 62, 54, 255),    // molten
		23 => new Color32(14, 14, 18, 255),     // void
		29 => new Color32(176, 146, 100, 255),  // foundry
		30 => new Color32(150, 170, 192, 255),  // permafrost
		_ => new Color32(112, 102, 86, 255),
	};

	/// <summary>The mockup's strategic dim: 22% toward grey, then x0.62, after a per-tile brightness factor.</summary>
	internal static Color32 Strategic(Color32 c, float k)
	{
		float r = c.r * k, g = c.g * k, b = c.b * k;
		var grey = (r + g + b) / 3f;
		return new Color32(Byte((r * 0.78f + grey * 0.22f) * 0.62f), Byte((g * 0.78f + grey * 0.22f) * 0.62f), Byte((b * 0.78f + grey * 0.22f) * 0.62f), 255);
	}

	/// <summary>Deterministic 0..1 per tile.</summary>
	internal static float Hash(int x, int y)
	{
		unchecked
		{
			var h = (uint)(x * 73856093) ^ (uint)(y * 19349663);
			h ^= h >> 13;
			h *= 0x5bd1e995;
			h ^= h >> 15;
			return (h & 0xFFFF) / 65535f;
		}
	}

	/// <summary>Per-tile brightness 0.94..1.06 (the mockup's tile variation).</summary>
	internal static float Jitter(int x, int y) => 0.94f + 0.12f * Hash(x + 7, y + 13);

	internal static Color32 Lighter(Color32 c, float k, int add) => new(Byte(c.r * k + add), Byte(c.g * k + add), Byte(c.b * k + add), 255);

	private static byte Byte(float v) => (byte)Math.Max(0f, Math.Min(255f, v));

	internal static Color32 Darker(Color32 c, float k) => new((byte)(c.r * k), (byte)(c.g * k), (byte)(c.b * k), 255);
}
