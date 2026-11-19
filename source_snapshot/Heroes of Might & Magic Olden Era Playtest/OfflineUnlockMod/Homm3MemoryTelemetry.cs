using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using BepInEx;
using BepInEx.Logging;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.Profiling;
using UnityEngine.SceneManagement;

namespace OfflineUnlockMod;

/// <summary>
/// Dev-only memory telemetry for the iPad port's 8 GB unified-memory budget (V:/olden_ios_port/MEMORY_PLAN.md).
/// Enabled by the flag file <c>homm3_memory_telemetry.flag</c> in the plugin folder; does nothing otherwise.
/// Writes <c>BepInEx/memory_telemetry/mem_&lt;time&gt;.csv</c>: one row every 5 s and on every active-scene change
/// (process, Unity native, game managed heap, mod CLR heap, texture memory). Every 60 s and on scene change it also
/// walks loaded textures / render textures / meshes / audio clips and writes estimated bytes by kind plus the largest
/// textures to <c>mem_&lt;time&gt;_detail.log</c>. Estimates count a readable texture twice (CPU copy + GPU copy),
/// which is what it costs on unified memory.
/// </summary>
internal static class Homm3MemoryTelemetry
{
	internal const string FlagFileName = "homm3_memory_telemetry.flag";
	private static bool _registered, _attached;

	internal static void Ensure(ManualLogSource log)
	{
		if (_attached || !Homm3DiagnosticFlags.IsEnabled(FlagFileName))
			return;
		try
		{
			if (!_registered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3MemoryTelemetryBehaviour>();
				_registered = true;
			}
			var go = new GameObject("OfflineUnlockMemoryTelemetry");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3MemoryTelemetryBehaviour>();
			UnityEngine.Object.DontDestroyOnLoad(go);
			_attached = true;
			log?.LogInfo("Memory telemetry: on (" + FlagFileName + "); output in BepInEx/memory_telemetry.");
		}
		catch (Exception ex)
		{
			log?.LogWarning("Memory telemetry attach failed: " + ex.Message);
		}
	}
}

public sealed class Homm3MemoryTelemetryBehaviour : MonoBehaviour
{
	private const float SampleSeconds = 5f, DetailSeconds = 60f;
	private const double MB = 1024.0 * 1024.0;
	private StreamWriter _csv, _detail;
	private float _nextSample, _nextDetail;
	private string _scene = "";
	private float _t0;

	public Homm3MemoryTelemetryBehaviour(IntPtr ptr) : base(ptr) { }

	private void Start()
	{
		try
		{
			var dir = Path.Combine(Paths.BepInExRootPath, "memory_telemetry");
			Directory.CreateDirectory(dir);
			var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture);
			_csv = new StreamWriter(Path.Combine(dir, "mem_" + stamp + ".csv"), false, Encoding.UTF8) { AutoFlush = true };
			_detail = new StreamWriter(Path.Combine(dir, "mem_" + stamp + "_detail.log"), false, Encoding.UTF8) { AutoFlush = true };
			_csv.WriteLine("t_s,scene,event,proc_working_mb,proc_private_mb,unity_alloc_mb,unity_reserved_mb,gfx_driver_mb,game_heap_mb,game_heap_used_mb,mod_clr_heap_mb,tex_current_mb,tex_total_mb,tex_nonstreaming_mb,tex_nonstreaming_count,bundles");
			_t0 = Time.realtimeSinceStartup;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Memory telemetry: cannot open output: " + ex.Message);
			enabled = false;
		}
	}

	private void Update()
	{
		var now = Time.realtimeSinceStartup;
		string scene;
		try { scene = SceneManager.GetActiveScene().name ?? ""; } catch { scene = "?"; }
		if (scene != _scene)
		{
			_scene = scene;
			Sample("scene");
			Detail("scene " + scene);
			_nextSample = now + SampleSeconds;
			_nextDetail = now + DetailSeconds;
			return;
		}
		if (now >= _nextSample) { _nextSample = now + SampleSeconds; Sample("tick"); }
		if (now >= _nextDetail) { _nextDetail = now + DetailSeconds; Detail("periodic"); }
	}

	private void OnApplicationQuit() { Sample("quit"); _csv?.Dispose(); _detail?.Dispose(); _csv = _detail = null; }

	private static string F(double v) => v.ToString("F1", CultureInfo.InvariantCulture);

	private void Sample(string evt)
	{
		if (_csv == null) return;
		try
		{
			double ws = 0, priv = 0;
			try { using var p = System.Diagnostics.Process.GetCurrentProcess(); ws = p.WorkingSet64 / MB; priv = p.PrivateMemorySize64 / MB; } catch { }
			int bundles = -1;
			try { bundles = Resources.FindObjectsOfTypeAll<AssetBundle>().Length; } catch { }
			_csv.WriteLine(string.Join(",",
				F(Time.realtimeSinceStartup - _t0), "\"" + _scene.Replace("\"", "'") + "\"", evt, F(ws), F(priv),
				F(Profiler.GetTotalAllocatedMemoryLong() / MB), F(Profiler.GetTotalReservedMemoryLong() / MB),
				F(Profiler.GetAllocatedMemoryForGraphicsDriver() / MB),
				F(Profiler.GetMonoHeapSizeLong() / MB), F(Profiler.GetMonoUsedSizeLong() / MB),
				F(GC.GetTotalMemory(false) / MB),
				F(Texture.currentTextureMemory / MB), F(Texture.totalTextureMemory / MB),
				F(Texture.nonStreamingTextureMemory / MB), Texture.nonStreamingTextureCount.ToString(CultureInfo.InvariantCulture),
				bundles.ToString(CultureInfo.InvariantCulture)));
		}
		catch (Exception ex)
		{
			_csv.WriteLine("# sample failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	// bits per pixel of the top mip; block formats as their average
	private static double Bpp(TextureFormat f) => f switch
	{
		TextureFormat.Alpha8 or TextureFormat.R8 => 8,
		TextureFormat.RGB565 or TextureFormat.RGBA4444 or TextureFormat.ARGB4444 or TextureFormat.R16 or TextureFormat.RHalf or TextureFormat.RG16 => 16,
		TextureFormat.RGB24 => 24,
		TextureFormat.RGBA32 or TextureFormat.ARGB32 or TextureFormat.BGRA32 or TextureFormat.RFloat or TextureFormat.RGHalf => 32,
		TextureFormat.RGBAHalf or TextureFormat.RGFloat => 64,
		TextureFormat.RGBAFloat => 128,
		TextureFormat.DXT1 or TextureFormat.DXT1Crunched or TextureFormat.BC4 or TextureFormat.ETC_RGB4 or TextureFormat.ETC2_RGB => 4,
		TextureFormat.DXT5 or TextureFormat.DXT5Crunched or TextureFormat.BC5 or TextureFormat.BC6H or TextureFormat.BC7 or TextureFormat.ETC2_RGBA8 or TextureFormat.ASTC_4x4 => 8,
		TextureFormat.ASTC_6x6 => 3.56,
		TextureFormat.ASTC_8x8 => 2,
		_ => 32,
	};

	private sealed class Bucket { public int Count; public double Bytes; }

	private void Detail(string why)
	{
		if (_detail == null) return;
		try
		{
			var sb = new StringBuilder();
			sb.Append("=== ").Append(F(Time.realtimeSinceStartup - _t0)).Append(" s, ").Append(why).AppendLine();
			var byKind = new SortedDictionary<string, Bucket>(StringComparer.Ordinal);
			void Add(string k, double bytes) { if (!byKind.TryGetValue(k, out var b)) byKind[k] = b = new Bucket(); b.Count++; b.Bytes += bytes; }
			var top = new List<(double bytes, string line)>();
			foreach (var t in Resources.FindObjectsOfTypeAll<Texture2D>())
			{
				if (t == null) continue;
				var mips = t.mipmapCount > 1 ? 4.0 / 3.0 : 1.0;
				var gpu = (double)t.width * t.height * Bpp(t.format) / 8.0 * mips;
				var readable = t.isReadable;
				var bytes = readable ? gpu * 2 : gpu;
				Add("Texture2D " + t.format + (readable ? " readable" : ""), bytes);
				top.Add((bytes, $"{bytes / MB,8:F1} MB  {t.width}x{t.height} {t.format}{(t.mipmapCount > 1 ? " mips" : "")}{(readable ? " readable" : "")}  {t.name}"));
			}
			foreach (var r in Resources.FindObjectsOfTypeAll<RenderTexture>())
			{
				if (r == null) continue;
				double px = (double)r.width * r.height * Math.Max(1, r.antiAliasing) * Math.Max(1, r.volumeDepth);
				var bpp = r.format switch { RenderTextureFormat.ARGBHalf => 8, RenderTextureFormat.ARGBFloat => 16, RenderTextureFormat.RHalf => 2, RenderTextureFormat.R8 => 1, RenderTextureFormat.RFloat => 4, _ => 4 };
				var bytes = px * (bpp + (r.depth > 0 ? 4 : 0)) * (r.useMipMap ? 4.0 / 3.0 : 1.0);
				Add("RenderTexture", bytes);
				top.Add((bytes, $"{bytes / MB,8:F1} MB  {r.width}x{r.height} RT {r.format} aa{r.antiAliasing}  {r.name}"));
			}
			foreach (var m in Resources.FindObjectsOfTypeAll<Mesh>())
			{
				if (m == null) continue;
				double bytes = 0;
				try
				{
					for (int s = 0; s < m.vertexBufferCount; s++) bytes += (double)m.vertexCount * m.GetVertexBufferStride(s);
					var ib = m.indexFormat == UnityEngine.Rendering.IndexFormat.UInt32 ? 4 : 2;
					for (int s = 0; s < m.subMeshCount; s++) bytes += (double)m.GetIndexCount(s) * ib;
				}
				catch { }
				if (m.isReadable) bytes *= 2;
				Add("Mesh" + (m.isReadable ? " readable" : ""), bytes);
			}
			foreach (var a in Resources.FindObjectsOfTypeAll<AudioClip>())
			{
				if (a == null) continue;
				double bytes = 0;
				try { bytes = Profiler.GetRuntimeMemorySizeLong(a); } catch { }
				if (bytes <= 0 && a.loadType == AudioClipLoadType.DecompressOnLoad) bytes = (double)a.samples * a.channels * 2; // PCM16
				Add("AudioClip " + a.loadType, bytes);
			}
			double total = 0;
			foreach (var kv in byKind.OrderByDescending(k => k.Value.Bytes))
			{
				total += kv.Value.Bytes;
				sb.Append($"{kv.Value.Bytes / MB,10:F1} MB  {kv.Value.Count,6}  {kv.Key}").AppendLine();
			}
			sb.Append($"{total / MB,10:F1} MB  total estimated (textures/RTs/meshes/audio)").AppendLine();
			sb.AppendLine("largest textures:");
			foreach (var x in top.OrderByDescending(x => x.bytes).Take(25)) sb.AppendLine(x.line);
			_detail.Write(sb.ToString());
		}
		catch (Exception ex)
		{
			_detail.WriteLine("# detail failed: " + ex.GetType().Name + ": " + ex.Message);
		}
	}
}
