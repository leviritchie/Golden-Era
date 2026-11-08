using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using BepInEx.Logging;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Dynamic metal shine for owned-skinned HoMM3 battle units (docs/homm3_metal_shine.md).
///
/// Opt-in per unit through <c>homm3_mesh_fx/metal_shine/catalog.json</c> (written by
/// tools/homm3_metal_shine/build_masks.py). A unit without a row gets no host and no material, so its runtime
/// path is unchanged. For a matched battle instance a <see cref="Homm3MetalShineHost"/> appends ONE extra material
/// (shader OldenEra/Homm3/MetalShine from the one-asset bundle <c>homm3_metal_shine_shader</c>) to the owned body
/// SkinnedMeshRenderer, after the Hex/Lit clone: an additive Blinn-Phong sun highlight plus a sky/ground sheen,
/// masked by the unit's metal mask (Meshy metallicRoughness B channel, base-colour UVs). The vanilla Hex/Lit clone and
/// the baked <c>lighting.metal</c> stay untouched underneath.
///
/// Per frame the host feeds the sun (the strongest active directional Light, which the Hex pipeline rotates from the
/// LightingSettings volume every render) and mirrors the body's <c>_HexFade</c>. The body material array is checked
/// every 30 frames; the Hex/Lit rebind skips materials named <see cref="MaterialPrefix"/>
/// (Homm3ImportVisuals.OwnedSkinnedMaterialNeedsHexLit), and Homm3MeshFx overlays keep foreign entries.
///
/// Interop: material/array writes only (no IL2CPP generic method instantiation the game never calls); string
/// property names go through Material.Set*/Get*(string), which the plugin already uses on Hex/Lit clones.
/// Proof: source/static + offline Unity render. The Hex SRP drawing this untagged additive pass in battle is
/// unproven until the in-game check; the attach log line records isSupported and the material counts.
/// </summary>
internal static class Homm3MetalShine
{
	internal const string CatalogSchema = "homm3_metal_shine_catalog.v1";
	internal const string RelativeDir = "homm3_mesh_fx/metal_shine/";
	internal const string MaterialPrefix = "HOMM3_metal_shine_";
	internal const string ShaderName = "OldenEra/Homm3/MetalShine";
	internal const string LaneBattle = "battle";
	private const int VerifyEveryFrames = 30;
	private const int MaxReappends = 6;
	private const int SunRescanFrames = 120;
	private const int MaxPendingFrames = 600;

	internal sealed class Row
	{
		internal string Id;
		internal string[] UnitSids;
		internal string MaskFile;
		internal string MaskSha256;
		internal float Intensity;
		internal float Gloss;
		internal float Sheen;
		internal float Tint;
	}

	internal sealed class State
	{
		internal Row Row;
		internal SkinnedMeshRenderer Body;
		internal Material BodyMaterial;
		internal Material Shine;
		internal bool BodyHasFade;
		internal int NextVerifyFrame;
		internal int Reappends;
		internal int PendingFrames;
		internal bool Closed;
		internal bool Logged;
		internal string Context;
	}

	private static bool _catalogAttempted;
	private static List<Row> _rows;
	private static string _bundleName;
	private static string _shaderAsset;
	private static bool _shaderAttempted;
	private static AssetBundle _bundle;
	private static Shader _shader;
	private static readonly Dictionary<string, Texture2D> Masks = new(StringComparer.Ordinal);
	private static readonly HashSet<string> MaskFailures = new(StringComparer.Ordinal);
	private static readonly Dictionary<int, State> StateByHostId = new();
	private static bool _typeRegistered;
	private static int _attachLogRemaining = 64;

	private static Light _sun;
	private static int _sunScanFrame = -100000;
	private static string _sunLogged;
	private static bool _noSunLogged;

	// ------------------------------------------------------------------ attach

	internal static void TryAttachForSkinnedBattle(GameObject battleRoot, Homm3ImportVisuals.Entry entry, ManualLogSource log)
	{
		try
		{
			if (!battleRoot || !Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(battleRoot))
				return;
			EnsureCatalog(log);
			if (_rows == null || _rows.Count == 0)
				return;
			var sids = CollectSids(entry);
			Row match = null;
			for (var i = 0; i < _rows.Count && match == null; i++)
			{
				foreach (var s in _rows[i].UnitSids)
				{
					if (sids.Contains(s))
					{
						match = _rows[i];
						break;
					}
				}
			}
			if (match == null)
				return;
			if (!_typeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3MetalShineHost>();
				_typeRegistered = true;
			}
			var host = battleRoot.GetComponent<Homm3MetalShineHost>();
			if (host)
				return; // pool reuse: already attached, the host re-verifies its material itself
			host = battleRoot.AddComponent<Homm3MetalShineHost>();
			if (!host)
			{
				log?.LogError("Homm3MetalShine: host AddComponent failed for id='" + match.Id + "'.");
				return;
			}
			StateByHostId[host.GetInstanceID()] = new State
			{
				Row = match,
				Context = "id='" + match.Id + "' sids='" + string.Join(",", sids) + "' root='" + battleRoot.name + "'",
			};
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MetalShine: attach failed: " + ex.Message);
		}
	}

	private static HashSet<string> CollectSids(Homm3ImportVisuals.Entry entry)
	{
		var sids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		if (entry?.GameUnitSids != null)
		{
			for (var i = 0; i < entry.GameUnitSids.Count; i++)
			{
				var s = entry.GameUnitSids[i];
				if (!string.IsNullOrWhiteSpace(s))
					sids.Add(s.Trim());
			}
		}
		var path = (entry?.BattlePrefabAssetPath ?? string.Empty).Replace('\\', '/');
		const string marker = "/homm3_lab/";
		var at = path.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
		if (at >= 0)
		{
			var rest = path.Substring(at + marker.Length);
			var slash = rest.IndexOf('/');
			if (slash > 0)
				sids.Add(rest.Substring(0, slash));
		}
		return sids;
	}

	// ------------------------------------------------------------------ per frame

	internal static void Tick(Homm3MetalShineHost host)
	{
		if (!host || !StateByHostId.TryGetValue(host.GetInstanceID(), out var st) || st == null || st.Closed)
			return;
		var log = Plugin.LogSource;
		try
		{
			if (!st.Shine)
			{
				if (!Prepare(host, st, log))
				{
					st.Closed = true;
					return;
				}
				if (!st.Shine)
					return; // body not rebound to Hex/Lit yet; Prepare bounds the wait
			}
			if (!st.Body)
			{
				st.Closed = true;
				return;
			}
			var frame = Time.frameCount;
			if (frame >= st.NextVerifyFrame)
			{
				st.NextVerifyFrame = frame + VerifyEveryFrames;
				if (!EnsureAppended(st, log))
				{
					st.Closed = true;
					return;
				}
			}
			FeedSun(st.Shine, frame, log);
			if (st.BodyHasFade && st.BodyMaterial)
				st.Shine.SetFloat("_HexFade", st.BodyMaterial.GetFloat("_HexFade"));
		}
		catch (Exception ex)
		{
			st.Closed = true;
			log?.LogError("Homm3MetalShine: " + st.Context + " tick failed, shine closed: " + ex.Message);
		}
	}

	internal static void Unregister(Homm3MetalShineHost host)
	{
		if (!host)
			return;
		var id = host.GetInstanceID();
		if (StateByHostId.TryGetValue(id, out var st) && st?.Shine)
			UnityEngine.Object.Destroy(st.Shine);
		StateByHostId.Remove(id);
	}

	/// <summary>Body SMR (the one carrying the Hex/Lit <c>_runtime_native</c> clone), shader, mask, material.</summary>
	private static bool Prepare(Homm3MetalShineHost host, State st, ManualLogSource log)
	{
		var skins = host.GetComponentsInChildren<SkinnedMeshRenderer>(true);
		SkinnedMeshRenderer body = null;
		Material bodyMat = null;
		var best = -1;
		for (var i = 0; skins != null && i < skins.Length; i++)
		{
			var s = skins[i];
			if (!s || !s.sharedMesh || Homm3MeshFx.IsFxDescendant(s.transform))
				continue;
			var name = s.name ?? string.Empty;
			if (name.EndsWith("_Rubble", StringComparison.Ordinal))
				continue;
			var mats = s.sharedMaterials;
			Material native = null;
			for (var j = 0; mats != null && j < mats.Length; j++)
			{
				if (mats[j] && (mats[j].name ?? string.Empty).EndsWith("_runtime_native", StringComparison.Ordinal))
				{
					native = mats[j];
					break;
				}
			}
			if (native == null)
				continue;
			var n = s.sharedMesh.vertexCount;
			if (n > best)
			{
				best = n;
				body = s;
				bodyMat = native;
			}
		}
		if (body == null)
		{
			// The Hex/Lit rebind has not run yet on this instance; retry next frame, bounded.
			st.PendingFrames++;
			if (st.PendingFrames > MaxPendingFrames)
			{
				log?.LogError("Homm3MetalShine: " + st.Context + " found no body SkinnedMeshRenderer with a Hex/Lit "
				              + "_runtime_native clone after " + MaxPendingFrames + " frames; shine closed.");
				return false;
			}
			return true;
		}
		var subMeshes = body.sharedMesh.subMeshCount;
		if (subMeshes != 1)
		{
			log?.LogError("Homm3MetalShine: " + st.Context + " body '" + body.name + "' has " + subMeshes
			              + " submeshes; the appended pass would only cover the last one. Refused (catalog needs a single-submesh body).");
			return false;
		}
		var shader = EnsureShader(log);
		if (!shader)
			return false;
		var mask = LoadMask(st.Row, log);
		if (!mask)
			return false;
		var m = new Material(shader) { name = MaterialPrefix + st.Row.Id };
		m.hideFlags = HideFlags.DontUnloadUnusedAsset;
		m.SetTexture("_ShineMask", mask);
		m.SetFloat("_ShineIntensity", st.Row.Intensity);
		m.SetFloat("_ShineGloss", st.Row.Gloss);
		m.SetFloat("_SheenStrength", st.Row.Sheen);
		m.SetFloat("_TintAmount", st.Row.Tint);
		m.SetFloat("_HexFade", 0f);
		var readIntensity = m.GetFloat("_ShineIntensity");
		if (Mathf.Abs(readIntensity - st.Row.Intensity) > 1e-4f)
		{
			log?.LogError("Homm3MetalShine: " + st.Context + " material readback _ShineIntensity=" + readIntensity
			              + " != " + st.Row.Intensity + "; refused.");
			UnityEngine.Object.Destroy(m);
			return false;
		}
		st.Body = body;
		st.BodyMaterial = bodyMat;
		st.BodyHasFade = bodyMat.HasProperty("_HexFade");
		st.Shine = m;
		st.NextVerifyFrame = 0;
		return true;
	}

	/// <summary>Append the shine once to the body's sharedMaterials (keeping every other entry), then read back.</summary>
	private static bool EnsureAppended(State st, ManualLogSource log)
	{
		var current = st.Body.sharedMaterials;
		var id = st.Shine.GetInstanceID();
		var count = current?.Length ?? 0;
		for (var j = 0; j < count; j++)
		{
			if (current[j] && current[j].GetInstanceID() == id)
				return true;
		}
		if (st.Logged)
		{
			st.Reappends++;
			if (st.Reappends > MaxReappends)
			{
				log?.LogError("Homm3MetalShine: " + st.Context + " another writer keeps dropping the shine from '"
				              + st.Body.name + "' (" + st.Reappends + " re-appends); shine closed.");
				return false;
			}
		}
		var next = new Il2CppReferenceArray<Material>(count + 1);
		for (var j = 0; j < count; j++)
			next[j] = current[j];
		next[count] = st.Shine;
		st.Body.sharedMaterials = next;
		var readback = st.Body.sharedMaterials;
		var present = false;
		for (var j = 0; readback != null && j < readback.Length; j++)
		{
			if (readback[j] && readback[j].GetInstanceID() == id)
				present = true;
		}
		if (!present)
		{
			log?.LogError("Homm3MetalShine: " + st.Context + " sharedMaterials readback on '" + st.Body.name
			              + "' did not hold the shine; closed.");
			return false;
		}
		if (!st.Logged || st.Reappends > 0)
		{
			st.Logged = true;
			if (_attachLogRemaining > 0)
			{
				_attachLogRemaining--;
				var inv = CultureInfo.InvariantCulture;
				log?.LogInfo("Homm3MetalShine: appended " + st.Context + " body='" + st.Body.name
				             + "' materials " + count + "->" + readback.Length
				             + " shaderSupported=" + (_shader && _shader.isSupported)
				             + " queue=" + st.Shine.renderQueue
				             + " intensity=" + st.Row.Intensity.ToString("0.###", inv)
				             + " gloss=" + st.Row.Gloss.ToString("0.#", inv)
				             + " sheen=" + st.Row.Sheen.ToString("0.###", inv)
				             + " hexFade=" + (st.BodyHasFade ? st.BodyMaterial.GetFloat("_HexFade").ToString("0.###", inv) : "n/a")
				             + " reappends=" + st.Reappends
				             + " proof=source/static");
			}
		}
		return true;
	}

	private static void FeedSun(Material m, int frame, ManualLogSource log)
	{
		if ((!_sun || !_sun.isActiveAndEnabled) && frame - _sunScanFrame >= SunRescanFrames)
		{
			_sunScanFrame = frame;
			_sun = FindSun();
			var desc = _sun ? _sun.name : null;
			if (desc != null && !string.Equals(desc, _sunLogged, StringComparison.Ordinal))
			{
				_sunLogged = desc;
				var f = _sun.transform.forward;
				log?.LogInfo("Homm3MetalShine: sun = directional light '" + desc + "' forward=("
				             + f.x.ToString("0.###", CultureInfo.InvariantCulture) + ", "
				             + f.y.ToString("0.###", CultureInfo.InvariantCulture) + ", "
				             + f.z.ToString("0.###", CultureInfo.InvariantCulture) + ") intensity="
				             + _sun.intensity.ToString("0.###", CultureInfo.InvariantCulture) + ".");
			}
			else if (desc == null && !_noSunLogged)
			{
				_noSunLogged = true;
				log?.LogWarning("Homm3MetalShine: no active directional light found; the sun highlight is off (sheen only).");
			}
		}
		if (_sun && _sun.isActiveAndEnabled)
		{
			var f = _sun.transform.forward;
			m.SetVector("_ShineSunDir", new Vector4(f.x, f.y, f.z, 0f));
			var c = _sun.color.linear;
			var k = _sun.intensity;
			m.SetColor("_ShineSunColor", new Color(c.r * k, c.g * k, c.b * k, 1f));
		}
		else
		{
			m.SetColor("_ShineSunColor", Color.black);
		}
	}

	private static Light FindSun()
	{
		Light best = null;
		var bestI = 0f;
		var all = Resources.FindObjectsOfTypeAll(Il2CppType.Of<Light>());
		for (var i = 0; all != null && i < all.Length; i++)
		{
			var l = all[i]?.TryCast<Light>();
			if (!l || !l.isActiveAndEnabled || l.type != LightType.Directional)
				continue;
			if (!l.gameObject.scene.IsValid())
				continue;
			if (l.intensity > bestI)
			{
				bestI = l.intensity;
				best = l;
			}
		}
		return best;
	}

	// ------------------------------------------------------------------ assets

	private static Shader EnsureShader(ManualLogSource log)
	{
		if (_shader)
			return _shader;
		if (_shaderAttempted)
			return null;
		_shaderAttempted = true;
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeDir + _bundleName);
		try
		{
			if (path == null || !File.Exists(path))
			{
				log?.LogError("Homm3MetalShine: shader bundle '" + RelativeDir + _bundleName + "' missing; shine off.");
				return null;
			}
			_bundle = AssetBundle.LoadFromFile(path);
			if (!_bundle)
			{
				log?.LogError("Homm3MetalShine: AssetBundle.LoadFromFile returned null for " + path + "; shine off.");
				return null;
			}
			var shader = _bundle.LoadAsset<Shader>(_shaderAsset);
			if (!shader || !string.Equals(shader.name, ShaderName, StringComparison.Ordinal))
			{
				log?.LogError("Homm3MetalShine: shader '" + ShaderName + "' not found at '" + _shaderAsset + "' in " + path + "; shine off.");
				return null;
			}
			log?.LogInfo("Homm3MetalShine: shader '" + shader.name + "' loaded isSupported=" + shader.isSupported
			             + " passCount=" + shader.passCount + " from " + path + ".");
			if (!shader.isSupported)
			{
				log?.LogError("Homm3MetalShine: shader '" + ShaderName + "' is not supported on this player; shine off.");
				return null;
			}
			shader.hideFlags = HideFlags.DontUnloadUnusedAsset;
			_shader = shader;
			return _shader;
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MetalShine: shader bundle load failed: " + ex.Message);
			return null;
		}
	}

	private static Texture2D LoadMask(Row row, ManualLogSource log)
	{
		if (Masks.TryGetValue(row.MaskFile, out var cached) && cached)
			return cached;
		if (MaskFailures.Contains(row.MaskFile))
			return null;
		string failure = null;
		Texture2D texture = null;
		try
		{
			var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeDir + row.MaskFile);
			if (path == null || !File.Exists(path))
				failure = "file missing";
			else
			{
				var bytes = File.ReadAllBytes(path);
				string digest;
				using (var sha = SHA256.Create())
					digest = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", string.Empty).ToLowerInvariant();
				if (!string.Equals(digest, row.MaskSha256, StringComparison.Ordinal))
					failure = "sha256 " + digest + " != catalog " + row.MaskSha256;
				else
				{
					// sRGB texture (default): RGB is the sRGB metal tint, A the linear mask.
					texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: true);
					var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
					for (var i = 0; i < bytes.Length; i++)
						il2cppBytes[i] = bytes[i];
					if (!ImageConversion.LoadImage(texture, il2cppBytes))
					{
						UnityEngine.Object.Destroy(texture);
						texture = null;
						failure = "PNG decode failed";
					}
				}
			}
		}
		catch (Exception ex)
		{
			failure = ex.Message;
			texture = null;
		}
		if (failure != null)
		{
			MaskFailures.Add(row.MaskFile);
			log?.LogError("Homm3MetalShine: id='" + row.Id + "' mask '" + row.MaskFile + "': " + failure + "; shine off for this row.");
			return null;
		}
		texture.name = "homm3_metal_shine_" + Path.GetFileNameWithoutExtension(row.MaskFile);
		texture.hideFlags = HideFlags.DontUnloadUnusedAsset;
		Masks[row.MaskFile] = texture;
		return texture;
	}

	private static void EnsureCatalog(ManualLogSource log)
	{
		if (_catalogAttempted)
			return;
		_catalogAttempted = true;
		_rows = new List<Row>();
		var path = Homm3ImportPortraitSpriteCache.ResolvePluginAssetPath(RelativeDir + "catalog.json");
		if (path == null || !File.Exists(path))
			return; // no catalog = no unit opted in; nothing to log per battle
		try
		{
			var root = JObject.Parse(File.ReadAllText(path));
			var schema = root["schema"]?.ToString() ?? string.Empty;
			if (!string.Equals(schema, CatalogSchema, StringComparison.Ordinal))
			{
				log?.LogError("Homm3MetalShine: catalog schema mismatch expected " + CatalogSchema + " got " + schema + "; shine off.");
				return;
			}
			// Same token handling as Homm3MeshFx: in game bare `as JObject/JArray` casts on child tokens
			// yield null (different Newtonsoft identity), so objects/arrays re-parse through their text.
			var shader = AsObject(root["shader"]);
			_bundleName = shader?["bundle"]?.ToString();
			_shaderAsset = shader?["asset"]?.ToString();
			if (string.IsNullOrEmpty(_bundleName) || string.IsNullOrEmpty(_shaderAsset)
			    || !string.Equals(shader?["name"]?.ToString(), ShaderName, StringComparison.Ordinal))
			{
				log?.LogError("Homm3MetalShine: catalog shader block is incomplete or names another shader; shine off.");
				return;
			}
			var entries = AsArray(root["entries"]);
			if (entries == null)
			{
				log?.LogError("Homm3MetalShine: catalog has no entries array; shine off.");
				return;
			}
			for (var i = 0; i < entries.Count; i++)
			{
				var e = AsObject(entries[i]);
				if (e == null)
					continue;
				var id = e["id"]?.ToString();
				var lanes = AsArray(e["lanes"]);
				var battle = false;
				for (var j = 0; lanes != null && j < lanes.Count; j++)
					battle |= string.Equals(lanes[j]?.ToString(), LaneBattle, StringComparison.Ordinal);
				var sidArr = AsArray(AsObject(e["match"])?["unitSids"]);
				var sids = new List<string>();
				for (var j = 0; sidArr != null && j < sidArr.Count; j++)
				{
					var sid = sidArr[j]?.ToString();
					if (!string.IsNullOrEmpty(sid))
						sids.Add(sid);
				}
				var mask = AsObject(e["mask"]);
				var shine = AsObject(e["shine"]);
				if (string.IsNullOrEmpty(id) || !battle || sids.Count == 0 || mask == null || shine == null)
				{
					log?.LogError("Homm3MetalShine: catalog row '" + id + "' is malformed or has no battle lane; row dropped.");
					continue;
				}
				_rows.Add(new Row
				{
					Id = id,
					UnitSids = sids.ToArray(),
					MaskFile = mask["file"]?.ToString(),
					MaskSha256 = mask["sha256"]?.ToString(),
					Intensity = ReadFloat(shine, "intensity", 0.35f),
					Gloss = ReadFloat(shine, "gloss", 48f),
					Sheen = ReadFloat(shine, "sheen", 0.12f),
					Tint = ReadFloat(shine, "tint", 0.6f),
				});
			}
			log?.LogInfo("Homm3MetalShine: catalog rows=" + _rows.Count + " bundle=" + _bundleName + ".");
		}
		catch (Exception ex)
		{
			log?.LogError("Homm3MetalShine: catalog parse failed: " + ex.Message);
			_rows.Clear();
		}
	}

	private static JObject AsObject(JToken token)
	{
		if (token == null || token.Type != JTokenType.Object)
			return null;
		return token as JObject ?? JObject.Parse(token.ToString());
	}

	private static JArray AsArray(JToken token)
	{
		if (token == null || token.Type != JTokenType.Array)
			return null;
		return token as JArray ?? JArray.Parse(token.ToString());
	}

	private static float ReadFloat(JObject parent, string property, float fallback)
	{
		var text = parent?[property]?.ToString();
		return !string.IsNullOrEmpty(text)
		       && float.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
			? v
			: fallback;
	}
}

public sealed class Homm3MetalShineHost : MonoBehaviour
{
	public Homm3MetalShineHost(IntPtr ptr)
		: base(ptr)
	{
	}

	private void LateUpdate()
	{
		Homm3MetalShine.Tick(this);
	}

	private void OnDestroy()
	{
		Homm3MetalShine.Unregister(this);
	}
}
