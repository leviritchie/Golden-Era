using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Hex.Session.Battle;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Battle hellgate for a gated stack. Timeline (seconds after entry):
///   0.00-0.40  ground sigil burns in, a camera-facing ring of fire tears open behind the entry hex;
///   0.40-1.70  the stack walks out of the ring onto its hex on its own move (or fly) animation, embers burst;
///   1.70-2.40  the ring collapses in a flare, the sigil cools and fades.
/// The unit is matched to its battle drawer by the drawer Init (TransferUnit sid + spawn position), which can
/// run inside the native spawn call, so the pending entry is registered before the spawn. Only the drawer's
/// Animator transform (a child node) is offset; its local position/scale are restored at the end, and the
/// move/fly bool is cleared only if the native drawer root has not moved (the unit did not start acting).
/// Proof tier: source + build; looks unproven until the owner sees it in game.
/// </summary>
internal static class Homm3InfernoGatingPortal
{
	private const float OpenTime = 0.40f;
	private const float WalkEnd = 1.70f;
	private const float CloseEnd = 2.40f;
	private const float RingBack = 1.25f;    // ring stands this far behind the hex, toward the stack's home side
	private const float RingHeight = 1.15f;  // ring centre height
	private const float RingSize = 2.1f;
	private const float SigilSize = 1.7f;
	private const int RingFrames = 10;
	private const int EmberCount = 36;
	private static readonly int MoveHash = Animator.StringToHash("move");
	private static readonly int FlyHash = Animator.StringToHash("fly");

	private sealed class Ember
	{
		internal Transform T;
		internal Vector3 Velocity;
		internal float Born;
		internal float Life;
		internal float Size;
	}

	private sealed class Show
	{
		internal string Sid;
		internal Vector3 HexPos;
		internal Vector3 Forward;
		internal float Start;
		internal bool Started;
		internal object Drawer;
		internal Transform RootTransform;
		internal Vector3 RootStart;
		internal Transform Visual;
		internal Vector3 VisualLocalPos;
		internal Vector3 VisualLocalScale;
		internal bool Flyer;
		internal bool AnimSet;
		internal GameObject Root;
		internal Transform Ring;
		internal MeshRenderer RingRenderer;
		internal Transform Sigil;
		internal MeshRenderer SigilRenderer;
		internal Light Light;
		internal readonly List<Ember> Embers = new();
		internal bool BurstDone;
	}

	private static readonly List<Show> Shows = new();
	private static ManualLogSource _log;
	private static bool _registered;
	private static Texture2D[] _ringTextures;
	private static Texture2D _sigilTexture;
	private static Texture2D _emberTexture;
	private static Material _baseMaterial;
	private static int _logged;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;
		_log = log;
		try
		{
			var drawerType = ResolveDrawerType() ?? throw new TypeLoadException("battle drawer type");
			var patched = 0;
			foreach (var method in drawerType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
			{
				var ps = method.GetParameters();
				if (method.ReturnType != typeof(bool) || ps.Length != 7 || ps[0].ParameterType != typeof(UnitViewConfig)
				    || ps[1].ParameterType != typeof(TransferUnit) || ps[3].ParameterType != typeof(Vector3))
					continue;
				harmony.Patch(method, postfix: new HarmonyMethod(typeof(Homm3InfernoGatingPortal), nameof(PostfixDrawerInit)) { priority = Priority.Last });
				patched++;
			}
			if (patched == 0)
				throw new MissingMethodException("drawer Init(UnitViewConfig, TransferUnit, Random, Vector3, float, bool, int)");
			_registered = true;
			_log?.LogInfo("HoMM3 Inferno Gating portal registered (" + patched + " drawer Init postfix(es)).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Inferno Gating portal: drawer binding unavailable (gate plays without the walk-in): " + ex.GetBaseException().Message);
		}
	}

	private static Type ResolveDrawerType()
	{
		foreach (var name in GameSymbols.BattleVisual.BattleDrawerTypeNames)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var type = typeof(TransferUnit).Assembly.GetType(name);
			if (type != null)
				return type;
		}
		return null;
	}

	/// <summary>Registers the gate before the native spawn (the drawer may bind inside the spawn call).</summary>
	internal static object Prepare(string sid, Vector3 hexPos, int homeSign)
	{
		var show = new Show
		{
			Sid = sid,
			HexPos = hexPos,
			Forward = new Vector3(homeSign > 0 ? -1f : 1f, 0f, 0f),
			Start = Time.time,
		};
		lock (Shows)
			Shows.Add(show);
		return show;
	}

	internal static void Cancel(object handle)
	{
		if (handle is not Show show)
			return;
		lock (Shows)
			Shows.Remove(show);
		Cleanup(show, restore: true);
	}

	/// <summary>Spawn succeeded: start the gate at the hex the factory accepted.</summary>
	internal static void Play(object handle, Vector3 hexPos)
	{
		if (handle is not Show show)
			return;
		show.HexPos = hexPos;
		show.Start = Time.time;
		show.Started = true;
		try
		{
			BuildScene(show);
		}
		catch (Exception ex)
		{
			LogLimited("gate scene failed (entry stands, no effect): " + ex.GetBaseException().Message);
		}
	}

	private static void PostfixDrawerInit(object __instance, object[] __args, bool __result)
	{
		if (!__result || __args == null || __args.Length < 4 || __args[1] is not TransferUnit transfer)
			return;
		try
		{
			var sid = transfer.configSid;
			var pos = __args[3] is Vector3 v ? v : Vector3.zero;
			lock (Shows)
			{
				foreach (var show in Shows)
				{
					if (show.Drawer != null || !string.Equals(show.Sid, sid, StringComparison.Ordinal))
						continue;
					var flat = pos - show.HexPos;
					flat.y = 0f;
					if (flat.sqrMagnitude > 1.0f)
						continue;
					show.Drawer = __instance;
					try
					{
						show.Flyer = string.Equals(transfer.prop_UnitLogicConfig_0?.stats?.moveType, "fly", StringComparison.OrdinalIgnoreCase);
					}
					catch
					{
					}
					break;
				}
			}
		}
		catch (Exception ex)
		{
			LogLimited("drawer match failed: " + ex.GetBaseException().Message);
		}
	}

	// ---------------------------------------------------------------- per-frame

	internal static void Tick()
	{
		Show[] snapshot;
		lock (Shows)
		{
			if (Shows.Count == 0)
				return;
			snapshot = Shows.ToArray();
		}
		var now = Time.time;
		foreach (var show in snapshot)
		{
			try
			{
				if (!show.Started)
				{
					if (now - show.Start > 5f)
						Cancel(show);
					continue;
				}
				var t = now - show.Start;
				BindVisual(show);
				AnimateScene(show, t);
				AnimateUnit(show, t);
				if (t >= CloseEnd)
				{
					lock (Shows)
						Shows.Remove(show);
					Cleanup(show, restore: true);
				}
			}
			catch (Exception ex)
			{
				LogLimited("gate tick failed (cleaned up): " + ex.GetBaseException().Message);
				lock (Shows)
					Shows.Remove(show);
				Cleanup(show, restore: true);
			}
		}
	}

	private static void BindVisual(Show show)
	{
		if (show.Drawer == null)
			return;
		var animator = ReadAnimator(show.Drawer);
		var visual = animator ? animator.transform : null;
		if (visual == null || visual == show.Visual)
			return;
		// (Re)bind: the HoMM3 visual hook may swap the drawer's Animator a frame after Init.
		if (show.Visual)
			RestoreVisual(show);
		show.Visual = visual;
		show.VisualLocalPos = visual.localPosition;
		show.VisualLocalScale = visual.localScale;
		show.RootTransform = ReadRootTransform(show.Drawer) ?? visual.parent;
		show.RootStart = show.RootTransform ? show.RootTransform.position : visual.position;
		show.AnimSet = false;
	}

	private static void AnimateUnit(Show show, float t)
	{
		if (!show.Visual)
			return;
		if (show.RootTransform && (show.RootTransform.position - show.RootStart).sqrMagnitude > 0.04f)
		{
			// The unit started acting natively: hand it back immediately.
			RestoreVisual(show);
			show.Visual = null;
			show.Drawer = null;
			return;
		}
		var animator = show.Visual.GetComponent<Animator>();
		if (t < OpenTime)
		{
			show.Visual.localScale = show.VisualLocalScale * 0.001f;
			return;
		}
		show.Visual.localScale = show.VisualLocalScale;
		if (t < WalkEnd)
		{
			var k = Mathf.Clamp01((t - OpenTime) / (WalkEnd - OpenTime));
			var eased = 1f - (1f - k) * (1f - k) * 0.35f - (1f - k) * 0.65f; // near-linear walk, soft arrival
			var offset = -show.Forward * RingBack * (1f - eased);
			show.Visual.localPosition = show.VisualLocalPos;
			show.Visual.position += offset;
			if (!show.AnimSet && animator)
			{
				SetBoolIfPresent(animator, show.Flyer ? FlyHash : MoveHash, true);
				show.AnimSet = true;
			}
			return;
		}
		RestoreVisual(show);
	}

	private static void RestoreVisual(Show show)
	{
		if (!show.Visual)
			return;
		show.Visual.localPosition = show.VisualLocalPos;
		show.Visual.localScale = show.VisualLocalScale;
		if (show.AnimSet)
		{
			var animator = show.Visual.GetComponent<Animator>();
			var rootStill = !show.RootTransform || (show.RootTransform.position - show.RootStart).sqrMagnitude <= 0.04f;
			if (animator && rootStill)
				SetBoolIfPresent(animator, show.Flyer ? FlyHash : MoveHash, false);
			show.AnimSet = false;
		}
	}

	private static void SetBoolIfPresent(Animator animator, int hash, bool value)
	{
		// AnimatorControllerParameter getters are stripped in the live build; every battle unit controller
		// (_Battle_Unit_Anim_ctrl_v2 and the HoMM3 overrides) carries the move/fly bools the native mover drives.
		try
		{
			animator.SetBool(hash, value);
		}
		catch
		{
		}
	}

	// ---------------------------------------------------------------- scene

	private static void BuildScene(Show show)
	{
		EnsureAssets();
		var root = new GameObject("HOMM3_INFERNO_GATE");
		show.Root = root;
		root.transform.position = show.HexPos;

		show.Sigil = MakeQuad("sigil", root.transform, _sigilTexture, out show.SigilRenderer);
		show.Sigil.localPosition = new Vector3(0f, 0.03f, 0f);
		show.Sigil.localRotation = Quaternion.Euler(90f, 0f, 0f);
		show.Sigil.localScale = Vector3.zero;

		show.Ring = MakeQuad("ring", root.transform, _ringTextures[0], out show.RingRenderer);
		show.Ring.localPosition = -show.Forward * RingBack + new Vector3(0f, RingHeight, 0f);
		show.Ring.localScale = Vector3.zero;

		var lightGo = new GameObject("light");
		lightGo.transform.SetParent(root.transform, false);
		lightGo.transform.localPosition = show.Ring.localPosition + new Vector3(0f, 0.2f, -0.4f);
		show.Light = lightGo.AddComponent<Light>();
		show.Light.type = LightType.Point;
		show.Light.color = new Color(1f, 0.45f, 0.12f);
		show.Light.range = 4.5f;
		show.Light.intensity = 0f;

		for (var i = 0; i < EmberCount; i++)
		{
			var ember = MakeQuad("ember" + i, root.transform, _emberTexture, out _);
			ember.localScale = Vector3.zero;
			show.Embers.Add(new Ember { T = ember });
		}
	}

	private static void AnimateScene(Show show, float t)
	{
		if (!show.Root)
			return;
		var cam = Camera.main;
		var camRot = cam ? cam.transform.rotation : Quaternion.identity;

		// ring: open with overshoot, hold with a breathing pulse, collapse with a flare
		float ringScale;
		if (t < OpenTime)
		{
			var k = t / OpenTime;
			ringScale = EaseOutBack(k);
		}
		else if (t < WalkEnd)
			ringScale = 1f + 0.04f * Mathf.Sin((t - OpenTime) * 9f);
		else
		{
			var k = Mathf.Clamp01((t - WalkEnd) / (CloseEnd - WalkEnd));
			ringScale = k < 0.18f ? 1f + k * 0.9f : Mathf.Max(0f, (1f - k) / 0.82f) * 1.16f;
		}
		if (show.Ring)
		{
			show.Ring.rotation = camRot;
			show.Ring.localScale = new Vector3(RingSize, RingSize, 1f) * ringScale;
			show.RingRenderer.material.mainTexture = _ringTextures[(int)(t * 14f) % RingFrames];
		}

		// sigil: burn in, slow turn, cool off
		if (show.Sigil)
		{
			var inK = Mathf.Clamp01(t / (OpenTime * 0.8f));
			var outK = Mathf.Clamp01((t - WalkEnd) / (CloseEnd - WalkEnd));
			show.Sigil.localScale = Vector3.one * SigilSize * EaseOutBack(inK);
			show.Sigil.localRotation = Quaternion.Euler(90f, t * 40f, 0f);
			show.SigilRenderer.material.color = new Color(1f, 1f, 1f, 1f - outK);
		}

		if (show.Light)
			show.Light.intensity = 3.2f * Mathf.Clamp01(ringScale) * (0.85f + 0.15f * Mathf.Sin(t * 23f));

		// embers: one burst as the ring opens, a trickle while it holds
		if (!show.BurstDone && t >= OpenTime * 0.6f)
		{
			show.BurstDone = true;
			for (var i = 0; i < show.Embers.Count; i++)
				Respawn(show, show.Embers[i], t, burst: i < show.Embers.Count * 2 / 3);
		}
		foreach (var ember in show.Embers)
		{
			if (!ember.T)
				continue;
			if (!show.BurstDone)
				continue;
			var age = t - ember.Born;
			if (age > ember.Life)
			{
				if (t < WalkEnd)
					Respawn(show, ember, t, burst: false);
				else
				{
					ember.T.localScale = Vector3.zero;
					continue;
				}
				age = 0f;
			}
			ember.Velocity += new Vector3(0f, 1.2f, 0f) * Time.deltaTime; // hot air lifts them
			ember.Velocity *= 1f - 1.4f * Time.deltaTime;
			ember.T.localPosition += ember.Velocity * Time.deltaTime;
			ember.T.rotation = camRot;
			var life = 1f - age / ember.Life;
			ember.T.localScale = Vector3.one * ember.Size * life;
		}
	}

	private static void Respawn(Show show, Ember ember, float t, bool burst)
	{
		var ringPos = -show.Forward * RingBack + new Vector3(0f, RingHeight, 0f);
		var a = UnityEngine.Random.value * Mathf.PI * 2f;
		var rim = new Vector3(Mathf.Cos(a) * 0.78f, Mathf.Sin(a) * 0.98f, 0f) * RingSize * 0.42f;
		ember.T.localPosition = ringPos + rim;
		var outward = rim.normalized;
		ember.Velocity = burst
			? outward * UnityEngine.Random.Range(1.4f, 3.2f) + show.Forward * UnityEngine.Random.Range(0.4f, 1.6f)
			: new Vector3(UnityEngine.Random.Range(-0.3f, 0.3f), UnityEngine.Random.Range(0.5f, 1.2f), UnityEngine.Random.Range(-0.3f, 0.3f));
		ember.Born = t;
		ember.Life = burst ? UnityEngine.Random.Range(0.6f, 1.2f) : UnityEngine.Random.Range(0.5f, 0.9f);
		ember.Size = burst ? UnityEngine.Random.Range(0.08f, 0.16f) : UnityEngine.Random.Range(0.05f, 0.10f);
	}

	private static float EaseOutBack(float k)
	{
		k = Mathf.Clamp01(k);
		const float c1 = 1.70158f;
		const float c3 = c1 + 1f;
		return 1f + c3 * Mathf.Pow(k - 1f, 3f) + c1 * Mathf.Pow(k - 1f, 2f);
	}

	private static void Cleanup(Show show, bool restore)
	{
		try
		{
			if (restore)
				RestoreVisual(show);
		}
		catch
		{
		}
		if (show.Root)
			UnityEngine.Object.Destroy(show.Root);
		show.Root = null;
	}

	private static Transform MakeQuad(string name, Transform parent, Texture2D texture, out MeshRenderer renderer)
	{
		var quad = GameObject.CreatePrimitive(PrimitiveType.Quad);
		quad.name = name;
		var collider = quad.GetComponent<Collider>();
		if (collider)
			UnityEngine.Object.Destroy(collider);
		quad.transform.SetParent(parent, false);
		renderer = quad.GetComponent<MeshRenderer>();
		renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
		renderer.receiveShadows = false;
		var material = new Material(_baseMaterial) { mainTexture = texture, renderQueue = 3100 };
		renderer.material = material;
		return quad.transform;
	}

	private static void EnsureAssets()
	{
		if (_ringTextures != null)
			return;
		var shader = Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Transparent")
		             ?? throw new InvalidOperationException("no unlit transparent shader (Sprites/Default, Unlit/Transparent)");
		_baseMaterial = new Material(shader) { hideFlags = HideFlags.DontUnloadUnusedAsset };
		_ringTextures = new Texture2D[RingFrames];
		for (var f = 0; f < RingFrames; f++)
			_ringTextures[f] = MakeTexture(Homm3InfernoGatingArt.PortalRing(160, f, RingFrames), 160, 160);
		_sigilTexture = MakeTexture(Homm3InfernoGatingArt.GroundSigil(192), 192, 192);
		_emberTexture = MakeTexture(Homm3InfernoGatingArt.Ember(24), 24, 24);
	}

	internal static Texture2D MakeTexture(byte[] rgba, int w, int h)
	{
		var tex = new Texture2D(w, h, TextureFormat.RGBA32, false) { filterMode = FilterMode.Bilinear, wrapMode = TextureWrapMode.Clamp };
		var colors = new Color32[w * h];
		for (var i = 0; i < colors.Length; i++)
			colors[i] = new Color32(rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2], rgba[i * 4 + 3]);
		tex.SetPixels32(colors);
		tex.Apply(false, true);
		tex.hideFlags = HideFlags.DontUnloadUnusedAsset;
		return tex;
	}

	private static Animator ReadAnimator(object drawer)
	{
		foreach (var name in GameSymbols.BattleVisual.EcdAnimatorFields)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = drawer.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (property?.GetValue(drawer) is Animator animator && animator)
				return animator;
		}
		return null;
	}

	private static Transform ReadRootTransform(object drawer)
	{
		foreach (var name in GameSymbols.InfernoGating.DrawerRootGameObjectMembers)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var property = drawer.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
			if (property?.GetValue(drawer) is GameObject go && go)
				return go.transform;
		}
		return null;
	}

	private static void LogLimited(string message)
	{
		if (_logged++ < 20)
			_log?.LogWarning("HoMM3 Inferno Gating portal: " + message);
	}
}
