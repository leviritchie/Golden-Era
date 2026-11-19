using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Session.Battle;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.Rendering;

namespace OfflineUnlockMod;

/// <summary>
/// Fortress Predator Instinct hover line: while the cursor rests on a predator stack, a blood-red ribbon arcs from the
/// predator to its prey, settles into a slow floating wave, sheds drifting droplets, and rings both ends on the ground.
/// Approved look: mockup artifact "Predator Instinct Line" (2026-11-14).
///
/// Hover signal (research_b, static): the battle input controller sets HighlightFlags.Cursor (4) on the hovered unit's
/// drawer and keeps that drawer in a field that goes stale when the cursor leaves, so the flag is tested every frame.
/// Anchors: the drawer's BhUnitViewHelper.projectileEndPoint (chest bone on HoMM3 rigs), then shieldPoint, then the
/// visual renderers' bounds, then the movement root. Both ends are read every LateUpdate, so the line follows motion.
///
/// Rendering: one runtime ribbon Mesh per layer (soft wide glow + thin hot core with a scrolling bead texture), rebuilt
/// each frame camera-facing; procedural textures only; Hex/Particles made additive when the shader exposes the blend
/// properties, else Sprites/Default. Shadows off, transparent queue, layer copied from the predator's visual.
/// Visual-only: any failure hides the line and logs once. Proof tier: build; runtime look unproven until the owner tests.
/// </summary>
internal static class Homm3FortressPredatorLine
{
	private const int Segments = 40;
	private const float FadeIn = 0.08f;
	private const float Grow = 0.12f;
	private const float FadeOut = 0.15f;
	private const float GlowHalfWidth = 0.20f;
	private const float CoreHalfWidth = 0.045f;
	private const float WaveAmplitude = 0.075f;
	private const int DropletPool = 28;
	private const int CursorFlag = 4;

	private static ManualLogSource _log;
	private static bool _registered;
	private static bool _failed;
	private static readonly HashSet<string> Logged = new();

	private static GameObject _root;
	private static Ribbon _glow;
	private static Ribbon _core;
	private static Transform _preyRing;
	private static Transform _predatorRing;
	private static Material _preyRingMaterial;
	private static Material _predatorRingMaterial;
	private static readonly List<Droplet> Droplets = new();

	private static Unit _shownPredator;
	private static Unit _shownPrey;
	private static object _shownPredatorDrawer;
	private static object _shownPreyDrawer;
	private static bool _frenzied;
	private static float _alpha;
	private static float _grow;
	private static float _dropletDebt;
	private static float _time;
	private static Camera _camera;
	private static readonly System.Random Rng = new();

	private sealed class Ribbon
	{
		internal GameObject Go;
		internal Mesh Mesh;
		internal Material Material;
		internal Vector3[] Vertices;
		internal Color32[] Colors;
	}

	private sealed class Droplet
	{
		internal Transform T;
		internal Material M;
		internal Vector3 Position;
		internal Vector3 Velocity;
		internal float Life;
		internal float Size;
	}

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered)
			return;
		_log = log;
		if (!Homm3FortressPredatorInstinctRuntime.Registered)
		{
			log?.LogWarning("HoMM3 Fortress Predator Instinct line not registered: the pairing runtime is not registered.");
			return;
		}
		try
		{
			try
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FortressPredatorLinePump>();
			}
			catch (Exception ex)
			{
				log?.LogDebug("HoMM3 Fortress Predator line pump already registered: " + ex.Message);
			}
			var go = new GameObject("Homm3FortressPredatorLinePump");
			go.AddComponent<Homm3FortressPredatorLinePump>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_registered = true;
			log?.LogInfo("HoMM3 Fortress Predator Instinct hover line registered.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("HoMM3 Fortress Predator Instinct line not registered: " + ex.GetBaseException().Message);
		}
	}

	// ------------------------------------------------------------------ frame

	internal static void Tick()
	{
		if (!_registered || _failed)
			return;
		try
		{
			var dt = Mathf.Min(0.05f, Time.unscaledDeltaTime);
			_time += dt;
			UpdateTarget(dt);
			if (_alpha <= 0f || _shownPredator == null)
			{
				HideAll();
				UpdateDroplets(dt, null, 0f);
				return;
			}
			var camera = GetCamera();
			if (!camera || !TryAnchor(_shownPredatorDrawer, out var a) || !TryAnchor(_shownPreyDrawer, out var b))
			{
				HideAll();
				return;
			}
			EnsureScene(_shownPredatorDrawer);
			var points = BuildCurve(a, b, camera);
			var pulse = _frenzied ? 0.78f + 0.22f * Mathf.Sin(_time * 9f) : 1f;
			FillRibbon(_glow, points, camera, GlowHalfWidth * (_frenzied ? 1.15f : 1f), _alpha * 0.55f * pulse);
			FillRibbon(_core, points, camera, CoreHalfWidth, _alpha * pulse);
			ScrollCore();
			PlaceRing(_predatorRing, _predatorRingMaterial, GroundPoint(_shownPredatorDrawer, a), 1.05f, 0.45f * _alpha, 3f);
			PlaceRing(_preyRing, _preyRingMaterial, GroundPoint(_shownPreyDrawer, b), 1.2f, 0.9f * _alpha, 5f);
			UpdateDroplets(dt, points, _grow >= 1f ? _alpha : 0f);
		}
		catch (Exception ex)
		{
			_failed = true;
			HideAll();
			_log?.LogWarning("HoMM3 Fortress Predator Instinct line disabled after a render failure: " + ex.GetBaseException().Message);
		}
	}

	private static void UpdateTarget(float dt)
	{
		Unit predator = null, prey = null;
		var frenzied = false;
		object predatorDrawer = null;
		if (TryReadHoveredUnit(out var hovered, out var hoveredDrawer)
		    && Homm3FortressPredatorInstinctRuntime.TryGetHoverPair(hovered, out predator, out prey, out frenzied))
			predatorDrawer = hoveredDrawer;

		if (predator != null && predatorDrawer != null)
		{
			if (_shownPredator == null || _shownPredator.Pointer != predator.Pointer || _shownPrey == null || _shownPrey.Pointer != prey.Pointer)
			{
				var preyDrawer = ResolveDrawer(prey);
				if (preyDrawer == null)
				{
					LogOnce("prey-drawer", "prey drawer not found for " + Homm3FortressPredatorInstinctRuntime.DescribeUnit(prey) + "; line hidden.");
					predator = null;
				}
				else
				{
					if (_alpha <= 0f || _shownPredator == null)
						_grow = 0f;
					else
						_grow = Mathf.Min(_grow, 0.35f);
					_shownPredator = predator;
					_shownPrey = prey;
					_shownPredatorDrawer = predatorDrawer;
					_shownPreyDrawer = preyDrawer;
				}
			}
		}
		if (predator != null)
		{
			_frenzied = frenzied;
			_alpha = Mathf.Min(1f, _alpha + dt / FadeIn);
			_grow = Mathf.Min(1f, _grow + dt / Grow);
		}
		else
		{
			_alpha = Mathf.Max(0f, _alpha - dt / FadeOut);
			if (_alpha <= 0f)
			{
				_shownPredator = _shownPrey = null;
				_shownPredatorDrawer = _shownPreyDrawer = null;
				_grow = 0f;
			}
		}
	}

	// ------------------------------------------------------------------ geometry

	private static readonly Vector3[] Curve = new Vector3[Segments + 1];

	private static Vector3[] BuildCurve(Vector3 a, Vector3 b, Camera camera)
	{
		var delta = b - a;
		var distance = delta.magnitude;
		var lift = Mathf.Min(1.6f, 0.22f * distance) + 0.25f;
		var mid = (a + b) * 0.5f;
		var toCamera = camera.orthographic ? -camera.transform.forward : (camera.transform.position - mid).normalized;
		var side = Vector3.Cross(delta.normalized, toCamera);
		if (side.sqrMagnitude < 1e-4f)
			side = Vector3.Cross(delta.normalized, Vector3.up);
		side.Normalize();
		var speed = _frenzied ? 1.8f : 1f;
		var amplitude = WaveAmplitude * Mathf.Clamp(distance / 4f, 0.6f, 1.4f);
		for (var i = 0; i <= Segments; i++)
		{
			var s = (float)i / Segments;
			var envelope = Mathf.Sin(Mathf.PI * s);
			var wave = (Mathf.Sin(s * 9f - _time * 2.1f * speed) * 0.7f + Mathf.Sin(s * 17f + _time * 3.3f * speed) * 0.3f) * amplitude * envelope;
			var bob = Mathf.Sin(_time * 1.3f) * 0.05f * envelope;
			Curve[i] = a + delta * s + Vector3.up * (lift * 4f * s * (1f - s) + bob) + side * wave;
		}
		return Curve;
	}

	private static void FillRibbon(Ribbon ribbon, Vector3[] points, Camera camera, float halfWidth, float alpha)
	{
		var visible = Mathf.Clamp01(_grow) * Segments;
		var a8 = (byte)Mathf.Clamp(Mathf.RoundToInt(alpha * 255f), 0, 255);
		var min = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue);
		var max = new Vector3(float.MinValue, float.MinValue, float.MinValue);
		for (var i = 0; i <= Segments; i++)
		{
			var clamped = Mathf.Min(i, visible);
			var lo = Mathf.FloorToInt(clamped);
			var hi = Mathf.Min(Segments, lo + 1);
			var p = Vector3.Lerp(points[lo], points[hi], clamped - lo);
			var prev = points[Mathf.Max(0, lo - 1)];
			var next = points[Mathf.Min(Segments, hi + 1)];
			var tangent = (next - prev).normalized;
			var toCamera = camera.orthographic ? -camera.transform.forward : (camera.transform.position - p).normalized;
			var normal = Vector3.Cross(tangent, toCamera).normalized;
			var s = (float)i / Segments;
			var taper = Mathf.Lerp(0.35f, 1f, Mathf.SmoothStep(0f, 1f, Mathf.Min(s, 1f - s) * 6f));
			var w = halfWidth * taper;
			ribbon.Vertices[i * 2] = p + normal * w;
			ribbon.Vertices[i * 2 + 1] = p - normal * w;
			ribbon.Colors[i * 2] = ribbon.Colors[i * 2 + 1] = new Color32(255, 255, 255, i <= visible + 0.5f ? a8 : (byte)0);
			min = Vector3.Min(min, p);
			max = Vector3.Max(max, p);
		}
		ribbon.Mesh.vertices = ribbon.Vertices;
		ribbon.Mesh.colors32 = ribbon.Colors;
		ribbon.Mesh.bounds = new Bounds((min + max) * 0.5f, max - min + Vector3.one);
		SetTint(ribbon.Material, alpha);
		ribbon.Go.SetActive(true);
	}

	private static void ScrollCore()
	{
		var speed = _frenzied ? 0.9f : 0.5f;
		_core.Material.mainTextureOffset = new Vector2(-_time * speed, 0f);
	}

	private static void PlaceRing(Transform ring, Material material, Vector3 ground, float size, float alpha, float pulseRate)
	{
		var pulse = 1f + 0.06f * Mathf.Sin(_time * pulseRate);
		ring.position = ground + Vector3.up * 0.03f;
		ring.rotation = Quaternion.Euler(90f, _time * 20f, 0f);
		ring.localScale = Vector3.one * size * pulse;
		SetTint(material, alpha);
		ring.gameObject.SetActive(alpha > 0.01f);
	}

	private static void UpdateDroplets(float dt, Vector3[] points, float alpha)
	{
		if (Droplets.Count == 0)
			return;
		if (points != null && alpha > 0f)
		{
			_dropletDebt += dt * (_frenzied ? 16f : 7f);
			while (_dropletDebt >= 1f)
			{
				_dropletDebt -= 1f;
				Droplet free = null;
				foreach (var d in Droplets)
				{
					if (d.Life <= 0f)
					{
						free = d;
						break;
					}
				}
				if (free == null)
					break;
				var index = 4 + Rng.Next(Segments - 8);
				free.Position = points[index];
				free.Velocity = new Vector3((float)(Rng.NextDouble() - 0.5) * 0.12f, 0.12f + (float)Rng.NextDouble() * 0.18f, (float)(Rng.NextDouble() - 0.5) * 0.12f);
				free.Life = 1f;
				free.Size = 0.05f + (float)Rng.NextDouble() * 0.06f;
			}
		}
		else
			_dropletDebt = 0f;
		var camera = GetCamera();
		var rotation = camera ? camera.transform.rotation : Quaternion.identity;
		foreach (var d in Droplets)
		{
			if (d.Life <= 0f)
			{
				if (d.T.gameObject.activeSelf)
					d.T.gameObject.SetActive(false);
				continue;
			}
			d.Life -= dt * 0.9f;
			d.Velocity += Vector3.down * 0.05f * dt;
			d.Position += d.Velocity * dt;
			d.T.position = d.Position;
			d.T.rotation = rotation;
			d.T.localScale = Vector3.one * d.Size * (0.55f + 0.45f * Mathf.Max(0f, d.Life));
			SetTint(d.M, Mathf.Max(0f, d.Life) * 0.85f * Mathf.Max(alpha, 0.35f));
			d.T.gameObject.SetActive(true);
		}
	}

	private static void HideAll()
	{
		if (!_root)
			return;
		_glow?.Go.SetActive(false);
		_core?.Go.SetActive(false);
		if (_preyRing)
			_preyRing.gameObject.SetActive(false);
		if (_predatorRing)
			_predatorRing.gameObject.SetActive(false);
	}

	// ------------------------------------------------------------------ hover + anchors

	private static Type _controllerType;
	private const float ControllerTypeRetryMaxSeconds = 30f;
	private const float ControllerProbeSeconds = 0.25f;
	private static float _controllerTypeRetryAt;
	private static float _controllerTypeRetryDelay = 1f;
	private static float _controllerProbeAt;
	private static readonly Dictionary<IntPtr, List<Renderer>> RendererCache = new();

	private static bool TryReadHoveredUnit(out Unit unit, out object drawer)
	{
		unit = null;
		drawer = null;
		var now = Time.realtimeSinceStartup;
		if (_controllerType == null)
		{
			// A failed type lookup walks the loaded assemblies; retry with a doubling delay instead of every frame.
			if (now < _controllerTypeRetryAt)
				return false;
			_controllerType = ResolveType(GameSymbols.BattleVisual.BattleControllerTypeNames);
			if (_controllerType == null)
			{
				_controllerTypeRetryAt = now + _controllerTypeRetryDelay;
				_controllerTypeRetryDelay = Mathf.Min(_controllerTypeRetryDelay * 2f, ControllerTypeRetryMaxSeconds);
				LogOnce("controller-type", "battle controller type not found; hover line inactive.");
				return false;
			}
		}
		// Outside battle the controller singleton is null: probe for it a few times a second, not every frame.
		// Once it exists it is read every frame as before.
		if (now < _controllerProbeAt)
			return false;
		var controller = ReadStatic(_controllerType, GameSymbols.FortressPredatorInstinct.BattleControllerSingletonMembers);
		if (controller == null)
		{
			_controllerProbeAt = now + ControllerProbeSeconds;
			return false;
		}
		var input = Read(controller, GameSymbols.FortressPredatorInstinct.ControllerInputMembers);
		var cursorDrawer = Read(input, GameSymbols.FortressPredatorInstinct.InputCursorDrawerMembers);
		if (cursorDrawer == null)
			return false;
		var flags = Read(cursorDrawer, GameSymbols.FortressPredatorInstinct.DrawerHighlightFlagsMembers);
		if (flags == null || (Convert.ToInt32(flags) & CursorFlag) == 0)
			return false;
		unit = Read(cursorDrawer, GameSymbols.FortressPredatorInstinct.DrawerUnitMembers) as Unit;
		drawer = cursorDrawer;
		return unit != null && unit.Pointer != IntPtr.Zero;
	}

	private static object ResolveDrawer(Unit unit)
	{
		var controller = _controllerType == null ? null : ReadStatic(_controllerType, GameSymbols.FortressPredatorInstinct.BattleControllerSingletonMembers);
		var manager = Read(controller, GameSymbols.BattleVisual.BattleControllerDrawerManagerMembers);
		if (manager == null)
			return null;
		foreach (var name in GameSymbols.BattleVisual.DrawerManagerDrawerForUnit.NameHints)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var method = manager.GetType().GetMethod(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, new[] { typeof(Unit) }, null);
			if (method != null)
				return method.Invoke(manager, new object[] { unit });
		}
		return null;
	}

	private static bool TryAnchor(object drawer, out Vector3 position)
	{
		position = default;
		if (drawer == null)
			return false;
		var helper = Read(drawer, GameSymbols.FortressPredatorInstinct.DrawerViewHelperMembers) as Component;
		if (helper)
		{
			foreach (var name in new[] { "projectileEndPoint", "shieldPoint" })
			{
				if (Read(helper, name) is Transform t && t)
				{
					position = t.position + Vector3.up * 0.12f;
					return true;
				}
			}
		}
		var visual = Read(drawer, GameSymbols.FortressPredatorInstinct.DrawerVisualGameObjectMembers) as GameObject;
		if (!visual)
			return false;
		var key = visual.Pointer;
		if (!RendererCache.TryGetValue(key, out var renderers))
		{
			renderers = new List<Renderer>();
			foreach (var r in visual.GetComponentsInChildren<Renderer>(false))
			{
				if (r && r is not ParticleSystemRenderer)
					renderers.Add(r);
			}
			if (RendererCache.Count > 64)
				RendererCache.Clear();
			RendererCache[key] = renderers;
		}
		var have = false;
		var bounds = default(Bounds);
		foreach (var r in renderers)
		{
			if (!r || !r.enabled)
				continue;
			if (!have)
			{
				bounds = r.bounds;
				have = true;
			}
			else
				bounds.Encapsulate(r.bounds);
		}
		position = have
			? new Vector3(bounds.center.x, bounds.min.y + bounds.size.y * 0.6f, bounds.center.z)
			: visual.transform.position + Vector3.up * 0.9f;
		return true;
	}

	private static Vector3 GroundPoint(object drawer, Vector3 anchor)
	{
		var visual = Read(drawer, GameSymbols.FortressPredatorInstinct.DrawerVisualGameObjectMembers) as GameObject;
		if (visual)
		{
			var p = visual.transform.position;
			return new Vector3(anchor.x, p.y, anchor.z);
		}
		return anchor + Vector3.down * 0.9f;
	}

	private static Camera GetCamera()
	{
		if (_camera && _camera.isActiveAndEnabled)
			return _camera;
		_camera = Camera.main;
		if (_camera && _camera.isActiveAndEnabled)
			return _camera;
		foreach (var c in Camera.allCameras)
		{
			if (c && c.isActiveAndEnabled)
				return _camera = c;
		}
		return null;
	}

	// ------------------------------------------------------------------ scene + art

	private static void EnsureScene(object predatorDrawer)
	{
		if (_root)
			return;
		_root = new GameObject("Homm3FortressPredatorLine");
		UnityEngine.Object.DontDestroyOnLoad(_root);
		var visual = Read(predatorDrawer, GameSymbols.FortressPredatorInstinct.DrawerVisualGameObjectMembers) as GameObject;
		var layer = visual ? visual.layer : 0;
		_root.layer = layer;

		var glowTex = MakeTexture(8, 64, false, (u, v) =>
		{
			var d = (v - 0.5f) / 0.5f;
			var a = Mathf.Exp(-d * d * 3.2f);
			return new Color(0.62f, 0.03f, 0.05f, a);
		});
		var coreTex = MakeTexture(128, 32, true, (u, v) =>
		{
			var d = (v - 0.5f) / 0.5f;
			var across = Mathf.Exp(-d * d * 14f);
			var hot = Mathf.Exp(-d * d * 60f);
			var beads = 0f;
			for (var k = 0; k < 3; k++)
			{
				var c = (k + 0.5f) / 3f + 0.07f * Mathf.Sin(k * 2.3f);
				var du = Mathf.Abs(u - c);
				du = Mathf.Min(du, 1f - du);
				beads = Mathf.Max(beads, Mathf.Exp(-du * du * 900f));
			}
			var streak = 0.82f + 0.18f * Mathf.Sin(u * Mathf.PI * 2f * 5f);
			var core = across * streak + beads * across * 0.6f;
			var white = Mathf.Clamp01(hot * (0.55f + 0.45f * beads));
			return new Color(Mathf.Lerp(0.86f, 1f, white), Mathf.Lerp(0.06f, 0.62f, white), Mathf.Lerp(0.08f, 0.52f, white), Mathf.Clamp01(core));
		});
		var dotTex = MakeTexture(32, 32, false, (u, v) =>
		{
			var dx = u - 0.5f;
			var dy = v - 0.5f;
			var r = Mathf.Sqrt(dx * dx + dy * dy) / 0.5f;
			var a = Mathf.Clamp01(1f - r);
			a *= a;
			var hot = Mathf.Clamp01(1f - r * 2.2f);
			return new Color(Mathf.Lerp(0.78f, 1f, hot), Mathf.Lerp(0.05f, 0.45f, hot), Mathf.Lerp(0.06f, 0.38f, hot), a);
		});
		var ringTex = MakeTexture(128, 128, false, (u, v) =>
		{
			var dx = u - 0.5f;
			var dy = v - 0.5f;
			var r = Mathf.Sqrt(dx * dx + dy * dy) / 0.5f;
			var band = Mathf.Exp(-Mathf.Pow((r - 0.82f) / 0.06f, 2f));
			var halo = Mathf.Exp(-Mathf.Pow((r - 0.78f) / 0.2f, 2f)) * 0.35f;
			var notch = 0.75f + 0.25f * Mathf.Cos(Mathf.Atan2(dy, dx) * 6f);
			var a = Mathf.Clamp01((band * notch + halo) * (r < 1f ? 1f : 0f));
			return new Color(0.9f, 0.08f, 0.1f, a);
		});

		_glow = MakeRibbon("glow", glowTex, 3101);
		_core = MakeRibbon("core", coreTex, 3102);
		_preyRing = MakeQuad("preyRing", ringTex, 3100, out _preyRingMaterial);
		_predatorRing = MakeQuad("predatorRing", ringTex, 3100, out _predatorRingMaterial);
		for (var i = 0; i < DropletPool; i++)
		{
			var t = MakeQuad("droplet" + i, dotTex, 3103, out var m);
			Droplets.Add(new Droplet { T = t, M = m });
		}
		_log?.LogInfo("HoMM3 Fortress Predator Instinct line scene built (shader '" + (_glow.Material.shader ? _glow.Material.shader.name : "?") + "', layer " + layer + ").");
	}

	private static Ribbon MakeRibbon(string name, Texture2D texture, int queue)
	{
		var go = new GameObject(name);
		go.layer = _root.layer;
		go.transform.SetParent(_root.transform, false);
		var mesh = new Mesh { name = "homm3_fortress_predator_" + name };
		mesh.MarkDynamic();
		var vertexCount = (Segments + 1) * 2;
		var vertices = new Vector3[vertexCount];
		var uvs = new Vector2[vertexCount];
		var triangles = new int[Segments * 6];
		for (var i = 0; i <= Segments; i++)
		{
			var u = (float)i / Segments * 3f;
			uvs[i * 2] = new Vector2(u, 1f);
			uvs[i * 2 + 1] = new Vector2(u, 0f);
			if (i == Segments)
				continue;
			var t = i * 6;
			var v = i * 2;
			triangles[t] = v;
			triangles[t + 1] = v + 2;
			triangles[t + 2] = v + 1;
			triangles[t + 3] = v + 1;
			triangles[t + 4] = v + 2;
			triangles[t + 5] = v + 3;
		}
		var colors = new Color32[vertexCount];
		mesh.vertices = vertices;
		mesh.uv = uvs;
		mesh.colors32 = colors;
		mesh.triangles = triangles;
		go.AddComponent<MeshFilter>().sharedMesh = mesh;
		var renderer = go.AddComponent<MeshRenderer>();
		renderer.shadowCastingMode = ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		var material = MakeMaterial(texture, queue);
		renderer.sharedMaterial = material;
		go.SetActive(false);
		return new Ribbon { Go = go, Mesh = mesh, Material = material, Vertices = vertices, Colors = colors };
	}

	private static Transform MakeQuad(string name, Texture2D texture, int queue, out Material material)
	{
		var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
		quad.name = name;
		quad.layer = _root.layer;
		var collider = quad.GetComponent<Collider>();
		if (collider)
			UnityEngine.Object.Destroy(collider);
		quad.transform.SetParent(_root.transform, false);
		var renderer = quad.GetComponent<MeshRenderer>();
		renderer.shadowCastingMode = ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		material = MakeMaterial(texture, queue);
		renderer.sharedMaterial = material;
		quad.SetActive(false);
		return quad.transform;
	}

	private static Shader _shader;
	private static bool _additive;

	private static Material MakeMaterial(Texture2D texture, int queue)
	{
		if (!_shader)
		{
			_shader = Shader.Find("Hex/Particles");
			if (_shader)
			{
				var probe = new Material(_shader);
				_additive = probe.HasProperty("_SrcBlend") && probe.HasProperty("_DstBlend");
				UnityEngine.Object.Destroy(probe);
				if (!_additive)
					_shader = null;
			}
			_shader ??= Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Transparent")
			            ?? throw new InvalidOperationException("no transparent shader (Hex/Particles, Sprites/Default, Unlit/Transparent)");
		}
		var material = new Material(_shader) { mainTexture = texture, renderQueue = queue, hideFlags = HideFlags.DontUnloadUnusedAsset };
		if (_additive)
		{
			material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
			material.SetFloat("_DstBlend", (float)BlendMode.One);
			if (material.HasProperty("_ZWrite"))
				material.SetFloat("_ZWrite", 0f);
			if (material.HasProperty("_ZTest"))
				material.SetFloat("_ZTest", (float)CompareFunction.LessEqual);
			if (material.HasProperty("_Cull"))
				material.SetFloat("_Cull", (float)CullMode.Off);
		}
		SetTint(material, 1f);
		return material;
	}

	private static void SetTint(Material material, float alpha)
	{
		var color = new Color(1f, 1f, 1f, Mathf.Clamp01(alpha));
		if (material.HasProperty("_Color"))
			material.SetColor("_Color", color);
		if (material.HasProperty("_TintColor"))
			material.SetColor("_TintColor", color);
		if (material.HasProperty("_BaseColor"))
			material.SetColor("_BaseColor", color);
	}

	private static Texture2D MakeTexture(int w, int h, bool repeatU, Func<float, float, Color> shade)
	{
		var rgba = new byte[w * h * 4];
		for (var y = 0; y < h; y++)
		{
			for (var x = 0; x < w; x++)
			{
				var c = shade((x + 0.5f) / w, (y + 0.5f) / h);
				var i = (y * w + x) * 4;
				rgba[i] = (byte)Mathf.Clamp(Mathf.RoundToInt(c.r * 255f), 0, 255);
				rgba[i + 1] = (byte)Mathf.Clamp(Mathf.RoundToInt(c.g * 255f), 0, 255);
				rgba[i + 2] = (byte)Mathf.Clamp(Mathf.RoundToInt(c.b * 255f), 0, 255);
				rgba[i + 3] = (byte)Mathf.Clamp(Mathf.RoundToInt(c.a * 255f), 0, 255);
			}
		}
		var tex = Homm3InfernoGatingPortal.MakeTexture(rgba, w, h);
		if (repeatU)
		{
			tex.wrapModeU = TextureWrapMode.Repeat;
			tex.wrapModeV = TextureWrapMode.Clamp;
		}
		return tex;
	}

	// ------------------------------------------------------------------ reflection

	private static Type ResolveType(string[] names)
	{
		var assembly = typeof(TransferBattle).Assembly;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = assembly.GetType(name, false) ?? GameMember.FindType("homm3.fortress.predator.line." + name, name, logMiss: false);
			if (type != null)
				return type;
		}
		return null;
	}

	private static object Read(object owner, params string[] names)
	{
		if (owner == null || names == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = owner.GetType(); type != null; type = type.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				var property = type.GetProperty(name, flags | BindingFlags.DeclaredOnly);
				if (property != null && property.GetIndexParameters().Length == 0)
					return property.GetValue(owner);
				var field = type.GetField(name, flags | BindingFlags.DeclaredOnly);
				if (field != null)
					return field.GetValue(owner);
			}
		}
		return null;
	}

	private static object ReadStatic(Type type, string[] names)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = type.GetProperty(name, flags);
			if (property != null && property.GetIndexParameters().Length == 0)
				return property.GetValue(null);
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(null);
		}
		return null;
	}

	private static void LogOnce(string key, string message)
	{
		if (Logged.Add(key))
			_log?.LogInfo("HoMM3 Fortress Predator Instinct line: " + message);
	}
}

public sealed class Homm3FortressPredatorLinePump : MonoBehaviour
{
	public Homm3FortressPredatorLinePump(IntPtr ptr) : base(ptr) { }

	private void LateUpdate()
	{
		Homm3FortressPredatorLine.Tick();
	}
}
