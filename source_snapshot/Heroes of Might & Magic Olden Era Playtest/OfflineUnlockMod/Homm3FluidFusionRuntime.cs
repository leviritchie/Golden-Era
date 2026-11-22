using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using BepInEx;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using OldenEra.FluidFusion;
using UnityEngine;
using UnityEngine.Rendering;
using NV = System.Numerics.Vector3;

namespace OfflineUnlockMod;

/// <summary>
/// Elemental Fusion runtime fluid body (prototype, 2026-11-20; lab: V:/olden_port_work/elemental_fusion/fluid/).
/// The fused body never exists as an asset: at spawn the host's and guest's per-elemental seed files
/// (<c>fluid_fusion/&lt;element&gt;.fluidseeds</c>, sampled offline per parent) are fitted to the live host mesh,
/// the guest infuses a share of the host's particles, and a position-based fluid bound to the host's animated
/// bones runs every frame on worker threads (<see cref="FluidRunner"/>). Its iso-surfaces replace the host body
/// renderers; MeshFx particles (the pair's reaction VFX) keep playing.
///
/// Off unless <c>fluid_fusion/fluid_fusion.json</c> has <c>"enabled": true</c> and lists the unit. Worker threads
/// touch only managed arrays; every Unity call stays on the main thread (LateUpdate).
/// </summary>
public sealed class Homm3FluidFusionRuntime : MonoBehaviour
{
	private const string FolderName = "fluid_fusion";
	private const float Dt = 1f / 60f;
	private static bool _typeRegistered;
	private static bool _configLoaded;
	private static Config _config;
	private static readonly Dictionary<string, SeedFile> Seeds = new(StringComparer.OrdinalIgnoreCase);
	private static int _logBudget = 40;
	private static Texture2D _noiseTex;
	// OldenEra/Homm3/FluidElement + FluidSprite (tools/conflux_fusion/fluid_shader), one bundle in fluid_fusion/; without
	// it the surfaces fall back to the host's Hex/Lit clone and no sprites are drawn
	private static AssetBundle _shaderBundle;
	private static Shader _elemShader, _spriteShader;
	private static bool _shadersAttempted;
	private static string _bundleName, _elemAsset, _spriteAsset;
	private static Color _sky = new(0.42f, 0.47f, 0.55f, 1f), _ground = new(0.2f, 0.17f, 0.13f, 1f);
	private static Light _sun;
	private static int _sunScanFrame = -100000;
	private static readonly int IdFluidTime = Shader.PropertyToID("_FluidTime"), IdSunDir = Shader.PropertyToID("_SunDir"),
		IdSunColor = Shader.PropertyToID("_SunColor"), IdSkyColor = Shader.PropertyToID("_SkyColor"), IdGroundColor = Shader.PropertyToID("_GroundColor");

	private sealed class Config
	{
		internal string Dir;
		internal readonly Dictionary<string, UnitRecipe> Units = new(StringComparer.OrdinalIgnoreCase);
	}

	/// <summary>One elemental's row in the shared kit: its fluid behaviour plus its surface look. Every fusion the
	/// element takes part in reuses it (15 rows serve all 142 fusions).</summary>
	private sealed class ElementDef
	{
		internal string Name;
		internal ElementFluid Fluid;
		internal Color Albedo = Color.white, Emission = Color.black, LightColor = Color.black;
		internal float UvTile = 1.6f, ScrollV, LightIntensity;
		internal readonly List<(int Id, float[] V)> Look = new();   // FluidElement material properties ("look")
	}

	private sealed class UnitRecipe
	{
		internal string Sid;
		internal float Vein = 9f, CellMul = 0.55f, RadiusMul = 2.2f, IsoFrac = 0.32f;
		internal int BattleParticles = 2500, PreviewParticles = 5000, SolverIterations = 2;
		internal ElementDef[] Elements = Array.Empty<ElementDef>();   // [0] = host (shape + rig), then the guests
		internal float[] Fractions = Array.Empty<float>();            // share of the host's particles per guest (index 0 unused)
		internal float LightRange = 1.1f;
	}

	/// <summary>One surface's mesh data in engine layout, filled on the worker (managed arrays only), bulk-copied on
	/// the main thread. Two per slot, swapped with the runner's buffers.</summary>
	private sealed class Stage
	{
		internal NV[] Pos = Array.Empty<NV>(), Nrm = Array.Empty<NV>();
		internal float[] Uv = Array.Empty<float>();   // 4 per vertex
		internal int[] Idx = Array.Empty<int>();
		internal int Nv, Ni;
		internal NV Lo, Hi;
	}

	private sealed class Slot
	{
		internal Stage Front = new(), Back = new();
		internal GameObject Go;
		internal Mesh Mesh;
		internal Material Material;
		internal ElementDef Recipe;
		internal Il2CppStructArray<Vector3> Pos, Nrm;
		internal Il2CppStructArray<Vector4> Uv;
		internal Il2CppStructArray<int> Idx;
		internal bool NormalsChannelFailed;
	}

	/// <summary>Sprite quads (SpriteVerts layout), filled on the worker, bulk-copied on the main thread.</summary>
	private sealed class SpriteStage
	{
		internal NV[] Pos = Array.Empty<NV>(), Vel = Array.Empty<NV>();
		internal float[] Uv0 = Array.Empty<float>(), Uv1 = Array.Empty<float>(), Col = Array.Empty<float>();
		internal int[] Idx = Array.Empty<int>();
		internal int Nv, Ni;
		internal NV Lo, Hi;
	}

	private ManualLogSource _log;
	private UnitRecipe _recipe;
	private string _lane;
	private FluidRunner _runner;
	private Transform _root;
	private Transform[] _bones = Array.Empty<Transform>();
	private Affine[] _boneSim = Array.Empty<Affine>();
	private float _simScale = 1f;
	private readonly List<Slot> _slots = new();
	private Light _light;
	private bool[] _lit = Array.Empty<bool>();
	private readonly List<Renderer> _hidden = new();
	private float _accum, _time;
	private int _frame;
	private double _uploadMs;
	private int _uploads;
	private float _kickTime;
	private NV _lightFront, _lightBack;
	private bool _lightOnFront, _lightOnBack;
	private bool _fluidShader;
	private ElementFluid[] _fluids = Array.Empty<ElementFluid>();
	private SpriteStage _spriteFront = new(), _spriteBack = new();
	private GameObject _spriteGo;
	private Mesh _spriteMesh;
	private Material _spriteMat;
	private Il2CppStructArray<Vector3> _spPos, _spVel;
	private Il2CppStructArray<Vector4> _spUv0, _spUv1, _spCol;
	private Il2CppStructArray<int> _spIdx;
	private static readonly int IdColor = Shader.PropertyToID("_Color"), IdAlbedoColor = Shader.PropertyToID("_AlbedoColor"),
		IdBaseColor = Shader.PropertyToID("_BaseColor"), IdEmissionTex = Shader.PropertyToID("_EmissionTex"),
		IdEmissionColor = Shader.PropertyToID("_EmissionColor"), IdEmissionMinPower = Shader.PropertyToID("_EmissionMinPower"),
		IdMainTex = Shader.PropertyToID("_MainTex"), IdBaseMap = Shader.PropertyToID("_BaseMap");

	public Homm3FluidFusionRuntime(IntPtr ptr) : base(ptr) { }

	/// <summary>Idempotent. Battle and unit-window lanes only; the adventure map keeps the crest look.</summary>
	internal static void TryAttach(GameObject instance, Homm3ImportVisuals.Entry entry, string lane, ManualLogSource log)
	{
		if (!instance || entry == null || (lane != "battle" && lane != "ui-preview"))
			return;
		try
		{
			EnsureConfig(log);
			if (_config == null || _config.Units.Count == 0)
				return;
			var recipe = FindRecipe(entry);
			if (recipe == null)
				return;
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3FluidFusionRuntime>();
				_typeRegistered = true;
			}
			if (instance.GetComponent<Homm3FluidFusionRuntime>() != null)
				return;
			var rt = instance.AddComponent<Homm3FluidFusionRuntime>();
			if (!rt.Initialise(recipe, lane, log))
				Destroy(rt);
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3FluidFusion: attach failed on '" + (instance ? instance.name : "?") + "': " + ex);
		}
	}

	private static UnitRecipe FindRecipe(Homm3ImportVisuals.Entry entry)
	{
		if (entry.GameUnitSids != null)
			foreach (var sid in entry.GameUnitSids)
				if (sid != null && _config.Units.TryGetValue(sid.Trim(), out var r))
					return r;
		foreach (var path in new[] { entry.BattleResPath, entry.BattlePrefabAssetPath })
		{
			if (string.IsNullOrEmpty(path))
				continue;
			var leaf = Path.GetFileNameWithoutExtension(path.Replace('\\', '/'));
			if (leaf != null && _config.Units.TryGetValue(leaf, out var r))
				return r;
		}
		return null;
	}

	// ------------------------------------------------------------------ config + seeds

	private static void EnsureConfig(ManualLogSource log)
	{
		if (_configLoaded)
			return;
		_configLoaded = true;
		var dir = Path.Combine(Paths.PluginPath, "OfflineUnlockMod", FolderName);
		var path = Path.Combine(dir, "fluid_fusion.json");
		if (!File.Exists(path))
			return;
		try
		{
			using var doc = JsonDocument.Parse(File.ReadAllText(path), new JsonDocumentOptions { AllowTrailingCommas = true, CommentHandling = JsonCommentHandling.Skip });
			var root = doc.RootElement;
			if (!root.TryGetProperty("enabled", out var en) || en.ValueKind != JsonValueKind.True)
			{
				log?.LogInfo("Homm3FluidFusion: " + path + " present but not enabled.");
				return;
			}
			var cfg = new Config { Dir = dir };
			if (root.TryGetProperty("shaders", out var sh) && sh.ValueKind == JsonValueKind.Object)
			{
				_bundleName = S(sh, "bundle"); _elemAsset = S(sh, "element"); _spriteAsset = S(sh, "sprite");
				_sky = C(sh, "sky", _sky); _ground = C(sh, "ground", _ground);
			}
			var elements = new Dictionary<string, ElementDef>(StringComparer.OrdinalIgnoreCase);
			foreach (var e in root.GetProperty("elements").EnumerateObject())
				elements[e.Name] = ParseElement(e.Name, e.Value);
			var defaults = root.TryGetProperty("defaults", out var d) ? d : default;
			var skipped = new List<string>();
			foreach (var u in root.GetProperty("units").EnumerateObject())
			{
				var r = ParseRecipe(u.Name, u.Value, defaults, elements);
				if (r == null)
					skipped.Add(u.Name);
				else
					cfg.Units[u.Name] = r;
			}
			_config = cfg;
			log?.LogInfo("Homm3FluidFusion: enabled for " + cfg.Units.Count + " fusion(s), " + elements.Count + " element(s)"
			             + (skipped.Count == 0 ? "." : "; skipped (unknown element): " + string.Join(",", skipped)));
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3FluidFusion: config " + path + " failed: " + ex.Message);
		}
	}

	private static string S(JsonElement e, string name) =>
		e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

	private static ElementDef ParseElement(string name, JsonElement e)
	{
		var d = NewElement(name, e);
		var f = d.Fluid;
		var kind = (int)F(e, "emitKind", SpriteKind.None);
		f.EmitKind = kind >= 0 && kind < 255 ? (byte)kind : SpriteKind.None;
		f.EmitRate = F(e, "emitRate", 0f);
		f.EmitHot = e.TryGetProperty("emitHot", out var hot) && hot.ValueKind == JsonValueKind.True;
		f.EmitLife = F(e, "emitLife", f.EmitLife);
		f.EmitSize = F(e, "emitSize", f.EmitSize);
		var ec = C(e, "emitColor", new Color(1f, 1f, 1f, 1f));
		f.EmitColor = new System.Numerics.Vector4(ec.r, ec.g, ec.b, ec.a);
		var sc = C(e, "steamColor", new Color(0.9f, 0.92f, 0.95f, 0.8f));
		f.SteamColor = new System.Numerics.Vector4(sc.r, sc.g, sc.b, sc.a);
		if (e.TryGetProperty("look", out var look) && look.ValueKind == JsonValueKind.Object)
			foreach (var p in look.EnumerateObject())
			{
				float[] v;
				if (p.Value.ValueKind == JsonValueKind.Number)
					v = new[] { p.Value.GetSingle() };
				else if (p.Value.ValueKind == JsonValueKind.Array)
				{
					var l = new List<float>();
					foreach (var x in p.Value.EnumerateArray()) l.Add(x.GetSingle());
					v = l.ToArray();
				}
				else
					continue;
				d.Look.Add((Shader.PropertyToID(p.Name), v));
			}
		return d;
	}

	private static ElementDef NewElement(string name, JsonElement e) => new()
	{
		Name = name,
		Fluid = new ElementFluid
		{
			Name = name,
			HomeStiffness = F(e, "homeStiffness", 40f), HomeDamping = F(e, "homeDamping", 6f), Viscosity = F(e, "viscosity", 0.1f),
			Cohesion = F(e, "cohesion", 0.5f), Repulsion = F(e, "repulsion", 0.5f), Buoyancy = F(e, "buoyancy", 0f),
			BaseTemp = F(e, "baseTemp", 0f), TempRelax = F(e, "tempRelax", 1f), Conductivity = F(e, "conductivity", 1f),
			BoilTemp = F(e, "boilTemp", 999f), BoilRate = F(e, "boilRate", 0f), GasLife = F(e, "gasLife", 1f),
			Jitter = F(e, "jitter", 0.1f), FlameRate = F(e, "flameRate", 0f),
		},
		Albedo = C(e, "albedo", Color.white), Emission = C(e, "emission", Color.black),
		UvTile = F(e, "uvTile", 1.6f), ScrollV = F(e, "scrollV", 0f),
		LightColor = C(e, "lightColor", Color.black), LightIntensity = F(e, "lightIntensity", 0f),
	};

	/// <summary>Null when the unit names an element the table lacks. Unit fields override <c>defaults</c>.</summary>
	private static UnitRecipe ParseRecipe(string sid, JsonElement u, JsonElement defaults, Dictionary<string, ElementDef> elements)
	{
		float G(string key, float def) => F(u, key, defaults.ValueKind == JsonValueKind.Object ? F(defaults, key, def) : def);
		var r = new UnitRecipe { Sid = sid };
		r.Vein = G("veinScale", r.Vein); r.CellMul = G("cellMul", r.CellMul); r.RadiusMul = G("radiusMul", r.RadiusMul); r.IsoFrac = G("isoFrac", r.IsoFrac);
		r.BattleParticles = (int)G("battleParticles", r.BattleParticles);
		r.PreviewParticles = (int)G("previewParticles", r.PreviewParticles);
		r.SolverIterations = (int)G("solverIterations", r.SolverIterations);
		r.LightRange = G("lightRange", r.LightRange);
		if (!elements.TryGetValue(u.GetProperty("host").GetString() ?? "", out var host))
			return null;
		var els = new List<ElementDef> { host };
		var fr = new List<float> { 0f };
		foreach (var g in u.GetProperty("guests").EnumerateArray())
		{
			if (!elements.TryGetValue(g[0].GetString() ?? "", out var ge))
				return null;
			els.Add(ge);
			fr.Add(g[1].GetSingle());
		}
		r.Elements = els.ToArray();
		r.Fractions = fr.ToArray();
		return r;
	}

	private static float F(JsonElement e, string name, float def) =>
		e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetSingle() : def;

	private static Color C(JsonElement e, string name, Color def)
	{
		if (!e.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.Array)
			return def;
		var a = new float[4] { 0, 0, 0, 1 };
		var i = 0;
		foreach (var x in v.EnumerateArray())
			if (i < 4)
				a[i++] = x.GetSingle();
		return new Color(a[0], a[1], a[2], a[3]);
	}

	private static SeedFile LoadSeeds(string element)
	{
		if (Seeds.TryGetValue(element, out var f))
			return f;
		var path = Path.Combine(_config.Dir, element + ".fluidseeds");
		using (var fs = File.OpenRead(path))
			f = SeedFile.Read(fs);
		Seeds[element] = f;
		return f;
	}

	// ------------------------------------------------------------------ spawn

	private bool Initialise(UnitRecipe recipe, string lane, ManualLogSource log)
	{
		_log = log; _recipe = recipe; _lane = lane; _root = transform;
		var t0 = System.Diagnostics.Stopwatch.GetTimestamp();
		var body = PickBody();
		if (!body)
		{
			Log("no host SkinnedMeshRenderer under '" + name + "'", true);
			return false;
		}
		var mesh = body.sharedMesh;
		var bonesArr = body.bones;
		_bones = new Transform[bonesArr.Length];
		var byName = new Dictionary<string, int>(StringComparer.Ordinal);
		for (var i = 0; i < _bones.Length; i++)
		{
			_bones[i] = bonesArr[i];
			if (_bones[i] && !byName.ContainsKey(_bones[i].name))
				byName[_bones[i].name] = i;
		}
		var bindArr = mesh.bindposes;
		var bind = new Affine[bindArr.Length];
		for (var i = 0; i < bind.Length; i++)
			bind[i] = ToAffine(bindArr[i]);
		_boneSim = new Affine[_bones.Length];

		var hostFile = LoadSeeds(recipe.Elements[0].Name);
		var target = lane == "battle" ? recipe.BattleParticles : recipe.PreviewParticles;
		var (hostSpacing, hostSeeds) = hostFile.Pick(target);

		// fit the seed file to the live mesh by bounds (mesh space; expected ~identity) and map bones by name
		var mb = mesh.bounds;
		var fitScale = mb.size.y / Math.Max(1e-5f, hostFile.BoundsSize.Y);
		var fit = Affine.ScaleTranslate(fitScale, new NV(mb.center.x, mb.center.y, mb.center.z) - fitScale * hostFile.BoundsCenter);
		var map = new int[hostFile.BoneNames.Length];
		var hips = byName.TryGetValue("Hips", out var hi) ? hi : 0;
		var missing = new List<string>();
		for (var i = 0; i < map.Length; i++)
		{
			if (byName.TryGetValue(hostFile.BoneNames[i] ?? "", out var j))
				map[i] = j;
			else
			{
				map[i] = hips;
				if (missing.Count < 8)
					missing.Add(hostFile.BoneNames[i]);
			}
		}
		var hs = new List<Seed>(hostSeeds.Count);
		foreach (var q in hostSeeds)
			hs.Add(new Seed
			{
				Rest = fit.Point(q.Rest), B0 = map[q.B0], B1 = map[q.B1], B2 = map[q.B2], B3 = map[q.B3],
				W0 = q.W0, W1 = q.W1, W2 = q.W2, W3 = q.W3, Surface = q.Surface,
			});
		var spacing = hostSpacing * fitScale;

		// each guest's volume aligned onto the host (lab rule: match heights, centre x/z, feet on feet), positions only; it
		// takes over its share of the particles still held by the host (later guests claim from what is left)
		var elemOf = new byte[hs.Count];
		var hostLeft = hs.Count;
		var guestLog = new List<string>();
		for (var k = 1; k < recipe.Elements.Length; k++)
		{
			var guestFile = LoadSeeds(recipe.Elements[k].Name);
			var (_, guestSeeds) = guestFile.Pick(hostSeeds.Count);
			var gScale = mb.size.y / Math.Max(1e-5f, guestFile.BoundsSize.Y);
			var gMin = guestFile.BoundsCenter - guestFile.BoundsSize * 0.5f;
			var align = Affine.ScaleTranslate(gScale, new NV(mb.center.x - gScale * guestFile.BoundsCenter.X, mb.min.y - gScale * gMin.Y, mb.center.z - gScale * guestFile.BoundsCenter.Z));
			var gs = new List<Seed>(guestSeeds.Count);
			foreach (var q in guestSeeds)
				gs.Add(new Seed { Rest = align.Point(q.Rest), W0 = 1f, Surface = q.Surface });
			// this guest's share of the WHOLE body = its best-ranked particles the host still holds
			var want = (int)(recipe.Fractions[k] * hs.Count);
			var rank = Seeder.InfuseRank(hs, gs, spacing, recipe.Vein, 13 + 7 * k);
			var got = 0;
			for (var r = 0; r < rank.Length && got < want; r++)
				if (elemOf[rank[r]] == 0) { elemOf[rank[r]] = (byte)k; got++; }
			hostLeft -= got;
			guestLog.Add(recipe.Elements[k].Name + ":" + got + "@" + gScale.ToString("0.00"));
		}

		// simulate in the root's local space scaled back to mesh units, so the lab-tuned forces hold at any unit scale
		var used = new bool[_bones.Length];
		foreach (var q in hs)
		{
			if (q.W0 > 0.05f && q.B0 < used.Length) used[q.B0] = true;
			if (q.W1 > 0.05f && q.B1 < used.Length) used[q.B1] = true;
			if (q.W2 > 0.05f && q.B2 < used.Length) used[q.B2] = true;
			if (q.W3 > 0.05f && q.B3 < used.Length) used[q.B3] = true;
		}
		_simScale = EstimateMeshToRootScale(bind, used, body.transform, out var scaleSrc);
		ReadBones();
		var fluids = new ElementFluid[recipe.Elements.Length];
		for (var k = 0; k < fluids.Length; k++)
			fluids[k] = recipe.Elements[k].Fluid;
		_fluids = fluids;
		var fluid = new FluidBody(fluids, spacing, hs.Count + 64, 7) { SolverIterations = Math.Max(1, recipe.SolverIterations) };
		fluid.Add(hs, elemOf, 0, bind, hs.Count);
		fluid.Initialise(_boneSim);
		float cell = spacing * recipe.CellMul, radius = spacing * recipe.RadiusMul;
		var iso = SurfaceNets.InteriorValue(spacing, radius) * recipe.IsoFrac;
		var elems = new byte[recipe.Elements.Length];   // one surface per element present
		for (var k = 0; k < elems.Length; k++)
			elems[k] = (byte)k;
		_runner = new FluidRunner(fluid, elems, () => new SurfaceNets(cell, radius, iso));

		var hostMaterial = body.sharedMaterial;
		_fluidShader = EnsureShaders(log);
		for (var k = 0; k < recipe.Elements.Length; k++)
			_slots.Add(MakeSlot(recipe.Elements[k], hostMaterial, k));
		if (_fluidShader)
			MakeSprites();
		_runner.PostWork = FillStaging;
		_runner.Swapped = SwapStaging;
		MakeLight();
		HideHostRenderers();
		var ms = (System.Diagnostics.Stopwatch.GetTimestamp() - t0) * 1000.0 / System.Diagnostics.Stopwatch.Frequency;
		Log("attached " + recipe.Sid + " lane=" + lane + " body='" + body.name + "' particles=" + fluid.Count + " spacing=" + spacing.ToString("0.0000")
		    + " fit=" + fitScale.ToString("0.000") + " host=" + recipe.Elements[0].Name + ":" + hostLeft + " guests=" + string.Join(",", guestLog) + " simScale=" + _simScale.ToString("0.000") + "(" + scaleSrc + ")"
		    + " bones=" + _bones.Length + " missingBones=" + (missing.Count == 0 ? "0" : string.Join(",", missing))
		    + " hidden=" + _hidden.Count + " shader=" + (_fluidShader ? "fluid" : "hexlit") + " spawnMs=" + ms.ToString("0.0"), false);
		return true;
	}

	private SkinnedMeshRenderer PickBody()
	{
		SkinnedMeshRenderer best = null;
		var bestVerts = -1;
		foreach (var s in GetComponentsInChildren<SkinnedMeshRenderer>(true))
		{
			if (!s || !s.sharedMesh)
				continue;
			var m = s.sharedMaterial;
			if (m && m.name != null && m.name.IndexOf("crest", StringComparison.OrdinalIgnoreCase) >= 0)
				continue;
			var v = s.sharedMesh.vertexCount;
			if (v > bestVerts) { best = s; bestVerts = v; }
		}
		return best;
	}

	/// <summary>Mesh-to-root-local scale: median column length of rootLocal(bone) * bindpose over the bones the seeds are
	/// skinned to. Bones scaled to ~0 at spawn (hidden effect bones, grow-in) are skipped: the fire rig's 74 bones once
	/// gave a median of ~0 in battle and the body vanished. Falls back to the renderer's own transform, then 1.</summary>
	private float EstimateMeshToRootScale(Affine[] bind, bool[] used, Transform rendererTransform, out string source)
	{
		var w2l = _root.worldToLocalMatrix;
		var vals = new List<float>();
		var collapsed = 0;
		for (var i = 0; i < _bones.Length && i < bind.Length; i++)
		{
			if (!_bones[i] || (used != null && i < used.Length && !used[i]))
				continue;
			var m = w2l * _bones[i].localToWorldMatrix * FromAffine(bind[i]);
			var c = new Vector3(m.m00, m.m10, m.m20).magnitude;
			if (c > 1e-3f && !float.IsNaN(c) && !float.IsInfinity(c))
				vals.Add(c);
			else
				collapsed++;
		}
		if (vals.Count > 0)
		{
			vals.Sort();
			source = "bones " + vals.Count + (collapsed > 0 ? " skip " + collapsed : "");
			return vals[vals.Count / 2];
		}
		var r = w2l * rendererTransform.localToWorldMatrix;
		var rc = new Vector3(r.m00, r.m10, r.m20).magnitude;
		if (rc > 1e-3f && !float.IsNaN(rc) && !float.IsInfinity(rc))
		{
			source = "renderer, bones collapsed " + collapsed;
			return rc;
		}
		source = "default, bones collapsed " + collapsed;
		return 1f;
	}

	private void ReadBones()
	{
		// sim space = root local / simScale
		var toSim = Matrix4x4.Scale(Vector3.one / _simScale) * _root.worldToLocalMatrix;
		for (var i = 0; i < _bones.Length; i++)
			_boneSim[i] = _bones[i] ? ToAffine(toSim * _bones[i].localToWorldMatrix) : Affine.Identity;
	}

	private Slot MakeSlot(ElementDef sr, Material hostMaterial, int index)
	{
		var go = new GameObject("__homm3_fluid_surface_" + index);
		go.transform.SetParent(_root, false);
		go.transform.localPosition = Vector3.zero;
		go.transform.localRotation = Quaternion.identity;
		go.transform.localScale = Vector3.one * _simScale;
		go.layer = gameObject.layer;
		var mesh = new Mesh { name = "homm3_fluid_" + _recipe.Sid + "_" + index };
		mesh.indexFormat = IndexFormat.UInt32;
		mesh.MarkDynamic();
		go.AddComponent<MeshFilter>().sharedMesh = mesh;
		var mr = go.AddComponent<MeshRenderer>();
		mr.shadowCastingMode = ShadowCastingMode.Off;
		if (_fluidShader)
		{
			var fm = new Material(_elemShader) { name = "homm3_fluid_" + _recipe.Sid + "_" + index };
			foreach (var (id, v) in sr.Look)
			{
				if (!fm.HasProperty(id))
					continue;
				if (v.Length == 1) fm.SetFloat(id, v[0]);
				else fm.SetVector(id, new Vector4(v[0], v.Length > 1 ? v[1] : 0f, v.Length > 2 ? v[2] : 0f, v.Length > 3 ? v[3] : 1f));
			}
			fm.SetColor(IdSkyColor, _sky); fm.SetColor(IdGroundColor, _ground);
			mr.sharedMaterial = fm;
			return new Slot { Go = go, Mesh = mesh, Material = fm, Recipe = sr };
		}
		// Clone for the shader and its keywords only: the unit's own texture slots (atlas, masks, maps laid out for the
		// unit's UVs) read as patchy colour under the fluid's triplanar UVs (2026-11-20 first install), so every texture
		// slot is cleared and the surface gets the neutral noise albedo tinted by the recipe colour.
		var mat = hostMaterial ? new Material(hostMaterial) : new Material(Shader.Find("Hex/Lit"));
		mat.name = "homm3_fluid_" + _recipe.Sid + "_" + index;
		var cleared = new List<string>();
		try
		{
			var names = mat.GetTexturePropertyNames();
			for (var i = 0; names != null && i < names.Length; i++)
			{
				string tn = names[i];
				if (string.IsNullOrEmpty(tn) || !mat.GetTexture(Shader.PropertyToID(tn)))
					continue;
				mat.SetTexture(Shader.PropertyToID(tn), null);
				cleared.Add(tn);
			}
		}
		catch (Exception ex)
		{
			Log("texture slot enumeration failed: " + ex.Message, true);
		}
		var noise = NoiseTexture();
		if (mat.HasProperty(IdMainTex)) mat.SetTexture(IdMainTex, noise);
		if (mat.HasProperty(IdBaseMap)) mat.SetTexture(IdBaseMap, noise);
		if (mat.HasProperty(IdColor)) mat.SetColor(IdColor, sr.Albedo);
		if (mat.HasProperty(IdAlbedoColor)) mat.SetColor(IdAlbedoColor, sr.Albedo);
		if (mat.HasProperty(IdBaseColor)) mat.SetColor(IdBaseColor, sr.Albedo);
		if (mat.HasProperty(IdEmissionTex)) mat.SetTexture(IdEmissionTex, noise);
		if (mat.HasProperty(IdEmissionColor)) mat.SetColor(IdEmissionColor, sr.Emission);
		if (mat.HasProperty(IdEmissionMinPower)) mat.SetFloat(IdEmissionMinPower, 1f);
		var keywords = new List<string>();
		try
		{
			var kw = mat.shaderKeywords;
			for (var i = 0; kw != null && i < kw.Length; i++)
				keywords.Add(kw[i]);
		}
		catch (Exception) { keywords.Add("?"); }
		Log("surface " + index + " material '" + (hostMaterial ? hostMaterial.name : "-") + "' shader '" + (mat.shader ? mat.shader.name : "-")
		    + "' cleared=[" + string.Join(",", cleared) + "] keywords=[" + string.Join(" ", keywords) + "]", false);
		mr.sharedMaterial = mat;
		return new Slot { Go = go, Mesh = mesh, Material = mat, Recipe = sr };
	}

	private void MakeSprites()
	{
		_spriteGo = new GameObject("__homm3_fluid_sprites");
		_spriteGo.transform.SetParent(_root, false);
		_spriteGo.transform.localScale = Vector3.one * _simScale;
		_spriteGo.layer = gameObject.layer;
		_spriteMesh = new Mesh { name = "homm3_fluid_sprites_" + _recipe.Sid };
		_spriteMesh.indexFormat = IndexFormat.UInt32;
		_spriteMesh.MarkDynamic();
		_spriteGo.AddComponent<MeshFilter>().sharedMesh = _spriteMesh;
		var mr = _spriteGo.AddComponent<MeshRenderer>();
		mr.shadowCastingMode = ShadowCastingMode.Off;
		mr.receiveShadows = false;
		_spriteMat = new Material(_spriteShader) { name = "homm3_fluid_sprites_" + _recipe.Sid };
		mr.sharedMaterial = _spriteMat;
	}

	private static bool EnsureShaders(ManualLogSource log)
	{
		if (_elemShader && _spriteShader)
			return true;
		if (_shadersAttempted)
			return false;
		_shadersAttempted = true;
		if (string.IsNullOrEmpty(_bundleName) || string.IsNullOrEmpty(_elemAsset) || string.IsNullOrEmpty(_spriteAsset))
		{
			log?.LogWarning("Homm3FluidFusion: no \"shaders\" block in fluid_fusion.json; Hex/Lit surfaces, no sprites.");
			return false;
		}
		var path = Path.Combine(_config.Dir, _bundleName);
		try
		{
			if (!File.Exists(path))
			{
				log?.LogError("Homm3FluidFusion: shader bundle missing: " + path + "; Hex/Lit surfaces, no sprites.");
				return false;
			}
			_shaderBundle = AssetBundle.LoadFromFile(path);
			if (!_shaderBundle)
			{
				log?.LogError("Homm3FluidFusion: AssetBundle.LoadFromFile returned null for " + path + ".");
				return false;
			}
			var e = _shaderBundle.LoadAsset<Shader>(_elemAsset);
			var sp = _shaderBundle.LoadAsset<Shader>(_spriteAsset);
			log?.LogInfo("Homm3FluidFusion: shaders element='" + (e ? e.name + "' supported=" + e.isSupported : "-'")
			             + " sprite='" + (sp ? sp.name + "' supported=" + sp.isSupported : "-'") + " from " + path);
			if (!e || !sp || !e.isSupported || !sp.isSupported)
				return false;
			e.hideFlags = HideFlags.DontUnloadUnusedAsset;
			sp.hideFlags = HideFlags.DontUnloadUnusedAsset;
			_elemShader = e; _spriteShader = sp;
			return true;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3FluidFusion: shader bundle load failed: " + ex.Message);
			return false;
		}
	}

	/// <summary>Strongest active directional light in a loaded scene (Homm3MetalShine.FindSun); rescanned every
	/// 120 frames while missing.</summary>
	private static void FeedSun(Material m)
	{
		var f = Time.frameCount;
		if ((!_sun || !_sun.isActiveAndEnabled) && f - _sunScanFrame >= 120)
		{
			_sunScanFrame = f;
			_sun = null;
			var bestI = 0f;
			var all = Resources.FindObjectsOfTypeAll(Il2CppInterop.Runtime.Il2CppType.Of<Light>());
			for (var i = 0; all != null && i < all.Length; i++)
			{
				var l = all[i]?.TryCast<Light>();
				if (!l || !l.isActiveAndEnabled || l.type != LightType.Directional || !l.gameObject.scene.IsValid())
					continue;
				if (l.intensity > bestI) { bestI = l.intensity; _sun = l; }
			}
		}
		if (_sun && _sun.isActiveAndEnabled)
		{
			var d = _sun.transform.forward;
			var c = _sun.color.linear;
			var k = _sun.intensity;
			m.SetVector(IdSunDir, new Vector4(d.x, d.y, d.z, 0f));
			m.SetColor(IdSunColor, new Color(c.r * k, c.g * k, c.b * k, 1f));
		}
	}

	private void MakeLight()
	{
		_lit = new bool[_recipe.Elements.Length];
		ElementDef best = null;
		for (var k = 0; k < _lit.Length; k++)
		{
			var e = _recipe.Elements[k];
			_lit[k] = e.LightIntensity > 0f;
			if (_lit[k] && (best == null || e.LightIntensity > best.LightIntensity))
				best = e;
		}
		if (best == null)
			return;
		var go = new GameObject("__homm3_fluid_light");
		go.transform.SetParent(_root, false);
		_light = go.AddComponent<Light>();
		_light.type = LightType.Point;
		_light.color = best.LightColor;
		_light.intensity = best.LightIntensity;
		_light.range = _recipe.LightRange * _simScale * Mathf.Abs(_root.lossyScale.y);
		_light.shadows = LightShadows.None;
		_light.enabled = false;
	}

	/// <summary>Procedural value noise (no asset): albedo/emission detail for non-host surfaces.</summary>
	private static Texture2D NoiseTexture()
	{
		if (_noiseTex)
			return _noiseTex;
		const int n = 64;
		var tex = new Texture2D(n, n, TextureFormat.RGBA32, true) { name = "homm3_fluid_noise", wrapMode = TextureWrapMode.Repeat };
		var px = new Color[n * n];
		var rng = new System.Random(5);
		var g = new float[9 * 9];
		for (var i = 0; i < g.Length; i++) g[i] = (float)rng.NextDouble();
		for (var y = 0; y < n; y++)
			for (var x = 0; x < n; x++)
			{
				float fx = x / 8f, fy = y / 8f;
				int x0 = (int)fx, y0 = (int)fy;
				float tx = fx - x0, ty = fy - y0;
				tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty);
				float a = g[y0 * 9 + x0], b = g[y0 * 9 + x0 + 1], c = g[(y0 + 1) * 9 + x0], d = g[(y0 + 1) * 9 + x0 + 1];
				var v = Mathf.Lerp(Mathf.Lerp(a, b, tx), Mathf.Lerp(c, d, tx), ty);
				v = 0.55f + 0.45f * v;
				px[y * n + x] = new Color(v, v, v, 1f);
			}
		tex.SetPixels(px);
		tex.Apply(true, false);
		_noiseTex = tex;
		return tex;
	}

	private void HideHostRenderers()
	{
		foreach (var r in GetComponentsInChildren<Renderer>(true))
		{
			if (!r || r is ParticleSystemRenderer)
				continue;
			var n = r.gameObject.name;
			if (n != null && n.StartsWith("__homm3_fluid", StringComparison.Ordinal))
				continue;
			if (r is SkinnedMeshRenderer || r is MeshRenderer)
			{
				if (r.enabled)
				{
					r.enabled = false;
					if (!_hidden.Contains(r))
						_hidden.Add(r);
				}
			}
		}
	}

	// ------------------------------------------------------------------ per frame

	private void LateUpdate()
	{
		if (_runner == null)
			return;
		try
		{
			if (_runner.Collect())
				Upload();
			if (_fluidShader)
			{
				foreach (var s in _slots)
				{
					s.Material.SetFloat(IdFluidTime, _time);
					FeedSun(s.Material);
				}
				if (_spriteMat) _spriteMat.SetFloat(IdFluidTime, _time);
			}
			_accum += Mathf.Min(Time.deltaTime, 0.1f);
			var steps = Mathf.Min(3, (int)(_accum / Dt));
			if (steps > 0)
			{
				ReadBones();
				if (!_runner.Busy)
					_kickTime = _time;   // read by the next job's FillStaging (UV scroll)
				_runner.TryKick(_boneSim, Dt, steps);   // a busy runner banks the time itself and catches up later
				_accum -= steps * Dt;
				_time += steps * Dt;
			}
			if ((++_frame & 31) == 0)
				HideHostRenderers();
			if (_frame == 600)
				Log(_recipe.Sid + " lane=" + _lane + " jobMs=" + _runner.LastJobMs.ToString("0.00") + " uploadMsAvg=" + (_uploadMs / Math.Max(1, _uploads)).ToString("0.00")
				    + " skipped=" + _runner.Skipped + " frames=" + _runner.Frames, false);
		}
		catch (Exception ex)
		{
			Log("frame failed, fluid body disabled: " + ex, true);
			_runner = null;
			foreach (var r in _hidden)
				if (r) r.enabled = true;
			foreach (var s in _slots)
				if (s.Go) s.Go.SetActive(false);
			if (_spriteGo) _spriteGo.SetActive(false);
		}
	}

	/// <summary>Worker thread, after the surfaces are built: engine-layout staging + fire-light centroid. Managed data
	/// only (no Unity or interop calls off the main thread).</summary>
	private void FillStaging()
	{
		for (var k = 0; k < _slots.Count; k++)
			Fill(_slots[k].Back, _runner.Back[k], _slots[k].Recipe, _kickTime, _fluidShader);
		var b = _runner.Body;
		if (_fluidShader)
			FillSprites(_spriteBack, b.Sprites, _fluids);
		NV c = NV.Zero; var w = 0;
		for (var i = 0; i < b.Count; i += 2)
			if (b.Phase[i] == FluidBody.Bound && _lit[b.Elem[i]]) { c += b.P[i]; w++; }
		_lightOnBack = w > 0;
		_lightBack = w > 0 ? c / w : NV.Zero;
	}

	private static void Fill(Stage st, SurfaceNets nets, ElementDef sr, float time, bool temp)
	{
		int nv = nets.Positions.Count, ni = nets.Indices.Count;
		if (st.Pos.Length < nv)
		{
			var cap = nv + nv / 4 + 64;
			st.Pos = new NV[cap]; st.Nrm = new NV[cap]; st.Uv = new float[cap * 4];
		}
		if (st.Idx.Length < ni)
			st.Idx = new int[ni + ni / 4 + 96];
		nets.Positions.CopyTo(st.Pos);
		nets.Normals.CopyTo(st.Nrm);
		nets.Indices.CopyTo(st.Idx);
		float scroll = sr.ScrollV * time, tile = sr.UvTile;
		NV lo = new(float.MaxValue), hi = new(float.MinValue);
		var uv = st.Uv;
		for (var v = 0; v < nv; v++)
		{
			NV p = st.Pos[v], n = st.Nrm[v];
			lo = NV.Min(lo, p); hi = NV.Max(hi, p);
			float ax = Math.Abs(n.X), ay = Math.Abs(n.Y), az = Math.Abs(n.Z), u, t;
			if (ax >= ay && ax >= az) { u = p.Z; t = p.Y; }
			else if (ay >= az) { u = p.X; t = p.Z; }
			else { u = p.X; t = p.Y; }
			uv[4 * v] = u * tile; uv[4 * v + 1] = t * tile + scroll;
			// z = temperature for FluidElement's heat ramp; on the Hex/Lit fallback z/w stay zero (patchy colour, 2026-11-20)
			uv[4 * v + 2] = temp && v < nets.Mix.Count ? nets.Mix[v] : 0f; uv[4 * v + 3] = 0f;
		}
		st.Nv = nv; st.Ni = ni; st.Lo = lo; st.Hi = hi;
	}

	/// <summary>Worker: the body's sprites (owned by this job until it ends) into quad staging.</summary>
	private static void FillSprites(SpriteStage st, List<OldenEra.FluidFusion.Sprite> sprites, ElementFluid[] fluids)
	{
		int n = sprites.Count, nv = n * 4, ni = n * 6;
		if (st.Pos.Length < nv)
		{
			var cap = nv + 256;
			st.Pos = new NV[cap]; st.Vel = new NV[cap]; st.Uv0 = new float[cap * 4]; st.Uv1 = new float[cap * 4]; st.Col = new float[cap * 4];
		}
		if (st.Idx.Length < ni)
			st.Idx = new int[ni + 384];
		st.Nv = SpriteVerts.Write(sprites, fluids, st.Pos, st.Vel, st.Uv0, st.Uv1, st.Col, st.Idx);
		st.Ni = n * 6;
		NV lo = new(float.MaxValue), hi = new(float.MinValue);
		for (var v = 0; v < st.Nv; v += 4) { lo = NV.Min(lo, st.Pos[v]); hi = NV.Max(hi, st.Pos[v]); }
		st.Lo = lo; st.Hi = hi;
	}

	private void UploadSprites()
	{
		var st = _spriteFront;
		int nv = st.Nv, ni = st.Ni;
		_spriteMesh.Clear();
		if (nv == 0 || ni == 0)
			return;
		if (_spPos == null || _spPos.Length < nv)
		{
			var cap = nv + 256;
			_spPos = new Il2CppStructArray<Vector3>(cap); _spVel = new Il2CppStructArray<Vector3>(cap);
			_spUv0 = new Il2CppStructArray<Vector4>(cap); _spUv1 = new Il2CppStructArray<Vector4>(cap); _spCol = new Il2CppStructArray<Vector4>(cap);
		}
		if (_spIdx == null || _spIdx.Length < ni)
			_spIdx = new Il2CppStructArray<int>(ni + 384);
		MemoryMarshal.Cast<NV, Vector3>(new ReadOnlySpan<NV>(st.Pos, 0, nv)).CopyTo(Data(_spPos, nv));
		MemoryMarshal.Cast<NV, Vector3>(new ReadOnlySpan<NV>(st.Vel, 0, nv)).CopyTo(Data(_spVel, nv));
		MemoryMarshal.Cast<float, Vector4>(new ReadOnlySpan<float>(st.Uv0, 0, nv * 4)).CopyTo(Data(_spUv0, nv));
		MemoryMarshal.Cast<float, Vector4>(new ReadOnlySpan<float>(st.Uv1, 0, nv * 4)).CopyTo(Data(_spUv1, nv));
		MemoryMarshal.Cast<float, Vector4>(new ReadOnlySpan<float>(st.Col, 0, nv * 4)).CopyTo(Data(_spCol, nv));
		new ReadOnlySpan<int>(st.Idx, 0, ni).CopyTo(Data(_spIdx, ni));
		const MeshUpdateFlags quiet = MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontValidateIndices;
		_spriteMesh.SetVertices(_spPos, 0, nv, quiet);
		var exact = new Il2CppStructArray<Vector3>(nv);   // velocity rides in the normal channel (exact-size: proven path)
		Data(_spVel, nv).CopyTo(Data(exact, nv));
		_spriteMesh.normals = exact;
		_spriteMesh.SetUVs(0, _spUv0, 0, nv);
		_spriteMesh.SetUVs(1, _spUv1, 0, nv);
		_spriteMesh.SetUVs(2, _spCol, 0, nv);
		_spriteMesh.SetTriangles(_spIdx, 0, ni, 0, false, 0);
		NV c = (st.Lo + st.Hi) * 0.5f, size = st.Hi - st.Lo + new NV(1f);   // + a margin for the quads' extent
		_spriteMesh.bounds = new Bounds(new Vector3(c.X, c.Y, c.Z), new Vector3(size.X, size.Y, size.Z));
	}

	/// <summary>Main thread, inside <see cref="FluidRunner.Collect"/>: the staging just filled becomes the front.</summary>
	private void SwapStaging()
	{
		foreach (var s in _slots)
			(s.Front, s.Back) = (s.Back, s.Front);
		(_spriteFront, _spriteBack) = (_spriteBack, _spriteFront);
		(_lightFront, _lightBack) = (_lightBack, _lightFront);
		(_lightOnFront, _lightOnBack) = (_lightOnBack, _lightOnFront);
	}

	/// <summary>Writable view of an interop struct array's native storage (Il2CppArrayBase.ArrayStartPointer: object
	/// header, bounds and length = 4 pointers). Its own AsSpan() returns a .NET 6 Span this netstandard2.1 build cannot
	/// bind, and its indexer re-reads the native length on every access. <paramref name="len"/> must not exceed the
	/// array's allocated length.</summary>
	private static unsafe Span<Vector3> Data(Il2CppStructArray<Vector3> a, int len) => new((void*)IntPtr.Add(a.Pointer, 4 * IntPtr.Size), len);
	private static unsafe Span<Vector4> Data(Il2CppStructArray<Vector4> a, int len) => new((void*)IntPtr.Add(a.Pointer, 4 * IntPtr.Size), len);
	private static unsafe Span<int> Data(Il2CppStructArray<int> a, int len) => new((void*)IntPtr.Add(a.Pointer, 4 * IntPtr.Size), len);

	private void Upload()
	{
		var t0 = System.Diagnostics.Stopwatch.GetTimestamp();
		for (var k = 0; k < _slots.Count; k++)
			UploadSurface(_slots[k]);
		if (_spriteMesh)
			UploadSprites();
		if (_light)
			_light.enabled = _lightOnFront;
		if (_light && _lightOnFront)
			_light.transform.localPosition = new Vector3(_lightFront.X * _simScale, _lightFront.Y * _simScale, _lightFront.Z * _simScale);
		_uploadMs += (System.Diagnostics.Stopwatch.GetTimestamp() - t0) * 1000.0 / System.Diagnostics.Stopwatch.Frequency;
		_uploads++;
	}

	/// <summary>Bulk copies only: each interop array's span is taken once. Its indexer re-reads the native length on
	/// every access, which cost 12-22 ms per stack per frame on the first install (2026-11-20).</summary>
	private void UploadSurface(Slot s)
	{
		var st = s.Front;
		int nv = st.Nv, ni = st.Ni;
		var mesh = s.Mesh;
		mesh.Clear();
		if (nv == 0 || ni == 0)
			return;
		if (s.Pos == null || s.Pos.Length < nv)
		{
			var cap = nv + nv / 4 + 64;
			s.Pos = new Il2CppStructArray<Vector3>(cap); s.Nrm = new Il2CppStructArray<Vector3>(cap); s.Uv = new Il2CppStructArray<Vector4>(cap);
		}
		if (s.Idx == null || s.Idx.Length < ni)
			s.Idx = new Il2CppStructArray<int>(ni + ni / 4 + 96);
		MemoryMarshal.Cast<NV, Vector3>(new ReadOnlySpan<NV>(st.Pos, 0, nv)).CopyTo(Data(s.Pos, nv));
		MemoryMarshal.Cast<NV, Vector3>(new ReadOnlySpan<NV>(st.Nrm, 0, nv)).CopyTo(Data(s.Nrm, nv));
		MemoryMarshal.Cast<float, Vector4>(new ReadOnlySpan<float>(st.Uv, 0, nv * 4)).CopyTo(Data(s.Uv, nv));
		new ReadOnlySpan<int>(st.Idx, 0, ni).CopyTo(Data(s.Idx, ni));
		const MeshUpdateFlags quiet = MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontValidateIndices;
		mesh.SetVertices(s.Pos, 0, nv, quiet);
		if (!s.NormalsChannelFailed)
		{
			try
			{
				mesh.SetSizedArrayForChannel(VertexAttribute.Normal, VertexAttributeFormat.Float32, 3, new Il2CppSystem.Array(s.Nrm.Pointer), s.Nrm.Length, 0, nv, quiet);
			}
			catch (Exception ex)
			{
				s.NormalsChannelFailed = true;
				Log("normal channel upload failed, using exact-size arrays: " + ex.Message, true);
			}
		}
		if (s.NormalsChannelFailed)
		{
			var exact = new Il2CppStructArray<Vector3>(nv);
			MemoryMarshal.Cast<NV, Vector3>(new ReadOnlySpan<NV>(st.Nrm, 0, nv)).CopyTo(Data(exact, nv));
			mesh.normals = exact;
		}
		mesh.SetUVs(0, s.Uv, 0, nv);
		mesh.SetTriangles(s.Idx, 0, ni, 0, false, 0);
		NV center = (st.Lo + st.Hi) * 0.5f, size = st.Hi - st.Lo;
		mesh.bounds = new Bounds(new Vector3(center.X, center.Y, center.Z), new Vector3(size.X, size.Y, size.Z));
	}

	private void OnDestroy()
	{
		try
		{
			_runner?.Wait();
			foreach (var s in _slots)
			{
				if (s.Mesh) Destroy(s.Mesh);
				if (s.Material) Destroy(s.Material);
			}
			if (_spriteMesh) Destroy(_spriteMesh);
			if (_spriteMat) Destroy(_spriteMat);
		}
		catch (Exception) { }
	}

	private void Log(string msg, bool error)
	{
		if (_logBudget-- <= 0)
			return;
		if (error) _log?.LogError("Homm3FluidFusion: " + msg);
		else _log?.LogInfo("Homm3FluidFusion: " + msg);
	}

	private static Affine ToAffine(Matrix4x4 m) => new()
	{
		M00 = m.m00, M01 = m.m01, M02 = m.m02, M03 = m.m03,
		M10 = m.m10, M11 = m.m11, M12 = m.m12, M13 = m.m13,
		M20 = m.m20, M21 = m.m21, M22 = m.m22, M23 = m.m23,
	};

	private static Matrix4x4 FromAffine(Affine a)
	{
		var m = Matrix4x4.identity;
		m.m00 = a.M00; m.m01 = a.M01; m.m02 = a.M02; m.m03 = a.M03;
		m.m10 = a.M10; m.m11 = a.M11; m.m12 = a.M12; m.m13 = a.M13;
		m.m20 = a.M20; m.m21 = a.M21; m.m22 = a.M22; m.m23 = a.M23;
		return m;
	}
}
